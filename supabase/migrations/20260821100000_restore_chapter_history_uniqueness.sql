-- Restore the uniqueness required by atomic Telegram post finalization.
--
-- Some long-lived databases predate the table-level UNIQUE declaration in
-- database/schema.sql.  finalize_quiz_post uses ON CONFLICT on these columns,
-- so the database contract must verify the corresponding constraint exists.

do $$
begin
    if exists (
        select 1
        from public.chapter_history
        group by subject_key, selected_for
        having count(*) > 1
    ) then
        raise exception
            'chapter_history contains duplicate subject/date rows; refusing to add uniqueness';
    end if;

    if not exists (
        select 1
        from pg_constraint constraint_info
        where constraint_info.conrelid = 'public.chapter_history'::regclass
          and constraint_info.contype in ('p', 'u')
          and constraint_info.conkey = array[
              (
                  select attribute.attnum
                  from pg_attribute attribute
                  where attribute.attrelid = 'public.chapter_history'::regclass
                    and attribute.attname = 'subject_key'
              ),
              (
                  select attribute.attnum
                  from pg_attribute attribute
                  where attribute.attrelid = 'public.chapter_history'::regclass
                    and attribute.attname = 'selected_for'
              )
          ]::smallint[]
    ) then
        alter table public.chapter_history
            add constraint chapter_history_subject_key_selected_for_key
            unique (subject_key, selected_for);
    end if;
end;
$$;

create or replace function public.get_post_finalization_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_columns(table_name, column_name) as (
        values
            ('quiz_runs', 'posting_intent_fingerprint'),
            ('quiz_runs', 'posting_intended_at'),
            ('quiz_runs', 'telegram_acknowledged_at'),
            ('quiz_micro_topics', 'usage_count'),
            ('quiz_chapters', 'usage_count'),
            ('quiz_chapters', 'last_used_at'),
            ('source_documents', 'usage_count'),
            ('source_documents', 'last_used_at')
    ), missing_columns as (
        select format('%s.%s', required.table_name, required.column_name) as name
        from required_columns required
        where not exists (
            select 1
            from information_schema.columns column_info
            where column_info.table_schema = 'public'
              and column_info.table_name = required.table_name
              and column_info.column_name = required.column_name
        )
    ), function_permissions as (
        select * from (values
            ('record_quiz_post_intent(text,text,text,timestamp with time zone)'),
            ('finalize_quiz_post(text,text,bigint,timestamp with time zone,bigint,bigint,integer,integer)'),
            ('record_quiz_post_unknown(text,text,bigint,timestamp with time zone,bigint,bigint,text)')
        ) functions(signature)
    ), permission_failures as (
        select role_name || ':' || functions.signature as failure
        from function_permissions functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(
            roles.role_name,
            'public.' || functions.signature,
            'EXECUTE'
        )
        union all
        select 'service_role:' || functions.signature
        from function_permissions functions
        where not has_function_privilege(
            'service_role',
            'public.' || functions.signature,
            'EXECUTE'
        )
    ), facts as (
        select
            coalesce((select jsonb_agg(name order by name) from missing_columns), '[]'::jsonb)
                as missing_columns,
            coalesce((select jsonb_agg(failure order by failure) from permission_failures), '[]'::jsonb)
                as function_permission_failures,
            to_regprocedure('public.record_quiz_post_intent(text,text,text,timestamp with time zone)') is not null
                and to_regprocedure('public.finalize_quiz_post(text,text,bigint,timestamp with time zone,bigint,bigint,integer,integer)') is not null
                and to_regprocedure('public.record_quiz_post_unknown(text,text,bigint,timestamp with time zone,bigint,bigint,text)') is not null
                as functions_ready,
            exists (
                select 1
                from pg_constraint constraint_info
                where constraint_info.conrelid = 'public.chapter_history'::regclass
                  and constraint_info.contype in ('p', 'u')
                  and constraint_info.conkey = array[
                      (
                          select attribute.attnum
                          from pg_attribute attribute
                          where attribute.attrelid = 'public.chapter_history'::regclass
                            and attribute.attname = 'subject_key'
                      ),
                      (
                          select attribute.attnum
                          from pg_attribute attribute
                          where attribute.attrelid = 'public.chapter_history'::regclass
                            and attribute.attname = 'selected_for'
                      )
                  ]::smallint[]
            ) as chapter_history_uniqueness_ready
    )
    select jsonb_build_object(
        'post_finalization_migration_version', '20260821100000',
        'post_finalization_migration_applied',
            jsonb_array_length(facts.missing_columns) = 0
            and facts.functions_ready
            and facts.chapter_history_uniqueness_ready,
        'ready',
            jsonb_array_length(facts.missing_columns) = 0
            and jsonb_array_length(facts.function_permission_failures) = 0
            and facts.functions_ready
            and facts.chapter_history_uniqueness_ready,
        'chapter_history_uniqueness_ready', facts.chapter_history_uniqueness_ready,
        'missing_columns', facts.missing_columns,
        'function_permission_failures', facts.function_permission_failures
    )
    from facts;
$$;

revoke all on function public.get_post_finalization_contract()
    from public, anon, authenticated;
grant execute on function public.get_post_finalization_contract()
    to service_role;
