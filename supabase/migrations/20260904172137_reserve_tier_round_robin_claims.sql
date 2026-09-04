-- Keep reserve-aware dispatch, but allocate the first available slot to every
-- under-reserve subject before a larger deficit consumes another worker slot.
-- This prevents persistent hard subjects from starving while retaining deficit
-- priority inside each round-robin slot.

create or replace function public.claim_content_replenishment_jobs(
    p_worker_id text,
    p_now timestamptz default now(),
    p_lease_minutes integer default 20,
    p_limit integer default 5
)
returns setof public.content_replenishment_jobs
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(p_worker_id), '') is null or p_now is null then
        raise exception 'worker and current timestamp are required';
    end if;

    return query
    with verified_subject_capacity as materialized (
        select
            question.subject as subject_key,
            count(*)::integer as verified_count
        from public.questions question
        join public.source_documents source
          on source.id = question.source_document_id
        where question.status = 'active'
          and question.verification_status = 'verified'
          and question.inventory_status in ('verified', 'used')
          and not question.review_required
          and question.knowledge_point_id is not null
          and question.variant_fingerprint is not null
          and (question.expires_at is null or question.expires_at >= p_now)
          and source.verification_status = 'verified'
          and not source.review_required
          and (source.expires_at is null or source.expires_at >= p_now)
          and exists (
              select 1
              from public.knowledge_point_evidence evidence
              join public.source_facts fact
                on fact.id = evidence.source_fact_id
              where evidence.knowledge_point_id = question.knowledge_point_id
                and evidence.support_type = 'supports'
                and fact.verification_status = 'verified'
                and not fact.review_required
                and (fact.expires_at is null or fact.expires_at >= p_now)
                and (fact.effective_until is null or fact.effective_until >= p_now)
          )
        group by question.subject
    ), eligible as (
        select
            job.id,
            job.status as prior_status,
            job.subject_key,
            job.due_at,
            greatest(
                0,
                150 - coalesce(capacity.verified_count, 0)
            ) as reserve_gap,
            row_number() over (
                partition by job.subject_key
                order by job.due_at, job.created_at, job.id
            ) as subject_slot
        from public.content_replenishment_jobs job
        left join verified_subject_capacity capacity
          on capacity.subject_key = job.subject_key
        where job.due_at <= p_now
          and (
              job.status = 'due'
              or (
                  job.status = 'retry_wait'
                  and coalesce(job.next_retry_at, job.due_at) <= p_now
              )
              or (
                  job.status in ('claimed', 'running')
                  and job.lease_expires_at <= p_now
              )
          )
    ), subject_recency as (
        select
            job.subject_key,
            max(event.created_at) as last_claimed_at
        from public.content_replenishment_jobs job
        join public.content_replenishment_job_events event
          on event.job_id = job.id
         and event.event_type = 'claimed'
        group by job.subject_key
    ), candidates as (
        select job.id, eligible.prior_status
        from eligible
        join public.content_replenishment_jobs job on job.id = eligible.id
        left join subject_recency recency
          on recency.subject_key = eligible.subject_key
        order by
            case when eligible.reserve_gap > 0 then 0 else 1 end,
            eligible.subject_slot,
            eligible.reserve_gap desc,
            recency.last_claimed_at asc nulls first,
            eligible.due_at,
            eligible.subject_key,
            job.id
        for update of job skip locked
        limit greatest(1, least(coalesce(p_limit, 5), 25))
    ), claimed as (
        update public.content_replenishment_jobs job
        set status = 'claimed',
            worker_id = p_worker_id,
            claimed_at = p_now,
            lease_expires_at = p_now + make_interval(
                mins => greatest(5, least(coalesce(p_lease_minutes, 20), 120))
            ),
            next_retry_at = null,
            updated_at = now()
        from candidates
        where job.id = candidates.id
        returning job.*, candidates.prior_status
    ), events as (
        insert into public.content_replenishment_job_events (
            job_id, event_type, from_status, to_status, worker_id
        )
        select id, 'claimed', prior_status, status, worker_id
        from claimed
        returning 1
    )
    select
        id, logical_date, subject_key, micro_topic_id, due_at, status,
        target_candidate_count, generation_batch_size, accepted_count,
        rejected_count, retry_count, next_retry_at, worker_id, claimed_at,
        lease_expires_at, last_error_code, created_at, updated_at
    from claimed
    order by subject_key, due_at, id;
end;
$$;

comment on function public.claim_content_replenishment_jobs(
    text, timestamptz, integer, integer
) is 'Claims under-reserve subjects in fair rounds, prioritizing larger gaps within each bounded round.';

revoke all on function public.claim_content_replenishment_jobs(
    text, timestamptz, integer, integer
) from public, anon, authenticated;
grant execute on function public.claim_content_replenishment_jobs(
    text, timestamptz, integer, integer
) to service_role;

alter function public.get_platform_contract_v1()
    rename to get_platform_contract_v1_before_reserve_round_robin;

revoke all on function public.get_platform_contract_v1_before_reserve_round_robin()
    from public, anon, authenticated;

create function public.get_platform_contract_v1()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_checks jsonb;
    v_missing jsonb;
    v_migration_applied boolean := false;
begin
    v_base := public.get_platform_contract_v1_before_reserve_round_robin();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = '20260904172137'
                   or name = 'reserve_tier_round_robin_claims'
            )
        $migration_check$ into v_migration_applied;
    end if;

    v_checks := coalesce(v_base->'checks', '{}'::jsonb)
        || jsonb_build_object(
            'reserveRoundRobinReplenishment',
            v_migration_applied
        );

    select coalesce(jsonb_agg(key order by key), '[]'::jsonb)
    into v_missing
    from jsonb_each(v_checks)
    where value is distinct from 'true'::jsonb;

    return v_base || jsonb_build_object(
        'ready',
            coalesce((v_base->>'ready')::boolean, false)
                and v_migration_applied,
        'contract_version', '1.3.0',
        'required_migration_version', '20260904172137',
        'migration_applied', v_migration_applied,
        'checks', v_checks,
        'missing_checks', v_missing
    );
end;
$$;

revoke all on function public.get_platform_contract_v1()
    from public, anon, authenticated;
grant execute on function public.get_platform_contract_v1() to service_role;
