-- Learning, revision feedback, preferences, and current-user ranking contract.
-- Applied only after 20260718220112_production_integrity_contract_v2.sql.

create extension if not exists pgcrypto;

-- Existing quizzes that were already posted before checksum contract v2 cannot
-- recover their original generator payload. Certify their immutable database
-- rows as a one-time historical baseline so they remain readable, without
-- making any unposted legacy run eligible for Telegram delivery.
with historical_posted as (
    select r.quiz_id, public.quiz_pack_checksum(r.quiz_id) as checksum
    from public.quiz_runs r
    where r.status = 'posted'
      and (select count(*) from public.quiz_questions qq where qq.quiz_id = r.quiz_id) = 10
)
update public.quiz_runs r
set content_checksum = h.checksum,
    generated_checksum = h.checksum,
    persisted_checksum = h.checksum,
    checksum_contract_version = 2,
    integrity_verified = h.checksum is not null,
    integrity_diagnostic_code = null,
    ready_at = coalesce(r.ready_at, r.posted_at, r.generated_at, now()),
    updated_at = now()
from historical_posted h
where r.quiz_id = h.quiz_id
  and h.checksum is not null
  and (
      r.checksum_contract_version is distinct from 2
      or r.integrity_verified is distinct from true
      or r.generated_checksum is distinct from h.checksum
      or r.persisted_checksum is distinct from h.checksum
  );

-- ---------------------------------------------------------------------------
-- Auditable spaced repetition and idempotent revision answers
-- ---------------------------------------------------------------------------

alter table public.personal_review_schedule
    add column if not exists first_attempted_at timestamptz;
alter table public.personal_review_schedule
    add column if not exists last_attempted_at timestamptz;
alter table public.personal_review_schedule
    add column if not exists last_revision_at timestamptz;
alter table public.personal_review_schedule
    add column if not exists attempt_count integer not null default 0;
alter table public.personal_review_schedule
    add column if not exists revision_attempt_count integer not null default 0;
alter table public.personal_review_schedule
    add column if not exists consecutive_correct_revisions integer not null default 0;
alter table public.personal_review_schedule
    add column if not exists is_overdue boolean not null default false;

update public.personal_review_schedule
set first_attempted_at = coalesce(first_attempted_at, last_review, updated_at, now()),
    last_attempted_at = coalesce(last_attempted_at, last_review, updated_at, now()),
    attempt_count = greatest(
        attempt_count,
        coalesce(correct_attempts, 0) + coalesce(wrong_attempts, 0)
    ),
    consecutive_correct_revisions = case
        when learning_stage = 'mastered' then greatest(repetition_count, 4)
        else consecutive_correct_revisions
    end,
    is_overdue = next_review < current_date;

alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_learning_stage_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_learning_stage_check check (
        learning_stage in ('new', 'weak', 'learning', 'review', 'mastered')
    );
alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_attempt_count_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_attempt_count_check check (
        attempt_count >= 0
        and revision_attempt_count >= 0
        and consecutive_correct_revisions >= 0
        and revision_attempt_count <= attempt_count
    );

alter table public.personal_practice_answers
    add column if not exists client_attempt_id uuid;
alter table public.personal_practice_answers
    add column if not exists mode text;

update public.personal_practice_answers
set client_attempt_id = extensions.gen_random_uuid()
where client_attempt_id is null;
update public.personal_practice_answers
set mode = case
        when source_type in ('due', 'wrong', 'weak_topic') then 'revision'
        else 'practice'
    end
where mode is null;

alter table public.personal_practice_answers
    alter column client_attempt_id set not null;
alter table public.personal_practice_answers
    alter column mode set not null;
alter table public.personal_practice_answers
    drop constraint if exists personal_practice_answers_mode_check;
alter table public.personal_practice_answers
    add constraint personal_practice_answers_mode_check
        check (mode in ('revision', 'practice'));

create unique index if not exists idx_personal_practice_attempt_idempotency
    on public.personal_practice_answers (user_id, client_attempt_id);

create or replace function public.refresh_personal_review_overdue(p_user_id uuid)
returns void
language sql
volatile
security invoker
set search_path = ''
as $$
    update public.personal_review_schedule
    set is_overdue = next_review < current_date,
        updated_at = case
            when is_overdue is distinct from (next_review < current_date) then now()
            else updated_at
        end
    where user_id = p_user_id
      and is_overdue is distinct from (next_review < current_date);
$$;

