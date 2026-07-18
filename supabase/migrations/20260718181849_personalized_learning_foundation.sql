-- Personalized preparation, revision, preferences, and bookmarks. The browser
-- continues to authenticate through FastAPI; every table and RPC is restricted
-- to the server-side service role.

alter table public.personal_review_schedule
    add column if not exists correct_attempts integer not null default 0;
alter table public.personal_review_schedule
    add column if not exists wrong_attempts integer not null default 0;
alter table public.personal_review_schedule
    add column if not exists average_response_time_seconds numeric;
alter table public.personal_review_schedule
    add column if not exists recent_confidence numeric not null default 0;
alter table public.personal_review_schedule
    add column if not exists mastery_score numeric not null default 0;
alter table public.personal_review_schedule
    add column if not exists updated_at timestamptz not null default now();

do $$
begin
    if not exists (
        select 1
        from pg_constraint c
        where c.conrelid = 'public.personal_review_schedule'::regclass
          and c.contype = 'u'
          and array(
              select a.attname
              from unnest(c.conkey) with ordinality as key(attnum, position)
              join pg_attribute a
                on a.attrelid = c.conrelid
               and a.attnum = key.attnum
              order by key.position
          ) = array['user_id', 'question_id']::name[]
    ) then
        alter table public.personal_review_schedule
            add constraint personal_review_schedule_user_question_key
            unique (user_id, question_id);
    end if;
end;
$$;

alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_attempt_counts_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_attempt_counts_check check (
        correct_attempts >= 0 and wrong_attempts >= 0
    );
alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_response_time_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_response_time_check check (
        average_response_time_seconds is null
        or average_response_time_seconds >= 0
    );
alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_confidence_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_confidence_check check (
        recent_confidence between 0 and 1
    );
alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_mastery_check;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_mastery_check check (
        mastery_score between 0 and 100
    );

create index if not exists idx_personal_review_schedule_user_due
    on public.personal_review_schedule (user_id, next_review, mastery_score);

create table if not exists public.exam_catalogue (
    exam_key text primary key check (
        exam_key = upper(exam_key) and exam_key !~ '[[:space:]]'
    ),
    display_name text not null,
    active boolean not null default true,
    display_order integer not null check (display_order > 0),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (display_order)
);

insert into public.exam_catalogue (exam_key, display_name, display_order)
values
    ('WBCS', 'WBCS', 1),
    ('WBPSC_CLERKSHIP', 'WBPSC Clerkship', 2),
    ('WBPSC_MISC', 'WBPSC Miscellaneous', 3),
    ('WBP_CONSTABLE', 'WBP Constable', 4),
    ('WBP_SI', 'WBP SI', 5),
    ('KOLKATA_POLICE', 'Kolkata Police', 6),
    ('PRIMARY_TET', 'Primary TET', 7),
    ('UPPER_PRIMARY_TET', 'Upper Primary TET', 8),
    ('SSC', 'SSC', 9),
    ('RAILWAY', 'Railway', 10),
    ('BANKING', 'Banking', 11)
on conflict (exam_key) do update set
    display_name = excluded.display_name,
    display_order = excluded.display_order,
    active = true,
    updated_at = now();

