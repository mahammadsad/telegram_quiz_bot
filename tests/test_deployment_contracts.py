from __future__ import annotations

import re
from pathlib import Path

import yaml

from database.contract import REQUIRED_MIGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"
PRODUCTION_PROJECT_REF = "tizxodkcpglmxgtwepor"


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

    assert main["permissions"] == {"contents": "read"}
    assert main["jobs"]["resolve_job"]["timeout-minutes"] == 5
    run_bot = main["jobs"]["run-bot"]
    assert run_bot["permissions"] == {"contents": "write"}
    assert run_bot["timeout-minutes"] == 45
    assert run_bot["environment"] == "production"
    assert run_bot["concurrency"]["cancel-in-progress"] is False

    assert resources["permissions"] == {"contents": "read"}
    maintenance = resources["jobs"]["maintain-resources"]
    assert maintenance["timeout-minutes"] == 20
    assert maintenance["environment"] == "production"
    assert maintenance["env"]["EXPECTED_SUPABASE_PROJECT_REF"] == PRODUCTION_PROJECT_REF
    assert resources["concurrency"]["cancel-in-progress"] is False


def test_authoritative_migration_version_is_latest_filename() -> None:
    migrations = sorted((ROOT / "supabase" / "migrations").glob("*.sql"))
    assert migrations
    assert migrations[-1].name.startswith(f"{REQUIRED_MIGRATION_VERSION}_")