create or replace function public.advance_personal_review_schedule_v2(
    p_user_id uuid,
    p_question_id uuid,
    p_is_correct boolean,
    p_mode text,
    p_response_time_seconds numeric default null,
    p_marked_for_review boolean default false
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_existing public.personal_review_schedule%rowtype;
    v_is_revision boolean;
    v_slow_or_uncertain boolean;
    v_consecutive integer;
    v_interval integer;
    v_stage text;
    v_ease numeric;
    v_has_existing boolean;
begin
    if p_mode not in ('quiz', 'revision', 'practice') then
        raise exception 'invalid learning event mode';
    end if;
    if p_response_time_seconds is not null
       and p_response_time_seconds not between 0 and 3600 then
        raise exception 'invalid response time';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('review:' || p_user_id::text || ':' || p_question_id::text, 0)
    );
    select * into v_existing
    from public.personal_review_schedule
    where user_id = p_user_id and question_id = p_question_id;
    v_has_existing := found;

    v_is_revision := p_mode = 'revision';
    v_slow_or_uncertain := p_is_correct is true and (
        p_marked_for_review or coalesce(p_response_time_seconds, 0) > 45
    );
    v_ease := case
        when not v_has_existing then case when p_is_correct then 2.50 else 2.30 end
        when p_is_correct is not true then greatest(1.30, v_existing.ease_factor - 0.20)
        when v_slow_or_uncertain then greatest(1.30, v_existing.ease_factor - 0.05)
        else least(2.80, v_existing.ease_factor + 0.05)
    end;

    v_consecutive := case
        when not v_is_revision then coalesce(v_existing.consecutive_correct_revisions, 0)
        when p_is_correct is true then coalesce(v_existing.consecutive_correct_revisions, 0) + 1
        else 0
    end;

    v_interval := case
        when p_is_correct is not true then case when v_is_revision then 1 else 0 end
        when not v_is_revision then 1
        when v_slow_or_uncertain then greatest(1, least(coalesce(v_existing.review_interval, 1), 3))
        when v_consecutive = 1 then 1
        when v_consecutive = 2 then 3
        when v_consecutive = 3 then 7
        when v_consecutive = 4 then 14
        when v_consecutive = 5 then 30
        when v_consecutive = 6 then 60
        else least(
            180,
            greatest(
                90,
                ceil(greatest(coalesce(v_existing.review_interval, 60), 60) * 1.5)::integer
            )
        )
    end;

    v_stage := case
        when p_is_correct is not true then 'weak'
        when v_is_revision and v_consecutive >= 4 and not v_slow_or_uncertain then 'mastered'
        when v_is_revision and v_consecutive >= 2 then 'review'
        else 'learning'
    end;

    insert into public.personal_review_schedule (
        user_id, question_id, ease_factor, review_interval, next_review,
        repetition_count, last_review, learning_stage, correct_attempts,
        wrong_attempts, average_response_time_seconds, recent_confidence,
        mastery_score, first_attempted_at, last_attempted_at,
        last_revision_at, attempt_count, revision_attempt_count,
        consecutive_correct_revisions, is_overdue, updated_at
    ) values (
        p_user_id, p_question_id, v_ease, v_interval,
        current_date + v_interval,
        case when p_is_correct then 1 else 0 end,
        now(), v_stage,
        case when p_is_correct then 1 else 0 end,
        case when p_is_correct then 0 else 1 end,
        p_response_time_seconds,
        case when p_is_correct then case when v_slow_or_uncertain then 0.6 else 1 end else 0 end,
        case when p_is_correct then case when v_slow_or_uncertain then 25 else 35 end else 0 end,
        now(), now(), case when v_is_revision then now() end,
        1, case when v_is_revision then 1 else 0 end,
        v_consecutive, false, now()
    )
    on conflict (user_id, question_id) do update set
        ease_factor = v_ease,
        review_interval = v_interval,
        next_review = current_date + v_interval,
        repetition_count = case
            when p_is_correct then public.personal_review_schedule.repetition_count + 1
            else 0
        end,
        last_review = now(),
        learning_stage = v_stage,
        correct_attempts = public.personal_review_schedule.correct_attempts
            + case when p_is_correct then 1 else 0 end,
        wrong_attempts = public.personal_review_schedule.wrong_attempts
            + case when p_is_correct then 0 else 1 end,
        average_response_time_seconds = case
            when p_response_time_seconds is null then
                public.personal_review_schedule.average_response_time_seconds
            when public.personal_review_schedule.average_response_time_seconds is null then
                p_response_time_seconds
            else round((
                public.personal_review_schedule.average_response_time_seconds
                    * public.personal_review_schedule.attempt_count
                + p_response_time_seconds
            ) / (public.personal_review_schedule.attempt_count + 1), 2)
        end,
        recent_confidence = case
            when p_is_correct then case when v_slow_or_uncertain then 0.6 else 1 end
            else 0
        end,
        mastery_score = round(case
            when p_is_correct is not true then
                public.personal_review_schedule.mastery_score * 0.55
            when v_slow_or_uncertain then
                public.personal_review_schedule.mastery_score * 0.75 + 12
            else public.personal_review_schedule.mastery_score * 0.75 + 25
        end, 2),
        first_attempted_at = coalesce(
            public.personal_review_schedule.first_attempted_at,
            now()
        ),
        last_attempted_at = now(),
        last_revision_at = case
            when v_is_revision then now()
            else public.personal_review_schedule.last_revision_at
        end,
        attempt_count = public.personal_review_schedule.attempt_count + 1,
        revision_attempt_count = public.personal_review_schedule.revision_attempt_count
            + case when v_is_revision then 1 else 0 end,
        consecutive_correct_revisions = v_consecutive,
        is_overdue = false,
        updated_at = now();
end;
$$;

-- Preserve the trigger-facing historical signature while routing it through
-- the understandable v2 algorithm as a normal first-attempt event.
create or replace function public.advance_personal_review_schedule(
    p_user_id uuid,
    p_question_id uuid,
    p_is_correct boolean,
    p_response_time_seconds numeric default null,
    p_marked_for_review boolean default false
)
returns void
language sql
security invoker
set search_path = ''
as $$
    select public.advance_personal_review_schedule_v2(
        p_user_id, p_question_id, p_is_correct, 'quiz',
        p_response_time_seconds, p_marked_for_review
    );
$$;

drop function if exists public.submit_personal_practice_answer(
    uuid, uuid, integer, text, numeric, boolean
);