create table if not exists public.user_preferences (
    user_id uuid primary key references public.users(id) on delete cascade,
    target_exams text[] not null default '{}',
    preferred_subjects text[] not null default '{}',
    daily_question_target integer not null default 30
        check (daily_question_target between 1 and 130),
    preferred_language text not null default 'bn'
        check (preferred_language in ('bn','hi','en')),
    difficulty_preference text not null default 'adaptive'
        check (difficulty_preference in ('adaptive','easy','medium','hard')),
    quiz_mode text not null default 'timed'
        check (quiz_mode in ('timed','practice')),
    leaderboard_visible boolean not null default true,
    public_display_name text check (
        public_display_name is null
        or length(btrim(public_display_name)) between 2 and 40
    ),
    username_visible boolean not null default false,
    daily_reminder_enabled boolean not null default false,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.user_question_bookmarks (
    user_id uuid not null references public.users(id) on delete cascade,
    question_id uuid not null references public.questions(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (user_id, question_id)
);

create index if not exists idx_user_question_bookmarks_question
    on public.user_question_bookmarks (question_id);

create table if not exists public.user_resource_bookmarks (
    user_id uuid not null references public.users(id) on delete cascade,
    resource_id uuid not null references public.learning_resources(id) on delete cascade,
    created_at timestamptz not null default now(),
    primary key (user_id, resource_id)
);

create index if not exists idx_user_resource_bookmarks_resource
    on public.user_resource_bookmarks (resource_id);

create or replace function public.sync_personal_review_schedule_from_answer()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_user_id uuid;
    v_slow_or_uncertain boolean;
    v_initial_interval integer;
    v_initial_repetitions integer;
    v_initial_confidence numeric;
    v_initial_mastery numeric;
begin
    select user_id into v_user_id
    from public.quiz_attempts
    where id = new.attempt_id and is_completed;

    if v_user_id is null then
        return new;
    end if;

    v_slow_or_uncertain := new.is_correct is true and (
        new.marked_for_review
        or coalesce(new.response_time_seconds, 0) > 45
    );
    v_initial_interval := case
        when new.is_correct is not true then 1
        when v_slow_or_uncertain then 3
        else 7
    end;
    v_initial_repetitions := case when new.is_correct is true then 1 else 0 end;
    v_initial_confidence := case
        when new.is_correct is not true then 0
        when v_slow_or_uncertain then 0.6
        else 1
    end;
    v_initial_mastery := case
        when new.is_correct is not true then 0
        when v_slow_or_uncertain then 25
        else 40
    end;

    insert into public.personal_review_schedule (
        user_id, question_id, ease_factor, review_interval, next_review,
        repetition_count, last_review, learning_stage, correct_attempts,
        wrong_attempts, average_response_time_seconds, recent_confidence,
        mastery_score, updated_at
    ) values (
        v_user_id,
        new.question_id,
        case when new.is_correct is true then 2.5 else 2.3 end,
        v_initial_interval,
        current_date + v_initial_interval,
        v_initial_repetitions,
        now(),
        case when new.is_correct is true then 'review' else 'learning' end,
        case when new.is_correct is true then 1 else 0 end,
        case when new.is_correct is true then 0 else 1 end,
        new.response_time_seconds,
        v_initial_confidence,
        v_initial_mastery,
        now()
    )
    on conflict (user_id, question_id) do update set
        ease_factor = case
            when new.is_correct is not true then
                greatest(1.3, public.personal_review_schedule.ease_factor - 0.20)
            when v_slow_or_uncertain then
                greatest(1.3, public.personal_review_schedule.ease_factor - 0.05)
            else least(2.8, public.personal_review_schedule.ease_factor + 0.05)
        end,
        review_interval = case
            when new.is_correct is not true then 1
            when v_slow_or_uncertain then 3
            when public.personal_review_schedule.repetition_count = 0 then 7
            when public.personal_review_schedule.repetition_count = 1 then 14
            when public.personal_review_schedule.repetition_count = 2 then 30
            else 60
        end,
        next_review = current_date + case
            when new.is_correct is not true then 1
            when v_slow_or_uncertain then 3
            when public.personal_review_schedule.repetition_count = 0 then 7
            when public.personal_review_schedule.repetition_count = 1 then 14
            when public.personal_review_schedule.repetition_count = 2 then 30
            else 60
        end,
        repetition_count = case
            when new.is_correct is not true then 0
            else public.personal_review_schedule.repetition_count + 1
        end,
        last_review = now(),
        learning_stage = case
            when new.is_correct is not true then 'learning'
            when public.personal_review_schedule.repetition_count + 1 >= 4
                and not v_slow_or_uncertain then 'mastered'
            else 'review'
        end,
        correct_attempts = public.personal_review_schedule.correct_attempts
            + case when new.is_correct is true then 1 else 0 end,
        wrong_attempts = public.personal_review_schedule.wrong_attempts
            + case when new.is_correct is true then 0 else 1 end,
        average_response_time_seconds = case
            when new.response_time_seconds is null then
                public.personal_review_schedule.average_response_time_seconds
            when public.personal_review_schedule.average_response_time_seconds is null then
                new.response_time_seconds
            else round((
                public.personal_review_schedule.average_response_time_seconds
                * (
                    public.personal_review_schedule.correct_attempts
                    + public.personal_review_schedule.wrong_attempts
                )
                + new.response_time_seconds
            ) / (
                public.personal_review_schedule.correct_attempts
                + public.personal_review_schedule.wrong_attempts
                + 1
            ), 2)
        end,
        recent_confidence = v_initial_confidence,
        mastery_score = round(case
            when new.is_correct is not true then
                public.personal_review_schedule.mastery_score * 0.70
            when v_slow_or_uncertain then
                public.personal_review_schedule.mastery_score * 0.70 + 18
            else public.personal_review_schedule.mastery_score * 0.70 + 30
        end, 2),
        updated_at = now();

    return new;
end;
$$;

drop trigger if exists sync_personal_review_schedule_after_answer
    on public.quiz_attempt_answers;
create trigger sync_personal_review_schedule_after_answer
after insert on public.quiz_attempt_answers
for each row execute function public.sync_personal_review_schedule_from_answer();

-- Backfill existing question-level attempts without overwriting any schedule
-- that has already been advanced by the trigger.
with answer_history as (
    select
        a.user_id,
        aa.question_id,
        count(*) filter (where aa.is_correct is true)::integer as correct_attempts,
        count(*) filter (where aa.is_correct is not true)::integer as wrong_attempts,
        avg(aa.response_time_seconds) as average_response_time_seconds,
        max(a.completed_at) as last_review,
        (array_agg(aa.is_correct order by a.completed_at desc, aa.id desc))[1]
            as latest_correct,
        (array_agg(aa.marked_for_review order by a.completed_at desc, aa.id desc))[1]
            as latest_marked
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    where a.is_completed
    group by a.user_id, aa.question_id
), prepared as (
    select
        *,
        case
            when latest_correct is not true then 1
            when latest_marked then 3
            when correct_attempts >= 4 then 60
            when correct_attempts = 3 then 30
            when correct_attempts = 2 then 14
            else 7
        end as interval_days
    from answer_history
)
insert into public.personal_review_schedule (
    user_id, question_id, ease_factor, review_interval, next_review,
    repetition_count, last_review, learning_stage, correct_attempts,
    wrong_attempts, average_response_time_seconds, recent_confidence,
    mastery_score, updated_at
)
select
    user_id,
    question_id,
    greatest(1.3, least(2.8, 2.5 + correct_attempts * 0.05 - wrong_attempts * 0.20)),
    interval_days,
    last_review::date + interval_days,
    case when latest_correct is true then least(correct_attempts, 4) else 0 end,
    last_review,
    case
        when latest_correct is not true then 'learning'
        when correct_attempts >= 4 then 'mastered'
        else 'review'
    end,
    correct_attempts,
    wrong_attempts,
    average_response_time_seconds,
    case when latest_correct is not true then 0 when latest_marked then 0.6 else 1 end,
    least(100, greatest(0, correct_attempts * 25 - wrong_attempts * 10)),
    now()
from prepared
on conflict (user_id, question_id) do nothing;

create or replace function public.get_user_due_reviews(
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
    select
        prs.*, q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
        q.subject, q.topic, q.micro_topic_key
    from public.personal_review_schedule prs
    join public.questions q on q.id = prs.question_id
    where prs.user_id = p_user_id
      and prs.next_review <= current_date
      and q.status in ('verified','active','reported')
), page as (
    select * from due
    order by next_review, mastery_score, question_id
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'total', (select count(*) from due),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'questionId', question_id,
        'q', question_text,
        'o', jsonb_build_array(option_a, option_b, option_c, option_d),
        'subjectKey', subject,
        'chapter', topic,
        'microTopicKey', micro_topic_key,
        'nextReview', next_review,
        'learningStage', learning_stage,
        'masteryScore', mastery_score,
        'repetitionCount', repetition_count
    ) order by next_review, mastery_score, question_id) from page), '[]'::jsonb)
);
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
with latest as (
    select distinct on (aa.question_id)
        aa.question_id, aa.is_correct, aa.marked_for_review, a.completed_at,
        q.question_text, q.option_a, q.option_b, q.option_c, q.option_d,
        q.subject, q.topic, q.micro_topic_key
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    join public.questions q on q.id = aa.question_id
    where a.user_id = p_user_id
      and a.is_completed
      and aa.selected_option is not null
      and (p_subject_key is null or q.subject = p_subject_key)
    order by aa.question_id, a.completed_at desc, aa.id desc
), wrong as (
    select * from latest where is_correct is false
), page as (
    select * from wrong
    order by completed_at desc, question_id
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
        'lastAttemptAt', completed_at,
        'markedForReview', marked_for_review
    ) order by completed_at desc, question_id) from page), '[]'::jsonb)
);
$$;

