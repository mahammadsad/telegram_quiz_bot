"""Read-only probes used by strict application readiness checks."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import Row, as_row, first_row


def get_contract() -> Row:
    result = get_client().rpc("get_application_schema_contract", {}).execute()
    return as_row(result.data, "application schema contract")


def active_quiz_probe() -> Row | None:
    result = (
        get_client()
        .table("quiz_runs")
        .select(
            "quiz_id,status,question_count,integrity_verified,"
            "checksum_contract_version,generated_checksum,persisted_checksum"
        )
        .in_("status", ["ready", "posting", "posted", "posting_failed"])
        .eq("question_count", 10)
        .order("quiz_date", desc=True)
        .limit(1)
        .execute()
    )
    return first_row(result.data, "active quiz probe")
