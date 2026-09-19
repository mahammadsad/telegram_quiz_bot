"""No hosted credentials or production archive needed for gate failure tests."""

import copy
import json
import shutil
from datetime import datetime, timedelta, timezone
from io import BytesIO
from unittest.mock import patch

import pytest

from scripts import verified_recovery_point as gate

NOW = datetime(2026, 9, 19, 16, tzinfo=timezone.utc)
PLAN = ("DRY RUN: migrations will *not* be pushed to the database.\n"
        f"Would push these migrations:\n • {gate.MIGRATION}\nFinished supabase db push.\n")


def evidence():
    receipt = {
        "format": "citizen-affairs-application-snapshot-v1", "project_ref": gate.PROJECT,
        "exporter_commit": gate.EXPORTER, "workflow_run_id": "1234",
        "captured_at": "2026-09-19T14:00:00Z",
        "scope": ["public", "supabase_migrations", "extensions"],
        "managed_services_included": False, "isolated_plaintext_restore_verified": True,
        "owner_decryption_verified": False, "source_inventory_sha256": "a" * 64,
        "plaintext_sha256": "b" * 64, "ciphertext_sha256": "c" * 64,
        "table_count": 75, "recipient_fingerprint": gate.RECIPIENT,
    }
    approval = {
        "format": "citizen-affairs-owner-recovery-approval-v1", "receipt": receipt,
        "artifact_id": 5678, "artifact_digest": "sha256:" + "d" * 64,
        "owner_verified_at": "2026-09-19T15:00:00Z",
        "approved_migration_sha256": gate.MIGRATION_SHA256,
    }
    repo = {"id": gate.REPOSITORY_ID, "full_name": gate.REPOSITORY}
    run = {
        "id": 1234, "status": "completed", "conclusion": "success", "run_attempt": 1,
        "event": "workflow_dispatch", "path": ".github/workflows/supabase-migration-plan.yml",
        "head_sha": gate.EXPORTER, "repository": repo.copy(), "head_repository": repo.copy(),
        "run_started_at": "2026-09-19T13:59:00Z", "updated_at": "2026-09-19T14:05:00Z",
    }
    jobs = {"total_count": 2, "jobs": [
        {"name": name, "status": "completed", "conclusion": conclusion,
         "run_id": 1234, "head_sha": gate.EXPORTER}
        for name, conclusion in [("backup-application", "success"), ("plan-migrations", "skipped")]
    ]}
    artifact = {
        "id": 5678, "name": "encrypted-application-backup-1234", "expired": False,
        "digest": approval["artifact_digest"], "created_at": "2026-09-19T14:04:00Z",
        "expires_at": "2026-10-19T14:04:00Z", "workflow_run": {
            "id": 1234, "head_sha": gate.EXPORTER,
            "repository_id": gate.REPOSITORY_ID, "head_repository_id": gate.REPOSITORY_ID,
        },
    }
    return approval, run, jobs, artifact


def test_complete_scoped_evidence_and_live_provenance():
    approval, run, jobs, artifact = evidence()
    gate.validate_provenance(approval, run, jobs, artifact, NOW)
    with patch.object(gate, "github_json", side_effect=[run, jobs, artifact]) as api:
        gate.verify_recovery_point(json.dumps(approval), "test-token", NOW, plan=PLAN)
    assert [call.args[0] for call in api.call_args_list] == [
        "runs/1234", "runs/1234/jobs?filter=latest&per_page=100", "artifacts/5678"]


@pytest.mark.parametrize("location,key,value", [
    ("approval", "format", "backup_verified=true"),
    ("approval", "approved_migration_sha256", "f" * 64),
    ("approval", "artifact_id", True), ("approval", "artifact_id", -1),
    ("approval", "artifact_digest", "sha256:bad"),
    ("approval", "owner_verified_at", "2026-09-19T13:00:00Z"),
    ("approval", "owner_verified_at", "2026-09-20T16:00:00Z"),
    ("approval", "owner_verified_at", "2026-09-19T15:00:00"),
    ("receipt", "project_ref", "other-project"),
    ("receipt", "exporter_commit", "f" * 40),
    ("receipt", "workflow_run_id", "1234/../../secret"),
    ("receipt", "workflow_run_id", 1234),
    ("receipt", "captured_at", "2026-09-17T15:59:59Z"),
    ("receipt", "captured_at", "2026-09-19T13:58:00Z"),
    ("receipt", "captured_at", "invalid"),
    ("receipt", "scope", ["public"]),
    ("receipt", "managed_services_included", True),
    ("receipt", "isolated_plaintext_restore_verified", False),
    ("receipt", "isolated_plaintext_restore_verified", 1),
    ("receipt", "owner_decryption_verified", True),
    ("receipt", "recipient_fingerprint", "F" * 40),
    ("receipt", "ciphertext_sha256", "g" * 64),
    ("receipt", "table_count", 0),
    ("run", "id", 5678), ("run", "conclusion", "failure"),
    ("run", "status", "in_progress"), ("run", "run_attempt", 2), ("run", "run_attempt", True),
    ("run", "event", "pull_request"), ("run", "path", ".github/workflows/ci.yml"),
    ("run", "head_sha", "f" * 40), ("run", "head_repository", {"id": 1}),
    ("run", "updated_at", "2026-09-19T16:01:00Z"),
    ("jobs", "total_count", 3), ("jobs", "jobs", []),
    ("artifact", "id", 9999), ("artifact", "expired", True),
    ("artifact", "name", "encrypted-application-backup-1235"),
    ("artifact", "digest", "sha256:" + "f" * 64),
    ("artifact", "workflow_run", {"id": 1234}),
    ("artifact", "expires_at", "2026-09-19T15:59:59Z"),
    ("artifact", "created_at", "2026-09-19T13:00:00Z"),
])
def test_tampered_stale_wrong_source_or_failed_evidence_is_rejected(location, key, value):
    approval, run, jobs, artifact = evidence()
    {"approval": approval, "receipt": approval["receipt"], "run": run,
     "jobs": jobs, "artifact": artifact}[location][key] = value
    with pytest.raises(ValueError):
        gate.validate_provenance(approval, run, jobs, artifact, NOW)