create function public.submit_personal_practice_answer(
    p_user_id uuid,
    p_question_id uuid,
    p_client_attempt_id uuid,
    p_selected_option integer,
    p_source_type text,
    p_mode text,
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
    v_existing public.personal_practice_answers%rowtype;
    v_correct_index integer;
    v_is_correct boolean;
    v_schedule public.personal_review_schedule%rowtype;
    v_result jsonb;
begin
    if p_client_attempt_id is null then
        raise exception 'a client-generated UUID practice identifier is required';
    end if;
    if p_selected_option not between 0 and 3 then
        raise exception 'selected option must be between 0 and 3';
    end if;
    if p_source_type not in ('wrong', 'due', 'bookmark', 'weak_topic') then
        raise exception 'invalid practice source';
    end if;
    if p_mode not in ('revision', 'practice') then
        raise exception 'invalid practice mode';
    end if;
    if p_mode = 'revision' and p_source_type not in ('wrong', 'due', 'weak_topic') then
        raise exception 'revision mode does not match the server queue';
    end if;
    if p_mode = 'practice' and p_source_type <> 'bookmark' then
        raise exception 'practice mode does not match the server queue';
    end if;
    if p_response_time_seconds is not null
       and p_response_time_seconds not between 0 and 3600 then
        raise exception 'invalid response time';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('practice:' || p_user_id::text || ':' || p_client_attempt_id::text, 0)
    );
    select * into v_existing
    from public.personal_practice_answers
    where user_id = p_user_id and client_attempt_id = p_client_attempt_id;
    if found then
        if v_existing.question_id <> p_question_id
           or v_existing.selected_option <> p_selected_option
           or v_existing.source_type <> p_source_type
           or v_existing.mode <> p_mode then
            raise exception 'practice identifier was already used with different content';
        end if;
        select * into v_question from public.questions where id = v_existing.question_id;
        select * into v_schedule
        from public.personal_review_schedule
        where user_id = p_user_id and question_id = p_question_id;
        v_result := jsonb_build_object(
            'questionId', v_question.id,
            'attemptId', v_existing.client_attempt_id,
            'mode', v_existing.mode,
            'q', v_question.question_text,
            'o', jsonb_build_array(
                v_question.option_a, v_question.option_b,
                v_question.option_c, v_question.option_d
            ),
            'selectedIndex', v_existing.selected_option,
            'correctIndex', v_existing.correct_option,
            'isCorrect', v_existing.is_correct,
            'explanation', coalesce(
                nullif(v_question.detailed_explanation, ''),
                v_question.explanation,
                ''
            ),
            'sourceUrl', v_question.source_url,
            'sourceTitle', v_question.source_title,
            'verifiedAt', v_question.verified_at,
            'factVersion', v_question.fact_version,
            'microTopicKey', v_question.micro_topic_key,
            'nextReview', v_schedule.next_review,
            'reviewIntervalDays', v_schedule.review_interval,
            'learningStage', v_schedule.learning_stage,
            'masteryScore', v_schedule.mastery_score,
            'idempotentReplay', true
        );
        return v_result;
    end if;

    if (
        select count(*)
        from public.personal_practice_answers
        where user_id = p_user_id
          and answered_at >= now() - interval '1 hour'
    ) >= 120 then
        raise exception 'practice answer rate limit exceeded';
    end if;

    select * into v_question
    from public.questions
    where id = p_question_id
      and status in ('verified', 'active', 'reported');
    if not found then
        raise exception 'question is not available';
    end if;

    -- Revision ownership must come from an existing user-question schedule;
    -- the browser cannot turn an unseen question into revision mode.
    if p_mode = 'revision' and not exists (
        select 1 from public.personal_review_schedule
        where user_id = p_user_id and question_id = p_question_id
    ) then
        raise exception 'question is not in this user revision queue';
    end if;

    v_correct_index := ascii(v_question.correct_option::text) - ascii('A');
    v_is_correct := p_selected_option = v_correct_index;

    insert into public.personal_practice_answers (
        user_id, question_id, client_attempt_id, source_type, mode,
        selected_option, correct_option, is_correct,
        response_time_seconds, marked_for_review
    ) values (
        p_user_id, p_question_id, p_client_attempt_id, p_source_type, p_mode,
        p_selected_option, v_correct_index, v_is_correct,
        p_response_time_seconds, p_marked_for_review
    );

    perform public.advance_personal_review_schedule_v2(
        p_user_id, p_question_id, v_is_correct, p_mode,
        p_response_time_seconds, p_marked_for_review
    );
    select * into v_schedule
    from public.personal_review_schedule
    where user_id = p_user_id and question_id = p_question_id;

    return jsonb_build_object(
        'questionId', v_question.id,
        'attemptId', p_client_attempt_id,
        'mode', p_mode,
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
        'factVersion', v_question.fact_version,
        'microTopicKey', v_question.micro_topic_key,
        'nextReview', v_schedule.next_review,
        'reviewIntervalDays', v_schedule.review_interval,
        'learningStage', v_schedule.learning_stage,
        'masteryScore', v_schedule.mastery_score,
        'idempotentReplay', false
    );
end;
$$;

