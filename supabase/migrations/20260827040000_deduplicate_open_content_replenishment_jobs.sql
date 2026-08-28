-- Keep content replenishment capacity bounded by the number of actual targets.
-- Historical daily ensure calls created a new unfinished row for the same
-- subject/micro-topic on every logical date. Preserve every row and event, but
-- quarantine redundant unfinished work and enforce one open row per target.

do $$
begin
    if exists (
        select 1
        from public.content_replenishment_jobs
        where status in ('claimed', 'running')
          and lease_expires_at > now()
    ) then
        raise exception 'active content replenishment leases must finish before backlog consolidation';
    end if;
end;
$$;

with ranked as materialized (
    select
        job.id,
        job.status as prior_status,
        job.worker_id as prior_worker_id,
        row_number() over (
            partition by job.subject_key, job.micro_topic_id
            order by
                case when job.status in ('claimed', 'running') then 0 else 1 end,
                job.accepted_count desc,
                job.retry_count asc,
                job.created_at,
                job.id
        ) as target_rank
    from public.content_replenishment_jobs job
    where job.status in ('due', 'claimed', 'running', 'retry_wait')
), superseded as (
    update public.content_replenishment_jobs job
    set status = 'quarantined',
        next_retry_at = null,
        worker_id = null,
        claimed_at = null,
        lease_expires_at = null,
        last_error_code = 'superseded_open_job',
        updated_at = now()
    from ranked
    where job.id = ranked.id
      and ranked.target_rank > 1
    returning job.id, ranked.prior_status, ranked.prior_worker_id
)
insert into public.content_replenishment_job_events (
    job_id, event_type, from_status, to_status, worker_id, error_code
)
select
    id, 'backlog_superseded', prior_status, 'quarantined',
    prior_worker_id, 'superseded_open_job'
from superseded;

create unique index if not exists idx_content_replenishment_one_open_target
    on public.content_replenishment_jobs (subject_key, micro_topic_id) nulls not distinct
    where status in ('due', 'claimed', 'running', 'retry_wait');

