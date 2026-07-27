-- Forward-only durability patch for write paths that previously relied on the
-- process-local button-storm guard. No learner or quiz data is rewritten.

create table if not exists public.write_rate_limit_buckets (
    scope text not null check (scope in (
        'bookmark', 'preferences', 'resource_feedback', 'resource_review'
    )),
    actor_key text not null check (length(actor_key) between 1 and 200),
    window_started_at timestamptz not null,
    event_count integer not null check (event_count > 0),
    updated_at timestamptz not null default now(),
    primary key (scope, actor_key, window_started_at)
);

create index if not exists idx_write_rate_limit_updated_at
    on public.write_rate_limit_buckets (updated_at);

alter table public.write_rate_limit_buckets enable row level security;
revoke all on table public.write_rate_limit_buckets
    from public, anon, authenticated;
grant select, insert, update, delete on table public.write_rate_limit_buckets
    to service_role;

create or replace function public.enforce_write_rate_limit(
    p_scope text,
    p_actor_key text,
    p_limit integer,
    p_window_seconds integer
)
returns void
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_window_started_at timestamptz;
    v_event_count integer;
begin
    if p_scope not in (
        'bookmark', 'preferences', 'resource_feedback', 'resource_review'
    ) then
        raise exception 'invalid durable rate-limit scope';
    end if;
    if nullif(btrim(p_actor_key), '') is null or length(p_actor_key) > 200 then
        raise exception 'invalid durable rate-limit actor';
    end if;
    if p_limit < 1 or p_window_seconds < 1 or p_window_seconds > 86400 then
        raise exception 'invalid durable rate-limit configuration';
    end if;

    v_window_started_at := to_timestamp(
        floor(extract(epoch from clock_timestamp()) / p_window_seconds)
        * p_window_seconds
    );
    delete from public.write_rate_limit_buckets
    where updated_at < clock_timestamp() - interval '2 days';
    perform pg_advisory_xact_lock(
        hashtextextended(p_scope || ':' || p_actor_key, 0)
    );

    insert into public.write_rate_limit_buckets (
        scope, actor_key, window_started_at, event_count, updated_at
    ) values (
        p_scope, p_actor_key, v_window_started_at, 1, clock_timestamp()
    )
    on conflict (scope, actor_key, window_started_at) do update
    set event_count = public.write_rate_limit_buckets.event_count + 1,
        updated_at = clock_timestamp()
    returning event_count into v_event_count;

    if v_event_count > p_limit then
        raise exception '% rate limit exceeded', replace(p_scope, '_', ' ');
    end if;
end;
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
    if p_item_type not in ('question', 'resource') then
        raise exception 'invalid bookmark type';
    end if;
    perform public.enforce_write_rate_limit(
        'bookmark', p_user_id::text, 60, 3600
    );

    if p_item_type = 'question' then
        if p_active then
            insert into public.user_question_bookmarks (user_id, question_id)
            values (p_user_id, p_item_id)
            on conflict do nothing;
        else
            delete from public.user_question_bookmarks
            where user_id = p_user_id and question_id = p_item_id;
        end if;
    else
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
    end if;

    return jsonb_build_object(
        'itemType', p_item_type,
        'itemId', p_item_id,
        'active', p_active
    );
end;
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

    perform public.enforce_write_rate_limit(
        'preferences', p_user_id::text, 20, 3600
    );

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
        'video_unavailable', 'article_unavailable', 'not_useful',
        'wrong_language', 'topic_mismatch', 'low_quality'
    ) then
        raise exception 'invalid resource feedback type';
    end if;
    if p_rating is not null and p_rating not between 1 and 5 then
        raise exception 'rating must be between 1 and 5';
    end if;
    if p_details is not null and length(btrim(p_details)) > 500 then
        raise exception 'feedback details are too long';
    end if;

    perform public.enforce_write_rate_limit(
        'resource_feedback', p_user_id::text, 20, 3600
    );

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
    if p_decision not in ('approve', 'reject', 'archive') then
        raise exception 'invalid resource review decision';
    end if;
    if length(btrim(p_actor)) not between 3 and 100 then
        raise exception 'review actor is required';
    end if;

    perform public.enforce_write_rate_limit(
        'resource_review', btrim(p_actor), 60, 3600
    );

    select * into v_resource
    from public.learning_resources where id = p_resource_id for update;
    if not found then
        raise exception 'resource does not exist';
    end if;

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

-- Preserve the complete 2.2.0 verifier as a private base and layer the
-- durability patch requirements over it. The public RPC name and result shape
-- remain stable throughout this transaction.
alter function public.get_application_schema_contract()
    rename to get_application_schema_contract_v220_base;

update public.application_schema_contract
set required_migration_version = '20260724212939',
    applied_at = now()
where contract_key = 'telegram_quiz_api';

create function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_migration_applied boolean := false;
    v_missing_tables jsonb;
    v_missing_indexes jsonb;
    v_missing_functions jsonb;
    v_function_permission_failures jsonb;
    v_missing_rls jsonb;
    v_table_permission_failures jsonb;
