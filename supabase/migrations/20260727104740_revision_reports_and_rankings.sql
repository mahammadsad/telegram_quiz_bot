-- Forward correction: attempt-owned revision reports and official, current-user
-- aware typed leaderboards. Apply after learning_and_leaderboard_contract_v2.

-- Revision reports refer to the immutable personal-practice answer that exposed
-- the checked answer. Existing quiz-attempt reports remain unchanged.
-- `answered_at` historically defaulted to transaction_timestamp(), so several
-- answers submitted in one transaction can share an identical timestamp. Keep
-- an immutable database sequence for deterministic latest-answer selection.
alter table public.personal_practice_answers
    add column if not exists event_sequence bigint generated always as identity;
create unique index if not exists idx_personal_practice_event_sequence
    on public.personal_practice_answers (event_sequence);

-- Enforce the same certified-pack gate for every insertion path. The earlier
-- RPC retained a narrow legacy `status = posted` exception; the trigger closes
-- that exception even for direct service-role inserts or older callers.
create or replace function public.require_quiz_attempt_uuid()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.client_attempt_uuid is null then
        raise exception 'a client-generated UUID attempt identifier is required';
    end if;
    if new.client_attempt_id <> new.client_attempt_uuid::text then
        raise exception 'attempt identifier representations do not match';
    end if;
    if not exists (
        select 1
        from public.quiz_runs r
        where r.quiz_id = new.quiz_id
          and r.status in ('ready', 'posting', 'posted', 'posting_failed')
          and r.integrity_verified
          and r.checksum_contract_version = 2
          and r.generated_checksum is not null
          and r.generated_checksum = r.persisted_checksum
    ) then
        raise exception 'quiz is not checksum-certified for submission';
    end if;
    return new;
end;
$$;

alter table public.question_reports
    add column if not exists practice_attempt_id uuid
        references public.personal_practice_answers(id) on delete cascade;
alter table public.question_reports alter column quiz_id drop not null;
alter table public.question_reports alter column attempt_id drop not null;
alter table public.question_reports
    drop constraint if exists question_reports_attempt_kind_check;
alter table public.question_reports
    add constraint question_reports_attempt_kind_check check (
        (
            quiz_id is not null
            and attempt_id is not null
            and practice_attempt_id is null
        ) or (
            quiz_id is null
            and attempt_id is null
            and practice_attempt_id is not null
        )
    );

create unique index if not exists idx_question_reports_practice_attempt_unique
    on public.question_reports (question_id, user_id, practice_attempt_id)
    where practice_attempt_id is not null;
create index if not exists idx_question_reports_practice_attempt
    on public.question_reports (practice_attempt_id)
    where practice_attempt_id is not null;

