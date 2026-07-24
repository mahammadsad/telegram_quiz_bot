"""Private audit trail for accepted and rejected independent verifier output."""

from __future__ import annotations

from database.client import get_client
from storage.contracts import as_json_value


def record(
    *,
    quiz_id: str,
    subject_key: str,
    chapter: str,
    micro_topic_id: str,
    source_document_ids: list[str],
    generated_questions: list[dict],
    verifier_output: object,
    verifier_raw_text: str,
    verdict: str,
    rejection_reasons: list[str],
    verifier_provider: str | None,
    verifier_model: str | None,
) -> None:
    payload = {
        "quiz_id": quiz_id,
        "subject_key": subject_key,
        "chapter": chapter,
        "micro_topic_id": micro_topic_id,
        "source_document_ids": source_document_ids,
        "generated_questions": generated_questions,
        "verifier_output": as_json_value(verifier_output, "verifier output"),
        "verifier_raw_text": verifier_raw_text,
        "verdict": verdict,
        "rejection_reasons": rejection_reasons,
        "verifier_provider": verifier_provider,
        "verifier_model": verifier_model,
    }
    get_client().table("question_generation_audits").insert(payload).execute()
