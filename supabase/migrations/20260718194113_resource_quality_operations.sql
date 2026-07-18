-- Resource feedback, link-health history, quota-bounded discovery queues, and
-- safe operational diagnostics. All writes remain behind FastAPI/service role.

create table if not exists public.resource_feedback (
    id uuid primary key default extensions.gen_random_uuid(),
    resource_id uuid not null references public.learning_resources(id) on delete cascade,
    user_id uuid not null references public.users(id) on delete cascade,
    feedback_type text not null check (feedback_type in (
        'video_unavailable','article_unavailable','not_useful',
        'wrong_language','topic_mismatch','low_quality'
    )),
    rating smallint check (rating between 1 and 5),
    details text check (details is null or length(btrim(details)) <= 500),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (resource_id, user_id, feedback_type)
);

create index if not exists idx_resource_feedback_resource
    on public.resource_feedback (resource_id, feedback_type, updated_at desc);
create index if not exists idx_resource_feedback_user
    on public.resource_feedback (user_id, updated_at desc);

create table if not exists public.resource_link_checks (
    id bigint generated always as identity primary key,
    resource_id uuid not null references public.learning_resources(id) on delete cascade,
    outcome text not null check (outcome in ('available','hard_failure','transient_error')),
    status_code integer check (status_code is null or status_code between 100 and 599),
    error_category text not null check (error_category in (
        'ok','not_found','gone','video_unavailable','access_denied',
        'rate_limited','timeout','network_error','server_error',
        'invalid_url','unexpected_status'
    )),
    response_ms integer check (response_ms is null or response_ms between 0 and 300000),
    failure_count_after integer not null check (failure_count_after >= 0),
    checked_at timestamptz not null default now()
);

create index if not exists idx_resource_link_checks_resource
    on public.resource_link_checks (resource_id, checked_at desc);
create index if not exists idx_resource_link_checks_failures
    on public.resource_link_checks (checked_at desc, error_category)
    where outcome = 'hard_failure';

create table if not exists public.resource_discovery_queue (
    id uuid primary key default extensions.gen_random_uuid(),
    micro_topic_id uuid not null references public.quiz_micro_topics(id) on delete cascade,
    language text not null check (language in ('bn','hi')),
    reason text not null check (reason in (
        'missing','stale','broken_link','candidate_rejected','manual'
    )),
    status text not null default 'pending' check (status in (
        'pending','processing','candidate_ready','resolved','failed','paused'
    )),
    priority smallint not null default 2 check (priority between 1 and 5),
    attempt_count integer not null default 0 check (attempt_count >= 0),
    last_error_category text,
    processing_started_at timestamptz,
    last_queued_at timestamptz not null default now(),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (micro_topic_id, language)
);

create index if not exists idx_resource_discovery_pending
    on public.resource_discovery_queue (status, priority desc, last_queued_at)
    where status in ('pending','processing');