create or replace function public.ensure_content_replenishment_job(
    p_logical_date date,
    p_subject_key text,
    p_micro_topic_id uuid,
    p_due_at timestamptz,
    p_target_candidate_count integer default 15,
    p_generation_batch_size integer default 5
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.content_replenishment_jobs%rowtype;
    v_inserted boolean := false;
begin
    if p_logical_date is null or p_due_at is null
       or nullif(btrim(p_subject_key), '') is null
       or p_target_candidate_count not between 12 and 15
       or p_generation_batch_size not between 3 and 5 then
        raise exception 'valid replenishment job specification is required';
    end if;

    select * into v_job
    from public.content_replenishment_jobs job
    where job.subject_key = p_subject_key
      and job.micro_topic_id is not distinct from p_micro_topic_id
      and job.status in ('due', 'claimed', 'running', 'retry_wait')
    order by job.created_at, job.id
    limit 1;

    if found then
        update public.content_replenishment_jobs job
        set due_at = least(job.due_at, p_due_at),
            updated_at = now()
        where job.id = v_job.id
        returning * into v_job;
    else
        insert into public.content_replenishment_jobs (
            logical_date, subject_key, micro_topic_id, due_at,
            target_candidate_count, generation_batch_size
        ) values (
            p_logical_date, p_subject_key, p_micro_topic_id, p_due_at,
            p_target_candidate_count, p_generation_batch_size
        )
        on conflict do nothing
        returning * into v_job;
        v_inserted := found;

        if not v_inserted then
            select * into v_job
            from public.content_replenishment_jobs job
            where job.subject_key = p_subject_key
              and job.micro_topic_id is not distinct from p_micro_topic_id
              and (
                  job.status in ('due', 'claimed', 'running', 'retry_wait')
                  or job.logical_date = p_logical_date
              )
            order by
                case when job.status in ('due', 'claimed', 'running', 'retry_wait') then 0 else 1 end,
                job.created_at,
                job.id
            limit 1;
        end if;
    end if;

    if v_job.id is null then
        raise exception 'replenishment job could not be ensured';
    end if;
    if v_inserted then
        insert into public.content_replenishment_job_events (
            job_id, event_type, to_status
        ) values (v_job.id, 'ensured', v_job.status);
    end if;
    return to_jsonb(v_job);
end;
$$;

create or replace function public.ensure_due_content_replenishment_jobs(
    p_now timestamptz default now()
)
returns setof public.content_replenishment_jobs
language sql
security invoker
set search_path = ''
as $$
    with candidates as materialized (
        select
            (p_now at time zone 'Asia/Kolkata')::date as logical_date,
            chapter.subject_key,
            topic.id as micro_topic_id,
            p_now as due_at
        from public.quiz_micro_topics topic
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        where topic.active and chapter.active and chapter.rotation_enabled
          and exists (
              select 1 from public.source_documents source
              where source.micro_topic_id = topic.id
                and source.verification_status = 'verified'
                and not source.review_required
                and (source.expires_at is null or source.expires_at >= p_now)
          )
          and (
              select count(*) from public.questions question
              where question.micro_topic_id = topic.id
                and question.status = 'active'
                and question.verification_status = 'verified'
                and question.inventory_status in ('verified','used')
                and not question.review_required
                and question.knowledge_point_id is not null
                and question.variant_fingerprint is not null
                and (question.expires_at is null or question.expires_at >= p_now)
          ) < 12
    ), inserted as (
        insert into public.content_replenishment_jobs (
            logical_date, subject_key, micro_topic_id, due_at,
            target_candidate_count, generation_batch_size
        )
        select
            candidate.logical_date, candidate.subject_key,
            candidate.micro_topic_id, candidate.due_at, 15, 5
        from candidates candidate
        where not exists (
            select 1
            from public.content_replenishment_jobs existing
            where existing.subject_key = candidate.subject_key
              and existing.micro_topic_id = candidate.micro_topic_id
              and existing.status in ('due', 'claimed', 'running', 'retry_wait')
        )
        on conflict do nothing
        returning public.content_replenishment_jobs.*
    ), events as (
        insert into public.content_replenishment_job_events (
            job_id, event_type, to_status
        )
        select id, 'auto_ensured', status from inserted
        returning 1
    ), ensured as (
        select distinct on (candidate.subject_key, candidate.micro_topic_id)
            job.*
        from candidates candidate
        join public.content_replenishment_jobs job
          on job.subject_key = candidate.subject_key
         and job.micro_topic_id = candidate.micro_topic_id
         and (
             job.status in ('due', 'claimed', 'running', 'retry_wait')
             or job.logical_date = candidate.logical_date
         )
        order by
            candidate.subject_key,
            candidate.micro_topic_id,
            case when job.status in ('due', 'claimed', 'running', 'retry_wait') then 0 else 1 end,
            job.accepted_count desc,
            job.created_at,
            job.id
    )
    select * from ensured order by due_at, subject_key, micro_topic_id;
$$;

create or replace function public.get_phase_c_inventory_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_functions(signature) as (values
        ('ensure_content_replenishment_job(date,text,uuid,timestamp with time zone,integer,integer)'),
        ('ensure_due_content_replenishment_jobs(timestamp with time zone)'),
        ('claim_content_replenishment_jobs(text,timestamp with time zone,integer,integer)'),
        ('complete_content_replenishment_batch(uuid,text,integer,integer,text[],text,timestamp with time zone)'),
        ('get_verified_question_inventory(text,timestamp with time zone,integer)'),
        ('get_recent_content_usage(text,timestamp with time zone)')
    ), permission_failures as (
        select role_name || ':' || signature as failure
        from required_functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
        union all
        select 'service_role:' || signature from required_functions
        where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
    ), facts as (
        select
            to_regclass('public.content_replenishment_jobs') is not null as jobs_ready,
            to_regclass('public.content_replenishment_job_events') is not null as events_ready,
            to_regclass('public.content_usage_events') is not null as usage_ready,
            to_regclass('public.idx_content_replenishment_one_open_target') is not null
                as open_job_uniqueness_ready,
            (
                select count(*)
                from (
                    select 1
                    from public.content_replenishment_jobs job
                    where job.status in ('due', 'claimed', 'running', 'retry_wait')
                    group by job.subject_key, job.micro_topic_id
                    having count(*) > 1
                ) duplicates
            ) as duplicate_open_job_count,
            coalesce(
                (select jsonb_agg(failure order by failure) from permission_failures),
                '[]'::jsonb
            ) as function_permission_failures
    )
    select jsonb_build_object(
        'ready', jobs_ready and events_ready and usage_ready
            and open_job_uniqueness_ready
            and duplicate_open_job_count = 0
            and jsonb_array_length(function_permission_failures) = 0,
        'inventory_jobs', jobs_ready,
        'usage_history', usage_ready,
        'open_job_uniqueness_ready', open_job_uniqueness_ready,
        'duplicate_open_job_count', duplicate_open_job_count,
        'replenishment_backlog_migration_version', '20260827040000',
        'function_permission_failures', function_permission_failures,
        'phase_c_inventory_migration_version', '20260808093621'
    ) from facts;
$$;

revoke all on function public.ensure_due_content_replenishment_jobs(timestamptz)
    from public, anon, authenticated;
revoke all on function public.ensure_content_replenishment_job(date,text,uuid,timestamptz,integer,integer)
    from public, anon, authenticated;
revoke all on function public.get_phase_c_inventory_contract()
    from public, anon, authenticated;
grant execute on function public.ensure_due_content_replenishment_jobs(timestamptz)
    to service_role;
grant execute on function public.ensure_content_replenishment_job(date,text,uuid,timestamptz,integer,integer)
    to service_role;
grant execute on function public.get_phase_c_inventory_contract()
    to service_role;
