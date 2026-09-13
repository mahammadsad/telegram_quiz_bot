"""Fail-closed routing, log redaction and snapshot scope, without hosted access."""

import os
import subprocess
from unittest.mock import patch

import pytest

from scripts import backup_snapshot as backup

URI = f"postgresql://postgres.{backup.PROJECT}@aws-0-ap-south-1.pooler.supabase.com:5432/postgres"


def test_production_connection_pins_identity_tls_and_read_only():
    options = backup.production_connection(URI, backup.PROJECT, "do-not-print")
    assert options["sslmode"] == "verify-full"
    assert options["sslrootcert"] == "/etc/ssl/certs/ca-certificates.crt"
    assert options["port"] == 5432
    assert "default_transaction_read_only=on" in options["options"]
    assert "statement_timeout=30000" in options["options"]


@pytest.mark.parametrize("uri", [
    URI.replace(":5432", ":6543"), URI.replace(backup.PROJECT, "prdrabmcivgbygzjnmko"),
    URI + "?sslmode=disable", URI + "#fragment", URI.replace("@", ":password@"),
    URI.replace("pooler.supabase.com", "pooler.supabase.com.evil.example"),
    URI.replace("postgresql:", "postgres:"), URI.replace("/postgres", "/other", 1),
    "host=attacker user=postgres", URI.replace(":5432", ":invalid"),
])
def test_connection_refuses_unknown_routing(uri):
    with pytest.raises((backup.SnapshotError, ValueError)):
        backup.production_connection(uri, backup.PROJECT, "secret")


@pytest.mark.parametrize("project,password", [("wrong", "secret"), (backup.PROJECT, "")])
def test_missing_password_or_wrong_project_is_refused(project, password):
    with pytest.raises(backup.SnapshotError):
        backup.production_connection(URI, project, password)


def identity():
    return {"GITHUB_ACTIONS": "true", "GITHUB_REPOSITORY": "mahammadsad/telegram_quiz_bot",
            "EXPECTED_SUPABASE_PROJECT_REF": backup.PROJECT,
            "INPUT_SAFETY_ACK": f"BACKUP APPLICATION SCHEMAS FOR {backup.PROJECT}",
            "GITHUB_SHA": "a" * 40, "GITHUB_RUN_ID": "12345"}


@pytest.mark.parametrize("field", list(identity()))
def test_workflow_requires_every_identity_field(field):
    environment = identity()
    environment[field] = "wrong"
    with pytest.raises(backup.SnapshotError):
        backup.workflow_identity(environment)


def test_workflow_identity_exposes_only_provenance():
    assert backup.workflow_identity(identity() | {"SUPABASE_DB_PASSWORD": "secret"}) == {
        "project_ref": backup.PROJECT, "exporter_commit": "a" * 40, "workflow_run_id": "12345",
    }


def test_child_failure_is_redacted_and_environment_not_inherited(monkeypatch):
    monkeypatch.setenv("PGPASSWORD", "secret")
    monkeypatch.setenv("DOCKER_HOST", "tcp://attacker:2375")
    with patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 1, b"private row")) as run:
        with pytest.raises(backup.SnapshotError, match="Backup subprocess failed"):
            backup.command(["synthetic-tool"], stdout=subprocess.PIPE)
    assert run.call_args.kwargs["stderr"] == subprocess.DEVNULL
    assert run.call_args.kwargs["env"] == {"PATH": os.environ["PATH"], "LANG": "C.UTF-8"}


def test_row_fingerprints_quote_identifiers_not_execute_them():
    query = backup.row_fingerprint_query("public", 'table"; DELETE FROM public.users; --')
    assert '"public"."table""; DELETE FROM public.users; --"' in query
    assert 'ORDER BY h COLLATE "C"' in query
    assert "row_to_json" in query


def test_inventory_compares_rows_security_and_contracts():
    def query(statement):
        return {backup.TABLES_SQL: [["public", "synthetic"]],
                backup.CONTRACT_SQL: backup.EXPECTED_CONTRACT,
                backup.SECURITY_SQL: [["public", "synthetic", True, False, None]]}.get(statement, [2, "a" * 32])
    evidence = backup.inventory(query)
    assert evidence["tables"] == [["public", "synthetic", 2, "a" * 32]]
    assert evidence["security"][0][2] is True


@pytest.mark.parametrize("tables", [[], [["private", "secrets"]], [["public"]], [["public", 3]], "invalid"])
def test_inventory_refuses_scope_drift(tables):
    with pytest.raises(backup.SnapshotError):
        backup.inventory(lambda statement: tables)


def test_failed_export_cli_never_prints_exception(monkeypatch, capsys):
    monkeypatch.setattr(backup, "workflow_identity", lambda env: (_ for _ in ()).throw(ValueError("secret learner row")))
    assert backup.main() == 1
    assert "secret learner" not in capsys.readouterr().out


@pytest.mark.parametrize("scope", [None, {}, {"large_objects": 0},
    {"large_objects": 1, "unsupported_relations": 0},
    {"large_objects": 0, "unsupported_relations": 1},
    {"large_objects": False, "unsupported_relations": 0}])
def test_scope_gate_refuses_unsupported_or_missing_evidence(scope):
    with pytest.raises(backup.SnapshotError):
        backup.validate_scope(scope)


def test_scope_gate_accepts_exact_supported_snapshot():
    backup.validate_scope({"large_objects": 0, "unsupported_relations": 0})


def test_security_comparison_uses_effective_privileges_not_acl_storage_order():
    assert "aclexplode(coalesce(c.relacl,acldefault(" in backup.SECURITY_SQL
    assert "pg_get_userbyid(a.grantee)" in backup.SECURITY_SQL
    assert "a.privilege_type,a.is_grantable" in backup.SECURITY_SQL
    assert "c.relacl::text" not in backup.SECURITY_SQL
    assert "WHEN c.relkind='S' THEN 's'" in backup.SECURITY_SQL


def test_production_workflow_uploads_only_encrypted_allowlist():
    import yaml

    workflow = yaml.safe_load((backup.archive.ROOT / ".github/workflows/supabase-migration-plan.yml").read_text())
    job = workflow["jobs"]["backup-application"]
    assert job["environment"] == "production"
    assert "services" not in job
    assert job["if"] == "inputs.operation == 'backup'"
    assert workflow["jobs"]["plan-migrations"]["if"] == "inputs.operation != 'backup'"
    upload = job["steps"][-1]
    assert "if" not in upload
    assert upload["with"]["retention-days"] == 30
    paths = upload["with"]["path"].splitlines()
    assert [path.rsplit("/", 1)[1] for path in paths] == ["database.dump.gpg", "manifest.json", "restore-receipt.json"]
    assert not any("db push" in step.get("run", "") for step in job["steps"])
