-- Repair chapter difficulty gaps without changing publication, source approval,
-- claim fairness, batch limits, or the existing public RPC signatures.
create function public.get_verified_chapter_difficulty_counts(p_now timestamptz default now())
returns table (chapter_id uuid, easy bigint, medium bigint, hard bigint, total bigint)
language sql
stable
security invoker
set search_path = ''
as $$
    -- Filter once before joining the catalogue, avoiding subject-wide fanout
    -- across every chapter when the planner underestimates eligible inventory.
    with verified as materialized (
    select question.micro_topic_id, question.subject, question.difficulty
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
    )
    select topic.chapter_id,
        count(*) filter (where question.difficulty = 'easy'),
        count(*) filter (where question.difficulty = 'medium'),
        count(*) filter (where question.difficulty = 'hard'),
        count(*)
    from verified question
    join public.quiz_micro_topics topic on topic.id = question.micro_topic_id
    join public.quiz_chapters chapter
      on chapter.id = topic.chapter_id and chapter.subject_key = question.subject
    group by topic.chapter_id;
$$;

create or replace function public.ensure_due_content_replenishment_jobs_source_optional_base(
    p_now timestamptz default now()
)
returns setof public.content_replenishment_jobs
language sql
security invoker
set search_path = ''
as $$
    with capacity as materialized (
        select * from public.get_verified_chapter_difficulty_counts(p_now)
    ), candidates as materialized (
        select (p_now at time zone 'Asia/Kolkata')::date as logical_date,
            chapter.subject_key, topic.id as micro_topic_id, p_now as due_at
        from public.quiz_micro_topics topic
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        left join capacity on capacity.chapter_id = chapter.id
        where topic.active and chapter.active
          and (chapter.rotation_enabled or chapter.subject_key <> 'current-affairs')
          and exists (
              select 1 from public.source_documents source
              where source.micro_topic_id = topic.id
                and source.verification_status = 'verified'
                and not source.review_required
                and (source.expires_at is null or source.expires_at >= p_now)
          )
          and (
              coalesce(capacity.easy, 0) < 3
              or coalesce(capacity.medium, 0) < 5
              or coalesce(capacity.hard, 0) < 2
              or (
                  select count(*) from public.questions question
                  where question.micro_topic_id = topic.id
                    and question.status = 'active'
                    and question.verification_status = 'verified'
                    and question.inventory_status in ('verified', 'used')
                    and not question.review_required
                    and question.knowledge_point_id is not null
                    and question.variant_fingerprint is not null
                    and (question.expires_at is null or question.expires_at >= p_now)
              ) < 12
          )
    ), inserted as (
        insert into public.content_replenishment_jobs (
            logical_date, subject_key, micro_topic_id, due_at,
            target_candidate_count, generation_batch_size
        )
        select candidate.logical_date, candidate.subject_key,
            candidate.micro_topic_id, candidate.due_at, 15, 5
        from candidates candidate
        where not exists (
            select 1 from public.content_replenishment_jobs existing
            where existing.subject_key = candidate.subject_key
              and existing.micro_topic_id = candidate.micro_topic_id
              and existing.status in ('due', 'claimed', 'running', 'retry_wait')
        )
        on conflict do nothing
        returning public.content_replenishment_jobs.*
    ), events as (
        insert into public.content_replenishment_job_events (job_id, event_type, to_status)
        select id, 'auto_ensured', status from inserted returning 1
    ), ensured as (
        select distinct on (candidate.subject_key, candidate.micro_topic_id) job.*
        from candidates candidate
        join public.content_replenishment_jobs job
          on job.subject_key = candidate.subject_key
         and job.micro_topic_id = candidate.micro_topic_id
         and (job.status in ('due', 'claimed', 'running', 'retry_wait')
              or job.logical_date = candidate.logical_date)
        order by candidate.subject_key, candidate.micro_topic_id,
            case when job.status in ('due', 'claimed', 'running', 'retry_wait') then 0 else 1 end,
            job.accepted_count desc, job.created_at, job.id
    )
    -- Include inserted rows directly: the base-table snapshot cannot see them.
    select * from ensured
    union all
    select * from inserted
    order by due_at, subject_key, micro_topic_id;
$$;

-- Preserve the existing source selection and append optional metadata. Older
-- application releases ignore this field, so application rollback stays safe.
alter function public.get_content_replenishment_bundle(uuid,timestamptz,integer)
    rename to get_content_replenishment_bundle_source_base;

create function public.get_content_replenishment_bundle(
    p_job_id uuid, p_now timestamptz default now(), p_limit integer default 8
)
returns setof jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with capacity as materialized (
        select counts.easy, counts.medium, counts.hard
        from public.content_replenishment_jobs job
        join public.quiz_micro_topics topic on topic.id = job.micro_topic_id
        join public.get_verified_chapter_difficulty_counts(p_now) counts
          on counts.chapter_id = topic.chapter_id
        where job.id = p_job_id
    )
    select bundle || jsonb_build_object('difficulty_counts', jsonb_build_object(
        'easy', coalesce(capacity.easy, 0),
        'medium', coalesce(capacity.medium, 0),
        'hard', coalesce(capacity.hard, 0)
    ))
    from public.get_content_replenishment_bundle_source_base(p_job_id, p_now, p_limit) bundle
    left join capacity on true;
$$;

revoke all on function public.get_verified_chapter_difficulty_counts(timestamptz)
    from public, anon, authenticated;
revoke all on function public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)
    from public, anon, authenticated;
revoke all on function public.get_content_replenishment_bundle_source_base(uuid,timestamptz,integer)
    from public, anon, authenticated;
revoke all on function public.get_content_replenishment_bundle(uuid,timestamptz,integer)
    from public, anon, authenticated;
grant execute on function public.get_verified_chapter_difficulty_counts(timestamptz) to service_role;
grant execute on function public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)
    to service_role;
grant execute on function public.get_content_replenishment_bundle_source_base(uuid,timestamptz,integer)
    to service_role;
grant execute on function public.get_content_replenishment_bundle(uuid,timestamptz,integer)
    to service_role;
