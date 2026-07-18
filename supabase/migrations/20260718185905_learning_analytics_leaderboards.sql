-- Scalable private learning analytics and fair, privacy-safe public
-- leaderboard families. Aggregation stays in PostgreSQL; FastAPI receives
-- bounded JSON pages rather than downloading raw attempt rows.

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

alter table public.personal_practice_answers enable row level security;
revoke all on table public.personal_practice_answers
    from public, anon, authenticated;
grant select, insert on table public.personal_practice_answers to service_role;

create or replace function public.get_user_learning_dashboard(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with answer_events as (
    select
        a.id as attempt_id,
        a.quiz_id,
        a.attempt_number,
        aa.question_id,
        aa.is_correct,
        aa.selected_option is not null as is_answered,
        aa.response_time_seconds,
        coalesce(aa.answered_at, a.completed_at) as answered_at,
        q.subject,
        q.topic as chapter,
        q.micro_topic_key,
        q.difficulty
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    join public.questions q on q.id = aa.question_id
    where a.user_id = p_user_id and a.is_completed
    union all
    select
        pa.id as attempt_id,
        null::text as quiz_id,
        null::integer as attempt_number,
        pa.question_id,
        pa.is_correct,
        true as is_answered,
        pa.response_time_seconds,
        pa.answered_at,
        q.subject,
        q.topic as chapter,
        q.micro_topic_key,
        q.difficulty
    from public.personal_practice_answers pa
    join public.questions q on q.id = pa.question_id
    where pa.user_id = p_user_id
), answered_events as (
    select * from answer_events where is_answered
), activity_days as (
    select distinct answered_at::date as activity_date from answered_events
), numbered_days as (
    select
        activity_date,
        activity_date - row_number() over (order by activity_date)::integer as island
    from activity_days
), streaks as (
    select max(activity_date) as ended_on, count(*)::integer as days
    from numbered_days
    group by island
), subject_stats as (
    select
        subject,
        count(*)::integer as attempted,
        count(*) filter (where is_correct)::integer as correct,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as accuracy
    from answered_events
    group by subject
), chapter_stats as (
    select
        subject,
        chapter,
        count(*)::integer as attempted,
        count(*) filter (where is_correct)::integer as correct,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as accuracy
    from answered_events
    group by subject, chapter
), micro_topic_stats as (
    select
        subject,
        chapter,
        micro_topic_key,
        count(*)::integer as attempted,
        count(*) filter (where is_correct)::integer as correct,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as accuracy,
        round(avg(coalesce(prs.mastery_score, 0)), 2) as mastery
    from answered_events e
    left join public.personal_review_schedule prs
      on prs.user_id = p_user_id
     and prs.question_id = e.question_id
    where nullif(micro_topic_key, '') is not null
    group by subject, chapter, micro_topic_key
), difficulty_stats as (
    select
        difficulty,
        count(*)::integer as attempted,
        count(*) filter (where is_correct)::integer as correct,
        round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as accuracy
    from answered_events
    group by difficulty
), attempt_rates as (
    select
        quiz_id,
        attempt_number,
        completed_at,
        round(100.0 * score / nullif(total, 0), 2) as accuracy,
        row_number() over (
            partition by quiz_id order by attempt_number, completed_at, id
        ) as first_order,
        row_number() over (
            partition by quiz_id order by attempt_number desc, completed_at desc, id desc
        ) as last_order,
        count(*) over (partition by quiz_id) as attempt_count
    from public.quiz_attempts
    where user_id = p_user_id and is_completed
), quiz_improvement as (
    select
        quiz_id,
        max(accuracy) filter (where first_order = 1) as first_accuracy,
        max(accuracy) filter (where last_order = 1) as latest_accuracy
    from attempt_rates
    where attempt_count > 1
    group by quiz_id
), progress_days as (
    select
        day::date as activity_date,
        count(e.answered_at)::integer as answered,
        count(e.answered_at) filter (where e.is_correct)::integer as correct
    from generate_series(current_date - 29, current_date, interval '1 day') day
    left join answered_events e on e.answered_at::date = day::date
    group by day
    order by day
), review_summary as (
    select
        count(*)::integer as total,
        count(*) filter (where next_review <= current_date)::integer as due,
        count(*) filter (where learning_stage = 'mastered')::integer as mastered
    from public.personal_review_schedule
    where user_id = p_user_id
), preferences as (
    select * from public.user_preferences where user_id = p_user_id
)
select jsonb_build_object(
    'todayAnswered', (select count(*) from answered_events where answered_at::date = current_date),
    'dailyTarget', coalesce((select daily_question_target from preferences), 30),
    'dueReviews', coalesce((select due from review_summary), 0),
    'bookmarkedQuestions', (select count(*) from public.user_question_bookmarks where user_id = p_user_id),
    'totalAnswered', (select count(*) from answered_events),
    'correctAnswers', (select count(*) from answered_events where is_correct),
    'accuracy', coalesce((select round(
        100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2
    ) from answered_events), 0),
    'averageResponseTimeSeconds', (select round(avg(response_time_seconds), 2)
        from answered_events where response_time_seconds is not null),
    'currentStreak', coalesce((select max(days) from streaks
        where ended_on in (current_date, current_date - 1)), 0),
    'longestStreak', coalesce((select max(days) from streaks), 0),
    'revisionTotal', coalesce((select total from review_summary), 0),
    'revisionMastered', coalesce((select mastered from review_summary), 0),
    'revisionCompletion', coalesce((select round(
        100.0 * mastered / nullif(total, 0), 2
    ) from review_summary), 0),
    'firstAttemptAccuracy', coalesce((select round(avg(first_accuracy), 2) from quiz_improvement), 0),
    'retakeAccuracy', coalesce((select round(avg(latest_accuracy), 2) from quiz_improvement), 0),
    'averageImprovement', coalesce((select round(avg(latest_accuracy - first_accuracy), 2)
        from quiz_improvement), 0),
    'weakSubjects', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'attempted', attempted, 'correct', correct, 'accuracy', accuracy
    ) order by accuracy, attempted desc, subject)
        from (select * from subject_stats where attempted >= 3 order by accuracy, attempted desc limit 3) s
    ), '[]'::jsonb),
    'subjectPerformance', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'attempted', attempted, 'correct', correct, 'accuracy', accuracy
    ) order by attempted desc, subject) from subject_stats), '[]'::jsonb),
    'chapterPerformance', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'chapter', chapter, 'attempted', attempted,
        'correct', correct, 'accuracy', accuracy
    ) order by attempted desc, subject, chapter)
        from (select * from chapter_stats order by attempted desc, subject, chapter limit 30) c
    ), '[]'::jsonb),
    'microTopicPerformance', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'chapter', chapter, 'microTopicKey', micro_topic_key,
        'attempted', attempted, 'correct', correct, 'accuracy', accuracy, 'mastery', mastery
    ) order by attempted desc, micro_topic_key)
        from (select * from micro_topic_stats order by attempted desc, micro_topic_key limit 30) m
    ), '[]'::jsonb),
    'difficultyPerformance', coalesce((select jsonb_agg(jsonb_build_object(
        'difficulty', difficulty, 'attempted', attempted, 'correct', correct, 'accuracy', accuracy
    ) order by difficulty) from difficulty_stats), '[]'::jsonb),
    'weakestTopics', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'chapter', chapter, 'microTopicKey', micro_topic_key,
        'attempted', attempted, 'accuracy', accuracy, 'mastery', mastery
    ) order by accuracy, mastery, attempted desc)
        from (select * from micro_topic_stats where attempted >= 2
              order by accuracy, mastery, attempted desc limit 5) w
    ), '[]'::jsonb),
    'strongestTopics', coalesce((select jsonb_agg(jsonb_build_object(
        'subjectKey', subject, 'chapter', chapter, 'microTopicKey', micro_topic_key,
        'attempted', attempted, 'accuracy', accuracy, 'mastery', mastery
    ) order by accuracy desc, mastery desc, attempted desc)
        from (select * from micro_topic_stats where attempted >= 2
              order by accuracy desc, mastery desc, attempted desc limit 5) s
    ), '[]'::jsonb),
    'weeklyActivity', coalesce((select jsonb_agg(jsonb_build_object(
        'date', activity_date, 'answered', answered, 'correct', correct
    ) order by activity_date) from progress_days where activity_date >= current_date - 6), '[]'::jsonb),
    'progressOverTime', coalesce((select jsonb_agg(jsonb_build_object(
        'date', activity_date, 'answered', answered, 'correct', correct,
        'accuracy', case when answered = 0 then 0 else round(100.0 * correct / answered, 2) end
    ) order by activity_date) from progress_days), '[]'::jsonb)
);
$$;

