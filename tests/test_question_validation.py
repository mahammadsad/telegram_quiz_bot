from copy import deepcopy

import pytest

from services.question_validation import QuizValidationError, content_checksum, validate_questions


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