begin
    v_base := public.get_application_schema_contract_v220_base();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute
            'select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = $1 or name = ''durable_write_rate_limits''
            )'
        into v_migration_applied
        using '20260724212939';
    end if;

    v_missing_tables := coalesce(v_base->'missing_tables', '[]'::jsonb)
        || case when to_regclass('public.write_rate_limit_buckets') is null
            then jsonb_build_array('write_rate_limit_buckets')
            else '[]'::jsonb end;
    v_missing_indexes := coalesce(v_base->'missing_indexes', '[]'::jsonb)
        || case when to_regclass('public.idx_write_rate_limit_updated_at') is null
            then jsonb_build_array('idx_write_rate_limit_updated_at')
            else '[]'::jsonb end;
    v_missing_functions := coalesce(v_base->'missing_functions', '[]'::jsonb)
        || case when to_regprocedure(
            'public.enforce_write_rate_limit(text,text,integer,integer)'
        ) is null
            then jsonb_build_array(
                'public.enforce_write_rate_limit(text,text,integer,integer)'
            )
            else '[]'::jsonb end;
    v_function_permission_failures :=
        coalesce(v_base->'function_permission_failures', '[]'::jsonb)
        || case when to_regprocedure(
            'public.enforce_write_rate_limit(text,text,integer,integer)'
        ) is not null and (
            not has_function_privilege(
                'service_role',
                'public.enforce_write_rate_limit(text,text,integer,integer)',
                'EXECUTE'
            )
            or has_function_privilege(
                'anon',
                'public.enforce_write_rate_limit(text,text,integer,integer)',
                'EXECUTE'
            )
            or has_function_privilege(
                'authenticated',
                'public.enforce_write_rate_limit(text,text,integer,integer)',
                'EXECUTE'
            )
        )
            then jsonb_build_array(
                'public.enforce_write_rate_limit(text,text,integer,integer)'
            )
            else '[]'::jsonb end;
    v_missing_rls := coalesce(v_base->'missing_rls', '[]'::jsonb)
        || case when exists (
            select 1
            from pg_catalog.pg_class relation
            join pg_catalog.pg_namespace namespace
              on namespace.oid = relation.relnamespace
            where namespace.nspname = 'public'
              and relation.relname = 'write_rate_limit_buckets'
              and not relation.relrowsecurity
        )
            then jsonb_build_array('write_rate_limit_buckets')
            else '[]'::jsonb end;
    v_table_permission_failures :=
        coalesce(v_base->'table_permission_failures', '[]'::jsonb)
        || case when to_regclass('public.write_rate_limit_buckets') is not null
          and (
              has_table_privilege(
                  'anon', 'public.write_rate_limit_buckets',
                  'SELECT,INSERT,UPDATE,DELETE'
              )
              or has_table_privilege(
                  'authenticated', 'public.write_rate_limit_buckets',
                  'SELECT,INSERT,UPDATE,DELETE'
              )
              or not has_table_privilege(
                  'service_role', 'public.write_rate_limit_buckets', 'SELECT'
              )
          )
            then jsonb_build_array('write_rate_limit_buckets')
            else '[]'::jsonb end;

    return v_base || jsonb_build_object(
        'required_migration_version', '20260724212939',
        'migration_applied', v_migration_applied,
        'missing_tables', v_missing_tables,
        'missing_indexes', v_missing_indexes,
        'missing_functions', v_missing_functions,
        'function_permission_failures', v_function_permission_failures,
        'missing_rls', v_missing_rls,
        'table_permission_failures', v_table_permission_failures,
        'ready',
            v_base->>'contract_key' = 'telegram_quiz_api'
            and v_base->>'contract_version' = '2.2.0'
            and (v_base->>'verification_threshold')::numeric = 0.85
            and v_migration_applied
            and v_missing_tables = '[]'::jsonb
            and coalesce(v_base->'missing_columns', '[]'::jsonb) = '[]'::jsonb
            and v_missing_indexes = '[]'::jsonb
            and coalesce(v_base->'missing_triggers', '[]'::jsonb) = '[]'::jsonb
            and v_missing_functions = '[]'::jsonb
            and v_function_permission_failures = '[]'::jsonb
            and coalesce(
                v_base->'function_configuration_failures', '[]'::jsonb
            ) = '[]'::jsonb
            and coalesce(
                v_base->'schema_permission_failures', '[]'::jsonb
            ) = '[]'::jsonb
            and v_missing_rls = '[]'::jsonb
            and v_table_permission_failures = '[]'::jsonb
    );
end;
$$;

revoke execute on function public.enforce_write_rate_limit(
    text, text, integer, integer
) from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract_v220_base()
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.enforce_write_rate_limit(
    text, text, integer, integer
) to service_role;
grant execute on function public.get_application_schema_contract_v220_base()
    to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