create or replace function public.get_user_learning_dashboard(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with answer_events as (
    select
        aa.is_correct,
        coalesce(aa.answered_at, a.completed_at) as answered_at,
        q.subject
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    join public.questions q on q.id = aa.question_id
    where a.user_id = p_user_id and a.is_completed and aa.selected_option is not null
), activity_days as (
    select distinct answered_at::date as activity_date from answer_events
), numbered_days as (
    select
        activity_date,
        activity_date - row_number() over (order by activity_date)::integer as island
    from activity_days
), streaks as (
    select min(activity_date) as started_on, max(activity_date) as ended_on, count(*)::integer as days
    from numbered_days
    group by island
), current_streak as (
    select coalesce(max(days), 0)::integer as days
    from streaks
    where ended_on in (current_date, current_date - 1)
), weak_subjects as (
    select
        subject,
        count(*)::integer as attempted,
        count(*) filter (where is_correct)::integer as correct,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2)
            as accuracy
    from answer_events
    group by subject
    having count(*) >= 3
    order by accuracy, attempted desc, subject
    limit 3
), weekly as (
    select
        day::date as activity_date,
        count(e.answered_at)::integer as answered,
        count(e.answered_at) filter (where e.is_correct)::integer as correct
    from generate_series(current_date - 6, current_date, interval '1 day') day
    left join answer_events e on e.answered_at::date = day::date
    group by day
    order by day
), preferences as (
    select * from public.user_preferences where user_id = p_user_id
)
select jsonb_build_object(
    'todayAnswered', (select count(*) from answer_events where answered_at::date = current_date),
    'dailyTarget', coalesce((select daily_question_target from preferences), 30),
    'dueReviews', (select count(*) from public.personal_review_schedule
        where user_id = p_user_id and next_review <= current_date),
    'bookmarkedQuestions', (select count(*) from public.user_question_bookmarks
        where user_id = p_user_id),
    'totalAnswered', (select count(*) from answer_events),
    'correctAnswers', (select count(*) from answer_events where is_correct),
    'accuracy', coalesce((select round(
        100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2
    ) from answer_events), 0),
    'currentStreak', (select days from current_streak),
    'weakSubjects', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject,
        'attempted', attempted,
        'correct', correct,
        'accuracy', accuracy
    ) order by accuracy, attempted desc, subject) from weak_subjects), '[]'::jsonb),
    'weeklyActivity', coalesce((select jsonb_agg(jsonb_build_object(
        'date', activity_date,
        'answered', answered,
        'correct', correct
    ) order by activity_date) from weekly), '[]'::jsonb)
);
$$;

