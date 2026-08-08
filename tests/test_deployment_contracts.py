from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from config.schedule import COMPLETENESS_CRON, DISPATCHER_CRON
from config.settings import (
    PRODUCTION_CONFIG,
    PRODUCTION_CONFIG_HASH,
    PRODUCTION_CONFIG_VERSION,
)
from database.contract import (
    APPLICATION_VERSION,
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
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PRODUCTION_PROJECT_REF = "tizxodkcpglmxgtwepor"
STAGING_PROJECT_REF = "prdrabmcivgbygzjnmko"
PRODUCTION_SUPABASE_URL = f"https://{PRODUCTION_PROJECT_REF}.supabase.co"
STAGING_SUPABASE_URL = f"https://{STAGING_PROJECT_REF}.supabase.co"


def _load_yaml(path: Path) -> dict:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)
    return payload


def test_render_blueprint_is_fail_closed_and_uses_readiness() -> None:
    blueprint = _load_yaml(ROOT / "render.yaml")
    services = blueprint.get("services")
    assert isinstance(services, list) and len(services) == 1
    service = services[0]

    assert service["runtime"] == "python"
    assert service["plan"] == "free"
    assert service["healthCheckPath"] == "/health/ready"
    assert service["autoDeployTrigger"] == "checksPass"
    assert "$PORT" in service["startCommand"]

    env = {item["key"]: item for item in service["envVars"]}
    assert env["EXPECTED_SUPABASE_PROJECT_REF"]["value"] == PRODUCTION_PROJECT_REF
    assert env["SOURCE_BACKED_ROTATION_ENABLED"]["value"] == "true"
    assert env["CURRENT_AFFAIRS_SOURCE_MAX_AGE_DAYS"]["value"] == "45"
    for secret_name in (
        "SUPABASE_URL",
        "SUPABASE_SERVICE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "GEMINI_API_KEY_PRIMARY",
        "GEMINI_API_KEY_SECONDARY",
    ):
        assert env[secret_name] == {"key": secret_name, "sync": False}


def test_every_github_action_is_pinned_to_a_commit() -> None:
    action_lines: list[tuple[Path, str]] = []
    for workflow in WORKFLOW_DIR.glob("*.yml"):
        for line in workflow.read_text(encoding="utf-8").splitlines():
            if "uses:" in line:
                action_lines.append((workflow, line))

    assert action_lines
    commit_ref = re.compile(r"uses:\s*[^\s]+@([0-9a-f]{40})(?:\s|$)")
    for workflow, line in action_lines:
        assert commit_ref.search(line), f"unpinned action in {workflow.name}: {line.strip()}"


def test_workflows_have_minimum_permissions_timeouts_and_environment_guards() -> None:
    ci = _load_yaml(WORKFLOW_DIR / "ci.yml")
    main = _load_yaml(WORKFLOW_DIR / "main.yml")
    resources = _load_yaml(WORKFLOW_DIR / "resource-quality.yml")

    assert ci["permissions"] == {"contents": "read"}
    assert ci["jobs"]["quality-and-tests"]["timeout-minutes"] == 20
    quality_checkout = ci["jobs"]["quality-and-tests"]["steps"][0]
    assert quality_checkout["with"]["fetch-depth"] == 0

    assert main["permissions"] == {"contents": "read"}
    assert main["jobs"]["resolve_job"]["timeout-minutes"] == 5
    run_bot = main["jobs"]["run-bot"]
    assert run_bot["permissions"] == {"contents": "write"}
    assert run_bot["timeout-minutes"] == 45
    assert run_bot["environment"] == "production"
    assert run_bot["concurrency"]["cancel-in-progress"] is False
    main_trigger = main.get("on") or main.get(True)
    assert main_trigger["schedule"] == [
        {"cron": DISPATCHER_CRON},
        {"cron": COMPLETENESS_CRON},
    ]
    bot_preflight = next(step for step in run_bot["steps"] if step.get("name") == "Sanitized configuration preflight")
    assert bot_preflight["env"]["SUPABASE_URL"] == PRODUCTION_SUPABASE_URL
    main_source = (WORKFLOW_DIR / "main.yml").read_text(encoding="utf-8")
    assert 'SOURCE_BACKED_ROTATION_ENABLED: "true"' in main_source

    assert resources["permissions"] == {"contents": "read"}
    maintenance = resources["jobs"]["maintain-resources"]
    assert maintenance["timeout-minutes"] == 20
    assert maintenance["environment"] == "production"
    assert maintenance["env"]["EXPECTED_SUPABASE_PROJECT_REF"] == PRODUCTION_PROJECT_REF
    assert maintenance["env"]["SUPABASE_URL"] == PRODUCTION_SUPABASE_URL
    assert resources["concurrency"]["cancel-in-progress"] is False


