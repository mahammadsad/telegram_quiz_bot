-- Allow the preparation view to serve historical packs created before
-- questions carried normalized micro-topic IDs. Compatibility is fail-closed:
-- an old question is mapped only when its subject key and chapter name resolve
-- to the single canonical legacy :core topic for that chapter. No question row
-- is rewritten.

create or replace function public.get_quiz_learning_resources(
    p_quiz_id text,
    p_limit_per_language integer default 3
)
returns table (
    subject_key text,
    subject_name text,
    chapter_key text,
    chapter_name text,
    micro_topic_key text,
    micro_topic_name text,
    resource_id uuid,
    language text,
    resource_type text,
    title text,
    url text,
    source_name text,
    source_domain text,
    youtube_video_id text,
    duration_seconds integer,
    thumbnail_url text,
    description text,
    quality_score numeric,
    relevance_score numeric,
    published_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
    with quiz_question_topics as (
        select
            qq.question_order,
            coalesce(q.micro_topic_id, keyed_mt.id, legacy_mt.id) as micro_topic_id
        from public.quiz_questions qq
        join public.questions q on q.id = qq.question_id
        left join public.quiz_micro_topics keyed_mt
            on q.micro_topic_id is null
           and nullif(q.micro_topic_key, '') is not null
           and keyed_mt.key = q.micro_topic_key
        left join public.quiz_chapters legacy_c
            on q.micro_topic_id is null
           and keyed_mt.id is null
           and legacy_c.subject_key = q.subject
           and legacy_c.name = q.topic
           and legacy_c.active
        left join public.quiz_micro_topics legacy_mt
            on legacy_mt.chapter_id = legacy_c.id
           and right(legacy_mt.key, 5) = ':core'
           and legacy_mt.active
        where qq.quiz_id = p_quiz_id
    ),
    quiz_topics as (
        select
            micro_topic_id,
            min(question_order) as first_question_order
        from quiz_question_topics
        where micro_topic_id is not null
        group by micro_topic_id
    ),
    ranked as (
        select
            lr.*,
            row_number() over (
                partition by lr.micro_topic_id, lr.language
                order by lr.relevance_score desc, lr.quality_score desc,
                         lr.published_at desc nulls last, lr.id
            ) as resource_rank
        from public.learning_resources lr
        join quiz_topics qt on qt.micro_topic_id = lr.micro_topic_id
        where lr.verified
          and lr.verification_status = 'verified'
          and lr.is_active
    )
    select
        s.subject_key,
        s.display_name,
        c.key,
        c.name,
        mt.key,
        mt.name,
        r.id,
        r.language,
        r.resource_type,
        r.title,
        r.url,
        r.source_name,
        r.source_domain,
        r.youtube_video_id,
        r.duration_seconds,
        r.thumbnail_url,
        r.description,
        r.quality_score,
        r.relevance_score,
        r.published_at
    from quiz_topics qt
    join public.quiz_micro_topics mt on mt.id = qt.micro_topic_id
    join public.quiz_chapters c on c.id = mt.chapter_id
    join public.quiz_subjects s on s.subject_key = c.subject_key
    left join ranked r
        on r.micro_topic_id = qt.micro_topic_id
       and r.resource_rank <= greatest(1, least(coalesce(p_limit_per_language, 3), 3))
    order by qt.first_question_order,
             case r.language when 'bn' then 1 when 'hi' then 2 when 'en' then 3 else 4 end,
             r.resource_rank;
$$;

revoke execute on function public.get_quiz_learning_resources(text, integer)
    from public, anon, authenticated;
grant execute on function public.get_quiz_learning_resources(text, integer)
    to service_role;
