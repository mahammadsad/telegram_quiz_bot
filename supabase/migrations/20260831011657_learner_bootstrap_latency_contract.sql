-- Learner bootstrap latency contract.
--
-- Keep Telegram identity fields current while throttling last_active-only
-- writes, and collapse dashboard/preferences and practice/preferences into
-- one projection RPC apiece. Browser clients still authenticate with FastAPI;
-- every function remains service-role-only.

create or replace function public.resolve_telegram_user_v2(
    p_telegram_id bigint,
    p_username text,
    p_first_name text,
    p_last_name text,
    p_photo_url text,
    p_touch_interval_seconds integer default 900
)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
    v_now timestamptz := now();
    v_user public.users%rowtype;
begin
    if p_telegram_id <= 0 then
        raise exception 'invalid telegram user';
    end if;
    if p_touch_interval_seconds not between 60 and 86400 then
        raise exception 'invalid user touch interval';
    end if;
    if p_photo_url is not null and p_photo_url !~ '^https://' then
        raise exception 'invalid profile photo url';
    end if;

    insert into public.users (
        telegram_id,
        username,
        first_name,
        last_name,
        photo_url,
        last_active
    ) values (
        p_telegram_id,
        nullif(btrim(p_username), ''),
        nullif(btrim(p_first_name), ''),
        nullif(btrim(p_last_name), ''),
        nullif(btrim(p_photo_url), ''),
        v_now
    )
    on conflict (telegram_id) do update set
        username = excluded.username,
        first_name = excluded.first_name,
        last_name = excluded.last_name,
        photo_url = excluded.photo_url,
        last_active = case
            when public.users.username is distinct from excluded.username
              or public.users.first_name is distinct from excluded.first_name
              or public.users.last_name is distinct from excluded.last_name
              or public.users.photo_url is distinct from excluded.photo_url
              or public.users.last_active <= v_now
                    - make_interval(secs => p_touch_interval_seconds)
            then v_now
            else public.users.last_active
        end
    where public.users.username is distinct from excluded.username
       or public.users.first_name is distinct from excluded.first_name
       or public.users.last_name is distinct from excluded.last_name
       or public.users.photo_url is distinct from excluded.photo_url
       or public.users.last_active <= v_now
            - make_interval(secs => p_touch_interval_seconds)
    returning * into v_user;

    if v_user.id is null then
        select * into strict v_user
        from public.users
        where telegram_id = p_telegram_id;
    end if;

    return jsonb_build_object(
        'id', v_user.id,
        'username', v_user.username,
        'first_name', v_user.first_name,
        'last_name', v_user.last_name,
        'photo_url', v_user.photo_url,
        'join_date', v_user.join_date,
        'last_active', v_user.last_active
    );
end;
$$;

create or replace function public.get_user_learning_dashboard_bootstrap(
    p_user_id uuid
)
returns jsonb
language sql
volatile
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'dashboard', public.get_user_learning_dashboard_v2(p_user_id),
        'preferences', public.get_user_preferences(p_user_id)
    );
$$;

create or replace function public.get_user_practice_bootstrap(
    p_user_id uuid,
    p_source_type text,
    p_subject_key text default null,
    p_limit integer default 100,
    p_offset integer default 0
)
returns jsonb
language plpgsql
volatile
security invoker
set search_path = ''
as $$
declare
    v_source text := lower(coalesce(p_source_type, ''));
    v_subject text := nullif(btrim(p_subject_key), '');
    v_queue jsonb;