def test_staging_workflow_is_manual_minimal_and_fail_closed() -> None:
    path = WORKFLOW_DIR / "staging-smoke.yml"
    staging = _load_yaml(path)
    workflow_trigger = staging.get("on") or staging.get(True)
    assert workflow_trigger == {"workflow_dispatch": workflow_trigger["workflow_dispatch"]}
    inputs = workflow_trigger["workflow_dispatch"]["inputs"]
    assert inputs["operation"]["options"] == ["preflight", "subject-quiz"]
    assert inputs["subject"]["default"] == "computer"
    assert inputs["subject"]["options"][0] == "computer"
    assert inputs["force_post"]["default"] is False
    assert inputs["force_regenerate"]["default"] is False

    assert staging["permissions"] == {"contents": "read"}
    assert staging["concurrency"]["cancel-in-progress"] is False
    job = staging["jobs"]["staging-smoke"]
    assert job["environment"] == "staging"
    assert job["timeout-minutes"] == 45
    assert job["env"]["EXPECTED_SUPABASE_PROJECT_REF"] == STAGING_PROJECT_REF
    assert job["env"]["DEV_ALLOW_UNVERIFIED_TELEGRAM"] == "false"
    assert job["env"]["WRITE_STATIC_QUIZ_JSON"] == "false"
    assert job["env"]["APP_TIMEZONE"] == "Asia/Kolkata"
    assert job["env"]["SOURCE_BACKED_ROTATION_ENABLED"] == "true"
    assert job["env"]["SUPABASE_URL"] == STAGING_SUPABASE_URL

    source = path.read_text(encoding="utf-8")
    assert PRODUCTION_PROJECT_REF not in source
    assert STAGING_SUPABASE_URL in source
    assert "secrets.SUPABASE_URL" not in source
    assert 'expected_host = f"{expected_ref}.supabase.co"' in source
    assert "ALLOW FORCE ON STAGING {expected_ref}" in source
    assert "recover-missed-quizzes" not in source
    assert "export-static-fallbacks" not in source
    assert "announce" not in source
    assert "git push" not in source
    assert "except HTTPError as exc" in source
    assert 'failures != ["active_quiz_retrieval"]' in source
    assert "Staging readiness must be HTTP 200 after quiz creation." in source
    assert "from database.contract import (" in source
    assert 'body.get("applicationVersion") != APPLICATION_VERSION' in source
    assert 'body.get("databaseContractVersion") != DATABASE_CONTRACT_VERSION' in source
    assert 'body.get("personalLearningMigrationVersion")' in source
    assert 'body.get("leaderboardPrivacyMigrationVersion")' in source
    assert 'body.get("leaderboardPrivacyRpcFixMigrationVersion")' in source
    assert 'body.get("postFinalizationMigrationVersion")' in source
    assert 'body.get("checks", {}).get("postFinalization") is not True' in source
    assert 'body.get("quizJobsMigrationVersion")' in source
    assert 'body.get("checks", {}).get("durableQuizJobs") is not True' in source
    assert 'body.get("phaseCIdentityMigrationVersion")' in source
    assert 'body.get("phaseCInventoryMigrationVersion")' in source
    assert 'body.get("phaseCCandidateMigrationVersion")' in source
    assert 'body.get("phaseDCurrentAffairsMigrationVersion")' in source
    assert 'body.get("phaseEPersonalLearningMigrationVersion")' in source
    assert 'body.get("phaseEExamConfigurationMigrationVersion")' in source
    assert 'body.get("phaseEPreviousYearMockMigrationVersion")' in source
    assert 'body.get("phaseEQuestionQualityMigrationVersion")' in source
    assert 'body.get("checks", {}).get("contentIdentity") is not True' in source
    assert 'body.get("checks", {}).get("verifiedInventory") is not True' in source
    assert 'body.get("checks", {}).get("currentAffairsEvents") is not True' in source
    assert 'body.get("checks", {}).get("personalKnowledgeMastery") is not True' in source
    assert 'body.get("checks", {}).get("examConfiguration") is not True' in source
    assert 'body.get("checks", {}).get("previousYearMocks") is not True' in source
    assert 'body.get("checks", {}).get("questionQualityAdministration")' in source
    assert '"7.1.0"' not in source


