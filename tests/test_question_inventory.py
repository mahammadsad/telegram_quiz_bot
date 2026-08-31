from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from services.question_inventory import (
    InventoryExhausted,
    assemble_verified_quiz,
    chapter_difficulty_report,
    exposure_quality_report,
    inventory_report,
    replenishment_plan,
    replenishment_quality_report,
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


def test_assembler_enforces_requested_difficulty_mix() -> None:
    rows = [
        candidate(index, difficulty="easy" if index < 6 else "medium" if index < 11 else "hard")
        for index in range(13)
    ]
    result = assemble_verified_quiz(
        rows,
        [],
        now=NOW,
        difficulty_targets={"easy": 3, "medium": 5, "hard": 2},
    )
    assert Counter(row["difficulty"] for row in result.questions) == Counter(
        {"easy": 3, "medium": 5, "hard": 2}
    )


def test_assembler_selects_a_balanced_pack_from_an_unbalanced_oldest_pool() -> None:
    difficulty_mix = ["easy", "medium", "hard", "easy", "medium", "medium", "easy", "medium", "medium", "hard"]
    rows = [
        candidate(
            index,
            correct_option="A",
            difficulty=difficulty_mix[index],
            eligible_at=(NOW - timedelta(days=100 - index)).isoformat(),
        )
        for index in range(10)
    ]
    balanced_tail = (
        ("B", "easy"), ("B", "medium"), ("B", "medium"),
        ("C", "easy"), ("C", "medium"),
        ("D", "medium"), ("D", "hard"),
    )
    rows.extend(
        candidate(
            10 + index,
            correct_option=position,
            difficulty=difficulty,
            eligible_at=(NOW - timedelta(days=20 - index)).isoformat(),
        )
        for index, (position, difficulty) in enumerate(balanced_tail)
    )

    result = assemble_verified_quiz(
        rows,
        [],
        now=NOW,
        difficulty_targets={"easy": 3, "medium": 5, "hard": 2},
        balanced_answer_positions=True,
    )

    assert Counter(row["difficulty"] for row in result.questions) == Counter(
        {"easy": 3, "medium": 5, "hard": 2}
    )
    assert sorted(Counter(row["correct_option"] for row in result.questions).values()) == [2, 2, 3, 3]


def test_assembler_fails_closed_when_answer_positions_cannot_be_balanced() -> None:
    rows = [candidate(index, correct_option="A") for index in range(12)]

    with pytest.raises(InventoryExhausted, match="balance correct answers"):
        assemble_verified_quiz(
            rows,
            [],
            now=NOW,
            balanced_answer_positions=True,
        )


def test_assembler_fails_closed_when_difficulty_inventory_is_short() -> None:
    rows = [
        candidate(index, difficulty="easy" if index < 5 else "medium")
        for index in range(12)
    ]
    with pytest.raises(InventoryExhausted, match="difficulty targets"):
        assemble_verified_quiz(
            rows,
            [],
            now=NOW,
            difficulty_targets={"easy": 3, "medium": 5, "hard": 2},
        )


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


def test_replenishment_quality_report_is_answer_free_and_bounded() -> None:
    report = replenishment_quality_report(
        [
            {
                "event_type": "batch_completed",
                "accepted_count": 3,
                "rejected_count": 2,
                "rejection_codes": ["historical_duplicate", "proof_invalid"],
                "error_code": None,
                "job_id": "must-not-leak",
                "worker_id": "must-not-leak",
            },
            {
                "event_type": "batch_failed",
                "accepted_count": 0,
                "rejected_count": 5,
                "rejection_codes": ["proof_invalid"],
                "error_code": "content_rejected",
            },
        ],
        sample_limit=2,
    )

    assert report == {
        "sample_events": 2,
        "sample_limit": 2,
        "sample_truncated": True,
        "accepted_candidates": 3,
        "rejected_candidates": 7,
        "acceptance_percent": 30.0,
        "event_types": {"batch_completed": 1, "batch_failed": 1},
        "rejection_codes": {"historical_duplicate": 1, "proof_invalid": 2},
        "error_codes": {"content_rejected": 1},
    }
    assert "job_id" not in report
    assert "worker_id" not in report


def test_chapter_difficulty_report_exposes_exact_answer_free_gaps() -> None:
    rows = [
        candidate(
            index,
            chapter="chapter-ready",
            difficulty="easy" if index < 3 else "medium" if index < 8 else "hard",
        )
        for index in range(10)
    ]
    rows.extend(
        candidate(
            20 + index,
            chapter="chapter-short",
            difficulty="easy" if index < 3 else "medium",
        )
        for index in range(8)
    )
    rows.append(
        candidate(
            99,
            chapter="chapter-empty",
            difficulty="hard",
            inventory_status="quarantined",
        )
    )

    report = chapter_difficulty_report(
        rows,
        ("chapter-ready", "chapter-short", "chapter-empty"),
        {"easy": 3, "medium": 5, "hard": 2},
        now=NOW,
    )

    assert report == {
        "difficulty_targets": {"easy": 3, "medium": 5, "hard": 2},
        "total_chapters": 3,
        "ready_chapters": 1,
        "readiness_percent": 33.33,
        "gaps": [
            {
                "chapter": "chapter-short",
                "available": {"easy": 3, "medium": 5, "hard": 0},
                "shortages": {"hard": 2},
            },
            {
                "chapter": "chapter-empty",
                "available": {"easy": 0, "medium": 0, "hard": 0},
                "shortages": {"easy": 3, "medium": 5, "hard": 2},
            },
        ],
    }


def test_exposure_quality_reports_repeat_and_same_quiz_targets() -> None:
    events = [
        {"question_id": "q1", "quiz_id": "quiz-a"},
        {"question_id": "q1", "quiz_id": "quiz-b"},
        {"question_id": "q2", "quiz_id": "quiz-b"},
        {"question_id": "q2", "quiz_id": "quiz-b"},
        {"quiz_id": "quiz-c"},
    ]
    assert exposure_quality_report(events) == {
        "total_events": 5,
        "identified_events": 4,
        "unidentified_events": 1,
        "unique_questions": 2,
        "repeated_questions": 2,
        "repeated_events": 2,
        "repeated_exposure_percent": 50.0,
        "same_quiz_duplicate_events": 1,
        "passes_repeat_target": False,
        "passes_same_quiz_target": False,
    }


def test_empty_exposure_quality_report_is_safe_and_green() -> None:
    report = exposure_quality_report([])
    assert report["repeated_exposure_percent"] == 0.0
    assert report["passes_repeat_target"] is True
    assert report["passes_same_quiz_target"] is True
