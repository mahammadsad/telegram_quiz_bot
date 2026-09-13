-- Rotate eligible targets using durable claim history, not their original due
-- time: a repeatedly rejected old job must not monopolise a subject forever.
-- Keep reserve tiers, bounded claims, cooldowns and exclusive ownership intact.
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
        select question.subject as subject_key, count(*)::integer as verified_count
        from public.questions question
        join public.source_documents source on source.id = question.source_document_id
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
              select 1 from public.knowledge_point_evidence evidence
              join public.source_facts fact on fact.id = evidence.source_fact_id
              where evidence.knowledge_point_id = question.knowledge_point_id
                and evidence.support_type = 'supports'
                and fact.verification_status = 'verified'
                and not fact.review_required
                and (fact.expires_at is null or fact.expires_at >= p_now)
                and (fact.effective_until is null or fact.effective_until >= p_now)
          )
        group by question.subject
    ), claim_recency as materialized (
        select event.job_id, max(event.created_at) as last_claimed_at,
            max(event.id) as last_claim_id
        from public.content_replenishment_job_events event
        where event.event_type = 'claimed'
        group by event.job_id
    ), eligible as (
        select job.id, job.status as prior_status, job.subject_key, job.due_at,
            greatest(0, 150 - coalesce(capacity.verified_count, 0)) as reserve_gap,
            row_number() over (
                partition by job.subject_key
                order by recent.last_claimed_at asc nulls first,
                    recent.last_claim_id asc nulls first,
                    job.due_at, job.created_at, job.id
            ) as subject_slot
        from public.content_replenishment_jobs job
        left join verified_subject_capacity capacity on capacity.subject_key = job.subject_key
        left join claim_recency recent on recent.job_id = job.id
        where job.due_at <= p_now
          and (
              job.status = 'due'
              or (job.status = 'retry_wait' and coalesce(job.next_retry_at, job.due_at) <= p_now)
              or (job.status in ('claimed', 'running') and job.lease_expires_at <= p_now)
          )
    ), subject_recency as (
        select job.subject_key, max(recent.last_claimed_at) as last_claimed_at,
            max(recent.last_claim_id) as last_claim_id
        from public.content_replenishment_jobs job
        join claim_recency recent on recent.job_id = job.id
        group by job.subject_key
    ), candidates as (
        select job.id, eligible.prior_status
        from eligible
        join public.content_replenishment_jobs job on job.id = eligible.id
        left join subject_recency recency on recency.subject_key = eligible.subject_key
        order by
            case when eligible.reserve_gap > 0 then 0 else 1 end,
            eligible.subject_slot,
            -- Recency precedes deficit within a reserve tier so repeated
            -- single-job RPC calls retain the same cross-subject fairness.
            recency.last_claimed_at asc nulls first,
            recency.last_claim_id asc nulls first,
            eligible.reserve_gap desc,
            eligible.due_at, eligible.subject_key, job.id
        for update of job skip locked
        limit greatest(1, least(coalesce(p_limit, 5), 25))
    ), claimed as (
        update public.content_replenishment_jobs job
        set status = 'claimed', worker_id = p_worker_id, claimed_at = p_now,
            lease_expires_at = p_now + make_interval(
                mins => greatest(5, least(coalesce(p_lease_minutes, 20), 120))
            ),
            next_retry_at = null, updated_at = now()
        from candidates
        where job.id = candidates.id
        returning job.*, candidates.prior_status
    ), events as (
        insert into public.content_replenishment_job_events (
            job_id, event_type, from_status, to_status, worker_id
        )
        select id, 'claimed', prior_status, status, worker_id from claimed
        returning 1
    )
    select id, logical_date, subject_key, micro_topic_id, due_at, status,
        target_candidate_count, generation_batch_size, accepted_count,
        rejected_count, retry_count, next_retry_at, worker_id, claimed_at,
        lease_expires_at, last_error_code, created_at, updated_at
    from claimed
    order by subject_key, due_at, id;
end;
$$;

comment on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)
is 'Claims eligible jobs in durable target and subject rounds within reserve tiers, without resetting retries or leasing waiting work.';

revoke all on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)
    from public, anon, authenticated;
grant execute on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)
    to service_role;