-- Queue payloads explicitly declare their mode. The Mini App must use this
-- field and must not infer revision behaviour from URL text.
create or replace function public.get_user_due_reviews(
    p_user_id uuid,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    perform public.refresh_personal_review_overdue(p_user_id);
    v_result := public.canonicalize_subject_rows(
        public.get_user_due_reviews_internal(p_user_id, p_limit, p_offset)
    );
    return v_result || jsonb_build_object(
        'mode', 'revision',
        'sourceType', 'due'
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
    select public.canonicalize_subject_rows(
        public.get_user_wrong_questions_internal(
            p_user_id,
            public.canonical_subject_internal_name(p_subject_key),
            p_limit,
            p_offset
        )
    ) || jsonb_build_object(
        'mode', 'revision',
        'sourceType', case
            when p_subject_key is null then 'wrong'
            else 'weak_topic'
        end
    );
$$;

create or replace function public.get_user_bookmarks(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select public.canonicalize_subject_rows(
        public.get_user_bookmarks_internal(p_user_id)
    ) || jsonb_build_object(
        'mode', 'practice',
        'sourceType', 'bookmark'
    );
$$;

-- ---------------------------------------------------------------------------
-- Revision feedback preferences and personal identity support
-- ---------------------------------------------------------------------------

alter table public.user_preferences
    add column if not exists revision_sound_enabled boolean not null default true;
alter table public.user_preferences
    add column if not exists revision_vibration_enabled boolean not null default false;
alter table public.users add column if not exists photo_url text;
alter table public.users drop constraint if exists users_photo_url_check;
alter table public.users add constraint users_photo_url_check check (
    photo_url is null or photo_url ~ '^https://'
);

create or replace function public.get_user_preferences(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'targetExams', coalesce(p.target_exams, '{}'),
    'preferredSubjects', coalesce(p.preferred_subjects, '{}'),
    'dailyQuestionTarget', coalesce(p.daily_question_target, 30),
    'preferredLanguage', coalesce(p.preferred_language, 'bn'),
    'difficultyPreference', coalesce(p.difficulty_preference, 'adaptive'),
    'quizMode', coalesce(p.quiz_mode, 'timed'),
    'leaderboardVisible', coalesce(p.leaderboard_visible, u.leaderboard_visible, true),
    'publicDisplayName', coalesce(p.public_display_name, u.public_display_name),
    'usernameVisible', coalesce(p.username_visible, u.username_visible, false),
    'dailyReminderEnabled', coalesce(p.daily_reminder_enabled, false),
    'revisionSoundEnabled', coalesce(p.revision_sound_enabled, true),
    'revisionVibrationEnabled', coalesce(p.revision_vibration_enabled, false)
)
from public.users u
left join public.user_preferences p on p.user_id = u.id
where u.id = p_user_id;
$$;

drop function if exists public.save_user_preferences(
    uuid, text[], text[], integer, text, text, text,
    boolean, text, boolean, boolean
);

create function public.save_user_preferences(
    p_user_id uuid,
    p_target_exams text[],
    p_preferred_subjects text[],
    p_daily_question_target integer,
    p_preferred_language text,
    p_difficulty_preference text,
    p_quiz_mode text,
    p_leaderboard_visible boolean,
    p_public_display_name text,
    p_username_visible boolean,
    p_daily_reminder_enabled boolean,
    p_revision_sound_enabled boolean,
    p_revision_vibration_enabled boolean
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if p_daily_question_target not between 1 and 130 then
        raise exception 'daily question target must be between 1 and 130';
    end if;
    if p_preferred_language not in ('bn', 'hi', 'en') then
        raise exception 'invalid preferred language';
    end if;
    if p_difficulty_preference not in ('adaptive', 'easy', 'medium', 'hard') then
        raise exception 'invalid difficulty preference';
    end if;
    if p_quiz_mode not in ('timed', 'practice') then
        raise exception 'invalid quiz mode';
    end if;
    if cardinality(coalesce(p_target_exams, '{}')) > 11
       or exists (
           select 1
           from unnest(coalesce(p_target_exams, '{}')) requested_exam(exam_key)
           where not exists (
               select 1 from public.exam_catalogue e
               where e.exam_key = requested_exam.exam_key and e.active
           )
       ) then
        raise exception 'invalid target exam';
    end if;
    if cardinality(coalesce(p_preferred_subjects, '{}')) > 13
       or exists (
           select 1
           from unnest(coalesce(p_preferred_subjects, '{}')) requested_subject(subject_key)
           where not exists (
               select 1 from public.quiz_subjects s
               where s.subject_key = requested_subject.subject_key and s.active
           )
       ) then
        raise exception 'invalid preferred subject';
    end if;

    insert into public.user_preferences (
        user_id, target_exams, preferred_subjects, daily_question_target,
        preferred_language, difficulty_preference, quiz_mode,
        leaderboard_visible, public_display_name, username_visible,
        daily_reminder_enabled, revision_sound_enabled,
        revision_vibration_enabled, updated_at
    ) values (
        p_user_id, coalesce(p_target_exams, '{}'),
        coalesce(p_preferred_subjects, '{}'), p_daily_question_target,
        p_preferred_language, p_difficulty_preference, p_quiz_mode,
        p_leaderboard_visible, nullif(btrim(p_public_display_name), ''),
        p_username_visible, p_daily_reminder_enabled,
        p_revision_sound_enabled, p_revision_vibration_enabled, now()
    )
    on conflict (user_id) do update set
        target_exams = excluded.target_exams,
        preferred_subjects = excluded.preferred_subjects,
        daily_question_target = excluded.daily_question_target,
        preferred_language = excluded.preferred_language,
        difficulty_preference = excluded.difficulty_preference,
        quiz_mode = excluded.quiz_mode,
        leaderboard_visible = excluded.leaderboard_visible,
        public_display_name = excluded.public_display_name,
        username_visible = excluded.username_visible,
        daily_reminder_enabled = excluded.daily_reminder_enabled,
        revision_sound_enabled = excluded.revision_sound_enabled,
        revision_vibration_enabled = excluded.revision_vibration_enabled,
        updated_at = now();

    update public.users
    set leaderboard_visible = p_leaderboard_visible,
        public_display_name = nullif(btrim(p_public_display_name), ''),
        username_visible = p_username_visible,
        last_active = now()
    where id = p_user_id;

    return public.get_user_preferences(p_user_id);
end;
$$;

create or replace function public.get_user_learning_dashboard(p_user_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_base jsonb;
begin
    perform public.refresh_personal_review_overdue(p_user_id);
    v_base := public.canonicalize_subject_rows(
        public.get_user_learning_dashboard_internal(p_user_id)
    );

    return v_base || (
        with all_answers as (
            select
                aa.is_correct,
                aa.selected_option is not null as answered,
                coalesce(aa.answered_at, a.completed_at) as answered_at,
                aa.response_time_seconds,
                public.canonical_subject_key(q.subject) as subject,
                q.topic,
                a.quiz_id,
                a.attempt_number
            from public.quiz_attempt_answers aa
            join public.quiz_attempts a on a.id = aa.attempt_id
            join public.questions q on q.id = aa.question_id
            where a.user_id = p_user_id and a.is_completed
            union all
            select
                pa.is_correct, true, pa.answered_at,
                pa.response_time_seconds,
                public.canonical_subject_key(q.subject), q.topic,
                null::text, null::integer
            from public.personal_practice_answers pa
            join public.questions q on q.id = pa.question_id
            where pa.user_id = p_user_id
        ), subject_stats as (
            select
                subject,
                count(*) filter (where answered)::integer as attempted,
                count(*) filter (where answered and is_correct)::integer as correct,
                round(
                    100.0 * count(*) filter (where answered and is_correct)
                    / nullif(count(*) filter (where answered), 0),
                    2
                ) as accuracy
            from all_answers
            group by subject
        ), overall_users as (
            select
                a.user_id,
                sum(a.score)::integer as correct,
                sum(a.answered)::integer as answered,
                round(100.0 * sum(a.score) / nullif(sum(a.answered), 0), 2) as accuracy,
                max(a.completed_at) as last_activity
            from public.quiz_attempts a
            where a.is_completed and a.attempt_number = 1
            group by a.user_id
        ), overall_ranked as (
            select user_id, row_number() over (
                order by correct desc, accuracy desc, answered desc,
                         last_activity asc, user_id
            ) as rank
            from overall_users
        ), weekly_users as (
            select
                a.user_id,
                sum(a.score)::integer as correct,
                sum(a.answered)::integer as answered,
                round(100.0 * sum(a.score) / nullif(sum(a.answered), 0), 2) as accuracy,
                max(a.completed_at) as last_activity
            from public.quiz_attempts a
            where a.is_completed
              and a.attempt_number = 1
              and a.completed_at >= date_trunc('week', now() at time zone 'Asia/Kolkata') at time zone 'Asia/Kolkata'
            group by a.user_id
        ), weekly_ranked as (
            select user_id, row_number() over (
                order by correct desc, accuracy desc, answered desc,
                         last_activity asc, user_id
            ) as rank
            from weekly_users
        ), review_summary as (
            select
                count(*) filter (where next_review = current_date)::integer as due_today,
                count(*) filter (where next_review < current_date)::integer as overdue,
                count(*) filter (where learning_stage = 'weak')::integer as weak,
                count(*) filter (
                    where learning_stage = 'mastered'
                      and last_revision_at >= now() - interval '7 days'
                )::integer as recently_mastered
            from public.personal_review_schedule
            where user_id = p_user_id
        ), subject_reviews as (
            select public.canonical_subject_key(q.subject) as subject,
                   count(*)::integer as due
            from public.personal_review_schedule prs
            join public.questions q on q.id = prs.question_id
            where prs.user_id = p_user_id and prs.next_review <= current_date
            group by q.subject
        ), recent_quizzes as (
            select distinct on (a.quiz_id)
                a.quiz_id, a.score, a.total, a.answered,
                a.attempt_number, a.duration_seconds, a.completed_at
            from public.quiz_attempts a
            where a.user_id = p_user_id and a.is_completed
            order by a.quiz_id, a.completed_at desc, a.id desc
        )
        select jsonb_build_object(
            'incorrectAnswers', greatest(
                0,
                coalesce((v_base ->> 'totalAnswered')::integer, 0)
                - coalesce((v_base ->> 'correctAnswers')::integer, 0)
            ),
            'totalQuizzesCompleted', (
                select count(distinct quiz_id)
                from public.quiz_attempts
                where user_id = p_user_id and is_completed
            ),
            'currentOverallRank', (
                select rank from overall_ranked where user_id = p_user_id
            ),
            'weeklyRank', (
                select rank from weekly_ranked where user_id = p_user_id
            ),
            'strongestSubject', (
                select jsonb_build_object(
                    'subjectKey', subject, 'accuracy', accuracy,
                    'attempted', attempted
                )
                from subject_stats
                where attempted > 0
                order by accuracy desc, attempted desc, subject
                limit 1
            ),
            'weakestSubject', (
                select jsonb_build_object(
                    'subjectKey', subject, 'accuracy', accuracy,
                    'attempted', attempted
                )
                from subject_stats
                where attempted > 0
                order by accuracy, attempted desc, subject
                limit 1
            ),
            'revisionDueToday', coalesce((select due_today from review_summary), 0),
            'overdueQuestions', coalesce((select overdue from review_summary), 0),
            'weakQuestions', coalesce((select weak from review_summary), 0),
            'recentlyMastered', coalesce((select recently_mastered from review_summary), 0),
            'subjectRevisionCounts', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'subjectKey', subject, 'due', due
                ) order by due desc, subject)
                from subject_reviews
            ), '[]'::jsonb),
            'recentQuizzes', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'quizId', quiz_id,
                    'score', score,
                    'total', total,
                    'answered', answered,
                    'unanswered', total - answered,
                    'accuracy', round(100.0 * score / nullif(total, 0), 2),
                    'attemptNumber', attempt_number,
                    'durationSeconds', duration_seconds,
                    'completedAt', completed_at
                ) order by completed_at desc)
                from (
                    select * from recent_quizzes
                    order by completed_at desc
                    limit 6
                ) recent
            ), '[]'::jsonb),
            'questionsReported', (
                select count(*) from public.question_reports where user_id = p_user_id
            )
        )
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- Current-user-aware official quiz leaderboard
-- ---------------------------------------------------------------------------

