-- Quiz quality contract:
-- 1. diversify every generated pack across verified facts and micro-topics;
-- 2. apply +1 / -0.25 / 0 marking only to quizzes created after this
--    migration, preserving all historical attempt scores and rankings.
--
-- Existing grounding callers remain compatible because the RPC signature and
-- returned columns are unchanged.

create or replace function public.get_grounding_bundle(
    p_subject_key text,
    p_chapter text,
    p_target_date date,
    p_limit integer default 8
)
returns table (
    source_document_id uuid,
    micro_topic_id uuid,
    micro_topic_key text,
    micro_topic_name text,
    source_url text,
    source_title text,
    source_domain text,
    source_kind text,
    source_published_at timestamptz,
    source_accessed_at timestamptz,
    fact_summary text,
    fact_version text,
    expires_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
with eligible as (
    select
        source.id as source_document_id,
        mt.id as micro_topic_id,
        mt.key as micro_topic_key,
        mt.name as micro_topic_name,
        source.source_url,
        source.source_title,
        source.source_domain,
        source.source_kind,
        source.source_published_at,
        source.source_accessed_at,
        source.fact_summary,
        source.fact_version,
        source.expires_at,
        dense_rank() over (
            order by
                mt.last_used_at asc nulls first,
                mt.target_coverage desc,
                mt.key
        ) as topic_rank,
        row_number() over (
            partition by mt.id
            order by
                source.source_published_at desc nulls last,
                source.verified_at desc,
                source.id
        ) as source_rank
    from public.quiz_chapters chapter
    join public.quiz_micro_topics mt on mt.chapter_id = chapter.id
    join public.source_documents source on source.micro_topic_id = mt.id
    where chapter.subject_key = p_subject_key
      and chapter.name = p_chapter
      and chapter.active
      and chapter.rotation_enabled
      and mt.active
      and source.verification_status = 'verified'
      and not source.review_required
      and (
          source.expires_at is null
          or (source.expires_at at time zone 'Asia/Kolkata')::date
              >= p_target_date
      )
      and (
          p_subject_key <> 'current-affairs'
          or (
              source.source_kind in ('official', 'primary')
              and (
                  source.source_published_at at time zone 'Asia/Kolkata'
              )::date between p_target_date - 45 and p_target_date
          )
      )
)
select
    eligible.source_document_id,
    eligible.micro_topic_id,
    eligible.micro_topic_key,
    eligible.micro_topic_name,
    eligible.source_url,
    eligible.source_title,
    eligible.source_domain,
    eligible.source_kind,
    eligible.source_published_at,
    eligible.source_accessed_at,
    eligible.fact_summary,
    eligible.fact_version,
    eligible.expires_at
from eligible
order by
    eligible.source_rank,
    eligible.topic_rank,
    eligible.source_published_at desc nulls last,
    eligible.source_document_id
limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

-- Historical quiz runs and attempts retain zero penalty. The changed default
-- applies only to rows created after this migration.
alter table public.quiz_runs
    add column if not exists negative_mark_penalty numeric(4, 2)
    not null default 0
    check (negative_mark_penalty between 0 and 1);

alter table public.quiz_runs
    alter column negative_mark_penalty set default 0.25;

create or replace function public.protect_quiz_marking_policy()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.negative_mark_penalty is distinct from old.negative_mark_penalty then
        raise exception 'quiz marking policy is immutable';
    end if;
    return new;
end;
$$;

drop trigger if exists protect_quiz_marking_policy on public.quiz_runs;
create trigger protect_quiz_marking_policy
before update on public.quiz_runs
for each row execute function public.protect_quiz_marking_policy();

alter table public.quiz_attempts
    add column if not exists negative_mark_penalty numeric(4, 2)
    not null default 0
    check (negative_mark_penalty between 0 and 1);

alter table public.quiz_attempts
    add column if not exists net_score numeric(6, 2)
    generated always as (
        score::numeric
        - ((answered - score)::numeric * negative_mark_penalty)
    ) stored;

create or replace function public.set_quiz_attempt_marking_policy()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    select coalesce(run.negative_mark_penalty, 0)
    into new.negative_mark_penalty
    from public.quiz_runs run
    where run.quiz_id = new.quiz_id;

    new.negative_mark_penalty := coalesce(new.negative_mark_penalty, 0);
    return new;
end;
$$;

drop trigger if exists set_quiz_attempt_marking_policy
    on public.quiz_attempts;
create trigger set_quiz_attempt_marking_policy
before insert on public.quiz_attempts
for each row execute function public.set_quiz_attempt_marking_policy();

create index if not exists idx_quiz_attempts_quiz_net_rank
    on public.quiz_attempts (
        quiz_id,
        net_score desc,
        score desc,
        answered asc,
        duration_seconds asc,
        completed_at asc
    )
    where is_completed;

-- Results preserve `score` as the number correct for compatibility and
-- analytics. `netScore` is the exam score used for quiz ranking.
create or replace function public.quiz_attempt_result(p_attempt_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with target as (
    select *
    from public.quiz_attempts
    where id = p_attempt_id and is_completed
), review as (
    select coalesce(jsonb_agg(
        jsonb_build_object(
            'questionId', aa.question_id,
            'questionVersion', q.content_version,
            'contentHash', q.content_hash,
            'q', q.question_text,
            'o', jsonb_build_array(
                q.option_a, q.option_b, q.option_c, q.option_d
            ),
            'selectedIndex', aa.selected_option,
            'correctIndex', aa.correct_option,
            'isCorrect', aa.is_correct,
            'explanation', coalesce(
                nullif(q.detailed_explanation, ''),
                q.explanation,
                ''
            ),
            'difficulty', q.difficulty,
            'chapter', q.topic,
            'microTopic', q.micro_topic_key,
            'sourceTitle', q.source_title,
            'sourceUrl', q.source_url,
            'sourcePublishedAt', q.source_published_at,
            'verifiedAt', q.verified_at,
            'factVersion', q.fact_version
        ) order by aa.question_order
    ), '[]'::jsonb) as rows
    from public.quiz_attempt_answers aa
    join public.questions q on q.id = aa.question_id
    where aa.attempt_id = p_attempt_id
), official as (
    select attempt.*
    from public.quiz_attempts attempt
    join target on target.quiz_id = attempt.quiz_id
    where attempt.is_completed and attempt.attempt_number = 1
), ranked as (
    select
        official.*,
        row_number() over (
            order by
                official.net_score desc,
                official.score desc,
                case
                    when official.negative_mark_penalty > 0
                    then official.answered - official.score
                    else -official.answered
                end asc,
                official.duration_seconds asc nulls last,
                official.completed_at asc,
                official.id
        ) as official_rank
    from official
), current_official as (
    select ranked.*
    from ranked
    join target on target.user_id = ranked.user_id
), totals as (
    select count(*)::integer as participants from official
)
select jsonb_build_object(
    'quizId', target.quiz_id,
    'attemptId', target.client_attempt_uuid,
    'score', target.score,
    'netScore', target.net_score,
    'bestScore', (
        select max(attempt.score)
        from public.quiz_attempts attempt
        where attempt.quiz_id = target.quiz_id
          and attempt.user_id = target.user_id
          and attempt.is_completed
    ),
    'bestNetScore', (
        select max(attempt.net_score)
        from public.quiz_attempts attempt
        where attempt.quiz_id = target.quiz_id
          and attempt.user_id = target.user_id
          and attempt.is_completed
    ),
    'total', target.total,
    'answered', target.answered,
    'correct', target.score,
    'incorrect', target.answered - target.score,
    'unanswered', target.total - target.answered,
    'negativeMarks', round(
        (target.answered - target.score) * target.negative_mark_penalty,
        2
    ),
    'markingScheme', jsonb_build_object(
        'rightMarks', 1,
        'wrongPenalty', target.negative_mark_penalty,
        'blankMarks', 0,
        'negativeMarking', target.negative_mark_penalty > 0
    ),
    'accuracy', round(
        100.0 * target.score / nullif(target.total, 0),
        2
    ),
    'attemptNumber', target.attempt_number,
    'isOfficialAttempt', target.attempt_number = 1,
    'rank', current_official.official_rank,
    'participants', totals.participants,
    'percentile', case
        when totals.participants <= 1 then 100.00
        else round(
            100.0 * (
                totals.participants - current_official.official_rank
            ) / (totals.participants - 1),
            2
        )
    end,
    'durationSeconds', target.duration_seconds,
    'rankMovement', null,
    'review', review.rows
)
from target
cross join review
cross join totals
left join current_official on true;
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
        users.leaderboard_visible,
        users.photo_url,
        coalesce(
            nullif(btrim(users.public_display_name), ''),
            case
                when users.username_visible
                 and nullif(btrim(users.username), '') is not null
                then '@' || btrim(users.username)
            end,
            nullif(
                btrim(concat_ws(
                    ' ',
                    users.first_name,
                    users.last_name
                )),
                ''
            ),
            'শিক্ষার্থী ' || upper(substr(md5(users.id::text), 1, 4))
        ) as display_name,
        upper(left(
            coalesce(nullif(btrim(users.first_name), ''), 'শি'),
            1
        )) as initials,
        (
            select count(*)::integer
            from public.quiz_attempts count_attempts
            where count_attempts.quiz_id = attempt.quiz_id
              and count_attempts.user_id = attempt.user_id
              and count_attempts.is_completed
        ) as attempts_count
    from public.quiz_attempts attempt
    join public.users users on users.id = attempt.user_id
    where attempt.quiz_id = p_quiz_id
      and attempt.is_completed
      and attempt.attempt_number = 1
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
        'profilePhotoUrl', case
            when user_id = p_user_id then photo_url
        end,
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
    from top_rows
), current_json as (
    select jsonb_build_object(
        'rank', rank,
        'displayName', display_name,
        'initials', initials,
        'profilePhotoUrl', photo_url,
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
    'rows', top_json.rows,
    'currentUser', (select row from current_json),
    'separatorRequired', coalesce(
        (select rank from current_row) > coalesce(
            (
                select max((row ->> 'rank')::integer)
                from jsonb_array_elements(top_json.rows) row
            ),
            0
        ),
        false
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
from top_json;
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
        coalesce(
            nullif(btrim(users.public_display_name), ''),
            case
                when users.username_visible
                 and nullif(btrim(users.username), '') is not null
                then '@' || btrim(users.username)
            end,
            'শিক্ষার্থী ' || upper(substr(md5(users.id::text), 1, 4))
        ) as display_name
    from latest
    join public.users users on users.id = latest.user_id
    where users.leaderboard_visible
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

-- Preserve the mature dashboard projection and replace only recent quiz
-- scores with the negative-marking-aware shape.
alter function public.get_user_learning_dashboard(uuid)
    rename to get_user_learning_dashboard_pre_quiz_quality;

create function public.get_user_learning_dashboard(p_user_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_base jsonb;
    v_recent jsonb;
begin
    v_base := public.get_user_learning_dashboard_pre_quiz_quality(p_user_id);

    with recent as (
        select distinct on (attempt.quiz_id)
            attempt.quiz_id,
            attempt.score,
            attempt.net_score,
            attempt.negative_mark_penalty,
            attempt.total,
            attempt.answered,
            attempt.attempt_number,
            attempt.duration_seconds,
            attempt.completed_at
        from public.quiz_attempts attempt
        where attempt.user_id = p_user_id and attempt.is_completed
        order by
            attempt.quiz_id,
            attempt.completed_at desc,
            attempt.id desc
    )
    select coalesce(jsonb_agg(jsonb_build_object(
        'quizId', quiz_id,
        'score', score,
        'netScore', net_score,
        'negativeMarks', round(
            (answered - score) * negative_mark_penalty,
            2
        ),
        'total', total,
        'answered', answered,
        'unanswered', total - answered,
        'accuracy', round(100.0 * score / nullif(total, 0), 2),
        'attemptNumber', attempt_number,
        'durationSeconds', duration_seconds,
        'completedAt', completed_at
    ) order by completed_at desc), '[]'::jsonb)
    into v_recent
    from (
        select *
        from recent
        order by completed_at desc
        limit 6
    ) latest;

    return v_base || jsonb_build_object('recentQuizzes', v_recent);
end;
$$;

alter function public.get_user_learning_dashboard(uuid)
    set timezone to 'Asia/Kolkata';

alter function public.get_application_schema_contract()
    rename to get_application_schema_contract_v220_source_rollout_base;

create function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_diverse_grounding_ready boolean := false;
    v_negative_marking_ready boolean := false;
begin
    v_base := public.get_application_schema_contract_v220_source_rollout_base();
    v_diverse_grounding_ready := to_regprocedure(
        'public.get_grounding_bundle(text,text,date,integer)'
    ) is not null;
    select
        exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'quiz_runs'
              and column_name = 'negative_mark_penalty'
        )
        and exists (
            select 1
            from information_schema.columns
            where table_schema = 'public'
              and table_name = 'quiz_attempts'
              and column_name = 'net_score'
              and is_generated = 'ALWAYS'
        )
        and exists (
            select 1
            from pg_catalog.pg_trigger
            where tgname = 'protect_quiz_marking_policy'
              and not tgisinternal
        )
        and exists (
            select 1
            from pg_catalog.pg_trigger
            where tgname = 'set_quiz_attempt_marking_policy'
              and not tgisinternal
        )
    into v_negative_marking_ready;

    return v_base || jsonb_build_object(
        'quiz_quality_migration_version', '20260728113750',
        'quiz_quality_migration_applied', true,
        'grounding_contract_version', '2',
        'diverse_grounding_ready', v_diverse_grounding_ready,
        'negative_marking_ready', v_negative_marking_ready,
        'ready',
            (v_base ->> 'ready')::boolean
            and v_diverse_grounding_ready
            and v_negative_marking_ready
    );
end;
$$;

revoke execute on function public.set_quiz_attempt_marking_policy()
    from public, anon, authenticated;
revoke execute on function public.protect_quiz_marking_policy()
    from public, anon, authenticated;
revoke execute on function public.quiz_attempt_result(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_page(
    text, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_quiz_leaderboard_for_user(
    text, uuid, integer
) from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard_pre_quiz_quality(
    uuid
) from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_grounding_bundle(text, text, date, integer)
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract_v220_source_rollout_base()
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.set_quiz_attempt_marking_policy()
    to service_role;
grant execute on function public.protect_quiz_marking_policy()
    to service_role;
grant execute on function public.quiz_attempt_result(uuid)
    to service_role;
grant execute on function public.get_quiz_leaderboard_page(
    text, integer, integer
) to service_role;
grant execute on function public.get_quiz_leaderboard_for_user(
    text, uuid, integer
) to service_role;
grant execute on function public.get_user_learning_dashboard_pre_quiz_quality(
    uuid
) to service_role;
grant execute on function public.get_user_learning_dashboard(uuid)
    to service_role;
grant execute on function public.get_grounding_bundle(text, text, date, integer)
    to service_role;
grant execute on function public.get_application_schema_contract_v220_source_rollout_base()
    to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
