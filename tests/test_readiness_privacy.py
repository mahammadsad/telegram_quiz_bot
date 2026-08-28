from __future__ import annotations

from database.contract import (
    PLATFORM_CONTRACT_KEY,
    PLATFORM_CONTRACT_MIGRATION_VERSION,
    PLATFORM_CONTRACT_REQUIRED_CHECKS,
    PLATFORM_CONTRACT_VERSION,
)
from services import readiness_service


def _configure_ready_dependencies(monkeypatch) -> None:
    for name in (
        "EXPECTED_SUPABASE_PROJECT_REF",
        "MINIAPP_SHORT_NAME",
        "SUPABASE_SERVICE_KEY",
        "SUPABASE_URL",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_BOT_USERNAME",
        "TELEGRAM_CHAT_ID",
    ):
        monkeypatch.setattr(readiness_service, name, "configured")
    monkeypatch.setattr(readiness_service, "PUBLIC_APP_URL", "https://app.example")
    monkeypatch.setattr(readiness_service, "PUBLIC_API_BASE_URL", "https://api.example")
    monkeypatch.setattr(readiness_service, "TELEGRAM_FORUM_TOPICS_JSON", "{}")
    monkeypatch.setattr(readiness_service, "TELEGRAM_GENERAL_THREAD_ID", "1")
    monkeypatch.setattr(readiness_service, "SOURCE_BACKED_ROTATION_ENABLED", False)
    monkeypatch.setattr(
        readiness_service,
        "gemini_provider_configuration",
        lambda: ("primary", "secondary"),
    )
    monkeypatch.setattr(
        readiness_service,
        "supabase_project_ref_matches",
        lambda: True,
    )
    monkeypatch.setattr(
        readiness_service.ForumRouter,
        "from_values",
        lambda *args: object(),
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_contract",
        lambda: {
            "ready": True,
            "contract_key": readiness_service.DATABASE_CONTRACT_KEY,
            "contract_version": readiness_service.DATABASE_CONTRACT_VERSION,
            "required_migration_version": (readiness_service.REQUIRED_MIGRATION_VERSION),
            "personal_learning_migration_version": (readiness_service.PERSONAL_LEARNING_MIGRATION_VERSION),
            "personal_learning_migration_applied": True,
            "personal_learning_projection_ready": True,
            "verification_threshold": (readiness_service.QUESTION_VERIFICATION_MIN_CONFIDENCE),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_platform_contract",
        lambda: {
            "ready": True,
            "contract_key": PLATFORM_CONTRACT_KEY,
            "contract_version": PLATFORM_CONTRACT_VERSION,
            "required_migration_version": PLATFORM_CONTRACT_MIGRATION_VERSION,
            "migration_applied": True,
            "checks": {name: True for name in PLATFORM_CONTRACT_REQUIRED_CHECKS},
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "active_quiz_probe",
        lambda: {
            "question_count": 10,
            "integrity_verified": True,
            "checksum_contract_version": 2,
            "generated_checksum": "same",
            "persisted_checksum": "same",
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_daily_attempt_timing_contract",
        lambda: {
            "ready": True,
            "migration_version": readiness_service.DAILY_ATTEMPT_TIMING_MIGRATION_VERSION,
            "server_timed_rank": True,
            "legacy_timing_untrusted": True,
            "client_response_times_untrusted": True,
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_primary_scheduler_contract",
        lambda: {
            "ready": True,
            "migration_version": readiness_service.PRIMARY_SCHEDULER_MIGRATION_VERSION,
            "pg_cron_ready": True,
            "pg_net_ready": True,
            "credential_present": True,
            "credential_outside_renewal_window": True,
            "dispatch_job_ready": True,
            "completeness_job_ready": True,
            "reconcile_job_ready": True,
            "recent_rejected_requests": 0,
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_post_finalization_contract",
        lambda: {
            "ready": True,
            "post_finalization_migration_version": (readiness_service.POST_FINALIZATION_MIGRATION_VERSION),
            "post_finalization_migration_applied": True,
            "chapter_history_uniqueness_ready": True,
            "missing_columns": [],
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_quiz_job_contract",
        lambda: {
            "ready": True,
            "quiz_job_migration_version": (readiness_service.QUIZ_JOBS_MIGRATION_VERSION),
            "quiz_job_migration_applied": True,
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_c_content_contract",
        lambda: {
            "ready": True,
            "knowledge_points": True,
            "atomic_source_facts": True,
            "question_variants": True,
            "append_only_verification": True,
            "append_only_usage": True,
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_c_inventory_contract",
        lambda: {
            "ready": True,
            "phase_c_inventory_migration_version": (readiness_service.PHASE_C_INVENTORY_MIGRATION_VERSION),
            "replenishment_backlog_migration_version": (
                readiness_service.CONTENT_REPLENISHMENT_BACKLOG_MIGRATION_VERSION
            ),
            "open_job_uniqueness_ready": True,
            "duplicate_open_job_count": 0,
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_c_candidate_contract",
        lambda: {
            "ready": True,
            "stable_identity_parity": True,
            "phase_c_candidate_migration_version": (readiness_service.PHASE_C_CANDIDATE_MIGRATION_VERSION),
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_d_current_affairs_contract",
        lambda: {
            "ready": True,
            "event_dates": True,
            "atomic_claims": True,
            "multi_source_clusters": True,
            "correction_and_expiry": True,
            "weighted_revision_pools": True,
            "phase_d_current_affairs_migration_version": (readiness_service.PHASE_D_CURRENT_AFFAIRS_MIGRATION_VERSION),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_e_personal_learning_contract",
        lambda: {
            "ready": True,
            "knowledge_point_state": True,
            "variant_history": True,
            "different_variant_selection": True,
            "daily_rollups": True,
            "transparent_recommendations": True,
            "cohort_definition": True,
            "phase_e_personal_learning_migration_version": (
                readiness_service.PHASE_E_PERSONAL_LEARNING_MIGRATION_VERSION
            ),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_e_exam_configuration_contract",
        lambda: {
            "ready": True,
            "versioned_exam_hierarchy": True,
            "effective_dating": True,
            "syllabus_weights": True,
            "shared_test_instances": True,
            "daily_quick_definition": True,
            "historical_ids_preserved": True,
            "attempt_links_backfilled": True,
            "phase_e_exam_configuration_migration_version": (
                readiness_service.PHASE_E_EXAM_CONFIGURATION_MIGRATION_VERSION
            ),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_e_previous_year_mock_contract",
        lambda: {
            "ready": True,
            "real_pyq_provenance": True,
            "correction_audit": True,
            "generated_style_separation": True,
            "timed_sections": True,
            "section_transitions": True,
            "mark_for_review": True,
            "idempotent_attempts": True,
            "section_specific_marking": True,
            "auto_submit": True,
            "rank_cohort": True,
            "topic_and_knowledge_analysis": True,
            "legacy_attempts_mirrored": True,
            "phase_e_previous_year_mock_migration_version": (
                readiness_service.PHASE_E_PREVIOUS_YEAR_MOCK_MIGRATION_VERSION
            ),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_phase_e_question_quality_contract",
        lambda: {
            "ready": True,
            "legacy_report_reasons_retained": True,
            "new_report_reasons": True,
            "independent_report_threshold": True,
            "abuse_resistance": True,
            "authoritative_quarantine": True,
            "append_only_history": True,
            "explicit_supersession": True,
            "protected_admin_queue": True,
            "silent_edit_protection": True,
            "phase_e_question_quality_migration_version": (
                readiness_service.PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION
            ),
            "function_permission_failures": [],
            "table_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_source_optional_generation_contract",
        lambda: {
            "ready": True,
            "migration_version": (
                readiness_service.SOURCE_OPTIONAL_GENERATION_MIGRATION_VERSION
            ),
            "current_affairs_source_required": True,
            "knowledge_cooldown_days": 30,
            "function_permission_failures": [],
        },
    )
    readiness_service._CACHE = None


def test_readiness_requires_exact_leaderboard_privacy_contract(monkeypatch) -> None:
    _configure_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_leaderboard_privacy_contract",
        lambda: {
            "ready": True,
            "leaderboard_privacy_migration_version": (readiness_service.LEADERBOARD_PRIVACY_MIGRATION_VERSION),
            "leaderboard_privacy_rpc_fix_migration_version": (
                readiness_service.LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION
            ),
            "leaderboard_privacy_migration_applied": True,
            "identity_projection_ready": True,
            "missing_functions": [],
            "unsafe_function_definitions": [],
            "function_configuration_failures": [],
            "function_permission_failures": [],
        },
    )

    result = readiness_service.assess(use_cache=False)

    assert result.ready is True
    assert result.checks["leaderboardPrivacy"] is True
    assert result.public_payload()["leaderboardPrivacyMigrationVersion"] == (
        readiness_service.LEADERBOARD_PRIVACY_MIGRATION_VERSION
    )
    assert (
        result.public_payload()["leaderboardPrivacyRpcFixMigrationVersion"]
        == readiness_service.LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION
    )


def test_readiness_fails_closed_when_primary_scheduler_needs_renewal(monkeypatch) -> None:
    _configure_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_primary_scheduler_contract",
        lambda: {
            "ready": False,
            "migration_version": readiness_service.PRIMARY_SCHEDULER_MIGRATION_VERSION,
            "pg_cron_ready": True,
            "pg_net_ready": True,
            "credential_present": True,
            "credential_outside_renewal_window": False,
            "dispatch_job_ready": True,
            "completeness_job_ready": True,
            "reconcile_job_ready": True,
        },
    )

    result = readiness_service.assess(use_cache=False)

    assert result.ready is False
    assert result.checks["primaryScheduler"] is False
    assert "primary_scheduler" in result.categories


def test_readiness_fails_closed_for_unsafe_leaderboard_functions(monkeypatch) -> None:
    _configure_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_leaderboard_privacy_contract",
        lambda: {
            "ready": False,
            "leaderboard_privacy_migration_version": "old",
            "leaderboard_privacy_migration_applied": False,
            "identity_projection_ready": False,
            "missing_functions": [],
            "unsafe_function_definitions": ["unsafe_rpc"],
            "function_configuration_failures": [],
            "function_permission_failures": [],
        },
    )

    result = readiness_service.assess(use_cache=False)

    assert result.ready is False
    assert result.checks["supabaseConnectivity"] is True
    assert result.checks["leaderboardPrivacy"] is False
    assert "leaderboard_privacy" in result.categories


def test_readiness_fails_closed_when_platform_contract_is_missing(monkeypatch) -> None:
    _configure_ready_dependencies(monkeypatch)
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_platform_contract",
        lambda: {
            "ready": False,
            "contract_key": "telegram_quiz_platform",
            "contract_version": "1.0.0",
            "required_migration_version": "20260822190025",
            "migration_applied": False,
            "checks": {},
        },
    )

    result = readiness_service.assess(use_cache=False)

    assert result.ready is False
    assert result.checks["platformContract"] is False
    assert "platform_contract" in result.categories
