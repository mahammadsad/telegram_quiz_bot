-- Public leaderboard identity is explicit-consent-only. Telegram first/last
-- names, private usernames, photos, Telegram IDs, and raw UUIDs never leave
-- this helper. Anonymous participation remains the default.

create or replace function public.get_public_leaderboard_identity(
    p_user_id uuid
)
returns table (
    display_name text,
    identity_source text,
    initials text,
    leaderboard_visible boolean
)
language sql
stable
security invoker
set search_path = ''
as $$
with selected as (
    select
        case
            when nullif(btrim(u.public_display_name), '') is not null
                 and char_length(btrim(u.public_display_name)) between 2 and 40
                 and btrim(u.public_display_name) !~ '[[:cntrl:]]'
            then btrim(u.public_display_name)
            when u.username_visible
                 and btrim(coalesce(u.username, ''))
                     ~ '^[A-Za-z0-9_]{5,32}$'
            then '@' || btrim(u.username)
            else 'শিক্ষার্থী ' || upper(substr(
                md5('leaderboard-public-v1:' || u.id::text),
                1,
                12
            ))
        end as display_name,
        case
            when nullif(btrim(u.public_display_name), '') is not null
                 and char_length(btrim(u.public_display_name)) between 2 and 40
                 and btrim(u.public_display_name) !~ '[[:cntrl:]]'
            then 'public_display_name'
            when u.username_visible
                 and btrim(coalesce(u.username, ''))
                     ~ '^[A-Za-z0-9_]{5,32}$'
            then 'public_username'
            else 'anonymous'
        end as identity_source,
        u.leaderboard_visible
    from public.users u
    where u.id = p_user_id
)
select
    selected.display_name,
    selected.identity_source,
    case
        when selected.identity_source = 'anonymous' then 'শি'
        else upper(left(ltrim(selected.display_name, '@'), 1))
    end as initials,
    selected.leaderboard_visible
from selected;
$$;

create or replace function public.get_leaderboard_privacy_contract()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_missing_functions jsonb;
    v_unsafe_definitions jsonb;
    v_missing_markers jsonb;
    v_configuration_failures jsonb;
    v_permission_failures jsonb;
    v_migration_applied boolean := false;
    v_ready boolean;