create or replace function public.submit_practice_question_report(
    p_question_id uuid,
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
    v_practice_attempt_id uuid;
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
        raise exception 'a completed UUID revision attempt identifier is required';
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

    select pa.id into v_practice_attempt_id
    from public.personal_practice_answers pa
    where pa.user_id = p_user_id
      and pa.question_id = p_question_id
      and pa.client_attempt_id = p_client_attempt_id
      and pa.mode = 'revision'
    limit 1;
    if not found then
        raise exception 'question report is not linked to this completed revision attempt';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(p_question_id::text, 0));
    insert into public.question_reports (
        question_id, quiz_id, user_id, attempt_id, practice_attempt_id,
        reason, details
    ) values (
        p_question_id, null, p_user_id, null, v_practice_attempt_id,
        p_reason, nullif(btrim(p_details), '')
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
    raise exception 'this question was already reported for this revision attempt';
end;
$$;

-- The wrong-answer queue follows the latest checked event across both quiz and
-- personal revision attempts and supports mixed legacy/canonical subject rows.
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
        aa.question_id,
        aa.is_correct,
        aa.marked_for_review,
        coalesce(aa.answered_at, a.completed_at) as event_at,
        0::bigint as event_sequence,
        aa.id as event_id
    from public.quiz_attempt_answers aa
    join public.quiz_attempts a on a.id = aa.attempt_id
    where a.user_id = p_user_id
      and a.is_completed
      and aa.selected_option is not null
    union all
    select
        pa.question_id,
        pa.is_correct,
        pa.marked_for_review,
        pa.answered_at,
        pa.event_sequence,
        pa.id
    from public.personal_practice_answers pa
    where pa.user_id = p_user_id
), latest as (
    select distinct on (e.question_id)
        e.question_id,
        e.is_correct,
        e.marked_for_review,
        e.event_at,
        q.question_text,
        q.option_a,
        q.option_b,
        q.option_c,
        q.option_d,
        public.canonical_subject_key(q.subject) as subject_key,
        q.topic,
        q.micro_topic_key
    from events e
    join public.questions q on q.id = e.question_id
    where p_subject_key is null
       or public.canonical_subject_key(q.subject) = p_subject_key
    order by e.question_id, e.event_at desc, e.event_sequence desc, e.event_id desc
), wrong as (
    select * from latest where is_correct is false
), page as (
    select * from wrong
    order by event_at desc, question_id
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(0, coalesce(p_offset, 0))
)
select jsonb_build_object(
    'total', (select count(*) from wrong),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(0, coalesce(p_offset, 0)),
    'mode', 'revision',
    'sourceType', case
        when p_subject_key is null then 'wrong'
        else 'weak_topic'
    end,
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'questionId', question_id,
        'q', question_text,
        'o', jsonb_build_array(option_a, option_b, option_c, option_d),
        'subjectKey', subject_key,
        'chapter', topic,
        'microTopicKey', micro_topic_key,
        'lastAttemptAt', event_at,
        'markedForReview', marked_for_review
    ) order by event_at desc, question_id) from page), '[]'::jsonb)
);
$$;

