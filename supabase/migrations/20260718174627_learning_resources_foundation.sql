-- Cached, operator-approved learning resources for the exact micro-topics in a
-- quiz pack. Resource content stays at the publisher; this table stores only
-- metadata and links. All reads pass through the server-side RPC below.

create table if not exists public.learning_resources (
    id uuid primary key default extensions.gen_random_uuid(),
    subject_key text not null references public.quiz_subjects(subject_key) on delete restrict,
    chapter_key text not null check (
        chapter_key = lower(chapter_key) and chapter_key !~ '[[:space:]]'
    ),
    micro_topic_id uuid not null references public.quiz_micro_topics(id) on delete restrict,
    micro_topic_key text not null references public.quiz_micro_topics(key) on delete restrict,
    source_document_id uuid references public.source_documents(id) on delete restrict,
    language text not null check (language in ('bn','hi','en')),
    resource_type text not null check (
        resource_type in ('youtube','article','official_webpage','pdf','study_note','internal_note')
    ),
    title text not null check (length(btrim(title)) between 3 and 300),
    url text not null check (url ~ '^https://'),
    source_name text not null check (length(btrim(source_name)) between 2 and 160),
    source_domain text not null check (
        source_domain = lower(source_domain) and source_domain !~ '[/:[:space:]]'
    ),
    youtube_video_id text,
    duration_seconds integer check (duration_seconds is null or duration_seconds > 0),
    thumbnail_url text check (thumbnail_url is null or thumbnail_url ~ '^https://'),
    description text check (description is null or length(btrim(description)) <= 500),
    quality_score numeric not null default 0.80 check (quality_score between 0 and 1),
    relevance_score numeric not null default 0.80 check (relevance_score between 0 and 1),
    verified boolean not null default false,
    verification_status text not null default 'pending_review' check (
        verification_status in ('pending_review','verified','rejected','stale','archived')
    ),
    is_active boolean not null default false,
    last_checked_at timestamptz,
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    approved_by text,
    verified_at timestamptz,
    failure_count integer not null default 0 check (failure_count >= 0),
    unique (micro_topic_id, language, url),
    check (micro_topic_key = lower(micro_topic_key) and micro_topic_key !~ '[[:space:]]'),
    check (verified = (verification_status = 'verified')),
    check (
        verification_status <> 'verified'
        or (approved_by is not null and verified_at is not null and last_checked_at is not null)
    ),
    check (
        resource_type = 'youtube'
        or (youtube_video_id is null and duration_seconds is null)
    ),
    check (
        youtube_video_id is null
        or youtube_video_id ~ '^[A-Za-z0-9_-]{11}$'
    )
);

create or replace function public.validate_learning_resource_taxonomy()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_subject_key text;
    v_chapter_key text;
    v_micro_topic_key text;
begin
    select c.subject_key, c.key, mt.key
    into v_subject_key, v_chapter_key, v_micro_topic_key
    from public.quiz_micro_topics mt
    join public.quiz_chapters c on c.id = mt.chapter_id
    where mt.id = new.micro_topic_id;

    if v_subject_key is null
       or new.subject_key <> v_subject_key
       or new.chapter_key <> v_chapter_key
       or new.micro_topic_key <> v_micro_topic_key then
        raise exception 'learning resource taxonomy does not match its normalized micro-topic';
    end if;
    return new;
end;
$$;

drop trigger if exists validate_learning_resource_taxonomy on public.learning_resources;
create trigger validate_learning_resource_taxonomy
before insert or update of subject_key, chapter_key, micro_topic_id, micro_topic_key
on public.learning_resources
for each row execute function public.validate_learning_resource_taxonomy();

create or replace function public.protect_verified_learning_resource()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if old.verified and (
        new.subject_key is distinct from old.subject_key
        or new.chapter_key is distinct from old.chapter_key
        or new.micro_topic_id is distinct from old.micro_topic_id
        or new.micro_topic_key is distinct from old.micro_topic_key
        or new.source_document_id is distinct from old.source_document_id
        or new.language is distinct from old.language
        or new.resource_type is distinct from old.resource_type
        or new.title is distinct from old.title
        or new.url is distinct from old.url
        or new.source_name is distinct from old.source_name
        or new.source_domain is distinct from old.source_domain
        or new.youtube_video_id is distinct from old.youtube_video_id
        or new.duration_seconds is distinct from old.duration_seconds
        or new.thumbnail_url is distinct from old.thumbnail_url
        or new.description is distinct from old.description
        or new.quality_score is distinct from old.quality_score
        or new.relevance_score is distinct from old.relevance_score
        or new.published_at is distinct from old.published_at
    ) then
        raise exception 'verified learning-resource metadata is immutable; insert a new review candidate';
    end if;
    return new;