begin
    if pg_catalog.to_regclass(
        'supabase_migrations.schema_migrations'
    ) is not null then
        execute
            'select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = $1
                   or name = ''leaderboard_privacy_hotfix''
            )'
        into v_migration_applied
        using '20260801045552';
    end if;

    with required(
        signature,
        privacy_projection,
        requires_identity_marker
    ) as (
        values
            (
                'public.get_public_leaderboard_identity(uuid)',
                true,
                true
            ),
            (
                'public.get_leaderboard_for_user(text,text,uuid,integer,integer)',
                true,
                true
            ),
            (
                'public.get_quiz_leaderboard_for_user(text,uuid,integer)',
                true,
                false
            ),
            (
                'public.get_quiz_leaderboard_for_user_page(text,uuid,integer,integer)',
                true,
                true
            ),
            (
                'public.get_leaderboard_page(text,text,integer,integer)',
                true,
                false
            ),
            (
                'public.get_leaderboard_page_internal(text,text,integer,integer)',
                true,
                true
            ),
            (
                'public.get_quiz_leaderboard_page(text,integer,integer)',
                true,
                true
            ),
            (
                'public.get_global_leaderboard_page(integer,integer)',
                true,
                true
            ),
            (
                'public.get_leaderboard_privacy_contract()',
                false,
                false
            )
    ), resolved as (
        select
            required.*,
            pg_catalog.to_regprocedure(required.signature) as function_oid
        from required
    ), inspected as (
        select
            resolved.*,
            procedure.prosecdef,
            procedure.proconfig,
            procedure.proacl,
            procedure.proowner,
            lower(coalesce(
                pg_catalog.pg_get_functiondef(resolved.function_oid),
                ''
            )) as definition
        from resolved
        left join pg_catalog.pg_proc procedure
            on procedure.oid = resolved.function_oid
    )
    select
        coalesce(jsonb_agg(to_jsonb(signature) order by signature)
            filter (where function_oid is null), '[]'::jsonb),
        coalesce(jsonb_agg(to_jsonb(signature) order by signature)
            filter (
                where function_oid is not null
                  and privacy_projection
                  and (
                      position('first_name' in definition) > 0
                      or position('last_name' in definition) > 0
                      or position('photo_url' in definition) > 0
                      or position('profilephotourl' in definition) > 0
                      or position('telegram_id' in definition) > 0
                  )
            ), '[]'::jsonb),
        coalesce(jsonb_agg(to_jsonb(signature) order by signature)
            filter (
                where function_oid is not null
                  and requires_identity_marker
                  and position('identitysource' in definition) = 0
                  and position('identity_source' in definition) = 0
            ), '[]'::jsonb),
        coalesce(jsonb_agg(to_jsonb(signature) order by signature)
            filter (
                where function_oid is not null
                  and (
                      prosecdef
                      or not coalesce(
                          'search_path=""' = any(proconfig),
                          false
                      )
                  )
            ), '[]'::jsonb),
        coalesce(jsonb_agg(to_jsonb(signature) order by signature)
            filter (
                where function_oid is not null
                  and (
                      not pg_catalog.has_function_privilege(
                          'service_role',
                          function_oid,
                          'EXECUTE'
                      )
                      or pg_catalog.has_function_privilege(
                          'anon',
                          function_oid,
                          'EXECUTE'
                      )
                      or pg_catalog.has_function_privilege(
                          'authenticated',
                          function_oid,
                          'EXECUTE'
                      )
                      or exists (
                          select 1
                          from pg_catalog.aclexplode(coalesce(
                              proacl,
                              pg_catalog.acldefault('f', proowner)
                          )) acl
                          where acl.grantee = 0
                            and acl.privilege_type = 'EXECUTE'
                      )
                  )
            ), '[]'::jsonb)
    into
        v_missing_functions,
        v_unsafe_definitions,
        v_missing_markers,
        v_configuration_failures,
        v_permission_failures
    from inspected;

    v_ready :=
        v_migration_applied
        and v_missing_functions = '[]'::jsonb
        and v_unsafe_definitions = '[]'::jsonb
        and v_missing_markers = '[]'::jsonb
        and v_configuration_failures = '[]'::jsonb
        and v_permission_failures = '[]'::jsonb;

    return jsonb_build_object(
        'leaderboard_privacy_migration_version', '20260801045552',
        'leaderboard_privacy_migration_applied', v_migration_applied,
        'identity_projection_ready', v_ready,
        'missing_functions', v_missing_functions,
        'unsafe_function_definitions', v_unsafe_definitions,
        'missing_identity_markers', v_missing_markers,
        'function_configuration_failures', v_configuration_failures,
        'function_permission_failures', v_permission_failures,
        'ready', v_ready
    );
end;
$$;

