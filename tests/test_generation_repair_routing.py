"""Route actual grounding failures to the existing batch-repair instruction."""

import pytest

import bot
from services.question_validation import QuizValidationError, _validate_grounding_diversity


@pytest.mark.parametrize("counts", [(10,), (4, 2, 2, 2)])
@pytest.mark.parametrize("dimension", ["topic", "source"])
def test_grounding_diversity_failure_reaches_distribution_repair(counts, dimension):
    rows = []
    for group, count in enumerate(counts):
        for _ in range(count):
            rows.append({
                "source_document_id": f"source-{group}",
                "micro_topic_key": f"topic-{group}",
                "options": [f"answer-{len(rows)}", "other"],
                "correct_index": 0,
            })

    with pytest.raises(QuizValidationError) as caught:
        _validate_grounding_diversity(
            rows,
            required_source_diversity=4 if dimension == "source" else 0,
            required_topic_diversity=4 if dimension == "topic" else 1,
            source_required=dimension == "source",
        )

    reason = bot._validation_reason_code(caught.value)
    expected = "micro_topic_diversity" if dimension == "topic" else "source_diversity"
    assert reason == expected
    prompt = bot._repair_generation_prompt("original grounded prompt", reason)
    assert "Redistribute all ten questions" in prompt
    assert "may appear more than three times" in prompt
    assert "same evidence and syllabus rules" in prompt
    assert "character-for-character" not in prompt


@pytest.mark.parametrize("message", [
    "Question 1 must contain a normalized micro-topic id.",
    "Question 1 must contain a reusable micro-topic key.",
    "Question 1 has a micro-topic that does not match its source.",
    "Question 1 has a micro-topic outside the curated chapter.",
    "Question 1 belongs to another micro-topic.",
])
def test_topic_identity_failures_keep_identity_repair(message):
    reason = bot._validation_reason_code(QuizValidationError(message))
    assert reason == "micro_topic"
    prompt = bot._repair_generation_prompt("base", reason)
    assert "character-for-character" in prompt
    assert "Redistribute" not in prompt


def test_structured_reason_still_takes_precedence_over_message():
    error = QuizValidationError(
        "Quiz micro-topics are not balanced across the grounded pack.",
        reason_code="custom_structured_reason",
    )
    assert bot._validation_reason_code(error) == "custom_structured_reason"
