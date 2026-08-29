from pathlib import Path

from database.contract import (
    PG_NET_REQUEST_SEQUENCE_MIGRATION_VERSION,
    PG_NET_SCHEMA_HARDENING_MIGRATION_VERSION,
    PRIMARY_SCHEDULER_MIGRATION_VERSION,
)

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{PRIMARY_SCHEDULER_MIGRATION_VERSION}_durable_primary_scheduler.sql"
)
HARDENING_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{PG_NET_SCHEMA_HARDENING_MIGRATION_VERSION}_pg_net_extension_schema_hardening.sql"
)
SEQUENCE_MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / f"{PG_NET_REQUEST_SEQUENCE_MIGRATION_VERSION}_pg_net_request_sequence_continuity.sql"
)


def test_primary_scheduler_uses_vault_and_observable_supabase_cron() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "create extension if not exists pg_cron" in sql
    assert "create extension if not exists pg_net" in sql
    assert "vault.decrypted_secrets" in sql
    assert "github_scheduler_token" in sql
    assert "github_scheduler_token_expires_at" in sql
    assert "4,19,34,49 * * * *" in sql
    assert "dispatch-due-jobs" in sql
    assert "daily-completeness" in sql
    assert "private.scheduler_dispatch_requests" in sql
    assert "net._http_response" in sql
    assert "recent_rejected_requests" in sql


def test_primary_scheduler_credentials_and_controls_are_not_public() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "authorization', 'bearer ' || v_token" in sql
    assert "revoke all on schema private from public, anon, authenticated, service_role" in sql
    assert "revoke all on function private.dispatch_github_workflow(text)" in sql
    assert "revoke all on function private.configure_primary_scheduler()" in sql
    assert "revoke all on function public.get_primary_scheduler_contract()" in sql
    assert "grant execute on function public.get_primary_scheduler_contract() to service_role" in sql
    assert "ghp_" not in sql
    assert "github_pat_" not in sql


def test_primary_scheduler_is_fail_closed_before_activation() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "valid scheduler credentials are required" in sql
    assert "expired or inside renewal window" in sql
    assert "private.configure_primary_scheduler()" in sql
    assert "perform cron.schedule" in sql
    assert sql.index("create or replace function private.configure_primary_scheduler()") < sql.index(
        "perform cron.schedule"
    )


def test_pg_net_schema_hardening_is_guarded_and_preserves_the_installed_version() -> None:
    sql = HARDENING_MIGRATION.read_text(encoding="utf-8").lower()

    assert "v_extension_schema <> 'public'" in sql
    assert "private.scheduler_dispatch_requests" in sql
    assert "outcome = 'queued'" in sql
    assert "net.http_request_queue" in sql
    assert "drop extension pg_net" in sql
    assert "create extension pg_net with schema extensions version %l" in sql
    assert "v_extension_version" in sql
    assert "pg_net was not recreated in the extensions schema" in sql


def test_pg_net_sequence_continuity_preserves_durable_scheduler_request_identity() -> None:
    sql = SEQUENCE_MIGRATION.read_text(encoding="utf-8").lower()

    assert "net.http_request_queue_id_seq" in sql
    assert "private.scheduler_dispatch_requests" in sql
    assert "select max(request_id)" in sql
    assert "v_sequence_last < v_audit_max" in sql
    assert "not v_sequence_called" in sql
    assert "setval('net.http_request_queue_id_seq'::regclass, v_audit_max, true)" in sql
