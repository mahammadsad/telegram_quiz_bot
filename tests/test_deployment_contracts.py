from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

from database.contract import (
    APPLICATION_VERSION,
    REQUIRED_MIGRATION_VERSION,
    SOURCE_ROLLOUT_MIGRATION_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PRODUCTION_PROJECT_REF = "tizxodkcpglmxgtwepor"
STAGING_PROJECT_REF = "prdrabmcivgbygzjnmko"


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
    assert env["SOURCE_BACKED_ROTATION_ENABLED"]["value"] == "false"
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
    main_source = (WORKFLOW_DIR / "main.yml").read_text(encoding="utf-8")
    assert (
        "SOURCE_BACKED_ROTATION_ENABLED: "
        "${{ vars.SOURCE_BACKED_ROTATION_ENABLED || 'false' }}"
    ) in main_source

    assert resources["permissions"] == {"contents": "read"}
    maintenance = resources["jobs"]["maintain-resources"]
    assert maintenance["timeout-minutes"] == 20
    assert maintenance["environment"] == "production"
    assert maintenance["env"]["EXPECTED_SUPABASE_PROJECT_REF"] == PRODUCTION_PROJECT_REF
    assert resources["concurrency"]["cancel-in-progress"] is False


def test_staging_workflow_is_manual_minimal_and_fail_closed() -> None:
    path = WORKFLOW_DIR / "staging-smoke.yml"
    staging = _load_yaml(path)
    workflow_trigger = staging.get("on") or staging.get(True)
    assert workflow_trigger == {
        "workflow_dispatch": workflow_trigger["workflow_dispatch"]
    }
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

    source = path.read_text(encoding="utf-8")
    assert PRODUCTION_PROJECT_REF not in source
    assert f"{STAGING_PROJECT_REF}.supabase.co" not in source
    assert 'expected_host = f"{expected_ref}.supabase.co"' in source
    assert "ALLOW FORCE ON STAGING {expected_ref}" in source
    assert "recover-missed-quizzes" not in source
    assert "export-static-fallbacks" not in source
    assert "announce" not in source
    assert "git push" not in source
    assert "except HTTPError as exc" in source
    assert 'failures != ["active_quiz_retrieval"]' in source
    assert "Staging readiness must be HTTP 200 after quiz creation." in source


def test_staging_workflow_uses_only_staging_secret_expressions() -> None:
    staging = _load_yaml(WORKFLOW_DIR / "staging-smoke.yml")
    env = staging["jobs"]["staging-smoke"]["env"]
    for name in (
        "SUPABASE_URL",
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
        assert "TELEGRAM_" not in source
        assert "GEMINI_" not in source
        assert "get_application_schema_contract" in source
        assert "SUPABASE_SERVICE_KEY" in source

    static_source = static_path.read_text(encoding="utf-8")
    assert static_source.index("get_application_schema_contract") < (
        static_source.index("scripts/import_source_rollout.py --approve")
    )
    assert "IMPORT REVIEWED SOURCES TO" in static_source

    current_source = current_path.read_text(encoding="utf-8")
    assert current_source.index("get_application_schema_contract") < (
        current_source.index("--max-items 200 --minimum-per-chapter 4 --approve")
    )
    assert "REFRESH PIB SOURCES IN" in current_source


def test_authoritative_migration_version_is_latest_filename() -> None:
    migrations = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    assert migrations
    assert migrations[-1].name.startswith(f"{SOURCE_ROLLOUT_MIGRATION_VERSION}_")
    assert any(
        path.name.startswith(f"{REQUIRED_MIGRATION_VERSION}_")
        for path in migrations
    )


def test_python_and_browser_packages_share_the_release_version() -> None:
    package = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    lock = json.loads((ROOT / "package-lock.json").read_text(encoding="utf-8"))

    assert APPLICATION_VERSION == "7.1.0"
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