begin
    if v_source not in ('wrong', 'due', 'bookmark', 'weak_topic') then
        raise exception 'invalid practice source';
    end if;
    if v_source = 'weak_topic' and v_subject is null then
        select kp.subject_key
        into v_subject
        from public.personal_knowledge_mastery mastery
        join public.knowledge_points kp
          on kp.id = mastery.knowledge_point_id
        where mastery.user_id = p_user_id
        group by kp.subject_key
        order by avg(mastery.mastery_score), sum(mastery.attempt_count) desc,
            kp.subject_key
        limit 1;
    end if;

    v_queue := case v_source
        when 'due' then public.get_user_due_reviews(
            p_user_id, p_limit, p_offset
        )
        when 'bookmark' then public.get_user_bookmarks(p_user_id)
        when 'weak_topic' then case
            when v_subject is null then jsonb_build_object(
                'total', 0,
                'limit', greatest(1, least(coalesce(p_limit, 100), 100)),
                'offset', greatest(0, coalesce(p_offset, 0)),
                'mode', 'revision',
                'sourceType', 'weak_topic',
                'rows', '[]'::jsonb
            )
            else public.get_user_wrong_questions(
                p_user_id, v_subject, p_limit, p_offset
            )
        end
        else public.get_user_wrong_questions(
            p_user_id, null, p_limit, p_offset
        )
    end;

    return jsonb_build_object(
        'queue', coalesce(v_queue, '{}'::jsonb),
        'preferences', coalesce(
            public.get_user_preferences(p_user_id),
            '{}'::jsonb
        )
    );
end;
$$;

create or replace function public.get_learner_bootstrap_latency_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'ready',
            to_regprocedure(
                'public.resolve_telegram_user_v2(bigint,text,text,text,text,integer)'
            ) is not null
            and to_regprocedure(
                'public.get_user_learning_dashboard_bootstrap(uuid)'
            ) is not null
            and to_regprocedure(
                'public.get_user_practice_bootstrap(uuid,text,text,integer,integer)'
            ) is not null,
        'contractVersion', '1.0.0',
        'lastActiveTouchIntervalSeconds', 900,
        'dashboardRoundTripsAfterIdentity', 1,
        'practiceRoundTripsAfterIdentity', 1
    );
$$;

revoke all on function public.resolve_telegram_user_v2(
    bigint, text, text, text, text, integer
) from public, anon, authenticated;
revoke all on function public.get_user_learning_dashboard_bootstrap(uuid)
    from public, anon, authenticated;
revoke all on function public.get_user_practice_bootstrap(
    uuid, text, text, integer, integer
) from public, anon, authenticated;
revoke all on function public.get_learner_bootstrap_latency_contract()
    from public, anon, authenticated;

grant execute on function public.resolve_telegram_user_v2(
    bigint, text, text, text, text, integer
) to service_role;
grant execute on function public.get_user_learning_dashboard_bootstrap(uuid)
    to service_role;
grant execute on function public.get_user_practice_bootstrap(
    uuid, text, text, integer, integer
) to service_role;
grant execute on function public.get_learner_bootstrap_latency_contract()
    to service_role;

-- Extend the established fail-closed scheduler/deployment contract without
-- duplicating its existing checks. The renamed predecessor remains private and
-- is called only by this new service-role wrapper.
alter function public.get_platform_contract_v1()
    rename to get_platform_contract_v1_before_learner_bootstrap;

revoke all on function public.get_platform_contract_v1_before_learner_bootstrap()
    from public, anon, authenticated;

create function public.get_platform_contract_v1()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_latency jsonb;
    v_checks jsonb;
    v_missing jsonb;
    v_migration_applied boolean := false;
begin
    v_base := public.get_platform_contract_v1_before_learner_bootstrap();
    v_latency := public.get_learner_bootstrap_latency_contract();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = '20260831011657'
            )
        $migration_check$ into v_migration_applied;
    end if;

    v_checks := coalesce(v_base->'checks', '{}'::jsonb)
        || jsonb_build_object(
            'learnerBootstrapLatency',
            coalesce((v_latency->>'ready')::boolean, false)
                and v_migration_applied
        );

    select coalesce(jsonb_agg(key order by key), '[]'::jsonb)
    into v_missing
    from jsonb_each(v_checks)
    where value is distinct from 'true'::jsonb;

    return v_base || jsonb_build_object(
        'ready',
            coalesce((v_base->>'ready')::boolean, false)
                and v_migration_applied
                and coalesce((v_latency->>'ready')::boolean, false),
        'contract_version', '1.1.0',
        'required_migration_version', '20260831011657',
        'migration_applied', v_migration_applied,
        'checks', v_checks,
        'missing_checks', v_missing
    );
end;
$$;

revoke all on function public.get_platform_contract_v1()
    from public, anon, authenticated;
grant execute on function public.get_platform_contract_v1() to service_role;