def test_freshness_boundary():
    approval, *_ = evidence()
    captured = gate.timestamp(approval["receipt"]["captured_at"])
    gate.validate_approval(approval, captured + timedelta(hours=48))
    with pytest.raises(ValueError):
        gate.validate_approval(approval, captured + timedelta(hours=48, microseconds=1))


@pytest.mark.parametrize("body", [b'[]', b'{"x":1,"x":2}', b'{"x":{"a":1,"a":2}}', b' ' * (gate.MAX_JSON + 1)])
def test_ambiguous_or_oversized_json_is_rejected(body):
    with pytest.raises(ValueError):
        gate.decode_json(body)


def test_no_network_without_approval_or_token():
    with patch.object(gate, "github_json") as api:
        for raw, token in [("", "token"), (json.dumps(evidence()[0]), "")]:
            with pytest.raises(ValueError):
                gate.verify_recovery_point(raw, token, NOW)
        api.assert_not_called()


def test_bounded_get_and_no_credential_redirect():
    with patch.object(gate, "build_opener") as opener:
        opener.return_value.open.return_value = BytesIO(b'{"ok":true}')
        assert gate.github_json("runs/1234", "test-token") == {"ok": True}
        call = opener.return_value.open.call_args
        assert call.kwargs == {"timeout": 20}
        assert call.args[0].get_method() == "GET"
        assert call.args[0].full_url == f"https://api.github.com/repos/{gate.REPOSITORY}/actions/runs/1234"
    assert gate.NoRedirects().redirect_request(None, None, 302, "", {}, "https://other.test") is None


@pytest.mark.parametrize("change", ["extra", "missing", "migration", "ledger", "historical", "symlink"])
def test_only_exact_reviewed_migration_set_is_eligible(tmp_path, change):
    shutil.copytree(gate.ROOT / "database", tmp_path / "database", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(gate.ROOT / "supabase/migrations", tmp_path / "supabase/migrations")
    gate.validate_migration_scope(tmp_path)
    target = tmp_path / "supabase/migrations" / gate.MIGRATION
    if change == "extra":
        (target.parent / "unreviewed.sql").write_text("select 1;")
    elif change == "missing":
        target.unlink()
    elif change == "migration":
        target.write_text(target.read_text() + "\nselect 1;")
    elif change == "ledger":
        (tmp_path / "database/migration_ledger.py").write_text("# changed")
    elif change == "historical":
        next(path for path in target.parent.glob("*.sql") if path != target).write_text("select 1;")
    else:
        target.unlink()
        target.symlink_to(gate.ROOT / "supabase/migrations" / gate.MIGRATION)
    with pytest.raises(ValueError):
        gate.validate_migration_scope(tmp_path)


def test_failed_backup_job_even_when_run_reports_success():
    approval, run, jobs, artifact = copy.deepcopy(evidence())
    jobs["jobs"][0]["conclusion"] = "failure"
    with pytest.raises(ValueError):
        gate.validate_provenance(approval, run, jobs, artifact, NOW)


@pytest.mark.parametrize("plan", [
    "", "Remote database is up to date.", PLAN.replace("DRY RUN:", "RUN:"),
    PLAN.replace(" • ", " • unexpected.sql\n • "),
    PLAN.replace(gate.MIGRATION, "other.sql"),
    PLAN + "Would push these migrations:\n • surprise.sql\n",
    PLAN.replace("Finished supabase db push.", ""),
    PLAN + "unreviewed.sql\n",
])
def test_missing_or_broader_actual_pending_plan_fails_closed(plan):
    with pytest.raises(ValueError):
        gate.validate_pending_plan(plan)


def test_invalid_plan_is_rejected_before_network():
    with patch.object(gate, "github_json") as api, pytest.raises(ValueError):
        gate.verify_recovery_point(json.dumps(evidence()[0]), "test-token", NOW, plan="")
    api.assert_not_called()
