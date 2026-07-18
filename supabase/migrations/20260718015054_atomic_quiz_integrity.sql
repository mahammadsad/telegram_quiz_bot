-- Atomic quiz lifecycle, ordered quiz packs, transactional attempts, and
-- privacy-safe SQL leaderboards. Additive and safe to rerun.

create extension if not exists pgcrypto;

alter table public.quiz_runs add column if not exists worker_id text;
alter table public.quiz_runs add column if not exists claimed_at timestamptz;
alter table public.quiz_runs add column if not exists claim_expires_at timestamptz;
alter table public.quiz_runs add column if not exists processing_started_at timestamptz;

alter table public.quiz_runs drop constraint if exists quiz_runs_status_check;
alter table public.quiz_runs add constraint quiz_runs_status_check check (
    status in (
        'pending', 'generating', 'generated', 'posting', 'posted',
        'generation_failed', 'posting_failed', 'posting_unknown'
    )
);

create index if not exists idx_quiz_runs_active_claims
    on public.quiz_runs (quiz_id, claim_expires_at)
    where worker_id is not null;

alter table public.users add column if not exists leaderboard_visible boolean not null default true;
alter table public.users add column if not exists public_display_name text;
alter table public.users add column if not exists username_visible boolean not null default false;

create table if not exists public.quiz_questions (
    id uuid primary key default gen_random_uuid(),
    quiz_id text not null references public.quiz_runs(quiz_id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    question_order smallint not null check (question_order between 1 and 10),
    created_at timestamptz not null default now(),
    unique (quiz_id, question_order),
    unique (quiz_id, question_id)
);

create index if not exists idx_quiz_questions_question
    on public.quiz_questions (question_id);

-- Preserve historical Mini App packs while removing the permanent dependency
-- on simulated Telegram poll IDs for all new packs.
insert into public.quiz_questions (quiz_id, question_id, question_order, created_at)
select ranked.run_slot, ranked.question_id, ranked.question_order, ranked.posted_at
from (
    select
        p.run_slot,
        p.question_id,
        p.posted_at,
        row_number() over (
            partition by p.run_slot
            order by p.telegram_message_id, p.id
        )::smallint as question_order
    from public.polls p
    join public.quiz_runs r on r.quiz_id = p.run_slot
    where p.bot_type = 'mock_test'
      and p.run_slot is not null
) ranked
where ranked.question_order between 1 and 10
on conflict do nothing;

create table if not exists public.quiz_attempts (
    id uuid primary key default gen_random_uuid(),
    quiz_id text not null,
    user_id uuid not null references public.users(id) on delete cascade,
    client_attempt_id text not null,
    answers jsonb not null check (jsonb_typeof(answers) = 'array'),
    answer_checksum text not null,
    score smallint not null check (score between 0 and 10),
    total smallint not null default 10 check (total = 10),
    answered smallint not null check (answered between 0 and 10),
    started_at timestamptz,
    completed_at timestamptz not null default now(),
    duration_seconds integer check (duration_seconds is null or duration_seconds >= 0),
    attempt_number integer not null check (attempt_number > 0),
    is_completed boolean not null default true,
    created_at timestamptz not null default now(),
    unique (quiz_id, user_id, client_attempt_id),
    unique (quiz_id, user_id, attempt_number)
);

create index if not exists idx_quiz_attempts_quiz_rank
    on public.quiz_attempts (
        quiz_id, score desc, answered desc, duration_seconds asc, completed_at asc
    ) where is_completed;
create index if not exists idx_quiz_attempts_user_history
    on public.quiz_attempts (user_id, completed_at desc);
create index if not exists idx_quiz_submissions_user_id
    on public.quiz_submissions (user_id);
create index if not exists idx_personal_review_schedule_question_id
    on public.personal_review_schedule (question_id);

create table if not exists public.quiz_attempt_answers (
    id uuid primary key default gen_random_uuid(),
    attempt_id uuid not null references public.quiz_attempts(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    question_order smallint not null check (question_order between 1 and 10),
    selected_option smallint check (selected_option between 0 and 3),
    correct_option smallint not null check (correct_option between 0 and 3),
    is_correct boolean,
    response_time_seconds numeric check (
        response_time_seconds is null or response_time_seconds >= 0
    ),
    marked_for_review boolean not null default false,
    answered_at timestamptz,
    created_at timestamptz not null default now(),
    unique (attempt_id, question_order),
    unique (attempt_id, question_id)
);

create index if not exists idx_quiz_attempt_answers_question
    on public.quiz_attempt_answers (question_id, is_correct);

-- Backfill the parent attempt history without modifying legacy submissions.
insert into public.quiz_attempts (
    id, quiz_id, user_id, client_attempt_id, answers, answer_checksum,
    score, total, answered, started_at, completed_at, duration_seconds,
    attempt_number, is_completed, created_at
)
select
    s.id,
    s.quiz_id,
    s.user_id,
    coalesce(nullif(s.client_attempt_id, ''), 'legacy:' || s.id::text),
    s.answers,
    encode(digest(s.answers::text, 'sha256'), 'hex'),
    s.score,
    s.total,
    s.answered,
    s.completed_at,
    s.completed_at,
    null,
    row_number() over (
        partition by s.quiz_id, s.user_id
        order by s.completed_at, s.id
    )::integer,
    true,
    s.completed_at
from public.quiz_submissions s
where jsonb_typeof(s.answers) = 'array'
  and jsonb_array_length(s.answers) = 10
on conflict do nothing;

insert into public.quiz_attempt_answers (
    attempt_id, question_id, question_order, selected_option, correct_option,
    is_correct, answered_at, created_at
)
select
    a.id,
    qq.question_id,
    qq.question_order,
    case when jsonb_typeof(answer.value) = 'null' then null
         else (answer.value #>> '{}')::smallint end,
    (strpos('ABCD', q.correct_option) - 1)::smallint,
    case when jsonb_typeof(answer.value) = 'null' then null
         else (answer.value #>> '{}')::smallint = strpos('ABCD', q.correct_option) - 1 end,
    case when jsonb_typeof(answer.value) = 'null' then null else a.completed_at end,
    a.created_at
from public.quiz_attempts a
join public.quiz_questions qq on qq.quiz_id = a.quiz_id
join public.questions q on q.id = qq.question_id
join lateral jsonb_array_elements(a.answers) with ordinality answer(value, ordinality)
  on answer.ordinality = qq.question_order
where jsonb_typeof(answer.value) = 'null'
   or (
       jsonb_typeof(answer.value) = 'number'
       and (answer.value #>> '{}') ~ '^[0-3]$'
   )
on conflict do nothing;

create or replace function public.claim_quiz_run(
    p_quiz_id text,
    p_worker_id text,
    p_target_status text,
    p_claim_timeout_minutes integer default 20,
    p_allow_completed boolean default false
)
returns setof public.quiz_runs
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(p_quiz_id), '') is null
       or nullif(btrim(p_worker_id), '') is null then
        raise exception 'quiz_id and worker_id are required';
    end if;
    if p_target_status not in ('generating', 'posting') then
        raise exception 'invalid claim target status';
    end if;

    return query
    update public.quiz_runs r
    set worker_id = p_worker_id,
        claimed_at = now(),
        claim_expires_at = now() + make_interval(
            mins => greatest(5, least(coalesce(p_claim_timeout_minutes, 20), 120))
        ),
        processing_started_at = coalesce(r.processing_started_at, now()),
        status = p_target_status,
        updated_at = now()
    where r.quiz_id = p_quiz_id
      and (p_allow_completed or r.status <> 'posted')
      and (
          r.worker_id is null
          or r.worker_id = p_worker_id
          or r.claim_expires_at is null
          or r.claim_expires_at <= now()
      )
    returning r.*;
end;
$$;

create or replace function public.save_quiz_pack_atomic(
    p_quiz_id text,
    p_worker_id text,
    p_questions jsonb,
    p_content_checksum text,
    p_replace boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_order integer;
    v_question_id uuid;
    v_existing public.questions%rowtype;
    v_mapping_count integer;
begin
    if jsonb_typeof(p_questions) <> 'array'
       or jsonb_array_length(p_questions) <> 10 then
        raise exception 'quiz pack must contain exactly 10 questions';
    end if;
    if nullif(btrim(p_content_checksum), '') is null then
        raise exception 'content checksum is required';
    end if;
    if not exists (
        select 1 from public.quiz_runs r
        where r.quiz_id = p_quiz_id
          and r.worker_id = p_worker_id
          and r.claim_expires_at > now()
    ) then
        raise exception 'quiz run is not owned by this worker';
    end if;

    select count(*) into v_mapping_count
    from public.quiz_questions qq where qq.quiz_id = p_quiz_id;
    if v_mapping_count = 10 and not p_replace then
        return jsonb_build_object(
            'quiz_id', p_quiz_id, 'question_count', 10, 'reused', true
        );
    end if;
    if v_mapping_count > 0 and not p_replace then
        raise exception 'existing quiz pack is incomplete; explicit replacement is required';
    end if;
    if p_replace then
        delete from public.quiz_questions where quiz_id = p_quiz_id;
    end if;

    v_order := 0;
    for v_item in select value from jsonb_array_elements(p_questions)
    loop
        v_order := v_order + 1;
        if nullif(btrim(v_item ->> 'question_hash'), '') is null
           or nullif(btrim(v_item ->> 'question_text'), '') is null
           or nullif(btrim(v_item ->> 'subject'), '') is null
           or nullif(btrim(v_item ->> 'topic'), '') is null
           or v_item ->> 'correct_option' not in ('A', 'B', 'C', 'D') then
            raise exception 'question % is missing required validated fields', v_order;
        end if;

        if v_item ? 'reuse_question_id' then
            select * into v_existing
            from public.questions q
            where q.id = (v_item ->> 'reuse_question_id')::uuid
            limit 1;
            if not found then
                raise exception 'requested reusable question does not exist at position %', v_order;
            end if;
        else
            select * into v_existing
            from public.questions q
            where q.question_hash = v_item ->> 'question_hash'
            limit 1;
        end if;

        if found then
            if v_existing.subject <> v_item ->> 'subject'
               or v_existing.topic <> v_item ->> 'topic' then
                raise exception 'question classification collision at position %', v_order;
            end if;
            v_question_id := v_existing.id;
        else
            insert into public.questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, explanation, detailed_explanation, subject,
                topic, difficulty, gemini_model, source, week_number, bot_type,
                question_hash, normalized_text, status
            ) values (
                v_item ->> 'question_text',
                v_item ->> 'option_a',
                v_item ->> 'option_b',
                v_item ->> 'option_c',
                v_item ->> 'option_d',
                v_item ->> 'correct_option',
                v_item ->> 'explanation',
                v_item ->> 'detailed_explanation',
                v_item ->> 'subject',
                v_item ->> 'topic',
                coalesce(nullif(v_item ->> 'difficulty', ''), 'medium'),
                nullif(v_item ->> 'gemini_model', ''),
                coalesce(nullif(v_item ->> 'source', ''), 'gemini_generated'),
                nullif(v_item ->> 'week_number', '')::integer,
                coalesce(nullif(v_item ->> 'bot_type', ''), 'mock_test'),
                v_item ->> 'question_hash',
                v_item ->> 'normalized_text',
                coalesce(nullif(v_item ->> 'status', ''), 'active')
            )
            returning id into v_question_id;
        end if;

        insert into public.quiz_questions (quiz_id, question_id, question_order)
        values (p_quiz_id, v_question_id, v_order);
    end loop;

    if (select count(*) from public.quiz_questions where quiz_id = p_quiz_id) <> 10 then
        raise exception 'atomic quiz save did not produce exactly 10 mappings';
    end if;

    update public.quiz_runs
    set status = 'generated',
        question_count = 10,
        content_checksum = p_content_checksum,
        generated_at = coalesce(generated_at, now()),
        updated_at = now()
    where quiz_id = p_quiz_id and worker_id = p_worker_id;

    return jsonb_build_object(
        'quiz_id', p_quiz_id, 'question_count', 10, 'reused', false
    );
end;
$$;

create or replace function public.quiz_attempt_result(p_attempt_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with target as (
    select * from public.quiz_attempts where id = p_attempt_id and is_completed
), review as (
    select coalesce(jsonb_agg(
        jsonb_build_object(
            'questionId', aa.question_id,
            'q', q.question_text,
            'o', jsonb_build_array(q.option_a, q.option_b, q.option_c, q.option_d),
            'selectedIndex', aa.selected_option,
            'correctIndex', aa.correct_option,
            'isCorrect', aa.is_correct,
            'explanation', coalesce(q.detailed_explanation, q.explanation, ''),
            'difficulty', q.difficulty,
            'chapter', q.topic
        ) order by aa.question_order
    ), '[]'::jsonb) as rows
    from public.quiz_attempt_answers aa
    join public.questions q on q.id = aa.question_id
    where aa.attempt_id = p_attempt_id
), latest as (
    select distinct on (a.user_id)
        a.user_id, a.score, a.answered, a.duration_seconds, a.completed_at, a.id
    from public.quiz_attempts a
    join target t on t.quiz_id = a.quiz_id
    where a.is_completed
    order by a.user_id, a.completed_at desc, a.id desc
), ranked as (
    select
        l.user_id,
        row_number() over (
            order by l.score desc, l.answered desc,
                     l.duration_seconds asc nulls last,
                     l.completed_at asc, l.id
        ) as rank
    from latest l
)
select jsonb_build_object(
    'quiz_id', t.quiz_id,
    'score', t.score,
    'best_score', (
        select max(a.score) from public.quiz_attempts a
        where a.quiz_id = t.quiz_id and a.user_id = t.user_id and a.is_completed
    ),
    'total', t.total,
    'answered', t.answered,
    'attempt_number', t.attempt_number,
    'rank', (select r.rank from ranked r where r.user_id = t.user_id),
    'participants', (select count(*) from latest),
    'duration_seconds', t.duration_seconds,
    'review', review.rows
)
from target t cross join review;
$$;

create or replace function public.submit_quiz_attempt_atomic(
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id text,
    p_answers jsonb,
    p_duration_seconds integer default null,
    p_response_times jsonb default null,
    p_marked_for_review jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt_id uuid;
    v_existing_answers jsonb;
    v_client_attempt_id text;
    v_score integer;
    v_answered integer;
    v_attempt_number integer;
begin
    if not exists (select 1 from public.users where id = p_user_id) then
        raise exception 'authenticated user does not exist';
    end if;
    if (select count(*) from public.quiz_questions where quiz_id = p_quiz_id) <> 10 then
        raise exception 'quiz must contain exactly 10 ordered questions';
    end if;
    if jsonb_typeof(p_answers) <> 'array' or jsonb_array_length(p_answers) <> 10 then
        raise exception 'answers must contain exactly 10 entries';
    end if;
    if exists (
        select 1 from jsonb_array_elements(p_answers) answer(value)
        where jsonb_typeof(answer.value) <> 'null'
          and not (
              jsonb_typeof(answer.value) = 'number'
              and (answer.value #>> '{}') ~ '^[0-3]$'
          )
    ) then
        raise exception 'each answer must be 0, 1, 2, 3, or null';
    end if;
    if p_duration_seconds is not null and p_duration_seconds < 0 then
        raise exception 'duration must not be negative';
    end if;

    v_client_attempt_id := coalesce(
        nullif(btrim(p_client_attempt_id), ''),
        'server:' || gen_random_uuid()::text
    );

    -- Serialize both the idempotency check and attempt-number allocation.
    perform pg_advisory_xact_lock(hashtextextended(p_quiz_id || ':' || p_user_id::text, 0));

    select id, answers into v_attempt_id, v_existing_answers
    from public.quiz_attempts
    where quiz_id = p_quiz_id
      and user_id = p_user_id
      and client_attempt_id = v_client_attempt_id;
    if found then
        if v_existing_answers <> p_answers then
            raise exception 'attempt identifier was already used with different answers';
        end if;
        return public.quiz_attempt_result(v_attempt_id);
    end if;

    select
        count(*) filter (where jsonb_typeof(answer.value) <> 'null'),
        count(*) filter (
            where jsonb_typeof(answer.value) <> 'null'
              and (answer.value #>> '{}')::integer = strpos('ABCD', q.correct_option) - 1
        )
    into v_answered, v_score
    from public.quiz_questions qq
    join public.questions q on q.id = qq.question_id
    join lateral jsonb_array_elements(p_answers) with ordinality answer(value, ordinality)
      on answer.ordinality = qq.question_order
    where qq.quiz_id = p_quiz_id;

    select coalesce(max(attempt_number), 0) + 1 into v_attempt_number
    from public.quiz_attempts
    where quiz_id = p_quiz_id and user_id = p_user_id;

    insert into public.quiz_attempts (
        quiz_id, user_id, client_attempt_id, answers, answer_checksum,
        score, total, answered, started_at, completed_at, duration_seconds,
        attempt_number, is_completed
    ) values (
        p_quiz_id, p_user_id, v_client_attempt_id, p_answers,
        encode(digest(p_answers::text, 'sha256'), 'hex'),
        v_score, 10, v_answered,
        case when p_duration_seconds is null then null
             else now() - make_interval(secs => p_duration_seconds) end,
        now(), p_duration_seconds, v_attempt_number, true
    ) returning id into v_attempt_id;

    insert into public.quiz_attempt_answers (
        attempt_id, question_id, question_order, selected_option,
        correct_option, is_correct, response_time_seconds,
        marked_for_review, answered_at
    )
    select
        v_attempt_id,
        qq.question_id,
        qq.question_order,
        case when jsonb_typeof(answer.value) = 'null' then null
             else (answer.value #>> '{}')::smallint end,
        (strpos('ABCD', q.correct_option) - 1)::smallint,
        case when jsonb_typeof(answer.value) = 'null' then null
             else (answer.value #>> '{}')::integer = strpos('ABCD', q.correct_option) - 1 end,
        case
            when jsonb_typeof(p_response_times) = 'array'
             and jsonb_array_length(p_response_times) = 10
             and jsonb_typeof(p_response_times -> (qq.question_order - 1)) = 'number'
            then greatest(0, (p_response_times ->> (qq.question_order - 1))::numeric)
            else null
        end,
        case
            when jsonb_typeof(p_marked_for_review) = 'array'
             and jsonb_array_length(p_marked_for_review) = 10
            then coalesce((p_marked_for_review ->> (qq.question_order - 1))::boolean, false)
            else false
        end,
        case when jsonb_typeof(answer.value) = 'null' then null else now() end
    from public.quiz_questions qq
    join public.questions q on q.id = qq.question_id
    join lateral jsonb_array_elements(p_answers) with ordinality answer(value, ordinality)
      on answer.ordinality = qq.question_order
    where qq.quiz_id = p_quiz_id;

    return public.quiz_attempt_result(v_attempt_id);
end;
$$;

create or replace function public.get_quiz_leaderboard_page(
    p_quiz_id text,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with attempt_counts as (
    select user_id, count(*)::integer as attempts_count
    from public.quiz_attempts
    where quiz_id = p_quiz_id and is_completed
    group by user_id
), latest as (
    select distinct on (a.user_id)
        a.user_id, a.score, a.total, a.answered, a.duration_seconds,
        a.completed_at, a.id, c.attempts_count
    from public.quiz_attempts a
    join attempt_counts c on c.user_id = a.user_id
    where a.quiz_id = p_quiz_id and a.is_completed
    order by a.user_id, a.completed_at desc, a.id desc
), visible as (
    select
        l.*,
        coalesce(
            nullif(btrim(u.public_display_name), ''),
            case when u.username_visible and nullif(btrim(u.username), '') is not null
                 then '@' || btrim(u.username) end,
            'শিক্ষার্থী ' || upper(substr(md5(u.id::text), 1, 4))
        ) as display_name
    from latest l
    join public.users u on u.id = l.user_id
    where u.leaderboard_visible
), ranked as (
    select
        row_number() over (
            order by score desc, answered desc, duration_seconds asc nulls last,
                     completed_at asc, id
        ) as rank,
        *
    from visible
), page as (
    select * from ranked
    order by rank
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'quiz_id', p_quiz_id,
    'participants', (select count(*) from visible),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', coalesce((
        select jsonb_agg(jsonb_build_object(
            'rank', rank,
            'display_name', display_name,
            'score', score,
            'total', total,
            'answered', answered,
            'attempts_count', attempts_count,
            'duration_seconds', duration_seconds,
            'completed_at', completed_at
        ) order by rank)
        from page
    ), '[]'::jsonb)
);
$$;

create or replace function public.get_global_leaderboard_page(
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with answer_events as (
    select ua.user_id, ua.is_correct, ua.answered_at
    from public.user_attempts ua
    where ua.session_type <> 'mock_test'
    union all
    select a.user_id, coalesce(aa.is_correct, false), coalesce(aa.answered_at, a.completed_at)
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    where aa.selected_option is not null and a.is_completed
), aggregated as (
    select
        user_id,
        count(*)::integer as total_attempts,
        count(*) filter (where is_correct)::integer as correct_attempts,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as accuracy_pct,
        max(answered_at) as last_attempt_at
    from answer_events
    group by user_id
), visible as (
    select
        a.*,
        coalesce(
            nullif(btrim(u.public_display_name), ''),
            case when u.username_visible and nullif(btrim(u.username), '') is not null
                 then '@' || btrim(u.username) end,
            'শিক্ষার্থী ' || upper(substr(md5(u.id::text), 1, 4))
        ) as display_name
    from aggregated a
    join public.users u on u.id = a.user_id
    where u.leaderboard_visible
), ranked as (
    select row_number() over (
        order by correct_attempts desc, accuracy_pct desc,
                 total_attempts desc, last_attempt_at asc, user_id
    ) as rank, *
    from visible
), page as (
    select * from ranked order by rank
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'participants', (select count(*) from visible),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', coalesce((
        select jsonb_agg(jsonb_build_object(
            'rank', rank,
            'display_name', display_name,
            'total_attempts', total_attempts,
            'correct_attempts', correct_attempts,
            'accuracy_pct', accuracy_pct,
            'last_attempt_at', last_attempt_at
        ) order by rank)
        from page
    ), '[]'::jsonb)
);
$$;

-- The browser talks only to FastAPI. Lock down the exposed public schema and
-- allow the server's service role to use the tables/RPCs deliberately.
alter table public.questions enable row level security;
alter table public.polls enable row level security;
alter table public.users enable row level security;
alter table public.user_attempts enable row level security;
alter table public.bot_state enable row level security;
alter table public.personal_review_schedule enable row level security;
alter table public.quiz_runs enable row level security;
alter table public.chapter_history enable row level security;
alter table public.quiz_submissions enable row level security;
alter table public.quiz_questions enable row level security;
alter table public.quiz_attempts enable row level security;
alter table public.quiz_attempt_answers enable row level security;

revoke all on table public.questions, public.polls, public.users,
    public.user_attempts, public.bot_state, public.personal_review_schedule,
    public.quiz_runs, public.chapter_history, public.quiz_submissions,
    public.quiz_questions, public.quiz_attempts, public.quiz_attempt_answers
    from anon, authenticated;

grant select, insert, update, delete on table public.questions, public.polls,
    public.users, public.user_attempts, public.bot_state,
    public.personal_review_schedule, public.quiz_runs, public.chapter_history,
    public.quiz_submissions, public.quiz_questions, public.quiz_attempts,
    public.quiz_attempt_answers to service_role;

-- Existing installations may have additional analytics views that predate
-- this repository's migration history. Make every public view invoker-safe
-- and server-only so legacy views cannot reveal Telegram identifiers.
do $$
declare
    view_name text;
begin
    for view_name in
        select quote_ident(schemaname) || '.' || quote_ident(viewname)
        from pg_catalog.pg_views
        where schemaname = 'public'
    loop
        execute 'alter view ' || view_name || ' set (security_invoker = true)';
        execute 'revoke all on table ' || view_name || ' from public, anon, authenticated';
        execute 'grant select on table ' || view_name || ' to service_role';
    end loop;
end;
$$;

alter function public.find_similar_questions(text, text, double precision, integer)
    set search_path = public, pg_temp;

-- Harden a legacy helper when it exists; it is not required by this app.
do $$
begin
    if to_regprocedure('public.rls_auto_enable()') is not null then
        execute 'revoke execute on function public.rls_auto_enable() from public, anon, authenticated';
    end if;
end;
$$;

revoke execute on function public.find_similar_questions(text, text, double precision, integer) from public, anon, authenticated;
revoke execute on function public.claim_quiz_run(text, text, text, integer, boolean) from public, anon, authenticated;
revoke execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean) from public, anon, authenticated;
revoke execute on function public.quiz_attempt_result(uuid) from public, anon, authenticated;
revoke execute on function public.submit_quiz_attempt_atomic(text, uuid, text, jsonb, integer, jsonb, jsonb) from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_page(text, integer, integer) from public, anon, authenticated;
revoke execute on function public.get_global_leaderboard_page(integer, integer) from public, anon, authenticated;

grant execute on function public.find_similar_questions(text, text, double precision, integer) to service_role;
grant execute on function public.claim_quiz_run(text, text, text, integer, boolean) to service_role;
grant execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean) to service_role;
grant execute on function public.quiz_attempt_result(uuid) to service_role;
grant execute on function public.submit_quiz_attempt_atomic(text, uuid, text, jsonb, integer, jsonb, jsonb) to service_role;
grant execute on function public.get_quiz_leaderboard_page(text, integer, integer) to service_role;
grant execute on function public.get_global_leaderboard_page(integer, integer) to service_role;
