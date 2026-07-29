from copy import deepcopy
from random import Random

import pytest

from services.question_validation import (
    QuizValidationError,
    content_checksum,
    randomize_balanced_answer_positions,
    validate_questions,
)


def test_exactly_ten_valid_questions_accepted(valid_questions):
    clean = validate_questions(valid_questions, "history", "আধুনিক ভারত")
    assert len(clean) == 10
    assert all(item["question_id"] for item in clean)


@pytest.mark.parametrize("count", [0, 5, 9, 11])
def test_wrong_question_counts_rejected(valid_questions, count):
    rows = (valid_questions * 2)[:count]
    with pytest.raises(QuizValidationError, match="exactly 10"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_duplicate_question_rejected(valid_questions):
    rows = deepcopy(valid_questions)
    rows[1]["question"] = rows[0]["question"]
    with pytest.raises(QuizValidationError, match="duplicated"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_duplicate_option_rejected(valid_questions):
    rows = deepcopy(valid_questions)
    rows[0]["options"][1] = rows[0]["options"][0]
    with pytest.raises(QuizValidationError, match="duplicate options"):
        validate_questions(rows, "history", "আধুনিক ভারত")


@pytest.mark.parametrize("index", [-1, 4, True, "1"])
def test_invalid_correct_index_rejected(valid_questions, index):
    rows = deepcopy(valid_questions)
    rows[0]["correct_index"] = index
    with pytest.raises(QuizValidationError, match="correct index"):
        validate_questions(rows, "history", "আধুনিক ভারত")


@pytest.mark.parametrize("field", ["explanation", "detailed_explanation"])
def test_blank_explanation_rejected(valid_questions, field):
    rows = deepcopy(valid_questions)
    rows[0][field] = ""
    with pytest.raises(QuizValidationError, match="explanations"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_cross_subject_and_chapter_rejected(valid_questions):
    rows = deepcopy(valid_questions)
    rows[0]["subject_key"] = "science"
    with pytest.raises(QuizValidationError, match="another subject"):
        validate_questions(rows, "history", "আধুনিক ভারত")
    rows = deepcopy(valid_questions)
    rows[0]["chapter"] = "প্রাচীন ভারত"
    with pytest.raises(QuizValidationError, match="another chapter"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_wrong_micro_topic_and_unapproved_source_are_rejected(valid_questions):
    rows = deepcopy(valid_questions)
    rows[0]["micro_topic_key"] = "history:another-topic"
    with pytest.raises(QuizValidationError, match="another micro-topic"):
        validate_questions(rows, "history", "আধুনিক ভারত")
    with pytest.raises(QuizValidationError, match="outside the grounding bundle"):
        validate_questions(
            valid_questions,
            "history",
            "আধুনিক ভারত",
            allowed_source_ids={"33333333-3333-4333-8333-333333333333"},
        )


def test_grounded_pack_requires_balanced_source_and_topic_diversity(valid_questions):
    rows = deepcopy(valid_questions)
    source_topics = {}
    distribution = (0, 1, 2, 3, 0, 1, 2, 3, 0, 1)
    for row, index in zip(rows, distribution, strict=True):
        source_id = f"22222222-2222-4222-8222-{index + 1:012d}"
        topic_id = f"11111111-1111-4111-8111-{index + 1:012d}"
        topic_key = f"history:modern-india:topic-{index + 1}"
        row["source_document_id"] = source_id
        row["micro_topic_id"] = topic_id
        row["micro_topic_key"] = topic_key
        source_topics[source_id] = (topic_id, topic_key)

    clean = validate_questions(
        rows,
        "history",
        "আধুনিক ভারত",
        allowed_source_ids=set(source_topics),
        allowed_source_topics=source_topics,
        required_source_diversity=4,
        required_topic_diversity=4,
    )
    assert len({row["source_document_id"] for row in clean}) == 4
    assert len({row["micro_topic_key"] for row in clean}) == 4

    repetitive = deepcopy(rows)
    for row in repetitive:
        row["source_document_id"] = rows[0]["source_document_id"]
        row["micro_topic_id"] = rows[0]["micro_topic_id"]
        row["micro_topic_key"] = rows[0]["micro_topic_key"]
    with pytest.raises(QuizValidationError, match="source diversity"):
        validate_questions(
            repetitive,
            "history",
            "আধুনিক ভারত",
            allowed_source_ids=set(source_topics),
            allowed_source_topics=source_topics,
            required_source_diversity=4,
            required_topic_diversity=4,
        )


def test_grounded_pack_rejects_one_overused_fact(valid_questions):
    rows = deepcopy(valid_questions)
    source_topics = {}
    distribution = (0, 0, 0, 0, 1, 1, 2, 2, 3, 3)
    for row, index in zip(rows, distribution, strict=True):
        source_id = f"22222222-2222-4222-8222-{index + 1:012d}"
        topic_id = f"11111111-1111-4111-8111-{index + 1:012d}"
        topic_key = f"history:modern-india:topic-{index + 1}"
        row["source_document_id"] = source_id
        row["micro_topic_id"] = topic_id
        row["micro_topic_key"] = topic_key
        source_topics[source_id] = (topic_id, topic_key)

    with pytest.raises(QuizValidationError, match="source facts are not balanced"):
        validate_questions(
            rows,
            "history",
            "আধুনিক ভারত",
            allowed_source_ids=set(source_topics),
            allowed_source_topics=source_topics,
            required_source_diversity=4,
            required_topic_diversity=4,
        )


def test_grounded_pack_rejects_rephrased_question_with_same_source_answer(
    valid_questions,
):
    rows = deepcopy(valid_questions)
    rows[1]["question"] = (
        "একই যাচাইকৃত তথ্যটি অন্যভাবে জানতে চাওয়া হয়েছে কোন বিকল্পে?"
    )
    rows[1]["options"][rows[1]["correct_index"]] = rows[0]["options"][
        rows[0]["correct_index"]
    ]

    with pytest.raises(QuizValidationError, match="question-answer relationship"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_unverified_question_is_rejected(valid_questions):
    rows = deepcopy(valid_questions)
    rows[0]["verification_status"] = "generated"
    with pytest.raises(QuizValidationError, match="not independently verified"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_content_checksum_is_stable_and_content_sensitive(valid_questions):
    first = content_checksum("20260710-history", "history", "আধুনিক ভারত", valid_questions)
    second = content_checksum("20260710-history", "history", "আধুনিক ভারত", deepcopy(valid_questions))
    changed = deepcopy(valid_questions)
    changed[0]["correct_index"] = 3
    assert first == second
    assert first != content_checksum("20260710-history", "history", "আধুনিক ভারত", changed)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("correct_index", 1),
        ("options", ["পরিবর্তিত বিকল্প", "বিকল্প 0-1", "বিকল্প 0-2", "বিকল্প 0-3"]),
        ("source_url", "https://ncert.nic.in/history/corrected-example"),
        ("explanation", "এটি সংশোধিত ও উৎস-সমর্থিত বাংলা ব্যাখ্যা।"),
    ],
)
def test_same_stem_changed_content_creates_distinct_immutable_hash(
    valid_questions, field, value
):
    original = validate_questions(
        valid_questions, "history", "আধুনিক ভারত", enforce_composition=False
    )[0]
    changed_rows = deepcopy(valid_questions)
    changed_rows[0][field] = value
    changed = validate_questions(
        changed_rows, "history", "আধুনিক ভারত", enforce_composition=False
    )[0]
    assert changed["stem_hash"] == original["stem_hash"]
    assert changed["content_hash"] != original["content_hash"]
    assert changed["question_id"] != original["question_id"]


def test_identical_content_reuses_the_same_hash(valid_questions):
    first = validate_questions(valid_questions, "history", "আধুনিক ভারত")[0]
    repeated = validate_questions(
        deepcopy(valid_questions), "history", "আধুনিক ভারত"
    )[0]
    assert repeated["stem_hash"] == first["stem_hash"]
    assert repeated["content_hash"] == first["content_hash"]
    assert repeated["question_id"] == first["question_id"]


def test_required_difficulty_distribution_is_enforced(valid_questions):
    rows = deepcopy(valid_questions)
    for row in rows:
        row["difficulty"] = "medium"
    with pytest.raises(QuizValidationError, match="difficulty distribution"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_correct_answer_positions_must_be_balanced(valid_questions):
    rows = deepcopy(valid_questions)
    for row in rows:
        row["correct_index"] = 0
    with pytest.raises(QuizValidationError, match="balanced"):
        validate_questions(rows, "history", "আধুনিক ভারত")


def test_answer_position_randomization_preserves_answers_and_balances_positions(
    valid_questions,
):
    original = deepcopy(valid_questions)
    original_answers = [
        row["options"][row["correct_index"]]
        for row in original
    ]

    balanced = randomize_balanced_answer_positions(
        original,
        rng=Random(20260727),
    )

    assert original == valid_questions
    assert sorted(
        sum(row["correct_index"] == position for row in balanced)
        for position in range(4)
    ) == [2, 2, 3, 3]
    assert [
        row["options"][row["correct_index"]]
        for row in balanced
    ] == original_answers
    validate_questions(balanced, "history", "আধুনিক ভারত")


def test_answer_position_randomization_is_repeatable_with_injected_rng(
    valid_questions,
):
    first = randomize_balanced_answer_positions(
        valid_questions,
        rng=Random(42),
    )
    second = randomize_balanced_answer_positions(
        valid_questions,
        rng=Random(42),
    )
    assert first == second


def test_answer_position_randomization_removes_stale_version_fields(
    valid_questions,
):
    clean = validate_questions(valid_questions, "history", "আধুনিক ভারত")
    balanced = randomize_balanced_answer_positions(clean, rng=Random(42))

    for row in balanced:
        assert {
            "content_hash",
            "question_hash",
            "question_id",
            "stem_hash",
        }.isdisjoint(row)
