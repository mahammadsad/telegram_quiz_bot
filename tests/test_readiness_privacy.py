from __future__ import annotations

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
            "required_migration_version": (
                readiness_service.REQUIRED_MIGRATION_VERSION
            ),
            "personal_learning_migration_version": (
                readiness_service.PERSONAL_LEARNING_MIGRATION_VERSION
            ),
            "personal_learning_migration_applied": True,
            "personal_learning_projection_ready": True,
            "verification_threshold": (
                readiness_service.QUESTION_VERIFICATION_MIN_CONFIDENCE
            ),
            "function_permission_failures": [],
            "table_permission_failures": [],
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
        "get_post_finalization_contract",
        lambda: {
            "ready": True,
            "post_finalization_migration_version": (
                readiness_service.POST_FINALIZATION_MIGRATION_VERSION
            ),
            "post_finalization_migration_applied": True,
            "missing_columns": [],
            "function_permission_failures": [],
        },
    )
    monkeypatch.setattr(
        readiness_service.schema_contract_repo,
        "get_quiz_job_contract",
        lambda: {
            "ready": True,
            "quiz_job_migration_version": (
                readiness_service.QUIZ_JOBS_MIGRATION_VERSION
            ),
            "quiz_job_migration_applied": True,
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
            "leaderboard_privacy_migration_version": (
                readiness_service.LEADERBOARD_PRIVACY_MIGRATION_VERSION
            ),
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
    assert result.public_payload()[
        "leaderboardPrivacyRpcFixMigrationVersion"
    ] == readiness_service.LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION


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
