-- Preserve object-shaped learner API responses while recursively normalizing
-- every nested subjectKey.  The previous array-only helper raised
-- "cannot extract elements from an object" for Dashboard and Revision RPCs.

create or replace function public.canonicalize_subject_rows(p_rows jsonb)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_kind text;
    v_result jsonb;
begin
    if p_rows is null then
        return '[]'::jsonb;
    end if;

    v_kind := jsonb_typeof(p_rows);
    if v_kind = 'array' then
        select coalesce(
            jsonb_agg(
                public.canonicalize_subject_rows(item)
                order by position
            ),
            '[]'::jsonb
        )
        into v_result
        from jsonb_array_elements(p_rows)
            with ordinality as items(item, position);
        return v_result;
    end if;

    if v_kind = 'object' then
        select coalesce(
            jsonb_object_agg(
                key,
                case
                    when key = 'subjectKey'
                         and jsonb_typeof(value) = 'string'
                    then to_jsonb(public.canonical_subject_key(p_rows ->> key))
                    else public.canonicalize_subject_rows(value)
                end
                order by key
            ),
            '{}'::jsonb
        )
        into v_result
        from jsonb_each(p_rows) as fields(key, value);
        return v_result;
    end if;

    return p_rows;
end;
$$;

alter function public.get_application_schema_contract()
    rename to get_application_schema_contract_v220_learning_base;

create function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_projection jsonb;
    v_projection_ready boolean := false;
    v_function_permission_failures jsonb;
begin
    v_base := public.get_application_schema_contract_v220_learning_base();
    v_projection := public.canonicalize_subject_rows(
        '{
            "rows": [{"subjectKey": "Computer Education"}],
            "total": 1
        }'::jsonb
    );
    v_projection_ready :=
        jsonb_typeof(v_projection) = 'object'
        and jsonb_typeof(v_projection -> 'rows') = 'array'
        and v_projection #>> '{rows,0,subjectKey}' = 'computer'
        and (v_projection ->> 'total')::integer = 1;

    v_function_permission_failures :=
        coalesce(v_base -> 'function_permission_failures', '[]'::jsonb)
        || case when
            not has_function_privilege(
                'service_role',
                'public.canonicalize_subject_rows(jsonb)',
                'EXECUTE'
            )
            or has_function_privilege(
                'anon',
                'public.canonicalize_subject_rows(jsonb)',
                'EXECUTE'
            )
            or has_function_privilege(
                'authenticated',
                'public.canonicalize_subject_rows(jsonb)',
                'EXECUTE'
            )
        then jsonb_build_array('public.canonicalize_subject_rows(jsonb)')
        else '[]'::jsonb end
        || case when
            not has_function_privilege(
                'service_role',
                'public.get_application_schema_contract_v220_learning_base()',
                'EXECUTE'
            )
            or has_function_privilege(
                'anon',
                'public.get_application_schema_contract_v220_learning_base()',
                'EXECUTE'
            )
            or has_function_privilege(
                'authenticated',
                'public.get_application_schema_contract_v220_learning_base()',
                'EXECUTE'
            )
        then jsonb_build_array(
            'public.get_application_schema_contract_v220_learning_base()'
        )
        else '[]'::jsonb end;

    return v_base || jsonb_build_object(
        'personal_learning_migration_version', '20260729134221',
        'personal_learning_migration_applied', true,
        'personal_learning_projection_ready', v_projection_ready,
        'function_permission_failures', v_function_permission_failures,
        'ready',
            coalesce((v_base ->> 'ready')::boolean, false)
            and v_projection_ready
            and v_function_permission_failures = '[]'::jsonb
    );
end;
$$;

revoke execute on function public.canonicalize_subject_rows(jsonb)
    from public, anon, authenticated;
revoke execute on function
    public.get_application_schema_contract_v220_learning_base()
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.canonicalize_subject_rows(jsonb)
    to service_role;
grant execute on function
    public.get_application_schema_contract_v220_learning_base()
    to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