create or replace function public.get_quiz_leaderboard_for_user(
    p_quiz_id text,
    p_user_id uuid default null,
    p_limit integer default 10
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with official as (
    select
        a.id,
        a.user_id,
        a.score,
        a.total,
        a.answered,
        a.duration_seconds,
        a.completed_at,
        u.leaderboard_visible,
        u.photo_url,
        coalesce(
            nullif(btrim(u.public_display_name), ''),
            case
                when u.username_visible and nullif(btrim(u.username), '') is not null
                then '@' || btrim(u.username)
            end,
            nullif(btrim(concat_ws(' ', u.first_name, u.last_name)), ''),
            'শিক্ষার্থী ' || upper(substr(md5(u.id::text), 1, 4))
        ) as display_name,
        upper(left(coalesce(nullif(btrim(u.first_name), ''), 'শি'), 1)) as initials,
        (select count(*)::integer from public.quiz_attempts count_attempts
         where count_attempts.quiz_id = a.quiz_id
           and count_attempts.user_id = a.user_id
           and count_attempts.is_completed) as attempts_count
    from public.quiz_attempts a
    join public.users u on u.id = a.user_id
    where a.quiz_id = p_quiz_id
      and a.is_completed
      and a.attempt_number = 1
), ranked as (
    select
        row_number() over (
            order by score desc, answered desc,
                     duration_seconds asc nulls last,
                     completed_at asc, id
        ) as rank,
        *
    from official
), top_rows as (
    select *
    from ranked
    where leaderboard_visible
    order by rank
    limit greatest(1, least(coalesce(p_limit, 10), 50))
), current_row as (
    select * from ranked where user_id = p_user_id
), top_json as (
    select coalesce(jsonb_agg(jsonb_build_object(
        'rank', rank,
        'displayName', display_name,
        'initials', initials,
        'profilePhotoUrl', case when user_id = p_user_id then photo_url end,
        'score', score,
        'total', total,
        'accuracy', round(100.0 * score / nullif(total, 0), 2),
        'correct', score,
        'incorrect', answered - score,
        'unanswered', total - answered,
        'answered', answered,
        'durationSeconds', duration_seconds,
        'attemptsCount', attempts_count,
        'percentile', case
            when (select count(*) from ranked) <= 1 then 100.00
            else round(
                100.0 * ((select count(*) from ranked) - rank)
                / ((select count(*) from ranked) - 1), 2
            )
        end,
        'rankMovement', null,
        'isCurrentUser', user_id = p_user_id
    ) order by rank), '[]'::jsonb) as rows
    from top_rows
), current_json as (
    select jsonb_build_object(
        'rank', rank,
        'displayName', display_name,
        'initials', initials,
        'profilePhotoUrl', photo_url,
        'score', score,
        'total', total,
        'accuracy', round(100.0 * score / nullif(total, 0), 2),
        'correct', score,
        'incorrect', answered - score,
        'unanswered', total - answered,
        'answered', answered,
        'durationSeconds', duration_seconds,
        'attemptsCount', attempts_count,
        'percentile', case
            when (select count(*) from ranked) <= 1 then 100.00
            else round(
                100.0 * ((select count(*) from ranked) - rank)
                / ((select count(*) from ranked) - 1), 2
            )
        end,
        'rankMovement', null,
        'isCurrentUser', true
    ) as row
    from current_row
)
select jsonb_build_object(
    'quizId', p_quiz_id,
    'participants', (select count(*) from ranked),
    'rows', top_json.rows,
    'currentUser', (select row from current_json),
    'separatorRequired', coalesce(
        (select rank from current_row) > coalesce(
            (select max((row ->> 'rank')::integer)
             from jsonb_array_elements(top_json.rows) row),
            0
        ),
        false
    ),
    'tieBreak', 'score, answered questions, faster time, earlier completion',
    'rankingScope', 'first_attempt_only',
    'retakesAffectOfficialRank', false,
    'practiceAffectsOfficialRank', false
)
from top_json;
$$;

drop function if exists public.submit_question_report(
    uuid, text, uuid, text, text, text, integer
);

create function public.submit_question_report(
    p_question_id uuid,
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid,
    p_reason text,
    p_details text default null,
    p_threshold integer default 3
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt_id uuid;
    v_report_id uuid;
    v_open_reports integer;
    v_question_status text;
begin
    if p_reason not in (
        'wrong_answer', 'multiple_correct', 'ambiguous',
        'incorrect_explanation', 'language_spelling', 'outdated',
        'outside_syllabus', 'broken_source', 'other'
    ) then
        raise exception 'invalid report reason';
    end if;
    if length(coalesce(p_details, '')) > 1000 then
        raise exception 'report details are too long';
    end if;
    if p_reason = 'other' and nullif(btrim(p_details), '') is null then
        raise exception 'other reports require details';
    end if;
    if p_client_attempt_id is null then
        raise exception 'a completed UUID attempt identifier is required';
    end if;

    perform pg_advisory_xact_lock(
        hashtextextended('report-rate:' || p_user_id::text, 0)
    );
    if (
        select count(*) from public.question_reports
        where user_id = p_user_id
          and created_at >= now() - interval '1 hour'
    ) >= 5 then
        raise exception 'report rate limit exceeded';
    end if;

    select a.id into v_attempt_id
    from public.quiz_attempts a
    join public.quiz_attempt_answers aa on aa.attempt_id = a.id
    where a.quiz_id = p_quiz_id
      and a.user_id = p_user_id
      and a.client_attempt_uuid = p_client_attempt_id
      and a.is_completed
      and aa.question_id = p_question_id
    limit 1;
    if not found then
        raise exception 'question report is not linked to this completed attempt';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(p_question_id::text, 0));
    insert into public.question_reports (
        question_id, quiz_id, user_id, attempt_id, reason, details
    ) values (
        p_question_id, p_quiz_id, p_user_id, v_attempt_id, p_reason,
        nullif(btrim(p_details), '')
    ) returning id into v_report_id;

    select count(distinct user_id)::integer into v_open_reports
    from public.question_reports
    where question_id = p_question_id
      and status in ('open', 'under_review');

    if v_open_reports >= greatest(2, p_threshold) then
        update public.question_reports
        set status = 'under_review'
        where question_id = p_question_id and status = 'open';
        update public.questions
        set status = 'quarantined', review_required = true
        where id = p_question_id and status not in ('rejected', 'archived');
    elseif v_open_reports > 0 then
        update public.questions
        set status = 'reported'
        where id = p_question_id and status = 'active';
    end if;

    select status into v_question_status
    from public.questions where id = p_question_id;
    return jsonb_build_object(
        'reportId', v_report_id,
        'status', 'accepted',
        'credibleReportCount', v_open_reports,
        'questionStatus', v_question_status,
        'quarantined', v_question_status = 'quarantined'
    );
exception when unique_violation then
    raise exception 'this question was already reported for this attempt';
end;
$$;

-- ---------------------------------------------------------------------------
-- Contract ledger and least privilege
-- ---------------------------------------------------------------------------

update public.application_schema_contract
set contract_version = '2.1.0',
    required_migration_version = '20260718222134',
    verification_threshold = 0.85,
    applied_at = now()
where contract_key = 'telegram_quiz_api';

create or replace function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_contract public.application_schema_contract%rowtype;
    v_migration_applied boolean := false;
    v_tables text[] := array[
        'questions', 'quiz_runs', 'quiz_questions', 'quiz_attempts',
        'quiz_attempt_answers', 'users', 'personal_review_schedule',
        'personal_practice_answers', 'user_preferences', 'question_reports',
        'source_documents', 'quiz_subjects', 'quiz_chapters',
        'quiz_micro_topics', 'application_schema_contract',
        'quiz_pack_integrity_failures'
    ];
    v_functions text[] := array[
        'public.claim_quiz_run(text,text,text,integer,boolean)',
        'public.save_quiz_pack_atomic(text,text,jsonb,text,boolean)',
        'public.quiz_pack_checksum(text)',
        'public.question_content_hash(jsonb)',
        'public.submit_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)',
        'public.quiz_attempt_result(uuid)',
        'public.get_grounding_bundle(text,text,date,integer)',
        'public.submit_question_report(uuid,text,uuid,uuid,text,text,integer)',
        'public.get_user_learning_dashboard(uuid)',
        'public.get_user_due_reviews(uuid,integer,integer)',
        'public.get_user_wrong_questions(uuid,text,integer,integer)',
        'public.submit_personal_practice_answer(uuid,uuid,uuid,integer,text,text,numeric,boolean)',
        'public.get_user_preferences(uuid)',
        'public.save_user_preferences(uuid,text[],text[],integer,text,text,text,boolean,text,boolean,boolean,boolean,boolean)',
        'public.get_quiz_leaderboard_for_user(text,uuid,integer)',
        'public.get_application_schema_contract()'
    ];
    v_missing_tables jsonb;
    v_missing_columns jsonb;
    v_missing_functions jsonb;
    v_function_permission_failures jsonb;
    v_missing_rls jsonb;
    v_table_permission_failures jsonb;
begin
    select * into v_contract
    from public.application_schema_contract
    where contract_key = 'telegram_quiz_api';

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute
            'select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = $1
                   or name = ''learning_and_leaderboard_contract_v2''
            )'
        into v_migration_applied
        using v_contract.required_migration_version;
    end if;

    select coalesce(jsonb_agg(name order by name), '[]'::jsonb)
    into v_missing_tables
    from unnest(v_tables) name
    where to_regclass('public.' || name) is null;

    with required(table_name, column_name) as (
        values
            ('questions','stem_hash'), ('questions','content_hash'),
            ('questions','content_version'), ('questions','language'),
            ('quiz_runs','generated_checksum'), ('quiz_runs','persisted_checksum'),
            ('quiz_runs','integrity_verified'),
            ('quiz_attempts','client_attempt_uuid'),
            ('personal_practice_answers','client_attempt_id'),
            ('personal_practice_answers','mode'),
            ('personal_review_schedule','first_attempted_at'),
            ('personal_review_schedule','last_attempted_at'),
            ('personal_review_schedule','last_revision_at'),
            ('personal_review_schedule','attempt_count'),
            ('personal_review_schedule','revision_attempt_count'),
            ('personal_review_schedule','consecutive_correct_revisions'),
            ('personal_review_schedule','is_overdue'),
            ('user_preferences','revision_sound_enabled'),
            ('user_preferences','revision_vibration_enabled'),
            ('users','photo_url')
    )
    select coalesce(jsonb_agg(
        table_name || '.' || column_name order by table_name, column_name
    ), '[]'::jsonb)
    into v_missing_columns
    from required
    where not exists (
        select 1 from information_schema.columns c
        where c.table_schema = 'public'
          and c.table_name = required.table_name
          and c.column_name = required.column_name
    );

    select coalesce(jsonb_agg(signature order by signature), '[]'::jsonb)
    into v_missing_functions
    from unnest(v_functions) signature
    where to_regprocedure(signature) is null;

    select coalesce(jsonb_agg(signature order by signature), '[]'::jsonb)
    into v_function_permission_failures
    from unnest(v_functions) signature
    where to_regprocedure(signature) is not null
      and (
          not has_function_privilege(
              'service_role', to_regprocedure(signature), 'EXECUTE'
          )
          or has_function_privilege(
              'anon', to_regprocedure(signature), 'EXECUTE'
          )
          or has_function_privilege(
              'authenticated', to_regprocedure(signature), 'EXECUTE'
          )
      );

    select coalesce(jsonb_agg(name order by name), '[]'::jsonb)
    into v_missing_rls
    from unnest(v_tables) name
    join pg_catalog.pg_class rel on rel.relname = name
    join pg_catalog.pg_namespace ns on ns.oid = rel.relnamespace
    where ns.nspname = 'public' and not rel.relrowsecurity;

    select coalesce(jsonb_agg(name order by name), '[]'::jsonb)
    into v_table_permission_failures
    from unnest(v_tables) name
    where to_regclass('public.' || name) is not null
      and (has_table_privilege(
              'anon', 'public.' || name, 'SELECT,INSERT,UPDATE,DELETE'
          )
       or has_table_privilege(
              'authenticated', 'public.' || name, 'SELECT,INSERT,UPDATE,DELETE'
          )
       or not has_table_privilege('service_role', 'public.' || name, 'SELECT'));

    return jsonb_build_object(
        'contract_key', v_contract.contract_key,
        'contract_version', v_contract.contract_version,
        'required_migration_version', v_contract.required_migration_version,
        'migration_applied', v_migration_applied,
        'verification_threshold', v_contract.verification_threshold,
        'missing_tables', v_missing_tables,
        'missing_columns', v_missing_columns,
        'missing_functions', v_missing_functions,
        'function_permission_failures', v_function_permission_failures,
        'missing_rls', v_missing_rls,
        'table_permission_failures', v_table_permission_failures,
        'ready',
            v_contract.contract_version = '2.1.0'
            and v_contract.required_migration_version = '20260718222134'
            and v_contract.verification_threshold = 0.85
            and v_migration_applied
            and v_missing_tables = '[]'::jsonb
            and v_missing_columns = '[]'::jsonb
            and v_missing_functions = '[]'::jsonb
            and v_function_permission_failures = '[]'::jsonb
            and v_missing_rls = '[]'::jsonb
            and v_table_permission_failures = '[]'::jsonb
    );
