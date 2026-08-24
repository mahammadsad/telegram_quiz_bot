-- Keep the leaderboard privacy contract callable through the service-role
-- Data API without granting access to Supabase's internal migration schema.
-- The function's own presence at this definition, plus the object and ACL
-- checks below, is the migration evidence.

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
    v_migration_applied boolean := true;
    v_ready boolean;
begin
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
        'leaderboard_privacy_rpc_fix_migration_version', '20260808084950',
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

revoke all on function public.get_leaderboard_privacy_contract()
    from public, anon, authenticated;
grant execute on function public.get_leaderboard_privacy_contract()
    to service_role;
