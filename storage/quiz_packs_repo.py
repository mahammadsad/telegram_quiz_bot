"""Atomic ordered quiz-pack persistence backed by PostgreSQL RPCs."""

from __future__ import annotations

from database.client import get_client
from errors import DatabaseIntegrityError
from storage.contracts import Row, as_row, as_rows


def list_questions(quiz_id: str) -> list[Row]:
    result = (
        get_client()
        .table("quiz_questions")
        .select("id,quiz_id,question_id,question_order,created_at,questions(*)")
        .eq("quiz_id", quiz_id)
        .order("question_order")
        .execute()
    )
    return as_rows(result.data, "quiz pack mappings")


def save_atomic(
    *,
    quiz_id: str,
    worker_id: str,
    questions: list[Row],
    content_checksum: str,
    replace: bool,
) -> Row:
    result = get_client().rpc(
        "save_quiz_pack_atomic",
        {
            "p_quiz_id": quiz_id,
            "p_worker_id": worker_id,
            "p_questions": questions,
            "p_content_checksum": content_checksum,
            "p_replace": replace,
        },
    ).execute()
    data = as_row(result.data, "save_quiz_pack_atomic")
    if (
        int(data.get("question_count") or 0) != 10
        or not data.get("generated_checksum")
        or not data.get("persisted_checksum")
    ):
        raise DatabaseIntegrityError("Atomic quiz save returned an invalid result.")
    return data


def record_readback_integrity_failure(
    *,
    quiz_id: str,
    worker_id: str,
    generated_checksum: str,
    persisted_checksum: str,
    question_ids: list[str],
) -> None:
    """Fail closed if the application read-back disagrees with the save RPC."""
    client = get_client()
    client.table("quiz_pack_integrity_failures").insert({
        "quiz_id": quiz_id,
        "worker_id": worker_id,
        "generated_checksum": generated_checksum,
        "persisted_checksum": persisted_checksum,
        "question_ids": question_ids,
        "question_count": len(question_ids),
        "diagnostic_code": "application_readback_checksum_mismatch",
    }).execute()
    client.table("quiz_runs").update({
        "status": "integrity_failed",
        "integrity_verified": False,
        "persisted_checksum": persisted_checksum,
        "integrity_diagnostic_code": "application_readback_checksum_mismatch",
        "last_error_category": "database_integrity_error",
    }).eq("quiz_id", quiz_id).eq("worker_id", worker_id).execute()