end;
$$;

revoke execute on function public.refresh_personal_review_overdue(uuid)
    from public, anon, authenticated;
revoke execute on function public.advance_personal_review_schedule_v2(
    uuid, uuid, boolean, text, numeric, boolean
) from public, anon, authenticated;
revoke execute on function public.advance_personal_review_schedule(
    uuid, uuid, boolean, numeric, boolean
) from public, anon, authenticated;
revoke execute on function public.submit_personal_practice_answer(
    uuid, uuid, uuid, integer, text, text, numeric, boolean
) from public, anon, authenticated;
revoke execute on function public.get_user_due_reviews(uuid, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_bookmarks(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_user_preferences(uuid)
    from public, anon, authenticated;
revoke execute on function public.save_user_preferences(
    uuid, text[], text[], integer, text, text, text,
    boolean, text, boolean, boolean, boolean, boolean
) from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_for_user(text, uuid, integer)
    from public, anon, authenticated;
revoke execute on function public.submit_question_report(
    uuid, text, uuid, uuid, text, text, integer
) from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.refresh_personal_review_overdue(uuid)
    to service_role;
grant execute on function public.advance_personal_review_schedule_v2(
    uuid, uuid, boolean, text, numeric, boolean
) to service_role;
grant execute on function public.advance_personal_review_schedule(
    uuid, uuid, boolean, numeric, boolean
) to service_role;
grant execute on function public.submit_personal_practice_answer(
    uuid, uuid, uuid, integer, text, text, numeric, boolean
) to service_role;
grant execute on function public.get_user_due_reviews(uuid, integer, integer)
    to service_role;
grant execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    to service_role;
grant execute on function public.get_user_bookmarks(uuid) to service_role;
grant execute on function public.get_user_preferences(uuid) to service_role;
grant execute on function public.save_user_preferences(
    uuid, text[], text[], integer, text, text, text,
    boolean, text, boolean, boolean, boolean, boolean
) to service_role;
grant execute on function public.get_user_learning_dashboard(uuid)
    to service_role;
grant execute on function public.get_quiz_leaderboard_for_user(text, uuid, integer)
    to service_role;
grant execute on function public.submit_question_report(
    uuid, text, uuid, uuid, text, text, integer
) to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
