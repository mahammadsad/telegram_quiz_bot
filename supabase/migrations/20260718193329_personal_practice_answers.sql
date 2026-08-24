-- Authenticated wrong-answer, due-review, bookmark, and weak-topic practice.
-- Correct answers remain private until a learner submits an option through
-- FastAPI. The shared scheduling helper keeps mock and practice behavior equal.

create table if not exists public.personal_practice_answers (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete cascade,
    source_type text not null check (
        source_type in ('wrong','due','bookmark','weak_topic')
    ),
    selected_option smallint not null check (selected_option between 0 and 3),
    correct_option smallint not null check (correct_option between 0 and 3),
    is_correct boolean not null,
    response_time_seconds numeric check (
        response_time_seconds is null
        or response_time_seconds between 0 and 3600
    ),
    marked_for_review boolean not null default false,
    answered_at timestamptz not null default now()
);

create index if not exists idx_personal_practice_user_activity
    on public.personal_practice_answers (user_id, answered_at desc);
create index if not exists idx_personal_practice_question
    on public.personal_practice_answers (question_id, answered_at desc);

create or replace function public.advance_personal_review_schedule(
    p_user_id uuid,
    p_question_id uuid,
    p_is_correct boolean,
    p_response_time_seconds numeric default null,
    p_marked_for_review boolean default false
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_slow_or_uncertain boolean;
    v_initial_interval integer;
    v_initial_repetitions integer;
    v_initial_confidence numeric;
    v_initial_mastery numeric;
begin
    v_slow_or_uncertain := p_is_correct is true and (
        p_marked_for_review or coalesce(p_response_time_seconds, 0) > 45
    );
    v_initial_interval := case
        when p_is_correct is not true then 1
        when v_slow_or_uncertain then 3
        else 7
    end;
    v_initial_repetitions := case when p_is_correct is true then 1 else 0 end;
    v_initial_confidence := case
        when p_is_correct is not true then 0
        when v_slow_or_uncertain then 0.6
        else 1
    end;
    v_initial_mastery := case
        when p_is_correct is not true then 0
        when v_slow_or_uncertain then 25
        else 40
    end;

    insert into public.personal_review_schedule (
        user_id, question_id, ease_factor, review_interval, next_review,
        repetition_count, last_review, learning_stage, correct_attempts,
        wrong_attempts, average_response_time_seconds, recent_confidence,
        mastery_score, updated_at
    ) values (
        p_user_id,
        p_question_id,
        case when p_is_correct is true then 2.5 else 2.3 end,
        v_initial_interval,
        current_date + v_initial_interval,
        v_initial_repetitions,
        now(),
        case when p_is_correct is true then 'review' else 'learning' end,
        case when p_is_correct is true then 1 else 0 end,
        case when p_is_correct is true then 0 else 1 end,
        p_response_time_seconds,
        v_initial_confidence,
        v_initial_mastery,
        now()
    )
    on conflict (user_id, question_id) do update set
        ease_factor = case
            when p_is_correct is not true then
                greatest(1.3, public.personal_review_schedule.ease_factor - 0.20)
            when v_slow_or_uncertain then
                greatest(1.3, public.personal_review_schedule.ease_factor - 0.05)
            else least(2.8, public.personal_review_schedule.ease_factor + 0.05)
        end,
        review_interval = case
            when p_is_correct is not true then 1
            when v_slow_or_uncertain then 3
            when public.personal_review_schedule.repetition_count = 0 then 7
            when public.personal_review_schedule.repetition_count = 1 then 14
            when public.personal_review_schedule.repetition_count = 2 then 30
            else 60
        end,
        next_review = current_date + case
            when p_is_correct is not true then 1
            when v_slow_or_uncertain then 3
            when public.personal_review_schedule.repetition_count = 0 then 7
            when public.personal_review_schedule.repetition_count = 1 then 14
            when public.personal_review_schedule.repetition_count = 2 then 30
            else 60
        end,
        repetition_count = case
            when p_is_correct is not true then 0
            else public.personal_review_schedule.repetition_count + 1
        end,
        last_review = now(),
        learning_stage = case
            when p_is_correct is not true then 'learning'
            when public.personal_review_schedule.repetition_count + 1 >= 4
                and not v_slow_or_uncertain then 'mastered'
            else 'review'
        end,
        correct_attempts = public.personal_review_schedule.correct_attempts
            + case when p_is_correct is true then 1 else 0 end,
        wrong_attempts = public.personal_review_schedule.wrong_attempts
            + case when p_is_correct is true then 0 else 1 end,
        average_response_time_seconds = case
            when p_response_time_seconds is null then
                public.personal_review_schedule.average_response_time_seconds
            when public.personal_review_schedule.average_response_time_seconds is null then
                p_response_time_seconds
            else round((
                public.personal_review_schedule.average_response_time_seconds
                * (
                    public.personal_review_schedule.correct_attempts
                    + public.personal_review_schedule.wrong_attempts
                )
                + p_response_time_seconds
            ) / (
                public.personal_review_schedule.correct_attempts
                + public.personal_review_schedule.wrong_attempts
                + 1
            ), 2)
        end,
        recent_confidence = v_initial_confidence,
        mastery_score = round(case
            when p_is_correct is not true then
                public.personal_review_schedule.mastery_score * 0.70
            when v_slow_or_uncertain then
                public.personal_review_schedule.mastery_score * 0.70 + 18
            else public.personal_review_schedule.mastery_score * 0.70 + 30
        end, 2),
        updated_at = now();
end;
$$;

create or replace function public.sync_personal_review_schedule_from_answer()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_user_id uuid;
begin
    select user_id into v_user_id
    from public.quiz_attempts
    where id = new.attempt_id and is_completed;

    if v_user_id is not null then
        perform public.advance_personal_review_schedule(
            v_user_id,
            new.question_id,
            new.is_correct,
            new.response_time_seconds,
            new.marked_for_review
        );
    end if;
    return new;
end;
$$;

create or replace function public.submit_personal_practice_answer(
    p_user_id uuid,
    p_question_id uuid,
    p_selected_option integer,
    p_source_type text,
    p_response_time_seconds numeric default null,
    p_marked_for_review boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_question public.questions%rowtype;
    v_correct_index integer;
    v_is_correct boolean;
    v_schedule public.personal_review_schedule%rowtype;
begin
    if p_selected_option not between 0 and 3 then
        raise exception 'selected option must be between 0 and 3';
    end if;
    if p_source_type not in ('wrong','due','bookmark','weak_topic') then
        raise exception 'invalid practice source';
    end if;
    if p_response_time_seconds is not null
       and p_response_time_seconds not between 0 and 3600 then
        raise exception 'invalid response time';
    end if;

    select * into v_question
    from public.questions
    where id = p_question_id
      and status in ('verified','active','reported');
    if not found then
        raise exception 'question is not available';
    end if;

    v_correct_index := ascii(v_question.correct_option::text) - ascii('A');
    v_is_correct := p_selected_option = v_correct_index;

    insert into public.personal_practice_answers (
        user_id, question_id, source_type, selected_option, correct_option,
        is_correct, response_time_seconds, marked_for_review
    ) values (
        p_user_id, p_question_id, p_source_type, p_selected_option,
        v_correct_index, v_is_correct, p_response_time_seconds,
        p_marked_for_review
    );

    perform public.advance_personal_review_schedule(
        p_user_id,
        p_question_id,
        v_is_correct,
        p_response_time_seconds,
        p_marked_for_review
    );
    select * into v_schedule
    from public.personal_review_schedule
    where user_id = p_user_id and question_id = p_question_id;

    return jsonb_build_object(
        'questionId', v_question.id,
        'q', v_question.question_text,
        'o', jsonb_build_array(
            v_question.option_a, v_question.option_b,
            v_question.option_c, v_question.option_d
        ),
        'selectedIndex', p_selected_option,
        'correctIndex', v_correct_index,
        'isCorrect', v_is_correct,
        'explanation', coalesce(
            nullif(v_question.detailed_explanation, ''),
            v_question.explanation,
            ''
        ),
        'sourceUrl', v_question.source_url,
        'sourceTitle', v_question.source_title,
        'verifiedAt', v_question.verified_at,
        'microTopicKey', v_question.micro_topic_key,
        'nextReview', v_schedule.next_review,
        'learningStage', v_schedule.learning_stage,
        'masteryScore', v_schedule.mastery_score
    );
end;
$$;

create or replace function public.get_user_wrong_questions(
    p_user_id uuid,
    p_subject_key text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with events as (
    select
        aa.question_id, aa.is_correct, aa.marked_for_review,
        coalesce(aa.answered_at, a.completed_at) as answered_at,
        aa.id as event_id,
        q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
        q.subject, q.topic, q.micro_topic_key
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    join public.questions q on q.id = aa.question_id
    where a.user_id = p_user_id and a.is_completed
      and aa.selected_option is not null
      and (p_subject_key is null or q.subject = p_subject_key)
    union all
    select
        pa.question_id, pa.is_correct, pa.marked_for_review,
        pa.answered_at, pa.id,
        q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
        q.subject, q.topic, q.micro_topic_key
    from public.personal_practice_answers pa
    join public.questions q on q.id = pa.question_id
    where pa.user_id = p_user_id
      and (p_subject_key is null or q.subject = p_subject_key)
), latest as (
    select distinct on (question_id) *
    from events
    order by question_id, answered_at desc, event_id desc
), wrong as (
    select * from latest where is_correct is false
), page as (
    select * from wrong
    order by answered_at desc, question_id
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'total', (select count(*) from wrong),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'questionId', question_id,
        'q', question_text,
        'o', jsonb_build_array(option_a, option_b, option_c, option_d),
        'subjectKey', subject,
        'chapter', topic,
        'microTopicKey', micro_topic_key,
        'lastAttemptAt', answered_at,
        'markedForReview', marked_for_review
    ) order by answered_at desc, question_id) from page), '[]'::jsonb)
);
$$;

alter table public.personal_practice_answers enable row level security;
revoke all on table public.personal_practice_answers
    from public, anon, authenticated;
grant select, insert on table public.personal_practice_answers to service_role;

revoke execute on function public.advance_personal_review_schedule(
    uuid, uuid, boolean, numeric, boolean
) from public, anon, authenticated;
revoke execute on function public.submit_personal_practice_answer(
    uuid, uuid, integer, text, numeric, boolean
) from public, anon, authenticated;
revoke execute on function public.sync_personal_review_schedule_from_answer()
    from public, anon, authenticated;

grant execute on function public.advance_personal_review_schedule(
    uuid, uuid, boolean, numeric, boolean
) to service_role;
grant execute on function public.submit_personal_practice_answer(
    uuid, uuid, integer, text, numeric, boolean
) to service_role;
grant execute on function public.sync_personal_review_schedule_from_answer()
    to service_role;