create or replace function public.get_leaderboard_for_user(
    p_type text default 'weekly_accuracy',
    p_subject_key text default null,
    p_user_id uuid default null,
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
    v_today date := (now() at time zone 'Asia/Kolkata')::date;
    v_result jsonb;
begin
    if v_type not in (
        'overall_rank', 'daily_accuracy', 'weekly_accuracy', 'monthly_accuracy',
        'subject_accuracy', 'improvement', 'consistency',
        'revision_completion'
    ) then
        raise exception 'invalid leaderboard type';
    end if;
    if v_type = 'subject_accuracy'
       and nullif(btrim(p_subject_key), '') is null then
        raise exception 'subject leaderboard requires a subject';
    end if;

    with official_answers as (
        select
            a.user_id,
            aa.is_correct,
            coalesce(aa.answered_at, a.completed_at) as answered_at,
            q.subject
        from public.quiz_attempt_answers aa
        join public.quiz_attempts a on a.id = aa.attempt_id
        join public.questions q on q.id = aa.question_id
        where a.is_completed
          and a.attempt_number = 1
          and aa.selected_option is not null
    ), overall_metrics as (
        select
            user_id,
            count(*) filter (where is_correct)::numeric as primary_value,
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct (
                answered_at at time zone 'Asia/Kolkata'
            )::date)::integer as activity_days,
            max(answered_at) as last_activity
        from official_answers
        group by user_id
        having count(*) >= 10
    ), accuracy_metrics as (
        select
            user_id,
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct (
                answered_at at time zone 'Asia/Kolkata'
            )::date)::integer as activity_days,
            max(answered_at) as last_activity
        from official_answers
        where v_type in (
            'daily_accuracy', 'weekly_accuracy',
            'monthly_accuracy', 'subject_accuracy'
        )
          and case v_type
              when 'daily_accuracy' then
                  (answered_at at time zone 'Asia/Kolkata')::date = v_today
              when 'weekly_accuracy' then
                  (answered_at at time zone 'Asia/Kolkata')::date >= v_today - 6
              when 'monthly_accuracy' then
                  (answered_at at time zone 'Asia/Kolkata')::date >= v_today - 29
              when 'subject_accuracy' then
                  public.canonical_subject_key(subject) = p_subject_key
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
                partition by user_id, quiz_id
                order by attempt_number, completed_at, id
            ) as first_order,
            row_number() over (
                partition by user_id, quiz_id
                order by attempt_number desc, completed_at desc, id desc
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
            count(distinct (
                answered_at at time zone 'Asia/Kolkata'
            )::date)::numeric as primary_value,
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct (
                answered_at at time zone 'Asia/Kolkata'
            )::date)::integer as activity_days,
            max(answered_at) as last_activity
        from official_answers
        where (answered_at at time zone 'Asia/Kolkata')::date >= v_today - 29
        group by user_id
        having count(*) >= 10
    ), revision_metrics as (
        select
            user_id,
            round(
                100.0 * count(*) filter (where learning_stage = 'mastered')
                / nullif(count(*), 0),
                2
            ) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (
                where learning_stage = 'mastered'
            )::integer as correct_answers,
            0::integer as activity_days,
            max(last_review) as last_activity
        from public.personal_review_schedule
        group by user_id
        having count(*) >= 3
    ), metrics as (
        select * from accuracy_metrics
        union all
        select * from overall_metrics where v_type = 'overall_rank'
        union all
        select * from improvement_metrics where v_type = 'improvement'
        union all
        select * from consistency_metrics where v_type = 'consistency'
        union all
        select * from revision_metrics where v_type = 'revision_completion'
    ), visible as (
        select
            m.*,
            identity.display_name,
            identity.identity_source,
            identity.initials
        from metrics m
        cross join lateral public.get_public_leaderboard_identity(
            m.user_id
        ) identity
        where identity.leaderboard_visible
    ), ranked as (
        select
            row_number() over (
                order by primary_value desc, secondary_value desc,
                         total_answers desc, last_activity asc nulls last,
                         user_id
            ) as rank,
            *
        from visible
    ), top_rows as (
        select *
        from ranked
        order by rank
        limit v_limit offset v_offset
    ), current_row as (
        select * from ranked where user_id = p_user_id
    ), top_json as (
        select coalesce(jsonb_agg(jsonb_build_object(
            'rank', rank,
            'displayName', display_name,
            'identitySource', identity_source,
            'initials', initials,
            'value', primary_value,
            'secondaryValue', secondary_value,
            'totalAnswered', total_answers,
            'correctAnswers', correct_answers,
            'activityDays', activity_days,
            'isCurrentUser', user_id = p_user_id
        ) order by rank), '[]'::jsonb) as rows
        from top_rows
    ), current_json as (
        select jsonb_build_object(
            'rank', rank,
            'displayName', display_name,
            'identitySource', identity_source,
            'initials', initials,
            'value', primary_value,
            'secondaryValue', secondary_value,
            'totalAnswered', total_answers,
            'correctAnswers', correct_answers,
            'activityDays', activity_days,
            'isCurrentUser', true
        ) as row
        from current_row
    )
    select jsonb_build_object(
        'type', v_type,
        'subjectKey', case
            when v_type = 'subject_accuracy' then p_subject_key
        end,
        'participants', (select count(*) from ranked),
        'limit', v_limit,
        'offset', v_offset,
        'rows', top_json.rows,
        'currentUser', (select row from current_json),
        'separatorRequired', exists(select 1 from current_row)
            and not exists(
                select 1 from top_rows where user_id = p_user_id
            ),
        'tieBreak', case
            when v_type = 'overall_rank'
                then 'correct answers, accuracy, answered, earlier completion'
            when v_type in (
                'daily_accuracy', 'weekly_accuracy',
                'monthly_accuracy', 'subject_accuracy'
            ) then 'accuracy, answered, earlier completion'
            when v_type = 'improvement'
                then 'average improvement, retaken quizzes'
            when v_type = 'consistency'
                then 'active days, accuracy, answered'
            else 'mastery completion, scheduled questions'
        end,
        'rankingScope', case
            when v_type = 'improvement' then 'retakes_specialized'
            when v_type = 'revision_completion' then 'revision_schedule'
            else 'official_first_attempt_only'
        end,
        'retakesAffectOfficialRank', false,
        'practiceAffectsOfficialRank', false
    ) into v_result
    from top_json;

    return v_result;
