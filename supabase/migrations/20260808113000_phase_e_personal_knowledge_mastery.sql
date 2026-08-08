-- Phase E1: knowledge-point mastery, immutable variant history, and bounded
-- learner analytics. Existing question-level review rows and APIs remain valid.

create table if not exists public.personal_knowledge_mastery (
    user_id uuid not null references public.users(id) on delete cascade,
    knowledge_point_id uuid not null
        references public.knowledge_points(id) on delete cascade,
    attempt_count integer not null default 0 check (attempt_count >= 0),
    correct_attempts integer not null default 0 check (correct_attempts >= 0),
    wrong_attempts integer not null default 0 check (wrong_attempts >= 0),
    skipped_attempts integer not null default 0 check (skipped_attempts >= 0),
    lapse_count integer not null default 0 check (lapse_count >= 0),
    consecutive_correct integer not null default 0
        check (consecutive_correct >= 0),
    average_response_time_seconds numeric check (
        average_response_time_seconds is null
        or average_response_time_seconds between 0 and 3600
    ),
    mastery_score numeric not null default 0
        check (mastery_score between 0 and 100),
    review_interval_days integer not null default 0
        check (review_interval_days between 0 and 365),
    next_review date,
    last_question_id uuid references public.questions(id) on delete set null,
    last_variant_fingerprint text check (
        last_variant_fingerprint is null
        or last_variant_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    last_attempted_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (user_id, knowledge_point_id),
    check (correct_attempts + wrong_attempts + skipped_attempts = attempt_count)
);

create index if not exists idx_personal_knowledge_mastery_due
    on public.personal_knowledge_mastery (
        user_id, next_review, mastery_score, knowledge_point_id
    );
create index if not exists idx_personal_knowledge_mastery_weak
    on public.personal_knowledge_mastery (
        user_id, mastery_score, last_attempted_at desc
    );

create table if not exists public.personal_knowledge_variant_history (
    id uuid primary key default extensions.gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    knowledge_point_id uuid not null
        references public.knowledge_points(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete restrict,
    variant_fingerprint text check (
        variant_fingerprint is null or variant_fingerprint ~ '^[0-9a-f]{64}$'
    ),
    source_event_kind text not null
        check (source_event_kind in ('quiz_answer','practice_answer')),
    source_event_id uuid not null,
    is_correct boolean,
    was_skipped boolean not null default false,
    response_time_seconds numeric check (
        response_time_seconds is null or response_time_seconds between 0 and 3600
    ),
    attempted_at timestamptz not null,
    created_at timestamptz not null default now(),
    unique (source_event_kind, source_event_id),
    check (not was_skipped or is_correct is null)
);

create index if not exists idx_personal_knowledge_variant_history_user_kp
    on public.personal_knowledge_variant_history (
        user_id, knowledge_point_id, attempted_at desc
    );

create table if not exists public.learner_daily_rollups (
    user_id uuid not null references public.users(id) on delete cascade,
    activity_date date not null,
    total_questions integer not null default 0 check (total_questions >= 0),
    correct_answers integer not null default 0 check (correct_answers >= 0),
    incorrect_answers integer not null default 0 check (incorrect_answers >= 0),
    skipped_answers integer not null default 0 check (skipped_answers >= 0),
    gross_score numeric not null default 0,
    negative_marks numeric not null default 0 check (negative_marks >= 0),
    net_score numeric not null default 0,
    total_response_time_seconds numeric not null default 0
        check (total_response_time_seconds >= 0),
    timed_answer_count integer not null default 0 check (timed_answer_count >= 0),
    quiz_attempts integer not null default 0 check (quiz_attempts >= 0),
    revision_attempts integer not null default 0 check (revision_attempts >= 0),
    updated_at timestamptz not null default now(),
    primary key (user_id, activity_date),
    check (correct_answers + incorrect_answers + skipped_answers = total_questions)
);

create index if not exists idx_learner_daily_rollups_user_date
    on public.learner_daily_rollups (user_id, activity_date desc);

alter table public.personal_knowledge_mastery enable row level security;
alter table public.personal_knowledge_variant_history enable row level security;
alter table public.learner_daily_rollups enable row level security;

revoke all on table public.personal_knowledge_mastery from public, anon, authenticated;
revoke all on table public.personal_knowledge_variant_history from public, anon, authenticated;
revoke all on table public.learner_daily_rollups from public, anon, authenticated;
grant select, insert, update on table public.personal_knowledge_mastery to service_role;
grant select, insert on table public.personal_knowledge_variant_history to service_role;
grant select, insert, update on table public.learner_daily_rollups to service_role;

-- Preserve existing learner state while moving the scheduling identity from a
-- question variant to its stable knowledge point.
with grouped as (
    select
        schedule.user_id,
        question.knowledge_point_id,
        sum(schedule.correct_attempts + schedule.wrong_attempts)::integer
            as attempt_count,
        sum(schedule.correct_attempts)::integer as correct_attempts,
        sum(schedule.wrong_attempts)::integer as wrong_attempts,
        sum(schedule.wrong_attempts)::integer as lapse_count,
        max(schedule.consecutive_correct_revisions)::integer
            as consecutive_correct,
        case when sum(schedule.attempt_count) = 0 then null else round(
            sum(coalesce(schedule.average_response_time_seconds, 0)
                * schedule.attempt_count) / nullif(sum(schedule.attempt_count), 0),
            2
        ) end as average_response_time_seconds,
        round(avg(schedule.mastery_score), 2) as mastery_score,
        min(schedule.review_interval)::integer as review_interval_days,
        min(schedule.next_review) as next_review,
        max(schedule.last_attempted_at) as last_attempted_at
    from public.personal_review_schedule schedule
    join public.questions question on question.id = schedule.question_id
    where question.knowledge_point_id is not null
    group by schedule.user_id, question.knowledge_point_id
), latest as (
    select distinct on (schedule.user_id, question.knowledge_point_id)
        schedule.user_id,
        question.knowledge_point_id,
        question.id as question_id,
        question.variant_fingerprint
    from public.personal_review_schedule schedule
    join public.questions question on question.id = schedule.question_id
    where question.knowledge_point_id is not null
    order by
        schedule.user_id,
        question.knowledge_point_id,
        schedule.last_attempted_at desc nulls last,
        schedule.updated_at desc,
        question.id
)
insert into public.personal_knowledge_mastery (
    user_id, knowledge_point_id, attempt_count, correct_attempts,
    wrong_attempts, skipped_attempts, lapse_count, consecutive_correct,
    average_response_time_seconds, mastery_score, review_interval_days,
    next_review, last_question_id, last_variant_fingerprint,
    last_attempted_at, updated_at
)
select
    grouped.user_id,
    grouped.knowledge_point_id,
    grouped.attempt_count,
    grouped.correct_attempts,
    grouped.wrong_attempts,
    0,
    grouped.lapse_count,
    grouped.consecutive_correct,
    grouped.average_response_time_seconds,
    greatest(0, least(grouped.mastery_score, 100)),
    greatest(0, least(grouped.review_interval_days, 365)),
    grouped.next_review,
    latest.question_id,
    latest.variant_fingerprint,
    grouped.last_attempted_at,
    now()
from grouped
join latest using (user_id, knowledge_point_id)
on conflict (user_id, knowledge_point_id) do nothing;

insert into public.personal_knowledge_variant_history (
    user_id, knowledge_point_id, question_id, variant_fingerprint,
    source_event_kind, source_event_id, is_correct, was_skipped,
    response_time_seconds, attempted_at
)
select
    attempt.user_id,
    question.knowledge_point_id,
    answer.question_id,
    question.variant_fingerprint,
    'quiz_answer',
    answer.id,
    answer.is_correct,
    answer.selected_option is null,
    answer.response_time_seconds,
    coalesce(answer.answered_at, attempt.completed_at, answer.created_at)
from public.quiz_attempt_answers answer
join public.quiz_attempts attempt on attempt.id = answer.attempt_id
join public.questions question on question.id = answer.question_id
where question.knowledge_point_id is not null
on conflict (source_event_kind, source_event_id) do nothing;

insert into public.personal_knowledge_variant_history (
    user_id, knowledge_point_id, question_id, variant_fingerprint,
    source_event_kind, source_event_id, is_correct, was_skipped,
    response_time_seconds, attempted_at
)
select
    answer.user_id,
    question.knowledge_point_id,
    answer.question_id,
    question.variant_fingerprint,
    'practice_answer',
    answer.id,
    answer.is_correct,
    false,
    answer.response_time_seconds,
    answer.answered_at
from public.personal_practice_answers answer
join public.questions question on question.id = answer.question_id
where question.knowledge_point_id is not null
on conflict (source_event_kind, source_event_id) do nothing;

with answer_events as (
    select
        attempt.user_id,
        (coalesce(answer.answered_at, attempt.completed_at, answer.created_at)
            at time zone 'Asia/Kolkata')::date as activity_date,
        answer.is_correct,
        answer.selected_option is null as was_skipped,
        answer.response_time_seconds,
        attempt.negative_mark_penalty as penalty,
        attempt.id as quiz_attempt_id,
        false as is_revision
    from public.quiz_attempt_answers answer
    join public.quiz_attempts attempt on attempt.id = answer.attempt_id
    union all
    select
        answer.user_id,
        (answer.answered_at at time zone 'Asia/Kolkata')::date,
        answer.is_correct,
        false,
        answer.response_time_seconds,
        0::numeric,
        null::uuid,
        true
    from public.personal_practice_answers answer
), aggregated as (
    select
        user_id,
        activity_date,
        count(*)::integer as total_questions,
        count(*) filter (where is_correct is true)::integer as correct_answers,
        count(*) filter (where is_correct is false)::integer as incorrect_answers,
        count(*) filter (where was_skipped)::integer as skipped_answers,
        count(*) filter (where is_correct is true)::numeric as gross_score,
        coalesce(sum(penalty) filter (where is_correct is false), 0) as negative_marks,
        count(*) filter (where is_correct is true)::numeric
            - coalesce(sum(penalty) filter (where is_correct is false), 0)
            as net_score,
        coalesce(sum(response_time_seconds), 0) as total_response_time_seconds,
        count(response_time_seconds)::integer as timed_answer_count,
        count(distinct quiz_attempt_id)::integer as quiz_attempts,
        count(*) filter (where is_revision)::integer as revision_attempts
    from answer_events
    group by user_id, activity_date
)
insert into public.learner_daily_rollups (
    user_id, activity_date, total_questions, correct_answers,
    incorrect_answers, skipped_answers, gross_score, negative_marks,
    net_score, total_response_time_seconds, timed_answer_count,
    quiz_attempts, revision_attempts, updated_at
)
select
    user_id, activity_date, total_questions, correct_answers,
    incorrect_answers, skipped_answers, gross_score, negative_marks,
    net_score, total_response_time_seconds, timed_answer_count,
    quiz_attempts, revision_attempts, now()
from aggregated
on conflict (user_id, activity_date) do nothing;

create or replace function public.record_personal_knowledge_attempt(
    p_user_id uuid,
    p_question_id uuid,
    p_source_event_kind text,
    p_source_event_id uuid,
    p_is_correct boolean,
    p_was_skipped boolean,
    p_response_time_seconds numeric,
    p_negative_penalty numeric,
    p_attempted_at timestamptz
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_knowledge_point_id uuid;
    v_variant_fingerprint text;
    v_attempted_at timestamptz := coalesce(p_attempted_at, now());
    v_activity_date date;
    v_slow_correct boolean;
begin
    if p_source_event_kind not in ('quiz_answer','practice_answer') then
        raise exception 'unsupported personal knowledge source event';
    end if;
    if p_was_skipped and p_is_correct is not null then
        raise exception 'a skipped answer cannot be correct or incorrect';
    end if;
    if p_response_time_seconds is not null
       and p_response_time_seconds not between 0 and 3600 then
        raise exception 'response time is outside the supported range';
    end if;

    select question.knowledge_point_id, question.variant_fingerprint
    into v_knowledge_point_id, v_variant_fingerprint
    from public.questions question
    where question.id = p_question_id;

    if v_knowledge_point_id is null then
        return;
    end if;

    insert into public.personal_knowledge_variant_history (
        user_id, knowledge_point_id, question_id, variant_fingerprint,
        source_event_kind, source_event_id, is_correct, was_skipped,
        response_time_seconds, attempted_at
    ) values (
        p_user_id, v_knowledge_point_id, p_question_id, v_variant_fingerprint,
        p_source_event_kind, p_source_event_id, p_is_correct, p_was_skipped,
        p_response_time_seconds, v_attempted_at
    ) on conflict (source_event_kind, source_event_id) do nothing;

    if not found then
        return;
    end if;

    v_slow_correct := p_is_correct is true and (
        coalesce(p_response_time_seconds, 0) > 45
    );

    insert into public.personal_knowledge_mastery (
        user_id, knowledge_point_id, attempt_count, correct_attempts,
        wrong_attempts, skipped_attempts, lapse_count, consecutive_correct,
        average_response_time_seconds, mastery_score, review_interval_days,
        next_review, last_question_id, last_variant_fingerprint,
        last_attempted_at, updated_at
    ) values (
        p_user_id,
        v_knowledge_point_id,
        1,
        case when p_is_correct is true then 1 else 0 end,
        case when p_is_correct is false then 1 else 0 end,
        case when p_was_skipped then 1 else 0 end,
        case when p_is_correct is false then 1 else 0 end,
        case when p_is_correct is true then 1 else 0 end,
        p_response_time_seconds,
        case
            when p_was_skipped then 0
            when p_is_correct is false then 0
            when v_slow_correct then 12
            else 25
        end,
        case
            when p_was_skipped or p_is_correct is false then 1
            when v_slow_correct then 3
            else 7
        end,
        (v_attempted_at at time zone 'Asia/Kolkata')::date + case
            when p_was_skipped or p_is_correct is false then 1
            when v_slow_correct then 3
            else 7
        end,
        p_question_id,
        v_variant_fingerprint,
        v_attempted_at,
        now()
    ) on conflict (user_id, knowledge_point_id) do update set
        attempt_count = public.personal_knowledge_mastery.attempt_count + 1,
        correct_attempts = public.personal_knowledge_mastery.correct_attempts
            + case when p_is_correct is true then 1 else 0 end,
        wrong_attempts = public.personal_knowledge_mastery.wrong_attempts
            + case when p_is_correct is false then 1 else 0 end,
        skipped_attempts = public.personal_knowledge_mastery.skipped_attempts
            + case when p_was_skipped then 1 else 0 end,
        lapse_count = public.personal_knowledge_mastery.lapse_count
            + case when p_is_correct is false then 1 else 0 end,
        consecutive_correct = case
            when p_is_correct is true
                then public.personal_knowledge_mastery.consecutive_correct + 1
            else 0
        end,
        average_response_time_seconds = case
            when p_response_time_seconds is null
                then public.personal_knowledge_mastery.average_response_time_seconds
            when public.personal_knowledge_mastery.average_response_time_seconds is null
                then p_response_time_seconds
            else round((
                public.personal_knowledge_mastery.average_response_time_seconds
                    * public.personal_knowledge_mastery.attempt_count
                + p_response_time_seconds
            ) / (public.personal_knowledge_mastery.attempt_count + 1), 2)
        end,
        mastery_score = case
            when p_was_skipped then greatest(
                0, public.personal_knowledge_mastery.mastery_score * 0.70
            )
            when p_is_correct is false then greatest(
                0, public.personal_knowledge_mastery.mastery_score * 0.55
            )
            when v_slow_correct then least(
                100, public.personal_knowledge_mastery.mastery_score * 0.75 + 12
            )
            else least(
                100, public.personal_knowledge_mastery.mastery_score * 0.75 + 25
            )
        end,
        review_interval_days = case
            when p_was_skipped or p_is_correct is false then 1
            when v_slow_correct then 3
            when public.personal_knowledge_mastery.consecutive_correct = 0 then 7
            when public.personal_knowledge_mastery.consecutive_correct = 1 then 14
            when public.personal_knowledge_mastery.consecutive_correct = 2 then 30
            else 60
        end,
        next_review = (v_attempted_at at time zone 'Asia/Kolkata')::date + case
            when p_was_skipped or p_is_correct is false then 1
            when v_slow_correct then 3
            when public.personal_knowledge_mastery.consecutive_correct = 0 then 7
            when public.personal_knowledge_mastery.consecutive_correct = 1 then 14
            when public.personal_knowledge_mastery.consecutive_correct = 2 then 30
            else 60
        end,
        last_question_id = p_question_id,
        last_variant_fingerprint = v_variant_fingerprint,
        last_attempted_at = v_attempted_at,
        updated_at = now();

    v_activity_date := (v_attempted_at at time zone 'Asia/Kolkata')::date;
    insert into public.learner_daily_rollups (
        user_id, activity_date, total_questions, correct_answers,
        incorrect_answers, skipped_answers, gross_score, negative_marks,
        net_score, total_response_time_seconds, timed_answer_count,
        revision_attempts, updated_at
    ) values (
        p_user_id,
        v_activity_date,
        1,
        case when p_is_correct is true then 1 else 0 end,
        case when p_is_correct is false then 1 else 0 end,
        case when p_was_skipped then 1 else 0 end,
        case when p_is_correct is true then 1 else 0 end,
        case when p_is_correct is false then greatest(coalesce(p_negative_penalty, 0), 0) else 0 end,
        case
            when p_is_correct is true then 1
            when p_is_correct is false then -greatest(coalesce(p_negative_penalty, 0), 0)
            else 0
        end,
        coalesce(p_response_time_seconds, 0),
        case when p_response_time_seconds is null then 0 else 1 end,
        case when p_source_event_kind = 'practice_answer' then 1 else 0 end,
        now()
    ) on conflict (user_id, activity_date) do update set
        total_questions = public.learner_daily_rollups.total_questions + 1,
        correct_answers = public.learner_daily_rollups.correct_answers
            + case when p_is_correct is true then 1 else 0 end,
        incorrect_answers = public.learner_daily_rollups.incorrect_answers
            + case when p_is_correct is false then 1 else 0 end,
        skipped_answers = public.learner_daily_rollups.skipped_answers
            + case when p_was_skipped then 1 else 0 end,
        gross_score = public.learner_daily_rollups.gross_score
            + case when p_is_correct is true then 1 else 0 end,
        negative_marks = public.learner_daily_rollups.negative_marks
            + case when p_is_correct is false then greatest(coalesce(p_negative_penalty, 0), 0) else 0 end,
        net_score = public.learner_daily_rollups.net_score + case
            when p_is_correct is true then 1
            when p_is_correct is false then -greatest(coalesce(p_negative_penalty, 0), 0)
            else 0
        end,
        total_response_time_seconds =
            public.learner_daily_rollups.total_response_time_seconds
            + coalesce(p_response_time_seconds, 0),
        timed_answer_count = public.learner_daily_rollups.timed_answer_count
            + case when p_response_time_seconds is null then 0 else 1 end,
        revision_attempts = public.learner_daily_rollups.revision_attempts
            + case when p_source_event_kind = 'practice_answer' then 1 else 0 end,
        updated_at = now();
end;
$$;

create or replace function public.capture_quiz_answer_knowledge_mastery()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_user_id uuid;
    v_penalty numeric;
    v_attempted_at timestamptz;
begin
    select attempt.user_id, attempt.negative_mark_penalty, attempt.completed_at
    into v_user_id, v_penalty, v_attempted_at
    from public.quiz_attempts attempt
    where attempt.id = new.attempt_id;

    perform public.record_personal_knowledge_attempt(
        v_user_id, new.question_id, 'quiz_answer', new.id,
        new.is_correct, new.selected_option is null,
        new.response_time_seconds, v_penalty,
        coalesce(new.answered_at, v_attempted_at, new.created_at)
    );
    return new;
end;
$$;

drop trigger if exists capture_quiz_answer_knowledge_mastery
    on public.quiz_attempt_answers;
create trigger capture_quiz_answer_knowledge_mastery
after insert on public.quiz_attempt_answers
for each row execute function public.capture_quiz_answer_knowledge_mastery();

create or replace function public.capture_practice_answer_knowledge_mastery()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    perform public.record_personal_knowledge_attempt(
        new.user_id, new.question_id, 'practice_answer', new.id,
        new.is_correct, false, new.response_time_seconds, 0, new.answered_at
    );
    return new;
end;
$$;

drop trigger if exists capture_practice_answer_knowledge_mastery
    on public.personal_practice_answers;
create trigger capture_practice_answer_knowledge_mastery
after insert on public.personal_practice_answers
for each row execute function public.capture_practice_answer_knowledge_mastery();

create or replace function public.capture_quiz_attempt_rollup()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    insert into public.learner_daily_rollups (
        user_id, activity_date, quiz_attempts, updated_at
    ) values (
        new.user_id,
        (new.completed_at at time zone 'Asia/Kolkata')::date,
        1,
        now()
    ) on conflict (user_id, activity_date) do update set
        quiz_attempts = public.learner_daily_rollups.quiz_attempts + 1,
        updated_at = now();
    return new;
end;
$$;

drop trigger if exists capture_quiz_attempt_rollup on public.quiz_attempts;
create trigger capture_quiz_attempt_rollup
after insert on public.quiz_attempts
for each row execute function public.capture_quiz_attempt_rollup();

create or replace function public.get_user_knowledge_review_queue(
    p_user_id uuid,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with due as (
    select mastery.*
    from public.personal_knowledge_mastery mastery
    join public.knowledge_points kp on kp.id = mastery.knowledge_point_id
    where mastery.user_id = p_user_id
      and mastery.next_review <= (now() at time zone 'Asia/Kolkata')::date
      and kp.status = 'active'
      and kp.syllabus_status = 'mapped'
    order by mastery.next_review, mastery.mastery_score, mastery.knowledge_point_id
), selected as (
    select
        due.*,
        candidate.id as question_id,
        candidate.question_text,
        jsonb_build_array(
            candidate.option_a, candidate.option_b,
            candidate.option_c, candidate.option_d
        ) as options,
        candidate.subject,
        candidate.topic,
        candidate.difficulty,
        candidate.language,
        candidate.variant_fingerprint,
        candidate.variant_fingerprint is distinct from due.last_variant_fingerprint
            as variant_changed
    from due
    cross join lateral (
        select question.*
        from public.questions question
        where question.knowledge_point_id = due.knowledge_point_id
          and question.status = 'active'
          and question.verification_status = 'verified'
          and question.inventory_status in ('verified','used')
          and not question.review_required
        order by
            (question.variant_fingerprint is not distinct from due.last_variant_fingerprint),
            question.last_used_at asc nulls first,
            question.id
        limit 1
    ) candidate
), page as (
    select * from selected
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from selected),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'mode', 'revision',
    'sourceType', 'due',
    'identityUnit', 'knowledge_point',
    'items', coalesce((select jsonb_agg(jsonb_build_object(
        'questionId', page.question_id,
        'knowledgePointId', page.knowledge_point_id,
        'question', page.question_text,
        'options', page.options,
        'subjectKey', page.subject,
        'chapter', page.topic,
        'difficulty', page.difficulty,
        'language', page.language,
        'masteryScore', page.mastery_score,
        'nextReview', page.next_review,
        'variantChanged', page.variant_changed
    ) order by page.next_review, page.mastery_score) from page), '[]'::jsonb)
);
$$;

create or replace function public.get_user_learning_daily_rollups(
    p_user_id uuid,
    p_date_from date default null,
    p_date_to date default null,
    p_limit integer default 30,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with filtered as (
    select
        rollup.*,
        case when rollup.timed_answer_count = 0 then null else round(
            rollup.total_response_time_seconds / rollup.timed_answer_count, 2
        ) end as average_response_time_seconds
    from public.learner_daily_rollups rollup
    where rollup.user_id = p_user_id
      and (p_date_from is null or rollup.activity_date >= p_date_from)
      and (p_date_to is null or rollup.activity_date <= p_date_to)
), page as (
    select * from filtered
    order by activity_date desc
    limit greatest(1, least(coalesce(p_limit, 30), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 30), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'dateFrom', p_date_from,
    'dateTo', p_date_to,
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'date', page.activity_date,
        'answered', page.total_questions - page.skipped_answers,
        'skipped', page.skipped_answers,
        'correct', page.correct_answers,
        'incorrect', page.incorrect_answers,
        'grossScore', page.gross_score,
        'negativeMarks', page.negative_marks,
        'netScore', page.net_score,
        'averageResponseTimeSeconds', page.average_response_time_seconds,
        'quizAttempts', page.quiz_attempts,
        'revisionAttempts', page.revision_attempts
    ) order by page.activity_date desc) from page), '[]'::jsonb)
);
$$;

create or replace function public.get_user_knowledge_mastery_page(
    p_user_id uuid,
    p_subject_key text default null,
    p_strength text default 'all',
    p_limit integer default 30,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with filtered as (
    select
        mastery.*,
        kp.knowledge_key,
        kp.subject_key,
        kp.canonical_claim,
        topic.key as micro_topic_key,
        topic.name as micro_topic_name,
        chapter.name as chapter_name
    from public.personal_knowledge_mastery mastery
    join public.knowledge_points kp on kp.id = mastery.knowledge_point_id
    left join public.quiz_micro_topics topic on topic.id = kp.micro_topic_id
    left join public.quiz_chapters chapter on chapter.id = topic.chapter_id
    where mastery.user_id = p_user_id
      and (p_subject_key is null or kp.subject_key = p_subject_key)
      and case coalesce(p_strength, 'all')
          when 'all' then true
          when 'due' then mastery.next_review <=
              (now() at time zone 'Asia/Kolkata')::date
          when 'weak' then mastery.mastery_score < 60
          when 'strong' then mastery.mastery_score >= 80
              and mastery.attempt_count >= 2
          else false
      end
), page as (
    select * from filtered
    order by
        (next_review <= (now() at time zone 'Asia/Kolkata')::date) desc,
        mastery_score,
        last_attempted_at desc,
        knowledge_key
    limit greatest(1, least(coalesce(p_limit, 30), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 30), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'subjectKey', p_subject_key,
    'strength', coalesce(p_strength, 'all'),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'knowledgePointId', page.knowledge_point_id,
        'knowledgeKey', page.knowledge_key,
        'subjectKey', page.subject_key,
        'chapter', page.chapter_name,
        'microTopicKey', page.micro_topic_key,
        'microTopic', page.micro_topic_name,
        'claim', page.canonical_claim,
        'masteryScore', page.mastery_score,
        'attempts', page.attempt_count,
        'correct', page.correct_attempts,
        'wrong', page.wrong_attempts,
        'skipped', page.skipped_attempts,
        'averageResponseTimeSeconds', page.average_response_time_seconds,
        'reviewIntervalDays', page.review_interval_days,
        'nextReview', page.next_review,
        'lastAttemptedAt', page.last_attempted_at
    ) order by
        (page.next_review <= (now() at time zone 'Asia/Kolkata')::date) desc,
        page.mastery_score,
        page.last_attempted_at desc
    ) from page), '[]'::jsonb)
);
$$;