create table if not exists public.resource_channel_policies (
    channel_id text primary key check (length(btrim(channel_id)) between 3 and 100),
    channel_name text not null check (length(btrim(channel_name)) between 2 and 160),
    default_language text check (default_language in ('bn','hi','en')),
    policy text not null check (policy in ('preferred','trusted','blocked')),
    notes text check (notes is null or length(btrim(notes)) <= 500),
    reviewed_by text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create or replace function public.submit_resource_feedback(
    p_user_id uuid,
    p_resource_id uuid,
    p_feedback_type text,
    p_rating integer default null,
    p_details text default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if p_feedback_type not in (
        'video_unavailable','article_unavailable','not_useful',
        'wrong_language','topic_mismatch','low_quality'
    ) then
        raise exception 'invalid resource feedback type';
    end if;
    if p_rating is not null and p_rating not between 1 and 5 then
        raise exception 'rating must be between 1 and 5';
    end if;
    if p_details is not null and length(btrim(p_details)) > 500 then
        raise exception 'feedback details are too long';
    end if;
    if not exists (
        select 1 from public.learning_resources
        where id = p_resource_id and verification_status <> 'archived'
    ) then
        raise exception 'resource is not available';
    end if;

    insert into public.resource_feedback (
        resource_id, user_id, feedback_type, rating, details
    ) values (
        p_resource_id, p_user_id, p_feedback_type, p_rating,
        nullif(btrim(p_details), '')
    )
    on conflict (resource_id, user_id, feedback_type) do update set
        rating = excluded.rating,
        details = excluded.details,
        updated_at = now();

    return jsonb_build_object(
        'accepted', true,
        'resourceId', p_resource_id,
        'feedbackType', p_feedback_type
    );
end;
$$;

create or replace function public.get_resource_link_check_batch(
    p_limit integer default 50
)
returns table (
    resource_id uuid,
    url text,
    resource_type text,
    youtube_video_id text,
    failure_count integer,
    last_checked_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
select lr.id, lr.url, lr.resource_type, lr.youtube_video_id,
       lr.failure_count, lr.last_checked_at
from public.learning_resources lr
where lr.verified and lr.verification_status = 'verified' and lr.is_active
  and (
      lr.last_checked_at is null
      or lr.last_checked_at <= now() - case
          when lr.failure_count > 0 then interval '1 day'
          else interval '7 days'
      end
  )
order by lr.failure_count desc, lr.last_checked_at nulls first, lr.id
limit greatest(1, least(coalesce(p_limit, 50), 200));
$$;

create or replace function public.record_resource_link_check(
    p_resource_id uuid,
    p_outcome text,
    p_status_code integer default null,
    p_error_category text default 'ok',
    p_response_ms integer default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_resource public.learning_resources%rowtype;
    v_failures integer;
    v_deactivated boolean := false;
begin
    if p_outcome not in ('available','hard_failure','transient_error') then
        raise exception 'invalid link-check outcome';
    end if;
    if p_error_category not in (
        'ok','not_found','gone','video_unavailable','access_denied',
        'rate_limited','timeout','network_error','server_error',
        'invalid_url','unexpected_status'
    ) then
        raise exception 'invalid link-check category';
    end if;

    select * into v_resource
    from public.learning_resources
    where id = p_resource_id
    for update;
    if not found then raise exception 'resource does not exist'; end if;

    v_failures := case
        when p_outcome = 'available' then 0
        when p_outcome = 'hard_failure' then v_resource.failure_count + 1
        else v_resource.failure_count
    end;
    v_deactivated := p_outcome = 'hard_failure' and v_failures >= 3;

    update public.learning_resources
    set failure_count = v_failures,
        last_checked_at = now(),
        is_active = case when v_deactivated then false else is_active end,
        verified = case when v_deactivated then false else verified end,
        verification_status = case when v_deactivated then 'stale' else verification_status end,
        updated_at = now()
    where id = p_resource_id;

    insert into public.resource_link_checks (
        resource_id, outcome, status_code, error_category,
        response_ms, failure_count_after
    ) values (
        p_resource_id, p_outcome, p_status_code, p_error_category,
        p_response_ms, v_failures
    );

    if v_deactivated and v_resource.language in ('bn','hi') then
        insert into public.resource_discovery_queue (
            micro_topic_id, language, reason, status, priority
        ) values (
            v_resource.micro_topic_id, v_resource.language,
            'broken_link', 'pending', 5
        )
        on conflict (micro_topic_id, language) do update set
            reason = 'broken_link', status = 'pending', priority = 5,
            processing_started_at = null, last_error_category = null,
            last_queued_at = now(), updated_at = now();
    end if;

    return jsonb_build_object(
        'resourceId', p_resource_id,
        'outcome', p_outcome,
        'failureCount', v_failures,
        'deactivated', v_deactivated
    );
end;
$$;

create or replace function public.queue_missing_resource_discovery(
    p_limit integer default 200
)
returns integer
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_count integer;
begin
    with missing as (
        select mt.id as micro_topic_id, language.code as language,
               greatest(c.priority, mt.priority)::smallint as priority
        from public.quiz_micro_topics mt
        join public.quiz_chapters c on c.id = mt.chapter_id
        join public.quiz_subjects s on s.subject_key = c.subject_key
        cross join (values ('bn'),('hi')) as language(code)
        where mt.active and c.active and c.rotation_enabled and s.active
          and not exists (
              select 1 from public.learning_resources lr
              where lr.micro_topic_id = mt.id
                and lr.language = language.code
                and lr.verified and lr.verification_status = 'verified'
                and lr.is_active
          )
        order by greatest(c.priority, mt.priority) desc,
                 mt.last_used_at desc nulls last, c.subject_key, c.display_order, mt.key
        limit greatest(1, least(coalesce(p_limit, 200), 500))
    ), queued as (
        insert into public.resource_discovery_queue (
            micro_topic_id, language, reason, status, priority
        )
        select micro_topic_id, language, 'missing', 'pending', least(priority, 5)
        from missing
        on conflict (micro_topic_id, language) do update set
            reason = case
                when resource_discovery_queue.reason = 'broken_link'
                    then 'broken_link'
                else 'missing'
            end,
            status = case
                when resource_discovery_queue.status in ('resolved','failed')
                    then 'pending'
                else resource_discovery_queue.status
            end,
            last_queued_at = now(), updated_at = now()
        returning 1
    )
    select count(*) into v_count from queued;
    return v_count;
end;
$$;

create or replace function public.get_resource_discovery_batch(
    p_limit integer default 5
)
returns table (
    queue_id uuid,
    subject_key text,
    chapter_key text,
    chapter_name text,
    micro_topic_id uuid,
    micro_topic_key text,
    micro_topic_name text,
    language text,
    reason text,
    priority smallint
)
language plpgsql
security invoker
set search_path = ''
as $$
begin
    return query
    with claimed as (
        select q.id
        from public.resource_discovery_queue q
        where q.status = 'pending'
           or (q.status = 'processing' and q.processing_started_at < now() - interval '1 hour')
        order by q.priority desc, q.last_queued_at, q.id
        for update skip locked
        limit greatest(1, least(coalesce(p_limit, 5), 20))
    ), updated as (
        update public.resource_discovery_queue q
        set status = 'processing', processing_started_at = now(),
            attempt_count = q.attempt_count + 1, updated_at = now()
        from claimed
        where q.id = claimed.id
        returning q.*
    )
    select u.id, c.subject_key, c.key, c.name, mt.id, mt.key, mt.name,
           u.language, u.reason, u.priority
    from updated u
    join public.quiz_micro_topics mt on mt.id = u.micro_topic_id
    join public.quiz_chapters c on c.id = mt.chapter_id
    order by u.priority desc, u.last_queued_at, u.id;
end;
$$;

create or replace function public.save_youtube_resource_candidate(
    p_queue_id uuid,
    p_title text,
    p_url text,
    p_source_name text,
    p_channel_id text,
    p_video_id text,
    p_duration_seconds integer,
    p_thumbnail_url text default null,
    p_description text default null,
    p_published_at timestamptz default null,
    p_quality_score numeric default 0.70,
    p_relevance_score numeric default 0.75
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_queue public.resource_discovery_queue%rowtype;
    v_topic public.quiz_micro_topics%rowtype;
    v_chapter public.quiz_chapters%rowtype;
    v_resource_id uuid;
begin
    select * into v_queue
    from public.resource_discovery_queue
    where id = p_queue_id
    for update;
    if not found or v_queue.status <> 'processing' then
        raise exception 'discovery queue item is not processing';
    end if;
    if exists (
        select 1 from public.resource_channel_policies
        where channel_id = p_channel_id and policy = 'blocked'
    ) then
        raise exception 'resource channel is blocked';
    end if;
    if p_video_id !~ '^[A-Za-z0-9_-]{11}$'
       or p_url <> 'https://www.youtube.com/watch?v=' || p_video_id then
        raise exception 'invalid youtube candidate';
    end if;

    select * into v_topic from public.quiz_micro_topics where id = v_queue.micro_topic_id;
    select * into v_chapter from public.quiz_chapters where id = v_topic.chapter_id;

    insert into public.learning_resources (
        subject_key, chapter_key, micro_topic_id, micro_topic_key,
        language, resource_type, title, url, source_name, source_domain,
        youtube_video_id, duration_seconds, thumbnail_url, description,
        quality_score, relevance_score, verified, verification_status,
        is_active, published_at
    ) values (
        v_chapter.subject_key, v_chapter.key, v_topic.id, v_topic.key,
        v_queue.language, 'youtube', btrim(p_title), p_url,
        btrim(p_source_name), 'youtube.com', p_video_id,
        p_duration_seconds, p_thumbnail_url, nullif(btrim(p_description), ''),
        p_quality_score, p_relevance_score, false, 'pending_review',
        false, p_published_at
    )
    on conflict (micro_topic_id, language, url) do nothing
    returning id into v_resource_id;

    if v_resource_id is null then
        select id into v_resource_id
        from public.learning_resources
        where micro_topic_id = v_topic.id
          and language = v_queue.language and url = p_url;
    end if;
    update public.resource_discovery_queue
    set status = 'candidate_ready', processing_started_at = null,
        last_error_category = null, updated_at = now()
    where id = p_queue_id;

    return jsonb_build_object(
        'queueId', p_queue_id,
        'resourceId', v_resource_id,
        'status', 'pending_review'
    );
end;
$$;

create or replace function public.complete_resource_discovery(
    p_queue_id uuid,
    p_outcome text,
    p_error_category text default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_status text;
begin
    if p_outcome not in ('candidate_ready','no_candidate','transient_error','paused') then
        raise exception 'invalid discovery outcome';
    end if;
    v_status := case p_outcome
        when 'candidate_ready' then 'candidate_ready'
        when 'transient_error' then 'pending'
        when 'paused' then 'paused'
        else 'failed'
    end;
    update public.resource_discovery_queue
    set status = v_status,
        processing_started_at = null,
        last_error_category = nullif(btrim(p_error_category), ''),
        updated_at = now()
    where id = p_queue_id;
    if not found then raise exception 'discovery queue item does not exist'; end if;
    return jsonb_build_object('queueId', p_queue_id, 'status', v_status);
end;
$$;

create or replace function public.get_resource_review_queue(
    p_limit integer default 50,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with candidates as (
    select lr.*, mt.name as micro_topic_name, c.name as chapter_name,
           coalesce(f.feedback_count, 0) as feedback_count
    from public.learning_resources lr
    join public.quiz_micro_topics mt on mt.id = lr.micro_topic_id
    join public.quiz_chapters c on c.id = mt.chapter_id
    left join (
        select resource_id, count(*)::integer as feedback_count
        from public.resource_feedback group by resource_id
    ) f on f.resource_id = lr.id
    where lr.verification_status in ('pending_review','stale')
), page as (
    select * from candidates
    order by feedback_count desc, updated_at, id
    limit greatest(1, least(coalesce(p_limit, 50), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'total', (select count(*) from candidates),
    'limit', greatest(1, least(coalesce(p_limit, 50), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'resourceId', id, 'subjectKey', subject_key, 'chapter', chapter_name,
        'microTopicKey', micro_topic_key, 'microTopic', micro_topic_name,
        'language', language, 'type', resource_type, 'title', title,
        'url', url, 'source', source_name, 'status', verification_status,
        'qualityScore', quality_score, 'relevanceScore', relevance_score,
        'failureCount', failure_count, 'feedbackCount', feedback_count,
        'updatedAt', updated_at
    ) order by feedback_count desc, updated_at, id) from page), '[]'::jsonb)
);
$$;

create or replace function public.review_resource_candidate(
    p_resource_id uuid,
    p_decision text,
    p_actor text
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_resource public.learning_resources%rowtype;
begin
    if p_decision not in ('approve','reject','archive') then
        raise exception 'invalid resource review decision';
    end if;
    if length(btrim(p_actor)) not between 3 and 100 then
        raise exception 'review actor is required';
    end if;
    select * into v_resource
    from public.learning_resources where id = p_resource_id for update;
    if not found then raise exception 'resource does not exist'; end if;

    if p_decision = 'approve' then
        update public.learning_resources
        set verified = true, verification_status = 'verified', is_active = true,
            last_checked_at = now(), verified_at = now(),
            approved_by = btrim(p_actor), failure_count = 0, updated_at = now()
        where id = p_resource_id;
        update public.resource_discovery_queue
        set status = 'resolved', processing_started_at = null, updated_at = now()
        where micro_topic_id = v_resource.micro_topic_id
          and language = v_resource.language;
    elsif p_decision = 'reject' then
        update public.learning_resources
        set verified = false, verification_status = 'rejected', is_active = false,
            approved_by = btrim(p_actor), updated_at = now()
        where id = p_resource_id;
        update public.resource_discovery_queue
        set status = 'pending', reason = 'candidate_rejected',
            priority = least(5, priority + 1), processing_started_at = null,
            last_queued_at = now(), updated_at = now()
        where micro_topic_id = v_resource.micro_topic_id
          and language = v_resource.language;
    else
        update public.learning_resources
        set verified = false, verification_status = 'archived', is_active = false,
            approved_by = btrim(p_actor), updated_at = now()
        where id = p_resource_id;
        update public.resource_discovery_queue
        set status = 'paused', processing_started_at = null, updated_at = now()
        where micro_topic_id = v_resource.micro_topic_id
          and language = v_resource.language;
    end if;

    return jsonb_build_object(
        'resourceId', p_resource_id,
        'decision', p_decision,
        'status', case p_decision
            when 'approve' then 'verified'
            when 'reject' then 'rejected'
            else 'archived'
        end
    );
end;
$$;

create or replace function public.get_operational_status()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'databaseConnectivity', true,
    'schemaReady',
        to_regclass('public.quiz_runs') is not null
        and to_regclass('public.learning_resources') is not null
        and to_regclass('public.resource_feedback') is not null
        and to_regprocedure('public.submit_quiz_attempt_atomic(text,uuid,text,jsonb,integer,jsonb,jsonb)') is not null
        and to_regprocedure('public.submit_resource_feedback(uuid,uuid,text,integer,text)') is not null,
    'latestSuccessfulGeneration', coalesce((
        select jsonb_build_object('quizId', quiz_id, 'at', generated_at)
        from public.quiz_runs where generated_at is not null
        order by generated_at desc limit 1
    ), 'null'::jsonb),
    'latestSuccessfulPosting', coalesce((
        select jsonb_build_object('quizId', quiz_id, 'at', posted_at)
        from public.quiz_runs where status = 'posted' and posted_at is not null
        order by posted_at desc limit 1
    ), 'null'::jsonb),
    'failedRunsToday', (
        select count(*) from public.quiz_runs
        where quiz_date = current_date
          and status in ('generation_failed','posting_failed','posting_unknown')
    ),
    'postingUnknown', (
        select count(*) from public.quiz_runs where status = 'posting_unknown'
    ),
    'resources', jsonb_build_object(
        'activeVerified', (select count(*) from public.learning_resources
            where verified and verification_status = 'verified' and is_active),
        'dueChecks', (select count(*) from public.learning_resources
            where verified and verification_status = 'verified' and is_active
              and (last_checked_at is null or last_checked_at <= now() - interval '7 days')),
        'hardFailures24h', (select count(*) from public.resource_link_checks
            where outcome = 'hard_failure' and checked_at >= now() - interval '24 hours'),
        'deactivated', (select count(*) from public.learning_resources
            where verification_status = 'stale' and not is_active),
        'feedbackItems', (select count(*) from public.resource_feedback),
        'pendingReviews', (select count(*) from public.learning_resources
            where verification_status in ('pending_review','stale')),
        'discoveryPending', (select count(*) from public.resource_discovery_queue
            where status in ('pending','processing'))
    )
);
$$;

alter table public.resource_feedback enable row level security;
alter table public.resource_link_checks enable row level security;
alter table public.resource_discovery_queue enable row level security;
alter table public.resource_channel_policies enable row level security;

revoke all on table public.resource_feedback from public, anon, authenticated;
revoke all on table public.resource_link_checks from public, anon, authenticated;
revoke all on table public.resource_discovery_queue from public, anon, authenticated;
revoke all on table public.resource_channel_policies from public, anon, authenticated;
grant select, insert, update, delete on table public.resource_feedback to service_role;
grant select, insert, update, delete on table public.resource_link_checks to service_role;
grant select, insert, update, delete on table public.resource_discovery_queue to service_role;
grant select, insert, update, delete on table public.resource_channel_policies to service_role;
revoke all on sequence public.resource_link_checks_id_seq from public, anon, authenticated;
grant usage, select on sequence public.resource_link_checks_id_seq to service_role;

revoke execute on function public.submit_resource_feedback(uuid, uuid, text, integer, text)
    from public, anon, authenticated;
revoke execute on function public.get_resource_link_check_batch(integer)
    from public, anon, authenticated;
revoke execute on function public.record_resource_link_check(uuid, text, integer, text, integer)
    from public, anon, authenticated;
revoke execute on function public.queue_missing_resource_discovery(integer)
    from public, anon, authenticated;
revoke execute on function public.get_resource_discovery_batch(integer)
    from public, anon, authenticated;
revoke execute on function public.save_youtube_resource_candidate(uuid, text, text, text, text, text, integer, text, text, timestamptz, numeric, numeric)
    from public, anon, authenticated;
revoke execute on function public.complete_resource_discovery(uuid, text, text)
    from public, anon, authenticated;
revoke execute on function public.get_resource_review_queue(integer, integer)
    from public, anon, authenticated;
revoke execute on function public.review_resource_candidate(uuid, text, text)
    from public, anon, authenticated;
revoke execute on function public.get_operational_status()
    from public, anon, authenticated;

grant execute on function public.submit_resource_feedback(uuid, uuid, text, integer, text)
    to service_role;
grant execute on function public.get_resource_link_check_batch(integer) to service_role;
grant execute on function public.record_resource_link_check(uuid, text, integer, text, integer)
    to service_role;
grant execute on function public.queue_missing_resource_discovery(integer) to service_role;
grant execute on function public.get_resource_discovery_batch(integer) to service_role;
grant execute on function public.save_youtube_resource_candidate(uuid, text, text, text, text, text, integer, text, text, timestamptz, numeric, numeric)
    to service_role;
grant execute on function public.complete_resource_discovery(uuid, text, text) to service_role;
grant execute on function public.get_resource_review_queue(integer, integer) to service_role;
grant execute on function public.review_resource_candidate(uuid, text, text) to service_role;
grant execute on function public.get_operational_status() to service_role;