create or replace function public.get_leaderboard_page(
    p_type text default 'weekly_accuracy',
    p_subject_key text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_type text := lower(coalesce(p_type, ''));
    v_limit integer := greatest(1, least(coalesce(p_limit, 20), 100));
    v_offset integer := greatest(0, coalesce(p_offset, 0));
    v_result jsonb;
begin
    if v_type not in (
        'daily_accuracy', 'weekly_accuracy', 'monthly_accuracy',
        'subject_accuracy', 'improvement', 'consistency', 'revision_completion'
    ) then
        raise exception 'invalid leaderboard type';
    end if;
    if v_type = 'subject_accuracy' and nullif(btrim(p_subject_key), '') is null then
        raise exception 'subject leaderboard requires a subject';
    end if;

    with answer_events as (
        select ua.user_id, ua.is_correct, ua.answered_at, q.subject
        from public.user_attempts ua
        join public.questions q on q.id = ua.question_id
        where ua.session_type <> 'mock_test'
        union all
        select a.user_id, coalesce(aa.is_correct, false),
               coalesce(aa.answered_at, a.completed_at), q.subject
        from public.quiz_attempt_answers aa
        join public.quiz_attempts a on a.id = aa.attempt_id
        join public.questions q on q.id = aa.question_id
        where aa.selected_option is not null and a.is_completed
    ), accuracy_metrics as (
        select
            user_id,
            round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct answered_at::date)::integer as activity_days,
            max(answered_at) as last_activity
        from answer_events
        where v_type in ('daily_accuracy','weekly_accuracy','monthly_accuracy','subject_accuracy')
          and case v_type
              when 'daily_accuracy' then answered_at::date = current_date
              when 'weekly_accuracy' then answered_at::date >= current_date - 6
              when 'monthly_accuracy' then answered_at::date >= current_date - 29
              when 'subject_accuracy' then subject = p_subject_key
              else false
          end
        group by user_id
        having count(*) >= case when v_type = 'daily_accuracy' then 5 else 10 end
    ), attempt_rates as (
        select
            user_id,
            quiz_id,
            round(100.0 * score / nullif(total, 0), 2) as accuracy,
            row_number() over (
                partition by user_id, quiz_id order by attempt_number, completed_at, id
            ) as first_order,
            row_number() over (
                partition by user_id, quiz_id order by attempt_number desc, completed_at desc, id desc
            ) as last_order,
            count(*) over (partition by user_id, quiz_id) as attempt_count,
            completed_at
        from public.quiz_attempts
        where is_completed
    ), quiz_improvements as (
        select
            user_id,
            quiz_id,
            max(accuracy) filter (where first_order = 1) as first_accuracy,
            max(accuracy) filter (where last_order = 1) as latest_accuracy,
            max(completed_at) as last_activity
        from attempt_rates
        where attempt_count > 1
        group by user_id, quiz_id
    ), improvement_metrics as (
        select
            user_id,
            round(avg(latest_accuracy - first_accuracy), 2) as primary_value,
            count(*)::numeric as secondary_value,
            (count(*) * 10)::integer as total_answers,
            0::integer as correct_answers,
            0::integer as activity_days,
            max(last_activity) as last_activity
        from quiz_improvements
        group by user_id
    ), consistency_metrics as (
        select
            user_id,
            count(distinct answered_at::date)::numeric as primary_value,
            round(100.0 * count(*) filter (where is_correct) / nullif(count(*), 0), 2) as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct answered_at::date)::integer as activity_days,
            max(answered_at) as last_activity
        from answer_events
        where answered_at::date >= current_date - 29
        group by user_id
        having count(*) >= 10
    ), revision_metrics as (
        select
            user_id,
            round(100.0 * count(*) filter (where learning_stage = 'mastered') /
                  nullif(count(*), 0), 2) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where learning_stage = 'mastered')::integer as correct_answers,
            0::integer as activity_days,
            max(last_review) as last_activity
        from public.personal_review_schedule
        group by user_id
        having count(*) >= 3
    ), metrics as (
        select * from accuracy_metrics
        union all select * from improvement_metrics where v_type = 'improvement'
        union all select * from consistency_metrics where v_type = 'consistency'
        union all select * from revision_metrics where v_type = 'revision_completion'
    ), visible as (
        select
            m.*,
            coalesce(
                nullif(btrim(u.public_display_name), ''),
                case when u.username_visible and nullif(btrim(u.username), '') is not null
                     then '@' || btrim(u.username) end,
                'শিক্ষার্থী ' || upper(substr(md5(u.id::text), 1, 4))
            ) as display_name
        from metrics m
        join public.users u on u.id = m.user_id
        where u.leaderboard_visible
    ), ranked as (
        select
            row_number() over (
                order by primary_value desc, secondary_value desc,
                         total_answers desc, last_activity asc nulls last, user_id
            ) as rank,
            *
        from visible
    ), page as (
        select * from ranked order by rank limit v_limit offset v_offset
    )
    select jsonb_build_object(
        'type', v_type,
        'subjectKey', case when v_type = 'subject_accuracy' then p_subject_key end,
        'participants', (select count(*) from visible),
        'limit', v_limit,
        'offset', v_offset,
        'tieBreak', case
            when v_type in ('daily_accuracy','weekly_accuracy','monthly_accuracy','subject_accuracy')
                then 'accuracy, answered, earlier completion'
            when v_type = 'improvement' then 'average improvement, retaken quizzes'
            when v_type = 'consistency' then 'active days, accuracy, answered'
            else 'mastery completion, scheduled questions'
        end,
        'rows', coalesce((select jsonb_agg(jsonb_build_object(
            'rank', rank,
            'display_name', display_name,
            'value', primary_value,
            'secondary_value', secondary_value,
            'total_answered', total_answers,
            'correct_answers', correct_answers,
            'activity_days', activity_days,
            'last_activity', last_activity
        ) order by rank) from page), '[]'::jsonb)
    ) into v_result;

    return v_result;
end;
$$;

revoke execute on function public.get_leaderboard_page(text, text, integer, integer)
    from public, anon, authenticated;
grant execute on function public.get_leaderboard_page(text, text, integer, integer)
    to service_role;

-- The existing dashboard RPC is replaced above, so repeat its least-privilege
-- grants explicitly for safe reruns and fresh projects.
revoke execute on function public.get_user_learning_dashboard(uuid)
    from public, anon, authenticated;
grant execute on function public.get_user_learning_dashboard(uuid)
    to service_role;
