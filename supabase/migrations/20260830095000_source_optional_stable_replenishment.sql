-- Replenish every stable-subject micro-topic that has an operator-verified
-- source, while retaining the explicit rotation allowlist for current affairs.
-- This changes queue eligibility only; it does not activate chapters, publish
-- questions, alter historical rows, or weaken candidate verification.

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
        where topic.active
          and chapter.active
          and (
              chapter.rotation_enabled
              or chapter.subject_key <> 'current-affairs'
          )
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

comment on function public.ensure_due_content_replenishment_jobs(timestamptz)
is 'Ensures bounded jobs for source-backed stable topics and rotation-approved current-affairs topics.';

revoke all on function public.ensure_due_content_replenishment_jobs(timestamptz)
    from public, anon, authenticated;
grant execute on function public.ensure_due_content_replenishment_jobs(timestamptz)
    to service_role;