end;
$$;

drop trigger if exists protect_verified_learning_resource on public.learning_resources;
create trigger protect_verified_learning_resource
before update on public.learning_resources
for each row execute function public.protect_verified_learning_resource();

create index if not exists idx_learning_resources_quiz_lookup
    on public.learning_resources (
        micro_topic_id, verification_status, is_active, language,
        relevance_score desc, quality_score desc
    );
create index if not exists idx_learning_resources_review_queue
    on public.learning_resources (verification_status, updated_at)
    where verification_status in ('pending_review','stale');
create index if not exists idx_learning_resources_source_document
    on public.learning_resources (source_document_id)
    where source_document_id is not null;

-- Mirror only metadata from source facts that an operator has already approved.
-- The import script calls this after a source bundle is approved; running it here
-- also backfills environments where the Computer pilot already exists.
create or replace function public.cache_verified_source_resources(p_subject_key text)
returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_count bigint;
begin
    if p_subject_key is null or btrim(p_subject_key) = '' then
        raise exception 'subject key is required';
    end if;

    insert into public.learning_resources (
        subject_key, chapter_key, micro_topic_id, micro_topic_key,
        source_document_id, language, resource_type, title, url,
        source_name, source_domain, description, quality_score,
        relevance_score, verified, verification_status, is_active,
        last_checked_at, published_at, approved_by, verified_at
    )
    select
        c.subject_key,
        c.key,
        mt.id,
        mt.key,
        sd.id,
        'en',
        case
            when lower(sd.source_url) ~ '\.pdf($|[?#])' then 'pdf'
            else 'official_webpage'
        end,
        sd.source_title,
        sd.source_url,
        case
            when sd.source_domain = 'nios.ac.in' then 'NIOS'
            when sd.source_domain = 'support.microsoft.com' then 'Microsoft Support'
            when sd.source_domain = 'cybercrime.gov.in' then 'Ministry of Home Affairs'
            else sd.source_domain
        end,
        sd.source_domain,
        'Operator-approved reference used to ground this quiz topic.',
        case sd.source_kind when 'official' then 1.0 when 'primary' then 0.95 else 0.80 end,
        0.90,
        true,
        'verified',
        true,
        sd.source_accessed_at,
        sd.source_published_at,
        'approved-source-bundle',
        sd.verified_at
    from public.source_documents sd
    join public.quiz_micro_topics mt on mt.id = sd.micro_topic_id
    join public.quiz_chapters c on c.id = mt.chapter_id
    where c.subject_key = p_subject_key
      and c.key is not null
      and sd.verification_status = 'verified'
      and not sd.review_required
      and (sd.expires_at is null or sd.expires_at >= now())
    on conflict (micro_topic_id, language, url) do update set
        is_active = true,
        last_checked_at = excluded.last_checked_at,
        failure_count = 0,
        updated_at = now();

    get diagnostics v_count = row_count;
    return v_count;
end;
$$;

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
    with quiz_topics as (
        select
            q.micro_topic_id,
            min(qq.question_order) as first_question_order
        from public.quiz_questions qq
        join public.questions q on q.id = qq.question_id
        where qq.quiz_id = p_quiz_id
          and q.micro_topic_id is not null
        group by q.micro_topic_id
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

alter table public.learning_resources enable row level security;

revoke all on table public.learning_resources from public, anon, authenticated;
grant select, insert, update, delete on table public.learning_resources to service_role;

revoke execute on function public.validate_learning_resource_taxonomy()
    from public, anon, authenticated;
revoke execute on function public.protect_verified_learning_resource()
    from public, anon, authenticated;
revoke execute on function public.cache_verified_source_resources(text)
    from public, anon, authenticated;
revoke execute on function public.get_quiz_learning_resources(text, integer)
    from public, anon, authenticated;

grant execute on function public.validate_learning_resource_taxonomy() to service_role;
grant execute on function public.protect_verified_learning_resource() to service_role;
grant execute on function public.cache_verified_source_resources(text) to service_role;
grant execute on function public.get_quiz_learning_resources(text, integer) to service_role;

select public.cache_verified_source_resources('computer');