-- Competitive accuracy boards use completed first attempts only. Retakes are
-- visible only in the explicitly named improvement board; practice/revision
-- answers never affect a competitive rank.
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
    if v_type = 'subject_accuracy' and nullif(btrim(p_subject_key), '') is null then
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
            count(distinct (answered_at at time zone 'Asia/Kolkata')::date)::integer
                as activity_days,
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
            count(distinct (answered_at at time zone 'Asia/Kolkata')::date)::integer
                as activity_days,
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
            count(distinct (answered_at at time zone 'Asia/Kolkata')::date)::numeric
                as primary_value,
            round(
                100.0 * count(*) filter (where is_correct)
                / nullif(count(*), 0),
                2
            ) as secondary_value,
            count(*)::integer as total_answers,
            count(*) filter (where is_correct)::integer as correct_answers,
            count(distinct (answered_at at time zone 'Asia/Kolkata')::date)::integer
                as activity_days,
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
            count(*) filter (where learning_stage = 'mastered')::integer
                as correct_answers,
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
    ), named as (
        select
            m.*,
            u.leaderboard_visible,
            u.photo_url,
            coalesce(
                nullif(btrim(u.public_display_name), ''),
                case
                    when u.username_visible
                         and nullif(btrim(u.username), '') is not null
                    then '@' || btrim(u.username)
                end,
                nullif(btrim(concat_ws(' ', u.first_name, u.last_name)), ''),
                'শিক্ষার্থী ' || upper(substr(md5(u.id::text), 1, 4))
            ) as display_name
        from metrics m
        join public.users u on u.id = m.user_id
    ), ranked as (
        select
            row_number() over (
                order by primary_value desc, secondary_value desc,
                         total_answers desc, last_activity asc nulls last,
                         user_id
            ) as rank,
            *
        from named
    ), top_rows as (
        select *
        from ranked
        where leaderboard_visible
        order by rank
        limit v_limit offset v_offset
    ), current_row as (
        select * from ranked where user_id = p_user_id
    ), top_json as (
        select coalesce(jsonb_agg(jsonb_build_object(
            'rank', rank,
            'displayName', display_name,
            'profilePhotoUrl', case when user_id = p_user_id then photo_url end,
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
            'profilePhotoUrl', photo_url,
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
        'subjectKey', case when v_type = 'subject_accuracy' then p_subject_key end,
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

-- A refreshed result page may recover only the authenticated learner's own
-- completed attempt. The public API never accepts a database attempt id and
-- cannot use this function to enumerate another user's results.
create or replace function public.get_quiz_attempt_result_for_client(
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select public.quiz_attempt_result(a.id)
from public.quiz_attempts a
where a.quiz_id = p_quiz_id
  and a.user_id = p_user_id
  and a.client_attempt_uuid = p_client_attempt_id
  and a.is_completed
limit 1;
$$;

-- Logical dates shown to learners and used by revision scheduling are Kolkata
-- dates regardless of the database server's default timezone.
alter function public.get_user_learning_dashboard(uuid)
    set timezone to 'Asia/Kolkata';
alter function public.get_user_due_reviews(uuid, integer, integer)
    set timezone to 'Asia/Kolkata';
alter function public.refresh_personal_review_overdue(uuid)
    set timezone to 'Asia/Kolkata';
alter function public.advance_personal_review_schedule_v2(
    uuid, uuid, boolean, text, numeric, boolean
) set timezone to 'Asia/Kolkata';
alter function public.advance_personal_review_schedule(
    uuid, uuid, boolean, numeric, boolean
) set timezone to 'Asia/Kolkata';
alter function public.submit_personal_practice_answer(
    uuid, uuid, uuid, integer, text, text, numeric, boolean
) set timezone to 'Asia/Kolkata';
alter function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean)
    set timezone to 'Asia/Kolkata';
alter function public.get_operational_status()
    set timezone to 'Asia/Kolkata';

update public.application_schema_contract
set contract_version = '2.2.0',
    required_migration_version = '20260722120827',
    verification_threshold = 0.85,
    applied_at = now()
where contract_key = 'telegram_quiz_api';

create or replace function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_contract public.application_schema_contract%rowtype;
    v_migration_applied boolean := false;
    v_tables text[] := array[
        'questions', 'polls', 'users', 'user_attempts', 'bot_state',
        'personal_review_schedule', 'quiz_runs', 'chapter_history',
        'quiz_submissions', 'quiz_questions', 'quiz_attempts',
        'quiz_attempt_answers', 'quiz_subjects', 'quiz_chapters',
        'quiz_micro_topics', 'source_documents', 'question_verifications',
        'question_generation_audits', 'question_reports', 'exam_catalogue',
        'user_preferences', 'user_question_bookmarks',
        'user_resource_bookmarks', 'learning_resources',
        'personal_practice_answers', 'resource_feedback',
        'resource_link_checks', 'resource_discovery_queue',
        'resource_channel_policies', 'application_schema_contract',
        'quiz_pack_integrity_failures'
    ];
    v_indexes text[] := array[
        'idx_questions_content_hash_unique',
        'idx_questions_stem_content_version_unique',
        'idx_questions_scheduler_pool',
        'idx_quiz_runs_active_claims',
        'idx_quiz_runs_recovery',
        'idx_quiz_questions_question',
        'idx_quiz_attempts_client_uuid_unique',
        'idx_quiz_attempts_quiz_rank',
        'idx_quiz_attempt_answers_question',
        'idx_personal_review_schedule_user_due',
        'idx_personal_practice_attempt_idempotency',
        'idx_personal_practice_event_sequence',
        'idx_question_reports_moderation',
        'idx_question_reports_practice_attempt_unique',
        'idx_source_documents_grounding',
        'idx_learning_resources_quiz_lookup',
        'idx_resource_discovery_pending'
    ];
    v_triggers text[] := array[
        'questions.protect_immutable_question_version',
        'source_documents.protect_verified_source_facts',
        'quiz_attempts.require_quiz_attempt_uuid',
        'quiz_attempt_answers.sync_personal_review_schedule_after_answer',
        'learning_resources.validate_learning_resource_taxonomy',
        'learning_resources.protect_verified_learning_resource'
    ];
    v_functions text[] := array[
        'public.claim_quiz_run(text,text,text,integer,boolean)',
        'public.save_quiz_pack_atomic(text,text,jsonb,text,boolean)',
        'public.quiz_pack_checksum(text)',
        'public.question_content_hash(jsonb)',
        'public.submit_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)',
        'public.quiz_attempt_result(uuid)',
        'public.get_quiz_attempt_result_for_client(text,uuid,uuid)',
        'public.get_grounding_bundle(text,text,date,integer)',
        'public.submit_question_report(uuid,text,uuid,uuid,text,text,integer)',
        'public.submit_practice_question_report(uuid,uuid,uuid,text,text,integer)',
        'public.get_user_learning_dashboard(uuid)',
        'public.get_user_due_reviews(uuid,integer,integer)',
        'public.get_user_wrong_questions(uuid,text,integer,integer)',
        'public.submit_personal_practice_answer(uuid,uuid,uuid,integer,text,text,numeric,boolean)',
        'public.get_user_bookmarks(uuid)',
        'public.set_user_bookmark(uuid,text,uuid,boolean)',
        'public.get_user_preferences(uuid)',
        'public.save_user_preferences(uuid,text[],text[],integer,text,text,text,boolean,text,boolean,boolean,boolean,boolean)',
        'public.get_quiz_leaderboard_for_user(text,uuid,integer)',
        'public.get_leaderboard_for_user(text,text,uuid,integer,integer)',
        'public.find_similar_questions(text,text,double precision,integer)',
        'public.get_quiz_learning_resources(text,integer)',
        'public.cache_verified_source_resources(text)',
        'public.submit_resource_feedback(uuid,uuid,text,integer,text)',
        'public.get_resource_link_check_batch(integer)',
        'public.record_resource_link_check(uuid,text,integer,text,integer)',
        'public.queue_missing_resource_discovery(integer)',
        'public.get_resource_discovery_batch(integer)',
        'public.save_youtube_resource_candidate(uuid,text,text,text,text,text,integer,text,text,timestamp with time zone,numeric,numeric)',
        'public.complete_resource_discovery(uuid,text,text)',
        'public.get_resource_review_queue(integer,integer)',
        'public.review_resource_candidate(uuid,text,text)',
        'public.get_operational_status()',
        'public.get_application_schema_contract()'
    ];
    v_kolkata_functions text[] := array[
        'public.get_user_learning_dashboard(uuid)',
        'public.get_user_due_reviews(uuid,integer,integer)',
        'public.refresh_personal_review_overdue(uuid)',
        'public.advance_personal_review_schedule_v2(uuid,uuid,boolean,text,numeric,boolean)',
        'public.submit_personal_practice_answer(uuid,uuid,uuid,integer,text,text,numeric,boolean)',
        'public.save_quiz_pack_atomic(text,text,jsonb,text,boolean)',
        'public.get_operational_status()'
    ];
    v_missing_tables jsonb;
    v_missing_columns jsonb;
    v_missing_indexes jsonb;
    v_missing_triggers jsonb;
    v_missing_functions jsonb;
    v_function_permission_failures jsonb;
    v_function_configuration_failures jsonb;
    v_schema_permission_failures jsonb;
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
                   or name = ''revision_reports_and_rankings''
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
            ('personal_practice_answers','event_sequence'),
            ('personal_review_schedule','first_attempted_at'),
            ('personal_review_schedule','last_attempted_at'),
            ('personal_review_schedule','last_revision_at'),
            ('personal_review_schedule','attempt_count'),
            ('personal_review_schedule','revision_attempt_count'),
            ('personal_review_schedule','consecutive_correct_revisions'),
            ('personal_review_schedule','is_overdue'),
            ('user_preferences','revision_sound_enabled'),
            ('user_preferences','revision_vibration_enabled'),
            ('users','photo_url'),
            ('question_reports','practice_attempt_id')
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

    select coalesce(jsonb_agg(name order by name), '[]'::jsonb)
    into v_missing_indexes
    from unnest(v_indexes) name
    where to_regclass('public.' || name) is null;

    select coalesce(jsonb_agg(name order by name), '[]'::jsonb)
    into v_missing_triggers
    from unnest(v_triggers) name
    where not exists (
        select 1
        from pg_catalog.pg_trigger trigger
        join pg_catalog.pg_class relation on relation.oid = trigger.tgrelid
        join pg_catalog.pg_namespace namespace
          on namespace.oid = relation.relnamespace
        where namespace.nspname = 'public'
          and relation.relname = split_part(name, '.', 1)
          and trigger.tgname = split_part(name, '.', 2)
          and not trigger.tgisinternal
          and trigger.tgenabled <> 'D'
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

    select coalesce(jsonb_agg(signature order by signature), '[]'::jsonb)
    into v_function_configuration_failures
    from unnest(v_kolkata_functions) signature
    where to_regprocedure(signature) is null
       or not exists (
            select 1
            from pg_catalog.pg_proc procedure,
                 unnest(coalesce(procedure.proconfig, '{}'::text[])) setting
            where procedure.oid = to_regprocedure(signature)
              and lower(setting) = 'timezone=asia/kolkata'
       );

    select coalesce(jsonb_agg(requirement order by requirement), '[]'::jsonb)
    into v_schema_permission_failures
    from (values ('service_role.public.USAGE')) required(requirement)
    where not has_schema_privilege('service_role', 'public', 'USAGE');

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
       or not has_table_privilege(
              'service_role', 'public.' || name, 'SELECT'
          ));

    return jsonb_build_object(
        'contract_key', v_contract.contract_key,
        'contract_version', v_contract.contract_version,
        'required_migration_version', v_contract.required_migration_version,
        'migration_applied', v_migration_applied,
        'verification_threshold', v_contract.verification_threshold,
        'missing_tables', v_missing_tables,
        'missing_columns', v_missing_columns,
        'missing_indexes', v_missing_indexes,
        'missing_triggers', v_missing_triggers,
        'missing_functions', v_missing_functions,
        'function_permission_failures', v_function_permission_failures,
        'function_configuration_failures', v_function_configuration_failures,
        'schema_permission_failures', v_schema_permission_failures,
        'missing_rls', v_missing_rls,
        'table_permission_failures', v_table_permission_failures,
        'ready',
            v_contract.contract_version = '2.2.0'
            and v_contract.required_migration_version = '20260722120827'
            and v_contract.verification_threshold = 0.85
            and v_migration_applied
            and v_missing_tables = '[]'::jsonb
            and v_missing_columns = '[]'::jsonb
            and v_missing_indexes = '[]'::jsonb
            and v_missing_triggers = '[]'::jsonb
            and v_missing_functions = '[]'::jsonb
            and v_function_permission_failures = '[]'::jsonb
            and v_function_configuration_failures = '[]'::jsonb
            and v_schema_permission_failures = '[]'::jsonb
            and v_missing_rls = '[]'::jsonb
            and v_table_permission_failures = '[]'::jsonb
    );
end;
$$;

revoke execute on function public.submit_practice_question_report(
    uuid, uuid, uuid, text, text, integer
) from public, anon, authenticated;
revoke execute on function public.get_leaderboard_for_user(
    text, text, uuid, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_quiz_attempt_result_for_client(
    text, uuid, uuid
) from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.submit_practice_question_report(
    uuid, uuid, uuid, text, text, integer
) to service_role;
grant execute on function public.get_leaderboard_for_user(
    text, text, uuid, integer, integer
) to service_role;
grant execute on function public.get_quiz_attempt_result_for_client(
    text, uuid, uuid
) to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
grant usage on schema public to service_role;