create or replace function public.get_user_bookmarks(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'questions', coalesce((
        select jsonb_agg(jsonb_build_object(
            'id', q.id,
            'q', q.question_text,
            'o', jsonb_build_array(q.option_a, q.option_b, q.option_c, q.option_d),
            'subjectKey', q.subject,
            'chapter', q.topic,
            'microTopicKey', q.micro_topic_key,
            'bookmarkedAt', b.created_at
        ) order by b.created_at desc)
        from public.user_question_bookmarks b
        join public.questions q on q.id = b.question_id
        where b.user_id = p_user_id
    ), '[]'::jsonb),
    'resources', coalesce((
        select jsonb_agg(jsonb_build_object(
            'id', lr.id,
            'title', lr.title,
            'url', lr.url,
            'language', lr.language,
            'type', lr.resource_type,
            'source', lr.source_name,
            'microTopicKey', lr.micro_topic_key,
            'bookmarkedAt', b.created_at
        ) order by b.created_at desc)
        from public.user_resource_bookmarks b
        join public.learning_resources lr on lr.id = b.resource_id
        where b.user_id = p_user_id and lr.verified and lr.is_active
    ), '[]'::jsonb)
);
$$;

create or replace function public.set_user_bookmark(
    p_user_id uuid,
    p_item_type text,
    p_item_id uuid,
    p_active boolean default true
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if p_item_type = 'question' then
        if p_active then
            insert into public.user_question_bookmarks (user_id, question_id)
            values (p_user_id, p_item_id)
            on conflict do nothing;
        else
            delete from public.user_question_bookmarks
            where user_id = p_user_id and question_id = p_item_id;
        end if;
    elsif p_item_type = 'resource' then
        if p_active then
            if not exists (
                select 1 from public.learning_resources
                where id = p_item_id and verified and is_active
            ) then
                raise exception 'resource is not available';
            end if;
            insert into public.user_resource_bookmarks (user_id, resource_id)
            values (p_user_id, p_item_id)
            on conflict do nothing;
        else
            delete from public.user_resource_bookmarks
            where user_id = p_user_id and resource_id = p_item_id;
        end if;
    else
        raise exception 'invalid bookmark type';
    end if;

    return jsonb_build_object(
        'itemType', p_item_type,
        'itemId', p_item_id,
        'active', p_active
    );
end;
$$;

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
    'dailyReminderEnabled', coalesce(p.daily_reminder_enabled, false)
)
from public.users u
left join public.user_preferences p on p.user_id = u.id
where u.id = p_user_id;
$$;

