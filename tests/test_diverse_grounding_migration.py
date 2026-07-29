from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (
    ROOT
    / "supabase"
    / "migrations"
    / "20260728113750_quiz_quality_and_negative_marking.sql"
)


def test_diverse_grounding_migration_round_robins_topics_without_data_rewrites():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "partition by mt.id" in sql
    assert "eligible.source_rank" in sql
    assert "eligible.topic_rank" in sql
    assert "chapter.rotation_enabled" in sql
    assert "'diverse_grounding_ready', v_diverse_grounding_ready" in sql
    for destructive in ("delete from", "truncate ", "drop table", "drop schema"):
        assert destructive not in sql


def test_diverse_grounding_rpc_remains_private_and_ist_aware():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "security invoker" in sql
    assert "set search_path = ''" in sql
    assert "at time zone 'asia/kolkata'" in sql
    assert (
        "revoke execute on function "
        "public.get_grounding_bundle(text, text, date, integer)"
    ) in sql
    assert (
        "grant execute on function "
        "public.get_grounding_bundle(text, text, date, integer)"
    ) in sql


def test_negative_marking_is_forward_only_and_preserves_raw_correct_count():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    assert "negative_mark_penalty numeric(4, 2)" in sql
    assert "not null default 0" in sql
    assert "alter column negative_mark_penalty set default 0.25" in sql
    assert "generated always as" in sql
    assert "function public.protect_quiz_marking_policy()" in sql
    assert "quiz marking policy is immutable" in sql
    assert "'score', target.score" in sql
    assert "'netscore', target.net_score" in sql
    assert "'negativemarks'" in sql
    assert "attempt.net_score" in sql
    assert "'negative_marking_ready', v_negative_marking_ready" in sql


def test_negative_marking_functions_remain_service_role_only():
    sql = MIGRATION.read_text(encoding="utf-8").casefold()

    for signature in (
        "public.quiz_attempt_result(uuid)",
        "public.get_quiz_leaderboard_page(\n    text, integer, integer\n)",
        "public.get_quiz_leaderboard_for_user(\n    text, uuid, integer\n)",
        "public.get_user_learning_dashboard(uuid)",
    ):
        assert f"revoke execute on function {signature}" in sql
        assert f"grant execute on function {signature}" in sql