def test_staging_workflow_uses_only_staging_secret_expressions() -> None:
    staging = _load_yaml(WORKFLOW_DIR / "staging-smoke.yml")
    env = staging["jobs"]["staging-smoke"]["env"]
    assert env["SUPABASE_URL"] == STAGING_SUPABASE_URL
    for name in (
        "SUPABASE_SERVICE_KEY",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
        "TELEGRAM_FORUM_TOPICS_JSON",
        "TELEGRAM_GENERAL_THREAD_ID",
        "GEMINI_API_KEY_PRIMARY",
        "GEMINI_API_KEY_SECONDARY",
    ):
        assert env[name] == f"${{{{ secrets.{name} }}}}"


def test_source_rollout_workflows_are_guarded_and_do_not_touch_telegram() -> None:
    static_path = WORKFLOW_DIR / "source-rollout.yml"
    static = _load_yaml(static_path)
    static_trigger = static.get("on") or static.get(True)
    assert set(static_trigger) == {"workflow_dispatch"}
    static_inputs = static_trigger["workflow_dispatch"]["inputs"]
    assert static_inputs["target"]["options"] == ["staging", "production"]
    assert static_inputs["target"]["default"] == "staging"
    assert static_inputs["operation"]["options"] == ["validate", "import"]
    assert static["permissions"] == {"contents": "read"}
    assert static["concurrency"]["cancel-in-progress"] is False

    current_path = WORKFLOW_DIR / "current-affairs-sources.yml"
    current = _load_yaml(current_path)
    current_trigger = current.get("on") or current.get(True)
    assert current_trigger["schedule"] == [{"cron": "30 0,12 * * *"}]
    current_inputs = current_trigger["workflow_dispatch"]["inputs"]
    assert current_inputs["target"]["options"] == ["staging", "production"]
    assert current_inputs["operation"]["options"] == ["validate", "refresh"]
    assert current["permissions"] == {"contents": "read"}
    assert current["concurrency"]["cancel-in-progress"] is False

    for path in (static_path, current_path):
        source = path.read_text(encoding="utf-8")
        assert PRODUCTION_PROJECT_REF in source
        assert STAGING_PROJECT_REF in source
        assert PRODUCTION_SUPABASE_URL in source
        assert STAGING_SUPABASE_URL in source
        assert "secrets.SUPABASE_URL" not in source
        assert "TELEGRAM_" not in source
        assert "GEMINI_" not in source
        assert "validate_database_schema" in source
        assert "SUPABASE_SERVICE_KEY" in source

    static_source = static_path.read_text(encoding="utf-8")
    assert static_source.index("validate_database_schema") < (
        static_source.index("scripts/import_source_rollout.py --approve")
    )
    assert "IMPORT REVIEWED SOURCES TO" in static_source

    current_source = current_path.read_text(encoding="utf-8")
    assert current_source.index("validate_database_schema") < (
        current_source.index("--max-items 200 --minimum-per-chapter 4 --approve")
    )
    assert "REFRESH PIB SOURCES IN" in current_source


def test_authoritative_migration_version_is_latest_filename() -> None:
    migrations = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    assert migrations
    assert migrations[-1].name.startswith(f"{PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION}_")
    assert any(path.name.startswith(f"{PHASE_C_IDENTITY_MIGRATION_VERSION}_") for path in migrations)
    assert any(path.name.startswith(f"{POST_FINALIZATION_MIGRATION_VERSION}_") for path in migrations)
    assert any(path.name.startswith(f"{LEADERBOARD_PRIVACY_MIGRATION_VERSION}_") for path in migrations)
    assert any(path.name.startswith(f"{PERSONAL_LEARNING_MIGRATION_VERSION}_") for path in migrations)
    assert any(path.name.startswith(f"{QUIZ_QUALITY_MIGRATION_VERSION}_") for path in migrations)
    assert any(path.name.startswith(f"{REQUIRED_MIGRATION_VERSION}_") for path in migrations)