end;
$$;

-- Pagination is added as a compatible extension. The original three-argument
-- RPC remains below as an offset-zero wrapper for existing callers.
create or replace function public.get_quiz_leaderboard_for_user_page(
    p_quiz_id text,
    p_user_id uuid default null,
    p_limit integer default 10,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with official as (
    select
        attempt.id,
        attempt.user_id,
        attempt.score,
        attempt.net_score,
        attempt.negative_mark_penalty,
        attempt.total,
        attempt.answered,
        attempt.duration_seconds,
        attempt.completed_at,
        (
            select count(*)::integer
            from public.quiz_attempts count_attempts
            where count_attempts.quiz_id = attempt.quiz_id
              and count_attempts.user_id = attempt.user_id
              and count_attempts.is_completed
        ) as attempts_count
    from public.quiz_attempts attempt
    where attempt.quiz_id = p_quiz_id
      and attempt.is_completed
      and attempt.attempt_number = 1
), visible as (
    select
        official.*,
        identity.display_name,
        identity.identity_source,
        identity.initials
    from official
    cross join lateral public.get_public_leaderboard_identity(
        official.user_id
    ) identity
    where identity.leaderboard_visible
), ranked as (
    select
        row_number() over (
            order by
                net_score desc,
                score desc,
                case
                    when negative_mark_penalty > 0
                    then answered - score
                    else -answered
                end asc,
                duration_seconds asc nulls last,
                completed_at asc,
                id
        ) as rank,
        *
    from visible
), page as (
    select *
    from ranked
    order by rank
    limit greatest(1, least(coalesce(p_limit, 10), 50))
    offset greatest(0, coalesce(p_offset, 0))
), current_row as (
    select * from ranked where user_id = p_user_id
), page_json as (
    select coalesce(jsonb_agg(jsonb_build_object(
        'rank', rank,
        'displayName', display_name,
        'identitySource', identity_source,
        'initials', initials,
        'score', score,
        'netScore', net_score,
        'negativeMarks', round(
            (answered - score) * negative_mark_penalty,
            2
        ),
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
                / ((select count(*) from ranked) - 1),
                2
            )
        end,
        'rankMovement', null,
        'isCurrentUser', user_id = p_user_id
    ) order by rank), '[]'::jsonb) as rows
    from page
), current_json as (
    select jsonb_build_object(
        'rank', rank,
        'displayName', display_name,
        'identitySource', identity_source,
        'initials', initials,
        'score', score,
        'netScore', net_score,
        'negativeMarks', round(
            (answered - score) * negative_mark_penalty,
            2
        ),
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
                / ((select count(*) from ranked) - 1),
                2
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
    'limit', greatest(1, least(coalesce(p_limit, 10), 50)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'rows', page_json.rows,
    'currentUser', (select row from current_json),
    'separatorRequired', exists(select 1 from current_row)
        and not exists(
            select 1 from page where user_id = p_user_id
        ),
    'markingScheme', jsonb_build_object(
        'rightMarks', 1,
        'wrongPenalty', coalesce(
            (select negative_mark_penalty from ranked limit 1),
            0
        ),
        'blankMarks', 0,
        'negativeMarking', coalesce(
            (select negative_mark_penalty > 0 from ranked limit 1),
            false
        )
    ),
    'tieBreak', case
        when coalesce(
            (select negative_mark_penalty > 0 from ranked limit 1),
            false
        )
        then
            'net score, correct answers, fewer wrong answers, faster time, earlier completion'
        else
            'score, answered questions, faster time, earlier completion'
    end,
    'rankingScope', 'first_attempt_only',
    'retakesAffectOfficialRank', false,
    'practiceAffectsOfficialRank', false
)
from page_json;
$$;

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
select public.get_quiz_leaderboard_for_user_page(
    p_quiz_id,
    p_user_id,
    p_limit,
    0
);
$$;

-- Preserve the older typed-page metrics and pagination while routing every
-- identity through the same explicit-consent helper.
create or replace function public.get_leaderboard_page_internal(
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
        'subject_accuracy', 'improvement', 'consistency',
        'revision_completion'
    ) then
        raise exception 'invalid leaderboard type';
    end if;
    if v_type = 'subject_accuracy'
       and nullif(btrim(p_subject_key), '') is null then
        raise exception 'subject leaderboard requires a subject';
    end if;

    with answer_events as (
        select ua.user_id, ua.is_correct, ua.answered_at, q.subject
        from public.user_attempts ua
        join public.questions q on q.id = ua.question_id
        where ua.session_type <> 'mock_test'
        union all
        select
            a.user_id,
            coalesce(aa.is_correct, false),
            coalesce(aa.answered_at, a.completed_at),
            q.subject
        from public.quiz_attempt_answers aa
        join public.quiz_attempts a on a.id = aa.attempt_id
        join public.questions q on q.id = aa.question_id
        where aa.selected_option is not null and a.is_completed
    ), accuracy_metrics as (
        select
            user_id,
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct answered_at::date)::integer as activity_days,
            max(answered_at) as last_activity
        from answer_events
        where v_type in (
            'daily_accuracy', 'weekly_accuracy',
            'monthly_accuracy', 'subject_accuracy'
        )
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
                partition by user_id, quiz_id
                order by attempt_number, completed_at, id
            ) as first_order,
            row_number() over (
                partition by user_id, quiz_id
                order by attempt_number desc, completed_at desc, id desc
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
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as secondary_value,
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
            round(
                100.0 * count(*) filter (where learning_stage = 'mastered')
                / nullif(count(*), 0),
                2
            ) as primary_value,
            count(*)::numeric as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (
                where learning_stage = 'mastered'
            )::integer as correct_answers,
            0::integer as activity_days,
            max(last_review) as last_activity
        from public.personal_review_schedule
        group by user_id
        having count(*) >= 3
    ), metrics as (
        select * from accuracy_metrics
        union all
        select * from improvement_metrics where v_type = 'improvement'
        union all
        select * from consistency_metrics where v_type = 'consistency'
        union all
        select * from revision_metrics where v_type = 'revision_completion'
    ), visible as (
        select
            m.*,
            identity.display_name,
            identity.identity_source,
            identity.initials
        from metrics m
        cross join lateral public.get_public_leaderboard_identity(
            m.user_id
        ) identity
        where identity.leaderboard_visible
    ), ranked as (
        select
            row_number() over (
                order by primary_value desc, secondary_value desc,
                         total_answers desc, last_activity asc nulls last,
                         user_id
            ) as rank,
            *
        from visible
    ), page as (
        select *
        from ranked
        order by rank
        limit v_limit offset v_offset
    )
    select jsonb_build_object(
        'type', v_type,
        'subjectKey', case
            when v_type = 'subject_accuracy' then p_subject_key
        end,
        'participants', (select count(*) from visible),
        'limit', v_limit,
        'offset', v_offset,
        'tieBreak', case
            when v_type in (
                'daily_accuracy', 'weekly_accuracy',
                'monthly_accuracy', 'subject_accuracy'
            ) then 'accuracy, answered, earlier completion'
            when v_type = 'improvement'
                then 'average improvement, retaken quizzes'
            when v_type = 'consistency'
                then 'active days, accuracy, answered'
            else 'mastery completion, scheduled questions'
        end,
        'rows', coalesce((select jsonb_agg(jsonb_build_object(
            'rank', rank,
            'display_name', display_name,
            'identity_source', identity_source,
            'initials', initials,
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
    v_result jsonb;
begin
    v_result := public.get_leaderboard_page_internal(
        p_type,
        public.canonical_subject_internal_name(p_subject_key),
        p_limit,
        p_offset
    );
    if lower(coalesce(p_type, '')) = 'subject_accuracy' then
        v_result := jsonb_set(
            v_result,
            '{subjectKey}',
            to_jsonb(public.canonical_subject_key(p_subject_key)),
            true
        );
    end if;
    return v_result;
end;
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
    select
        a.user_id,
        coalesce(aa.is_correct, false),
        coalesce(aa.answered_at, a.completed_at)
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    where aa.selected_option is not null and a.is_completed
), aggregated as (
    select
        user_id,
        count(*)::integer as total_attempts,
        count(*) filter (where is_correct)::integer as correct_attempts,
        round(
            100.0 * count(*) filter (where is_correct)
            / nullif(count(*), 0),
            2
        ) as accuracy_pct,
        max(answered_at) as last_attempt_at
    from answer_events
    group by user_id
), visible as (
    select
        aggregated.*,
        identity.display_name,
        identity.identity_source,
        identity.initials
    from aggregated
    cross join lateral public.get_public_leaderboard_identity(
        aggregated.user_id
    ) identity
    where identity.leaderboard_visible
), ranked as (
    select row_number() over (
        order by correct_attempts desc, accuracy_pct desc,
                 total_attempts desc, last_attempt_at asc, user_id
    ) as rank, *
    from visible
), page as (
    select *
    from ranked
    order by rank
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
            'identity_source', identity_source,
            'initials', initials,
            'total_attempts', total_attempts,
            'correct_attempts', correct_attempts,
            'accuracy_pct', accuracy_pct,
            'last_attempt_at', last_attempt_at
        ) order by rank)
        from page
    ), '[]'::jsonb)
);
$$;

-- Preserve this older page RPC's latest-attempt semantics; only its public
-- identity projection is centralized and hardened.
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
    select distinct on (attempt.user_id)
        attempt.user_id,
        attempt.score,
        attempt.net_score,
        attempt.negative_mark_penalty,
        attempt.total,
        attempt.answered,
        attempt.duration_seconds,
        attempt.completed_at,
        attempt.id,
        counts.attempts_count
    from public.quiz_attempts attempt
    join attempt_counts counts on counts.user_id = attempt.user_id
    where attempt.quiz_id = p_quiz_id and attempt.is_completed
    order by
        attempt.user_id,
        attempt.completed_at desc,
        attempt.id desc
), visible as (
    select
        latest.*,
        identity.display_name,
        identity.identity_source,
        identity.initials
    from latest
    cross join lateral public.get_public_leaderboard_identity(
        latest.user_id
    ) identity
    where identity.leaderboard_visible
), ranked as (
    select
        row_number() over (
            order by
                net_score desc,
                score desc,
                case
                    when negative_mark_penalty > 0
                    then answered - score
                    else -answered
                end asc,
                duration_seconds asc nulls last,
                completed_at asc,
                id
        ) as rank,
        *
    from visible
), page as (
    select *
    from ranked
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
            'identity_source', identity_source,
            'initials', initials,
            'score', score,
            'net_score', net_score,
            'negative_marks', round(
                (answered - score) * negative_mark_penalty,
                2
            ),
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

revoke execute on function public.get_public_leaderboard_identity(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_leaderboard_for_user(
    text, text, uuid, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_for_user(
    text, uuid, integer
) from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_for_user_page(
    text, uuid, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_leaderboard_page(
    text, text, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_leaderboard_page_internal(
    text, text, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_page(
    text, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_global_leaderboard_page(
    integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_leaderboard_privacy_contract()
    from public, anon, authenticated;

grant execute on function public.get_public_leaderboard_identity(uuid)
    to service_role;
grant execute on function public.get_leaderboard_for_user(
    text, text, uuid, integer, integer
) to service_role;
grant execute on function public.get_quiz_leaderboard_for_user(
    text, uuid, integer
) to service_role;
grant execute on function public.get_quiz_leaderboard_for_user_page(
    text, uuid, integer, integer
) to service_role;
grant execute on function public.get_leaderboard_page(
    text, text, integer, integer
) to service_role;
grant execute on function public.get_leaderboard_page_internal(
    text, text, integer, integer
) to service_role;
grant execute on function public.get_quiz_leaderboard_page(
    text, integer, integer
) to service_role;
grant execute on function public.get_global_leaderboard_page(
    integer, integer
) to service_role;
grant execute on function public.get_leaderboard_privacy_contract()
    to service_role;
