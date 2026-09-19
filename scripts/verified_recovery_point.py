"""One-release application recovery gate, not a full-project backup assertion.

The protected environment record is an operator attestation made ONLY after
retained-key verification. GitHub independently establishes artifact/workflow
provenance; encryption checksums alone cannot establish that provenance.
No learner data, archive download URLs, or private keys are accessed here.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "tizxodkcpglmxgtwepor"
REPOSITORY = "mahammadsad/telegram_quiz_bot"
REPOSITORY_ID = 1291473847
RECIPIENT = "39F3FC1CE7F58FAA4CCB823FCBC34F51F9DA20DC"
EXPORTER = "e4bb797295c5964f78e3b21c89f0a0b7c978a6bb"
MIGRATION = "20260912132928_durable_replenishment_job_rotation.sql"
MIGRATION_SHA256 = "2b30579692d04c7e95a4aecfb0a85aaf86b31fdaa8337080b012e1082cfaf9c0"
LEDGER_SHA256 = "e08ca5fd479f0679ed1e17765daba2a221ec691c8b7641983784e0bbb7521d3c"
MAX_AGE = timedelta(hours=48)
MAX_JSON = 1024 * 1024


class RecoveryEvidenceError(ValueError):
    """Intentionally generic: callers must not log remote response bodies."""


def require(condition: bool) -> None:
    if not condition:
        raise RecoveryEvidenceError("Application recovery evidence is not valid.")


def timestamp(value: object) -> datetime:
    require(isinstance(value, str))
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    require(parsed.tzinfo is not None)
    return parsed.astimezone(timezone.utc)


def digest(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def unique_object(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        require(key not in result)
        result[key] = value
    return result


def decode_json(raw: bytes | str) -> dict:
    require(len(raw) <= MAX_JSON)
    value = json.loads(raw, object_pairs_hook=unique_object)
    require(isinstance(value, dict))
    return value


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def github_json(path: str, token: str) -> dict:
    # Paths are constructed internally from validated positive integer IDs.
    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}/actions/{path}",
        headers={"Authorization": f"Bearer {token}",
                 "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with build_opener(NoRedirects()).open(request, timeout=20) as response:
        return decode_json(response.read(MAX_JSON + 1))


def validate_migration_scope(root: Path = ROOT) -> None:
    """Fail closed when this exact 65-to-66 migration release changes."""
    ledger = root / "database/migration_ledger.py"
    require(not ledger.is_symlink())
    contents = ledger.read_bytes()
    require(hashlib.sha256(contents).hexdigest() == LEDGER_SHA256)
    # Parse the pinned literal source rather than executing a candidate module.
    import ast

    assignment = next(node for node in ast.parse(contents).body if isinstance(node, ast.AnnAssign))
    if assignment.value is None:
        raise RecoveryEvidenceError("Missing pinned ledger literal.")
    pins = ast.literal_eval(assignment.value)
    require(isinstance(pins, dict) and len(pins) == 65)
    directory = root / "supabase/migrations"
    expected = {f"{version}_{name}.sql": checksum for name, (version, checksum) in pins.items()}
    require({path.name for path in directory.glob("*.sql")} == set(expected) | {MIGRATION})
    for name, checksum in expected.items():
        path = directory / name
        require(not path.is_symlink())
        require(hashlib.md5(path.read_bytes(), usedforsecurity=False).hexdigest() == checksum)
    migration = directory / MIGRATION
    require(not migration.is_symlink())
    require(hashlib.sha256(migration.read_bytes()).hexdigest() == MIGRATION_SHA256)


def validate_approval(approval: dict, now: datetime) -> dict:
    require(set(approval) == {
        "format", "receipt", "artifact_id", "artifact_digest", "owner_verified_at",
        "approved_migration_sha256",
    })
    require(approval["format"] == "citizen-affairs-owner-recovery-approval-v1")
    require(approval["approved_migration_sha256"] == MIGRATION_SHA256)
    require(type(approval["artifact_id"]) is int and approval["artifact_id"] > 0)
    require(isinstance(approval["artifact_digest"], str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", approval["artifact_digest"]) is not None)
    receipt = approval["receipt"]
    require(isinstance(receipt, dict))
    require(set(receipt) == {
        "format", "project_ref", "exporter_commit", "workflow_run_id", "captured_at", "scope",
        "managed_services_included", "isolated_plaintext_restore_verified", "owner_decryption_verified",
        "source_inventory_sha256", "plaintext_sha256", "ciphertext_sha256", "table_count",
        "recipient_fingerprint",
    })
    require(receipt["format"] == "citizen-affairs-application-snapshot-v1")
    require(receipt["project_ref"] == PROJECT and receipt["exporter_commit"] == EXPORTER)
    require(isinstance(receipt["workflow_run_id"], str)
            and re.fullmatch(r"[1-9][0-9]{0,19}", receipt["workflow_run_id"]) is not None)
    require(receipt["scope"] == ["public", "supabase_migrations", "extensions"])
    require(receipt["managed_services_included"] is False)
    require(receipt["isolated_plaintext_restore_verified"] is True)
    # The exporter cannot verify an owner-held private key. Preserve its receipt.
    require(receipt["owner_decryption_verified"] is False)
    require(type(receipt["table_count"]) is int and receipt["table_count"] == 75)
    require(receipt["recipient_fingerprint"] == RECIPIENT)
    require(all(digest(receipt[field]) for field in (
        "plaintext_sha256", "ciphertext_sha256", "source_inventory_sha256")))
    captured = timestamp(receipt["captured_at"])
    verified = timestamp(approval["owner_verified_at"])
    require(captured <= verified <= now and timedelta(0) <= now - captured <= MAX_AGE)
    return receipt


def validate_provenance(approval: dict, run: dict, jobs: dict, artifact: dict, now: datetime) -> None:
    receipt = validate_approval(approval, now)
    run_id = int(receipt["workflow_run_id"])
    require(type(run.get("id")) is int and run["id"] == run_id)
    require(run.get("status") == "completed" and run.get("conclusion") == "success")
    require(run.get("event") == "workflow_dispatch"
            and type(run.get("run_attempt")) is int and run["run_attempt"] == 1)
    require(run.get("path") == ".github/workflows/supabase-migration-plan.yml")
    require(run.get("head_sha") == EXPORTER)
    for field in ("repository", "head_repository"):
        repo = run.get(field)
        require(isinstance(repo, dict) and repo.get("id") == REPOSITORY_ID
                and repo.get("full_name") == REPOSITORY)
    require(type(jobs.get("total_count")) is int and jobs["total_count"] == 2)
    records = jobs.get("jobs")
    if not isinstance(records, list) or len(records) != 2:
        raise RecoveryEvidenceError("Unexpected backup jobs.")
    require(all(isinstance(job, dict) and job.get("status") == "completed"
                and job.get("run_id") == run_id and job.get("head_sha") == EXPORTER for job in records))
    require({(job.get("name"), job.get("conclusion")) for job in records} == {
        ("backup-application", "success"), ("plan-migrations", "skipped")})
    require(artifact.get("id") == approval["artifact_id"] and artifact.get("expired") is False)
    require(artifact.get("name") == f"encrypted-application-backup-{run_id}")
    require(artifact.get("digest") == approval["artifact_digest"])
    origin = artifact.get("workflow_run")
    require(isinstance(origin, dict) and origin.get("id") == run_id
            and origin.get("repository_id") == REPOSITORY_ID
            and origin.get("head_repository_id") == REPOSITORY_ID
            and origin.get("head_sha") == EXPORTER)
    require(timestamp(run.get("run_started_at")) <= timestamp(receipt["captured_at"])
            <= timestamp(artifact.get("created_at")) <= timestamp(run.get("updated_at"))
            <= timestamp(approval["owner_verified_at"]) <= now < timestamp(artifact.get("expires_at")))


def validate_pending_plan(plan: str) -> None:
    """Require the actual linked dry run, not just local migration filenames."""
    require(len(plan) <= MAX_JSON)
    require("DRY RUN: migrations will *not* be pushed to the database." in plan)
    require(plan.count("Would push these migrations:") == 1)
    require(plan.count("Finished supabase db push.") == 1)
    pending = plan.split("Would push these migrations:", 1)[1].split("Finished supabase db push.", 1)[0]
    require(pending.strip() == f"• {MIGRATION}")
    require(re.findall(r"[\w.-]+\.sql", plan) == [MIGRATION])


def verify_recovery_point(raw: str, token: str, now: datetime, root: Path = ROOT, *, plan: str = "") -> None:
    require(bool(raw) and bool(token))
    approval = decode_json(raw)
    receipt = validate_approval(approval, now)
    validate_migration_scope(root)
    validate_pending_plan(plan)
    run_id = receipt["workflow_run_id"]
    run = github_json(f"runs/{run_id}", token)
    jobs = github_json(f"runs/{run_id}/jobs?filter=latest&per_page=100", token)
    artifact = github_json(f"artifacts/{approval['artifact_id']}", token)
    validate_provenance(approval, run, jobs, artifact, now)