def test_versioned_production_manifest_matches_deployment_intent() -> None:
    manifest_path = ROOT / "config" / "production.toml"
    assert manifest_path.is_file()
    assert PRODUCTION_CONFIG_VERSION == "2026-08-08.10"
    assert re.fullmatch(r"[0-9a-f]{64}", PRODUCTION_CONFIG_HASH)
    assert PRODUCTION_CONFIG["quiz"]["source_backed_rotation_enabled"] is True
    assert PRODUCTION_CONFIG["gemini"] == {
        "primary_model": "gemini-3.1-flash-lite",
        "fallback_model": "gemini-2.5-flash",
        "failover_enabled": True,
    }
    assert PRODUCTION_CONFIG["verification"] == {
        "deterministic_proof_version": 1,
        "require_new_candidate_proof": True,
    }
    assert PRODUCTION_CONFIG["database"]["post_finalization_migration_version"] == (POST_FINALIZATION_MIGRATION_VERSION)
    assert PRODUCTION_CONFIG["database"]["quiz_jobs_migration_version"] == (QUIZ_JOBS_MIGRATION_VERSION)
    assert (
        PRODUCTION_CONFIG["database"]["leaderboard_privacy_rpc_fix_migration_version"]
        == LEADERBOARD_PRIVACY_RPC_FIX_MIGRATION_VERSION
    )
    assert PRODUCTION_CONFIG["database"]["phase_c_identity_migration_version"] == (PHASE_C_IDENTITY_MIGRATION_VERSION)
    assert PRODUCTION_CONFIG["database"]["phase_c_inventory_migration_version"] == (PHASE_C_INVENTORY_MIGRATION_VERSION)
    assert PRODUCTION_CONFIG["database"]["phase_c_candidate_migration_version"] == (PHASE_C_CANDIDATE_MIGRATION_VERSION)
    assert (
        PRODUCTION_CONFIG["database"]["phase_d_current_affairs_migration_version"]
        == PHASE_D_CURRENT_AFFAIRS_MIGRATION_VERSION
    )
    assert (
        PRODUCTION_CONFIG["database"]["phase_e_personal_learning_migration_version"]
        == PHASE_E_PERSONAL_LEARNING_MIGRATION_VERSION
    )
    assert (
        PRODUCTION_CONFIG["database"]["phase_e_exam_configuration_migration_version"]
        == PHASE_E_EXAM_CONFIGURATION_MIGRATION_VERSION
    )
    assert (
        PRODUCTION_CONFIG["database"]["phase_e_previous_year_mock_migration_version"]
        == PHASE_E_PREVIOUS_YEAR_MOCK_MIGRATION_VERSION
    )
    assert (
        PRODUCTION_CONFIG["database"]["phase_e_question_quality_migration_version"]
        == PHASE_E_QUESTION_QUALITY_MIGRATION_VERSION
    )

    render = _load_yaml(ROOT / "render.yaml")
    render_env = {row["key"]: row.get("value") for row in render["services"][0]["envVars"] if "value" in row}
    assert render_env["GEMINI_MODEL_PRIMARY"] == PRODUCTION_CONFIG["gemini"]["primary_model"]
    assert render_env["GEMINI_MODEL_FALLBACK"] == PRODUCTION_CONFIG["gemini"]["fallback_model"]
    assert render_env["QUESTION_VERIFICATION_MIN_CONFIDENCE"] == str(
        PRODUCTION_CONFIG["quiz"]["verification_min_confidence"]
    )


def test_python_and_browser_packages_share_the_release_version() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert APPLICATION_VERSION == "8.4.0"
    assert package["version"] == APPLICATION_VERSION
    assert lock["version"] == APPLICATION_VERSION
    assert lock["packages"][""]["version"] == APPLICATION_VERSION


def test_disposable_database_builder_can_run_as_a_direct_script() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/apply_test_database.py", "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "Disposable PostgreSQL connection URL" in result.stdout
