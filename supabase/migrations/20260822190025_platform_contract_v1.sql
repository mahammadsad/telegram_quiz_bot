-- One fail-closed, service-role-only view of every database capability required
-- by application version 8.6.0.  Deployments and schedulers must call this
-- contract before any work that can generate or publish a quiz.

create or replace function public.get_platform_contract_v1()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_application jsonb;
    v_leaderboard_privacy jsonb;
    v_post_finalization jsonb;
    v_quiz_jobs jsonb;
    v_phase_c_content jsonb;
    v_phase_c_inventory jsonb;
    v_phase_c_candidate jsonb;
    v_phase_d_current_affairs jsonb;
    v_phase_e_personal_learning jsonb;
    v_phase_e_exam_configuration jsonb;
    v_phase_e_previous_year_mock jsonb;
    v_phase_e_question_quality jsonb;
    v_source_optional_generation jsonb;
    v_daily_attempt_timing jsonb;
    v_question_verification jsonb;
    v_migration_applied boolean := false;
    v_checks jsonb;
    v_missing jsonb;
begin
    v_application := public.get_application_schema_contract();
    v_leaderboard_privacy := public.get_leaderboard_privacy_contract();
    v_post_finalization := public.get_post_finalization_contract();
    v_quiz_jobs := public.get_quiz_job_contract();
    v_phase_c_content := public.get_phase_c_content_contract();
    v_phase_c_inventory := public.get_phase_c_inventory_contract();
    v_phase_c_candidate := public.get_phase_c_candidate_contract();
    v_phase_d_current_affairs := public.get_phase_d_current_affairs_contract();
    v_phase_e_personal_learning := public.get_phase_e_personal_learning_contract();
    v_phase_e_exam_configuration := public.get_phase_e_exam_configuration_contract();
    v_phase_e_previous_year_mock := public.get_phase_e_previous_year_mock_contract();
    v_phase_e_question_quality := public.get_phase_e_question_quality_contract();
    v_source_optional_generation := public.get_source_optional_generation_contract();
    v_daily_attempt_timing := public.get_daily_attempt_timing_contract();
    v_question_verification := public.get_question_verification_independence_contract();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = '20260822190025'
            )
        $migration_check$ into v_migration_applied;
    end if;

    v_checks := jsonb_build_object(
        'migrationLedger', v_migration_applied,
        'applicationSchema', coalesce((v_application ->> 'ready')::boolean, false),
        'leaderboardPrivacy', coalesce((v_leaderboard_privacy ->> 'ready')::boolean, false),
        'postFinalization', coalesce((v_post_finalization ->> 'ready')::boolean, false),
        'durableQuizJobs', coalesce((v_quiz_jobs ->> 'ready')::boolean, false),
        'contentIdentity', coalesce((v_phase_c_content ->> 'ready')::boolean, false),
        'verifiedInventory', coalesce((v_phase_c_inventory ->> 'ready')::boolean, false)
            and coalesce((v_phase_c_candidate ->> 'ready')::boolean, false),
        'currentAffairsEvents', coalesce((v_phase_d_current_affairs ->> 'ready')::boolean, false),
        'personalKnowledgeMastery', coalesce((v_phase_e_personal_learning ->> 'ready')::boolean, false),
        'examConfiguration', coalesce((v_phase_e_exam_configuration ->> 'ready')::boolean, false),
        'previousYearMocks', coalesce((v_phase_e_previous_year_mock ->> 'ready')::boolean, false),
        'questionQualityAdministration', coalesce((v_phase_e_question_quality ->> 'ready')::boolean, false),
        'sourceOptionalGeneration', coalesce((v_source_optional_generation ->> 'ready')::boolean, false),
        'dailyAttemptTiming', coalesce((v_daily_attempt_timing ->> 'ready')::boolean, false),
        'questionVerificationIndependence',
            coalesce((v_question_verification ->> 'ready')::boolean, false)
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'question_generation_audits'
                  and column_name = 'generator_provider'
            )
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'question_generation_audits'
                  and column_name = 'generator_model'
            ),
        'learningTestCatalog',
            to_regprocedure(
                'public.get_learning_test_catalog(text,text,text,integer,integer)'
            ) is not null,
        'privacyRights',
            to_regclass('public.account_deletion_requests') is not null
            and to_regclass('public.account_deletion_audit') is not null
            and to_regprocedure('public.export_learner_data(uuid)') is not null
            and to_regprocedure('public.request_account_deletion(uuid)') is not null
            and to_regprocedure('public.cancel_account_deletion(uuid)') is not null
            and to_regprocedure('public.process_due_account_deletions(integer)') is not null,
        'advisorHardening',
            exists (
                select 1
                from pg_extension extension_info
                join pg_namespace extension_schema
                  on extension_schema.oid = extension_info.extnamespace
                where extension_info.extname = 'pg_trgm'
                  and extension_schema.nspname = 'extensions'
            )
            and to_regprocedure(
                'public.find_similar_questions(text,text,double precision,integer)'
            ) is not null,
        'postUnknownRecovery',
            to_regprocedure(
                'public.finalize_quiz_post(text,text,bigint,timestamp with time zone,bigint,bigint,integer,integer)'
            ) is not null
    );

    select coalesce(jsonb_agg(key order by key), '[]'::jsonb)
    into v_missing
    from jsonb_each(v_checks)
    where value is distinct from 'true'::jsonb;

    return jsonb_build_object(
        'ready', jsonb_array_length(v_missing) = 0,
        'contract_key', 'telegram_quiz_platform',
        'contract_version', '1.0.0',
        'required_migration_version', '20260822190025',
        'migration_applied', v_migration_applied,
        'checks', v_checks,
        'missing_checks', v_missing
    );
end;
$$;

revoke all on function public.get_platform_contract_v1()
    from public, anon, authenticated;
grant execute on function public.get_platform_contract_v1() to service_role;
