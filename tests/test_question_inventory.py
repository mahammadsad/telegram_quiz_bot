from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.question_inventory import (
    InventoryExhausted,
    assemble_verified_quiz,
    inventory_report,
    replenishment_plan,
)

NOW = datetime(2026, 8, 8, 8, 0, tzinfo=timezone.utc)


def candidate(index: int, **overrides):
    row = {
        "id": f"question-{index}",
        "subject": "history",
        "chapter": f"chapter-{index % 3}",
        "topic_key": f"topic-{index}",
        "micro_topic_id": f"micro-{index}",
        "source_document_id": f"source-{index}",
        "knowledge_point_id": f"knowledge-{index}",
        "variant_fingerprint": f"variant-{index}",
        "semantic_cluster_id": f"semantic-{index}",
        "status": "active",
        "verification_status": "verified",
        "inventory_status": "verified",
        "review_required": False,
        "eligible_at": (NOW - timedelta(days=index + 1)).isoformat(),
        "usage_count": 0,
        "created_at": (NOW - timedelta(days=30 - index)).isoformat(),
    }
    row.update(overrides)
    return row


def usage(row, *, days_ago: int = 1, quiz_id: str = "prior-quiz"):
    return {
        **{
            key: row.get(key)
            for key in (
                "chapter",
                "topic_key",
                "micro_topic_id",
                "source_document_id",
                "knowledge_point_id",
                "variant_fingerprint",
                "semantic_cluster_id",
            )
        },
        "question_id": row["id"],
        "quiz_id": quiz_id,
        "occurred_at": (NOW - timedelta(days=days_ago)).isoformat(),
    }


def test_strict_inventory_selects_oldest_eligible_ten() -> None:
    rows = [candidate(index) for index in range(12)]
    result = assemble_verified_quiz(rows, [], now=NOW)
    assert len(result.questions) == 10
    assert result.relaxed_constraints == ()
    assert [row["id"] for row in result.questions[:2]] == ["question-11", "question-10"]


def test_assembler_fills_ten_through_recorded_degradation() -> None:
    rows = [candidate(index) for index in range(10)]
    history = [usage(row) for row in rows]
    result = assemble_verified_quiz(rows, history, now=NOW)
    assert len(result.questions) == 10
    assert "exact_variant" in result.relaxed_constraints
    assert "knowledge_point" in result.relaxed_constraints
    assert all(result.selected_with_relaxation[row["id"]] for row in rows)


@pytest.mark.parametrize(
    "unsafe",
    [
        {"inventory_status": "quarantined"},
        {"verification_status": "expired"},
        {"review_required": True},
        {"source_fact_verification_status": "stale"},
        {"source_fact_review_required": True},
        {"knowledge_point_id": None},
    ],
)
def test_quarantined_stale_or_unsupported_candidates_never_relax(unsafe) -> None:
    rows = [candidate(index) for index in range(10)]
    rows.append(candidate(99, **unsafe))
    result = assemble_verified_quiz(rows, [], now=NOW)
    assert "question-99" not in {row["id"] for row in result.questions}


def test_fewer_than_ten_safe_candidates_fails_closed() -> None:
    rows = [candidate(index) for index in range(9)]
    rows.append(candidate(99, inventory_status="quarantined"))
    with pytest.raises(InventoryExhausted, match="Only 9 verified"):
        assemble_verified_quiz(rows, [], now=NOW)


def test_inventory_days_and_replenishment_batches_are_reported() -> None:
    rows = [candidate(index) for index in range(25)]
    report = inventory_report(rows, now=NOW)
    assert report["history"] == {
        "verified": 25,
        "eligible_now": 25,
        "verified_days": 2.5,
        "eligible_days": 2.5,
    }
    assert replenishment_plan(130) == {
        "verified_count": 130,
        "target_count": 150,
        "missing_count": 20,
        "batch_size": 5,
        "batch_count": 4,
    }

