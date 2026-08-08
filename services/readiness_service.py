"""Fail-closed, sanitized readiness assessment for Render and operators."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from config.settings import (
    EXPECTED_SUPABASE_PROJECT_REF,
    GEMINI_FAILOVER_ENABLED,
    MINIAPP_SHORT_NAME,
    PRODUCTION_CONFIG_HASH,
    PRODUCTION_CONFIG_VERSION,
    QUESTION_VERIFICATION_MIN_CONFIDENCE,
    SOURCE_BACKED_ROTATION_ENABLED,
    SUPABASE_SERVICE_KEY,
    SUPABASE_URL,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_BOT_USERNAME,
    TELEGRAM_CHAT_ID,
    TELEGRAM_FORUM_TOPICS_JSON,
    TELEGRAM_GENERAL_THREAD_ID,
    gemini_provider_configuration,
    supabase_project_ref_matches,
)
from database.contract import (
    APPLICATION_VERSION,
    DATABASE_CONTRACT_KEY,
    DATABASE_CONTRACT_VERSION,
    LEADERBOARD_PRIVACY_MIGRATION_VERSION,
    LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION,
    PERSONAL_LEARNING_MIGRATION_VERSION,
    PHASE_C_CANDIDATE_MIGRATION_VERSION,
    PHASE_C_IDENTITY_MIGRATION_VERSION,
    PHASE_C_INVENTORY_MIGRATION_VERSION,
    PHASE_D_CURRENT_AFFAIRS_MIGRATION_VERSION,
    PHASE_E_EXAM_CONFIGURATION_MIGRATION_VERSION,
    PHASE_E_PERSONAL_LEARNING_MIGRATION_VERSION,
    PHASE_E_PREVIOUS_YEAR_MOCK_MIGRATION_VERSION,
    PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION,
    POST_FINALIZATION_MIGRATION_VERSION,
    QUIZ_JOBS_MIGRATION_VERSION,
    QUIZ_QUALITY_MIGRATION_VERSION,
    REQUIRED_MIGRATION_VERSION,
    SOURCE_OPTIONAL_GENERATION_MIGRATION_VERSION,
    SOURCE_ROLLOUT_MIGRATION_VERSION,
)
from storage import schema_contract_repo
from telegram.routing import ForumRouter, ForumRoutingError

LOG = logging.getLogger("services.readiness")
_CACHE: tuple[float, "Readiness"] | None = None


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    checks: dict[str, bool]
    categories: tuple[str, ...]
    provider_category: str

    def public_payload(self) -> dict:
        return {
            "ok": self.ready,
            "status": "ready" if self.ready else "not_ready",
            "checks": self.checks,
            "failureCategories": list(self.categories),
            "aiProviderCategory": self.provider_category,
            "applicationVersion": APPLICATION_VERSION,
            "requiredMigrationVersion": REQUIRED_MIGRATION_VERSION,
            "sourceRolloutMigrationVersion": SOURCE_ROLLOUT_MIGRATION_VERSION,
            "quizQualityMigrationVersion": QUIZ_QUALITY_MIGRATION_VERSION,
            "personalLearningMigrationVersion": (PERSONAL_LEARNING_MIGRATION_VERSION),
            "leaderboardPrivacyMigrationVersion": (LEADERBOARD_PRIVACY_MIGRATION_VERSION),
            "leaderboardPrivacyRpcFixMigrationVersion": (LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION),
            "sourceBackedRotationEnabled": SOURCE_BACKED_ROTATION_ENABLED,
            "databaseContractVersion": DATABASE_CONTRACT_VERSION,
            "postFinalizationMigrationVersion": POST_FINALIZATION_MIGRATION_VERSION,
            "quizJobsMigrationVersion": QUIZ_JOBS_MIGRATION_VERSION,
            "phaseCIdentityMigrationVersion": PHASE_C_IDENTITY_MIGRATION_VERSION,
            "phaseCInventoryMigrationVersion": PHASE_C_INVENTORY_MIGRATION_VERSION,
            "phaseCCandidateMigrationVersion": PHASE_C_CANDIDATE_MIGRATION_VERSION,
            "phaseDCurrentAffairsMigrationVersion": (PHASE_D_CURRENT_AFFAIRS_MIGRATION_VERSION),
            "phaseEPersonalLearningMigrationVersion": (PHASE_E_PERSONAL_LEARNING_MIGRATION_VERSION),
            "phaseEExamConfigurationMigrationVersion": (PHASE_E_EXAM_CONFIGURATION_MIGRATION_VERSION),
            "phaseEPreviousYearMockMigrationVersion": (PHASE_E_PREVIOUS_YEAR_MOCK_MIGRATION_VERSION),
            "phaseEQuestionQualityMigrationVersion": (PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION),
            "sourceOptionalGenerationMigrationVersion": (SOURCE_OPTIONAL_GENERATION_MIGRATION_VERSION),
            "productionConfigVersion": PRODUCTION_CONFIG_VERSION,
            "productionConfigHash": PRODUCTION_CONFIG_HASH,
        }


def assess(*, use_cache: bool = True) -> Readiness:
    global _CACHE
    now = time.monotonic()
    if use_cache and _CACHE and now - _CACHE[0] < 15:
        return _CACHE[1]

    checks = {
        "criticalEnvironment": False,
        "environmentOwnership": False,
        "telegramConfiguration": False,
        "aiConfiguration": False,
        "supabaseConnectivity": False,
        "databaseContract": False,
        "databasePermissions": False,
        "leaderboardPrivacy": False,
        "postFinalization": False,
        "durableQuizJobs": False,
        "contentIdentity": False,
        "verifiedInventory": False,
        "currentAffairsEvents": False,
        "personalKnowledgeMastery": False,
        "examConfiguration": False,
        "previousYearMocks": False,
        "questionQualityAdministration": False,
        "sourceOptionalGeneration": False,
        "activeQuizRetrieval": False,
    }
    failures: list[str] = []

    primary, secondary = gemini_provider_configuration()
    provider_category = (
        "primary_and_secondary"
        if primary and secondary
        else "primary_only"
        if primary
        else "secondary_only"
        if secondary
        else "unavailable"
    )

    checks["criticalEnvironment"] = bool(
        SUPABASE_URL
        and SUPABASE_SERVICE_KEY
        and EXPECTED_SUPABASE_PROJECT_REF
        and TELEGRAM_BOT_TOKEN
        and TELEGRAM_CHAT_ID
        and TELEGRAM_BOT_USERNAME
        and MINIAPP_SHORT_NAME
    )
    if not checks["criticalEnvironment"]:
        failures.append("configuration")

    checks["environmentOwnership"] = bool(EXPECTED_SUPABASE_PROJECT_REF and supabase_project_ref_matches())
    if not checks["environmentOwnership"]:
        failures.append("environment_ownership")

    try:
        ForumRouter.from_values(TELEGRAM_FORUM_TOPICS_JSON, TELEGRAM_GENERAL_THREAD_ID)
        checks["telegramConfiguration"] = bool(TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID)
    except ForumRoutingError:
        checks["telegramConfiguration"] = False
    if not checks["telegramConfiguration"]:
        failures.append("telegram_configuration")

    checks["aiConfiguration"] = primary or (secondary and GEMINI_FAILOVER_ENABLED)
    if not checks["aiConfiguration"]:
        failures.append("ai_configuration")

    if checks["environmentOwnership"] and SUPABASE_URL and SUPABASE_SERVICE_KEY:
        try:
            contract = schema_contract_repo.get_contract()
            checks["supabaseConnectivity"] = True
            try:
                privacy_contract = schema_contract_repo.get_leaderboard_privacy_contract()
            except Exception as exc:
                privacy_contract = {}
                LOG.warning(
                    "READINESS_LEADERBOARD_PRIVACY_FAILURE category=%s",
                    type(exc).__name__,
                )
            try:
                post_contract = schema_contract_repo.get_post_finalization_contract()
            except Exception as exc:
                post_contract = {}
                LOG.warning(
                    "READINESS_POST_FINALIZATION_FAILURE category=%s",
                    type(exc).__name__,
                )
            try:
                job_contract = schema_contract_repo.get_quiz_job_contract()
            except Exception as exc:
                job_contract = {}
                LOG.warning(
                    "READINESS_QUIZ_JOBS_FAILURE category=%s",
                    type(exc).__name__,
                )
            try:
                phase_c_content = schema_contract_repo.get_phase_c_content_contract()
                phase_c_inventory = schema_contract_repo.get_phase_c_inventory_contract()
                phase_c_candidate = schema_contract_repo.get_phase_c_candidate_contract()
                phase_d_current_affairs = schema_contract_repo.get_phase_d_current_affairs_contract()
                phase_e_personal_learning = schema_contract_repo.get_phase_e_personal_learning_contract()
                phase_e_exam_configuration = schema_contract_repo.get_phase_e_exam_configuration_contract()
                phase_e_previous_year_mock = schema_contract_repo.get_phase_e_previous_year_mock_contract()
                phase_e_question_quality = schema_contract_repo.get_phase_e_question_quality_contract()
                source_optional_generation = schema_contract_repo.get_source_optional_generation_contract()
            except Exception as exc:
                phase_c_content = {}
                phase_c_inventory = {}
                phase_c_candidate = {}
                phase_d_current_affairs = {}
                phase_e_personal_learning = {}
                phase_e_exam_configuration = {}
                phase_e_previous_year_mock = {}
                phase_e_question_quality = {}
                source_optional_generation = {}
                LOG.warning(
                    "READINESS_PHASE_C_FAILURE category=%s",
                    type(exc).__name__,
                )
            permission_failures = (
                (contract.get("function_permission_failures") or [])
                + (contract.get("table_permission_failures") or [])
                + (privacy_contract.get("function_permission_failures") or [])
                + (post_contract.get("function_permission_failures") or [])
                + (job_contract.get("function_permission_failures") or [])
                + (phase_c_inventory.get("function_permission_failures") or [])
                + (phase_c_candidate.get("function_permission_failures") or [])
                + (phase_d_current_affairs.get("function_permission_failures") or [])
                + (phase_d_current_affairs.get("table_permission_failures") or [])
                + (phase_e_personal_learning.get("function_permission_failures") or [])
                + (phase_e_personal_learning.get("table_permission_failures") or [])
                + (phase_e_exam_configuration.get("function_permission_failures") or [])
                + (phase_e_exam_configuration.get("table_permission_failures") or [])
                + (phase_e_previous_year_mock.get("function_permission_failures") or [])
                + (phase_e_previous_year_mock.get("table_permission_failures") or [])
                + (phase_e_question_quality.get("function_permission_failures") or [])
                + (phase_e_question_quality.get("table_permission_failures") or [])
                + (source_optional_generation.get("function_permission_failures") or [])
            )
            checks["databasePermissions"] = not permission_failures
            checks["leaderboardPrivacy"] = bool(
                privacy_contract.get("ready") is True
                and privacy_contract.get("leaderboard_privacy_migration_version")
                == LEADERBOARD_PRIVACY_MIGRATION_VERSION
                and privacy_contract.get("leaderboard_privacy_rpc_fix_migration_version")
                == LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION
                and privacy_contract.get("leaderboard_privacy_migration_applied") is True
                and privacy_contract.get("identity_projection_ready") is True
                and not privacy_contract.get("missing_functions")
                and not privacy_contract.get("unsafe_function_definitions")
                and not privacy_contract.get("function_configuration_failures")
                and not privacy_contract.get("function_permission_failures")
            )
            checks["postFinalization"] = bool(
                post_contract.get("ready") is True
                and post_contract.get("post_finalization_migration_version") == POST_FINALIZATION_MIGRATION_VERSION
                and post_contract.get("post_finalization_migration_applied") is True
                and not post_contract.get("missing_columns")
                and not post_contract.get("function_permission_failures")
            )
            checks["durableQuizJobs"] = bool(
                job_contract.get("ready") is True
                and job_contract.get("quiz_job_migration_version") == QUIZ_JOBS_MIGRATION_VERSION
                and job_contract.get("quiz_job_migration_applied") is True
                and not job_contract.get("function_permission_failures")
            )
            checks["contentIdentity"] = bool(
                phase_c_content.get("ready") is True
                and phase_c_content.get("knowledge_points") is True
                and phase_c_content.get("atomic_source_facts") is True
                and phase_c_content.get("question_variants") is True
                and phase_c_content.get("append_only_verification") is True
                and phase_c_content.get("append_only_usage") is True
            )
            checks["verifiedInventory"] = bool(
                phase_c_inventory.get("ready") is True
                and phase_c_inventory.get("phase_c_inventory_migration_version") == PHASE_C_INVENTORY_MIGRATION_VERSION
                and phase_c_candidate.get("ready") is True
                and phase_c_candidate.get("stable_identity_parity") is True
                and phase_c_candidate.get("phase_c_candidate_migration_version") == PHASE_C_CANDIDATE_MIGRATION_VERSION
            )
            checks["currentAffairsEvents"] = bool(
                phase_d_current_affairs.get("ready") is True
                and phase_d_current_affairs.get("event_dates") is True
                and phase_d_current_affairs.get("atomic_claims") is True
                and phase_d_current_affairs.get("multi_source_clusters") is True
                and phase_d_current_affairs.get("correction_and_expiry") is True
                and phase_d_current_affairs.get("weighted_revision_pools") is True
                and phase_d_current_affairs.get("phase_d_current_affairs_migration_version")
                == PHASE_D_CURRENT_AFFAIRS_MIGRATION_VERSION
            )
            checks["personalKnowledgeMastery"] = bool(
                phase_e_personal_learning.get("ready") is True
                and phase_e_personal_learning.get("knowledge_point_state") is True
                and phase_e_personal_learning.get("variant_history") is True
                and phase_e_personal_learning.get("different_variant_selection") is True
                and phase_e_personal_learning.get("daily_rollups") is True
                and phase_e_personal_learning.get("transparent_recommendations") is True
                and phase_e_personal_learning.get("cohort_definition") is True
                and phase_e_personal_learning.get("phase_e_personal_learning_migration_version")
                == PHASE_E_PERSONAL_LEARNING_MIGRATION_VERSION
            )
            checks["examConfiguration"] = bool(
                phase_e_exam_configuration.get("ready") is True
                and phase_e_exam_configuration.get("versioned_exam_hierarchy") is True
                and phase_e_exam_configuration.get("effective_dating") is True
                and phase_e_exam_configuration.get("syllabus_weights") is True
                and phase_e_exam_configuration.get("shared_test_instances") is True
                and phase_e_exam_configuration.get("daily_quick_definition") is True
                and phase_e_exam_configuration.get("historical_ids_preserved") is True
                and phase_e_exam_configuration.get("attempt_links_backfilled") is True
                and phase_e_exam_configuration.get("phase_e_exam_configuration_migration_version")
                == PHASE_E_EXAM_CONFIGURATION_MIGRATION_VERSION
            )
            checks["previousYearMocks"] = bool(
                phase_e_previous_year_mock.get("ready") is True
                and phase_e_previous_year_mock.get("real_pyq_provenance") is True
                and phase_e_previous_year_mock.get("correction_audit") is True
                and phase_e_previous_year_mock.get("generated_style_separation") is True
                and phase_e_previous_year_mock.get("timed_sections") is True
                and phase_e_previous_year_mock.get("section_transitions") is True
                and phase_e_previous_year_mock.get("mark_for_review") is True
                and phase_e_previous_year_mock.get("idempotent_attempts") is True
                and phase_e_previous_year_mock.get("section_specific_marking") is True
                and phase_e_previous_year_mock.get("auto_submit") is True
                and phase_e_previous_year_mock.get("rank_cohort") is True
                and phase_e_previous_year_mock.get("topic_and_knowledge_analysis") is True
                and phase_e_previous_year_mock.get("legacy_attempts_mirrored") is True
                and phase_e_previous_year_mock.get("phase_e_previous_year_mock_migration_version")
                == PHASE_E_PREVIOUS_YEAR_MOCK_MIGRATION_VERSION
            )
            checks["questionQualityAdministration"] = bool(
                phase_e_question_quality.get("ready") is True
                and phase_e_question_quality.get("legacy_report_reasons_retained") is True
                and phase_e_question_quality.get("new_report_reasons") is True
                and phase_e_question_quality.get("independent_report_threshold") is True
                and phase_e_question_quality.get("abuse_resistance") is True
                and phase_e_question_quality.get("authoritative_quarantine") is True
                and phase_e_question_quality.get("append_only_history") is True
                and phase_e_question_quality.get("explicit_supersession") is True
                and phase_e_question_quality.get("protected_admin_queue") is True
                and phase_e_question_quality.get("silent_edit_protection") is True
                and phase_e_question_quality.get("phase_e_question_quality_migration_version")
                == PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION
            )
            checks["sourceOptionalGeneration"] = bool(
                source_optional_generation.get("ready") is True
                and source_optional_generation.get("migration_version")
                == SOURCE_OPTIONAL_GENERATION_MIGRATION_VERSION
                and source_optional_generation.get("current_affairs_source_required") is True
                and source_optional_generation.get("knowledge_cooldown_days") == 30
                and not source_optional_generation.get("function_permission_failures")
            )
            source_rollout_ready = bool(
                contract.get("source_rollout_migration_version") == SOURCE_ROLLOUT_MIGRATION_VERSION
                and contract.get("source_rollout_migration_applied") is True
                and contract.get("source_backed_rotation_ready") is True
                and contract.get("source_coverage_ready") is True
            )
            quiz_quality_ready = bool(
                contract.get("quiz_quality_migration_version") == QUIZ_QUALITY_MIGRATION_VERSION
                and contract.get("quiz_quality_migration_applied") is True
                and contract.get("diverse_grounding_ready") is True
                and contract.get("negative_marking_ready") is True
            )
            personal_learning_ready = bool(
                contract.get("personal_learning_migration_version") == PERSONAL_LEARNING_MIGRATION_VERSION
                and contract.get("personal_learning_migration_applied") is True
                and contract.get("personal_learning_projection_ready") is True
            )
            checks["databaseContract"] = bool(
                contract.get("ready")
                and contract.get("contract_key") == DATABASE_CONTRACT_KEY
                and contract.get("contract_version") == DATABASE_CONTRACT_VERSION
                and contract.get("required_migration_version") == REQUIRED_MIGRATION_VERSION
                and (not SOURCE_BACKED_ROTATION_ENABLED or (source_rollout_ready and quiz_quality_ready))
                and personal_learning_ready
                and checks["postFinalization"]
                and checks["durableQuizJobs"]
                and checks["contentIdentity"]
                and checks["verifiedInventory"]
                and checks["currentAffairsEvents"]
                and checks["personalKnowledgeMastery"]
                and checks["examConfiguration"]
                and checks["previousYearMocks"]
                and checks["questionQualityAdministration"]
                and checks["sourceOptionalGeneration"]
                and float(contract.get("verification_threshold") or 0) == QUESTION_VERIFICATION_MIN_CONFIDENCE
            )
            active = schema_contract_repo.active_quiz_probe()
            checks["activeQuizRetrieval"] = bool(
                active
                and active.get("question_count") == 10
                and active.get("integrity_verified")
                and int(active.get("checksum_contract_version") or 0) == 2
                and active.get("generated_checksum") == active.get("persisted_checksum")
            )
        except Exception as exc:
            LOG.warning(
                "READINESS_DATABASE_FAILURE category=%s",
                type(exc).__name__,
            )
    if not checks["supabaseConnectivity"]:
        failures.append("database_connectivity")
    elif not checks["databaseContract"]:
        failures.append("database_contract")
    if not checks["leaderboardPrivacy"]:
        failures.append("leaderboard_privacy")
    if not checks["postFinalization"]:
        failures.append("post_finalization")
    if not checks["durableQuizJobs"]:
        failures.append("durable_quiz_jobs")
    if not checks["contentIdentity"]:
        failures.append("content_identity")
    if not checks["verifiedInventory"]:
        failures.append("verified_inventory")
    if not checks["currentAffairsEvents"]:
        failures.append("current_affairs_events")
    if not checks["personalKnowledgeMastery"]:
        failures.append("personal_knowledge_mastery")
    if not checks["examConfiguration"]:
        failures.append("exam_configuration")
    if not checks["previousYearMocks"]:
        failures.append("previous_year_mocks")
    if not checks["questionQualityAdministration"]:
        failures.append("question_quality_administration")
    if not checks["sourceOptionalGeneration"]:
        failures.append("source_optional_generation")
    if not checks["databasePermissions"]:
        failures.append("database_permissions")
    if not checks["activeQuizRetrieval"]:
        failures.append("active_quiz_retrieval")

    result = Readiness(
        ready=all(checks.values()),
        checks=checks,
        categories=tuple(dict.fromkeys(failures)),
        provider_category=provider_category,
    )
    _CACHE = (now, result)
    return result