create or replace function public.get_user_learning_dashboard_v2(p_user_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_base jsonb;
    v_due integer;
    v_wrong integer;
    v_weak integer;
    v_next_action text;
begin
    v_base := public.get_user_learning_dashboard(p_user_id);

    select
        count(*) filter (
            where next_review <= (now() at time zone 'Asia/Kolkata')::date
        ),
        count(*) filter (where wrong_attempts > 0),
        count(*) filter (where mastery_score < 60)
    into v_due, v_wrong, v_weak
    from public.personal_knowledge_mastery
    where user_id = p_user_id;

    v_next_action := case
        when v_due > 0 then 'continue_due_revision'
        when v_wrong > 0 then 'continue_mistakes'
        when v_weak > 0 then 'practice_weak_topics'
        else 'broad_maintenance'
    end;

    return coalesce(v_base, '{}'::jsonb) || jsonb_build_object(
        'knowledgePointMastery', jsonb_build_object(
            'identityUnit', 'user_knowledge_point',
            'due', v_due,
            'wrong', v_wrong,
            'weak', v_weak,
            'weakest', coalesce((
                select jsonb_agg(row_value order by mastery_score, knowledge_key)
                from (
                    select jsonb_build_object(
                        'knowledgePointId', mastery.knowledge_point_id,
                        'knowledgeKey', kp.knowledge_key,
                        'subjectKey', kp.subject_key,
                        'claim', kp.canonical_claim,
                        'masteryScore', mastery.mastery_score,
                        'attempts', mastery.attempt_count
                    ) as row_value, mastery.mastery_score, kp.knowledge_key
                    from public.personal_knowledge_mastery mastery
                    join public.knowledge_points kp
                      on kp.id = mastery.knowledge_point_id
                    where mastery.user_id = p_user_id
                    order by mastery.mastery_score, mastery.last_attempted_at desc
                    limit 5
                ) rows
            ), '[]'::jsonb),
            'strongest', coalesce((
                select jsonb_agg(row_value order by mastery_score desc, knowledge_key)
                from (
                    select jsonb_build_object(
                        'knowledgePointId', mastery.knowledge_point_id,
                        'knowledgeKey', kp.knowledge_key,
                        'subjectKey', kp.subject_key,
                        'claim', kp.canonical_claim,
                        'masteryScore', mastery.mastery_score,
                        'attempts', mastery.attempt_count
                    ) as row_value, mastery.mastery_score, kp.knowledge_key
                    from public.personal_knowledge_mastery mastery
                    join public.knowledge_points kp
                      on kp.id = mastery.knowledge_point_id
                    where mastery.user_id = p_user_id
                      and mastery.attempt_count >= 2
                    order by mastery.mastery_score desc, mastery.last_attempted_at desc
                    limit 5
                ) rows
            ), '[]'::jsonb)
        ),
        'recommendationPolicy', jsonb_build_object(
            'version', 1,
            'dueOrWrongPercent', 50,
            'weakTopicPercent', 30,
            'broadMaintenancePercent', 20,
            'nextAction', v_next_action
        ),
        'dailyTrend', coalesce((
            select payload->'rows'
            from (
                select public.get_user_learning_daily_rollups(
                    p_user_id,
                    (now() at time zone 'Asia/Kolkata')::date - 13,
                    (now() at time zone 'Asia/Kolkata')::date,
                    14,
                    0
                ) as payload
            ) trend
        ), '[]'::jsonb),
        'rankCohort', jsonb_build_object(
            'definition', 'learners with at least one completed official first attempt',
            'retakesIncluded', false,
            'practiceIncluded', false,
            'privacy', 'opted-in public identities only'
        )
    );
end;
$$;

create or replace function public.get_phase_e_personal_learning_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with required_functions(signature) as (values
    ('get_user_knowledge_review_queue(uuid,integer,integer)'),
    ('get_user_learning_daily_rollups(uuid,date,date,integer,integer)'),
    ('get_user_knowledge_mastery_page(uuid,text,text,integer,integer)'),
    ('get_user_learning_dashboard_v2(uuid)')
), function_permission_failures as (
    select role_name || ':' || signature as failure
    from required_functions
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
    union all
    select 'service_role:' || signature from required_functions
    where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
), required_tables(name) as (values
    ('personal_knowledge_mastery'),
    ('personal_knowledge_variant_history'),
    ('learner_daily_rollups')
), table_permission_failures as (
    select role_name || ':' || name as failure
    from required_tables
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_table_privilege(role_name, 'public.' || name, 'SELECT')
       or has_table_privilege(role_name, 'public.' || name, 'INSERT')
       or has_table_privilege(role_name, 'public.' || name, 'UPDATE')
       or has_table_privilege(role_name, 'public.' || name, 'DELETE')
)
select jsonb_build_object(
    'phase_e_personal_learning_migration_version', '20260808113000',
    'ready',
        to_regclass('public.personal_knowledge_mastery') is not null
        and to_regclass('public.personal_knowledge_variant_history') is not null
        and to_regclass('public.learner_daily_rollups') is not null
        and to_regprocedure('public.get_user_knowledge_review_queue(uuid,integer,integer)') is not null
        and to_regprocedure('public.get_user_learning_daily_rollups(uuid,date,date,integer,integer)') is not null
        and to_regprocedure('public.get_user_knowledge_mastery_page(uuid,text,text,integer,integer)') is not null
        and to_regprocedure('public.get_user_learning_dashboard_v2(uuid)') is not null
        and not exists (select 1 from function_permission_failures)
        and not exists (select 1 from table_permission_failures),
    'knowledge_point_state', true,
    'variant_history', true,
    'different_variant_selection', true,
    'daily_rollups', true,
    'transparent_recommendations', true,
    'cohort_definition', true,
    'function_permission_failures', coalesce(
        (select jsonb_agg(failure order by failure) from function_permission_failures),
        '[]'::jsonb
    ),
    'table_permission_failures', coalesce(
        (select jsonb_agg(failure order by failure) from table_permission_failures),
        '[]'::jsonb
    )
);
$$;

revoke execute on function public.record_personal_knowledge_attempt(
    uuid,uuid,text,uuid,boolean,boolean,numeric,numeric,timestamptz
) from public, anon, authenticated;
revoke execute on function public.capture_quiz_answer_knowledge_mastery()
    from public, anon, authenticated;
revoke execute on function public.capture_practice_answer_knowledge_mastery()
    from public, anon, authenticated;
revoke execute on function public.capture_quiz_attempt_rollup()
    from public, anon, authenticated;
revoke execute on function public.get_user_knowledge_review_queue(uuid,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_learning_daily_rollups(uuid,date,date,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_knowledge_mastery_page(uuid,text,text,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard_v2(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_phase_e_personal_learning_contract()
    from public, anon, authenticated;

grant execute on function public.record_personal_knowledge_attempt(
    uuid,uuid,text,uuid,boolean,boolean,numeric,numeric,timestamptz
) to service_role;
grant execute on function public.capture_quiz_answer_knowledge_mastery()
    to service_role;
grant execute on function public.capture_practice_answer_knowledge_mastery()
    to service_role;
grant execute on function public.capture_quiz_attempt_rollup()
    to service_role;
grant execute on function public.get_user_knowledge_review_queue(uuid,integer,integer)
    to service_role;
grant execute on function public.get_user_learning_daily_rollups(uuid,date,date,integer,integer)
    to service_role;
grant execute on function public.get_user_knowledge_mastery_page(uuid,text,text,integer,integer)
    to service_role;
grant execute on function public.get_user_learning_dashboard_v2(uuid)
    to service_role;
grant execute on function public.get_phase_e_personal_learning_contract()
    to service_role;
