-- Prevent a large verified-content backlog in one subject from starving every
-- later subject. Each claim round prefers the first eligible job per subject,
-- then the second, and orders subjects by their most recent durable claim.

create index if not exists idx_content_replenishment_claim_events
    on public.content_replenishment_job_events (job_id, created_at desc)
    where event_type = 'claimed';

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
    with eligible as (
        select
            job.id,
            job.status as prior_status,
            job.subject_key,
            job.due_at,
            row_number() over (
                partition by job.subject_key
                order by job.due_at, job.created_at, job.id
            ) as subject_slot
        from public.content_replenishment_jobs job
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
            eligible.subject_slot,
            recency.last_claimed_at asc nulls first,
            eligible.due_at,
            eligible.subject_key,
            job.id
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
    select
        id, logical_date, subject_key, micro_topic_id, due_at, status,
        target_candidate_count, generation_batch_size, accepted_count,
        rejected_count, retry_count, next_retry_at, worker_id, claimed_at,
        lease_expires_at, last_error_code, created_at, updated_at
    from claimed
    order by subject_key, due_at, id;
end;
$$;

comment on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)
is 'Claims bounded replenishment work fairly across subjects before taking additional same-subject backlog jobs.';