create or replace function public.save_user_preferences(
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
    p_daily_reminder_enabled boolean
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
    if p_preferred_language not in ('bn','hi','en') then
        raise exception 'invalid preferred language';
    end if;
    if p_difficulty_preference not in ('adaptive','easy','medium','hard') then
        raise exception 'invalid difficulty preference';
    end if;
    if p_quiz_mode not in ('timed','practice') then
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
        daily_reminder_enabled, updated_at
    ) values (
        p_user_id,
        coalesce(p_target_exams, '{}'),
        coalesce(p_preferred_subjects, '{}'),
        p_daily_question_target,
        p_preferred_language,
        p_difficulty_preference,
        p_quiz_mode,
        p_leaderboard_visible,
        nullif(btrim(p_public_display_name), ''),
        p_username_visible,
        p_daily_reminder_enabled,
        now()
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
        updated_at = now();

    update public.users set
        leaderboard_visible = p_leaderboard_visible,
        public_display_name = nullif(btrim(p_public_display_name), ''),
        username_visible = p_username_visible,
        last_active = now()
    where id = p_user_id;

    return public.get_user_preferences(p_user_id);
end;
$$;

alter table public.exam_catalogue enable row level security;
alter table public.user_preferences enable row level security;
alter table public.user_question_bookmarks enable row level security;
alter table public.user_resource_bookmarks enable row level security;

revoke all on table public.exam_catalogue, public.user_preferences,
    public.user_question_bookmarks, public.user_resource_bookmarks
    from public, anon, authenticated;
grant select, insert, update, delete on table public.exam_catalogue,
    public.user_preferences, public.user_question_bookmarks,
    public.user_resource_bookmarks to service_role;

revoke execute on function public.sync_personal_review_schedule_from_answer()
    from public, anon, authenticated;
revoke execute on function public.get_user_due_reviews(uuid, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_user_bookmarks(uuid)
    from public, anon, authenticated;
revoke execute on function public.set_user_bookmark(uuid, text, uuid, boolean)
    from public, anon, authenticated;
revoke execute on function public.get_user_preferences(uuid)
    from public, anon, authenticated;
revoke execute on function public.save_user_preferences(
    uuid, text[], text[], integer, text, text, text, boolean, text, boolean, boolean
) from public, anon, authenticated;

grant execute on function public.sync_personal_review_schedule_from_answer()
    to service_role;
grant execute on function public.get_user_due_reviews(uuid, integer, integer)
    to service_role;
grant execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    to service_role;
grant execute on function public.get_user_learning_dashboard(uuid)
    to service_role;
grant execute on function public.get_user_bookmarks(uuid) to service_role;
grant execute on function public.set_user_bookmark(uuid, text, uuid, boolean)
    to service_role;
grant execute on function public.get_user_preferences(uuid) to service_role;
grant execute on function public.save_user_preferences(
    uuid, text[], text[], integer, text, text, text, boolean, text, boolean, boolean
) to service_role;
