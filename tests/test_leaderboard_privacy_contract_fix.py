from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260808084950_fix_leaderboard_privacy_contract_invoker.sql"
)


def test_privacy_contract_fix_is_invoker_safe_and_service_only() -> None:
    sql = MIGRATION.read_text(encoding="utf-8").lower()

    assert "create or replace function public.get_leaderboard_privacy_contract()" in sql
    assert "security invoker" in sql
    assert "security definer" not in sql
    assert "supabase_migrations" not in sql
    assert "'leaderboard_privacy_rpc_fix_migration_version', '20260808084950'" in sql
    assert "from public, anon, authenticated" in sql
    assert "to service_role" in sql
