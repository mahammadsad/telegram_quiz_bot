from __future__ import annotations

import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import dataclass

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from config.source_rollout import ROTATION_CHAPTER_KEYS
from database.contract import (
    DATABASE_CONTRACT_VERSION,
    LEADERBOARD_PRIVACY_MIGRATION_VERSION,
    PERSONAL_LEARNING_MIGRATION_VERSION,
    QUIZ_QUALITY_MIGRATION_VERSION,
    REQUIRED_MIGRATION_VERSION,
    SOURCE_ROLLOUT_MIGRATION_VERSION,
)
from services.question_validation import content_checksum, validate_questions
from utils.hashing import normalize_text

pytestmark = pytest.mark.database_integration

SOURCE_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
UPDATED_SOURCE_ID = uuid.UUID("33333333-3333-4333-8333-333333333333")
ATTEMPT_ID = uuid.UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
ANONYMOUS_LEADER_ALIAS = re.compile(r"^শিক্ষার্থী [0-9A-F]{12}$")


@dataclass(frozen=True)
class Catalogue:
    micro_topic_id: uuid.UUID
    micro_topic_key: str


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


def connect(database_url: str) -> psycopg.Connection:
    return psycopg.connect(database_url, row_factory=dict_row)


@pytest.fixture(scope="module")
def catalogue(database_url: str) -> Catalogue:
    with connect(database_url) as connection:
        chapter = connection.execute(
            """
            select c.id, mt.id as micro_topic_id, mt.key
            from public.quiz_chapters c
            join public.quiz_micro_topics mt on mt.chapter_id = c.id
            where c.subject_key = 'history' and c.name = 'আধুনিক ভারত'
            order by mt.created_at
            limit 1
            """
        ).fetchone()
        assert chapter
        for source_id, source_url, fact_version in (
            (SOURCE_ID, "https://ncert.nic.in/history/integration", "2026-07-18"),
            (
                UPDATED_SOURCE_ID,
                "https://ncert.nic.in/history/integration-corrected",
                "2026-07-22",
            ),
        ):
            connection.execute(
                """
                insert into public.source_documents (
                    id, micro_topic_id, source_url, source_title, source_domain,
                    source_kind, source_accessed_at, fact_summary,
                    verification_status, verification_notes, fact_version,
                    review_required, verified_at
                ) values (
                    %s, %s, %s, 'NCERT ইতিহাসের যাচাইকৃত উৎস', 'ncert.nic.in',
                    'official', '2026-07-18T09:00:00Z',
                    'যাচাইকৃত সরকারি উৎসে প্রশ্নগুলির তথ্য সরাসরি ও স্পষ্টভাবে সমর্থিত।',
                    'verified', 'Integration-test verified source.', %s,
                    false, '2026-07-18T10:00:00Z'
                )
                """,
                (source_id, chapter["micro_topic_id"], source_url, fact_version),
            )
        return Catalogue(chapter["micro_topic_id"], chapter["key"])


def raw_questions(catalogue: Catalogue, *, source_id: uuid.UUID = SOURCE_ID) -> list[dict]:
    source_url = (
        "https://ncert.nic.in/history/integration-corrected"
        if source_id == UPDATED_SOURCE_ID
        else "https://ncert.nic.in/history/integration"
    )
    fact_version = "2026-07-22" if source_id == UPDATED_SOURCE_ID else "2026-07-18"
    return [
        {
            "question": f"ইন্টিগ্রেশন পরীক্ষার ইতিহাস প্রশ্ন নম্বর {index} কী?",
            "options": [f"ইতিহাস বিকল্প {index}-{option}" for option in range(4)],
            "correct_index": index % 4,
            "explanation": "যাচাইকৃত উৎস অনুযায়ী এটি সংক্ষিপ্ত বাংলা ব্যাখ্যা।",
            "detailed_explanation": "যাচাইকৃত সরকারি উৎস অনুযায়ী এটি বিস্তারিত বাংলা ব্যাখ্যা।",
            "subject_key": "history",
            "chapter": "আধুনিক ভারত",
            "difficulty": "easy" if index < 3 else "medium" if index < 8 else "hard",
            "micro_topic_id": str(catalogue.micro_topic_id),
            "micro_topic_key": catalogue.micro_topic_key,
            "source_document_id": str(source_id),
            "source_url": source_url,
            "source_title": "NCERT ইতিহাসের যাচাইকৃত উৎস",
            "source_domain": "ncert.nic.in",
            "source_kind": "official",
            "source_published_at": None,
            "source_accessed_at": "2026-07-18T09:00:00Z",
            "evidence_summary": "যাচাইকৃত সরকারি উৎসে প্রশ্নগুলির তথ্য সরাসরি ও স্পষ্টভাবে সমর্থিত।",
            "fact_version": fact_version,
            "language": "bn",
            "verification_status": "verified",
            "verification_score": 0.95,
            "verification_notes": "All source-grounded checks passed.",
            "verification_checks": {"correct_answer_supported": True},
            "verified_at": "2026-07-18T10:00:00Z",
            "verification_model": "integration-verifier",
        }
        for index in range(10)
    ]


def atomic_rows(raw: list[dict]) -> tuple[list[dict], list[dict]]:
    clean = validate_questions(raw, "history", "আধুনিক ভারত")
    rows = []
    for question in clean:
        rows.append(
            {
                "question_text": question["question"],
                "option_a": question["options"][0],
                "option_b": question["options"][1],
                "option_c": question["options"][2],
                "option_d": question["options"][3],
                "correct_option": "ABCD"[question["correct_index"]],
                "explanation": question["explanation"],
                "detailed_explanation": question["detailed_explanation"],
                "subject": question["subject_key"],
                "topic": question["chapter"],
                "difficulty": question["difficulty"],
                "language": question["language"],
                "source": "verified_source",
                "bot_type": "mock_test",
                "question_hash": question["stem_hash"],
                "stem_hash": question["stem_hash"],
                "content_hash": question["content_hash"],
                "normalized_text": normalize_text(question["question"]),
                "micro_topic_id": question["micro_topic_id"],
                "micro_topic_key": question["micro_topic_key"],
                "source_document_id": question["source_document_id"],
                "source_url": question["source_url"],
                "source_title": question["source_title"],
                "source_domain": question["source_domain"],
                "source_kind": question["source_kind"],
                "source_published_at": question["source_published_at"],
                "source_accessed_at": question["source_accessed_at"],
                "evidence_summary": question["evidence_summary"],
                "fact_version": question["fact_version"],
                "verification_status": question["verification_status"],
                "verification_score": question["verification_score"],
                "verification_notes": question["verification_notes"],
                "verification_checks": question["verification_checks"],
                "verified_at": question["verified_at"],
                "verification_model": question["verification_model"],
            }
        )
    return clean, rows


def save_quiz(
    database_url: str,
    quiz_id: str,
    quiz_date: str,
    raw: list[dict],
    *,
    worker_id: str,
) -> dict:
    clean, rows = atomic_rows(raw)
    checksum = content_checksum(quiz_id, "history", "আধুনিক ভারত", clean)
    with connect(database_url) as connection:
        connection.execute(
            """
            insert into public.quiz_runs (
                quiz_id, quiz_date, subject_key, subject_display_name,
                internal_subject, chapter, status, worker_id, claimed_at,
                claim_expires_at
            ) values (
                %s, %s, 'history', 'ইতিহাস', 'History', 'আধুনিক ভারত',
                'generating', %s, now(), now() + interval '20 minutes'
            )
            """,
            (quiz_id, quiz_date, worker_id),
        )
        result = connection.execute(
            "select public.save_quiz_pack_atomic(%s, %s, %s, %s, false) as result",
            (quiz_id, worker_id, Jsonb(rows), checksum),
        ).fetchone()["result"]
        assert result["ready"] is True
        assert result["generated_checksum"] == checksum
        assert result["persisted_checksum"] == checksum
        return result


@pytest.fixture(scope="module")
def versioned_quizzes(database_url: str, catalogue: Catalogue) -> dict:
    original = raw_questions(catalogue)
    save_quiz(
        database_url,
        "20260601-history",
        "2026-06-01",
        original,
        worker_id="version-worker-1",
    )

    corrected = deepcopy(original)
    corrected[0]["correct_index"] = 1
    # Keep the required 3/3/2/2 answer-position distribution after correcting
    # question 0's answer key.
    corrected[9]["correct_index"] = 0
    corrected[1]["options"][3] = "সংশোধিত চতুর্থ ইতিহাস বিকল্প"
    corrected[2]["explanation"] = "উৎস অনুযায়ী সংশোধিত সংক্ষিপ্ত বাংলা ব্যাখ্যা।"
    source_update = raw_questions(catalogue, source_id=UPDATED_SOURCE_ID)[3]
    corrected[3].update(
        {
            key: source_update[key]
            for key in (
                "source_document_id",
                "source_url",
                "source_title",
                "source_domain",
                "source_kind",
                "source_published_at",
                "source_accessed_at",
                "evidence_summary",
                "fact_version",
            )
        }
    )
    save_quiz(
        database_url,
        "20260602-history",
        "2026-06-02",
        corrected,
        worker_id="version-worker-2",
    )
    with connect(database_url) as connection:
        before_repeat = connection.execute(
            "select count(*) as count from public.questions"
        ).fetchone()["count"]
    save_quiz(
        database_url,
        "20260603-history",
        "2026-06-03",
        deepcopy(corrected),
        worker_id="version-worker-3",
    )
    return {
        "original": original,
        "corrected": corrected,
        "countBeforeRepeat": before_repeat,
    }


def test_exact_database_contract_and_permissions(database_url: str) -> None:
    with connect(database_url) as connection:
        contract = connection.execute(
            "select public.get_application_schema_contract() as contract"
        ).fetchone()["contract"]
        privacy_contract = connection.execute(
            "select public.get_leaderboard_privacy_contract() as contract"
        ).fetchone()["contract"]
    assert contract["ready"] is True
    assert contract["contract_version"] == DATABASE_CONTRACT_VERSION
    assert contract["required_migration_version"] == REQUIRED_MIGRATION_VERSION
    assert (
        contract["source_rollout_migration_version"]
        == SOURCE_ROLLOUT_MIGRATION_VERSION
    )
    assert contract["source_rollout_migration_applied"] is True
    assert contract["source_backed_rotation_ready"] is True
    assert isinstance(contract["source_coverage_ready"], bool)
    assert (
        contract["quiz_quality_migration_version"]
        == QUIZ_QUALITY_MIGRATION_VERSION
    )
    assert contract["quiz_quality_migration_applied"] is True
    assert contract["diverse_grounding_ready"] is True
    assert contract["negative_marking_ready"] is True
    assert (
        contract["personal_learning_migration_version"]
        == PERSONAL_LEARNING_MIGRATION_VERSION
    )
    assert contract["personal_learning_migration_applied"] is True
    assert contract["personal_learning_projection_ready"] is True
    for key in (
        "missing_tables",
        "missing_columns",
        "missing_indexes",
        "missing_triggers",
        "missing_functions",
        "function_permission_failures",
        "function_configuration_failures",
        "schema_permission_failures",
        "missing_rls",
        "table_permission_failures",
    ):
        assert contract[key] == []
    assert privacy_contract["ready"] is True
    assert privacy_contract["leaderboard_privacy_migration_version"] == (
        LEADERBOARD_PRIVACY_MIGRATION_VERSION
    )
    assert privacy_contract["leaderboard_privacy_migration_applied"] is True
    for key in (
        "missing_functions",
        "unsafe_function_definitions",
        "missing_identity_markers",
        "function_configuration_failures",
        "function_permission_failures",
    ):
        assert privacy_contract[key] == []


def test_database_rotation_is_exactly_the_reviewed_source_allowlist(
    database_url: str,
) -> None:
    expected = {
        key
        for chapter_keys in ROTATION_CHAPTER_KEYS.values()
        for key in chapter_keys
    }
    with connect(database_url) as connection:
        rows = connection.execute(
            """
            select key
            from public.quiz_chapters
            where active and rotation_enabled
            order by key
            """
        ).fetchall()

    assert {row["key"] for row in rows} == expected


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_browser_roles_cannot_read_private_tables_or_call_service_rpcs(
    database_url: str, role: str
) -> None:
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(f"set role {role}")
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("select count(*) from public.quiz_attempts")
        finally:
            connection.execute("reset role")

    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(f"set role {role}")
        try:
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("select public.get_application_schema_contract()")
        finally:
            connection.execute("reset role")


def test_service_role_can_execute_the_authoritative_contract(database_url: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row, autocommit=True) as connection:
        connection.execute("set role service_role")
        try:
            contract = connection.execute(
                "select public.get_application_schema_contract() as contract"
            ).fetchone()["contract"]
        finally:
            connection.execute("reset role")
    assert contract["ready"] is True


def test_dashboard_and_due_reviews_preserve_object_response_shape(
    database_url: str,
    versioned_quizzes: dict,
) -> None:
    del versioned_quizzes
    with connect(database_url) as connection:
        user_id = connection.execute(
            """
            insert into public.users (telegram_id, first_name)
            values (%s, 'Projection test') returning id
            """,
            (9_000_000_000 + uuid.uuid4().int % 8_000_000_000,),
        ).fetchone()["id"]
        question_id = connection.execute(
            """
            select question_id
            from public.quiz_questions
            where quiz_id = '20260602-history'
            order by question_order
            limit 1
            """
        ).fetchone()["question_id"]
        connection.execute(
            """
            select public.advance_personal_review_schedule_v2(
                %s, %s, false, 'quiz', 12, false
            )
            """,
            (user_id, question_id),
        )
        dashboard = connection.execute(
            "select public.get_user_learning_dashboard(%s) as payload",
            (user_id,),
        ).fetchone()["payload"]
        due = connection.execute(
            "select public.get_user_due_reviews(%s, 100, 0) as payload",
            (user_id,),
        ).fetchone()["payload"]
        connection.rollback()

    assert isinstance(dashboard, dict)
    assert dashboard["revisionDueToday"] == 1
    assert isinstance(dashboard["subjectPerformance"], list)
    assert isinstance(dashboard["subjectRevisionCounts"], list)
    assert dashboard["subjectRevisionCounts"][0]["subjectKey"] == "history"
    assert isinstance(due, dict)
    assert due["mode"] == "revision"
    assert due["sourceType"] == "due"
    assert due["total"] >= 1
    assert due["rows"][0]["subjectKey"] == "history"


def test_same_stem_versions_and_identical_reuse(
    database_url: str, versioned_quizzes: dict
) -> None:
    clean, _ = atomic_rows(versioned_quizzes["original"])
    stems = [row["stem_hash"] for row in clean[:4]]
    with connect(database_url) as connection:
        versions = connection.execute(
            """
            select stem_hash, array_agg(content_version order by content_version) as versions
            from public.questions where stem_hash = any(%s)
            group by stem_hash
            """,
            (stems,),
        ).fetchall()
        after_repeat = connection.execute(
            "select count(*) as count from public.questions"
        ).fetchone()["count"]
        repeated_ids = connection.execute(
            """
            select a.question_id = b.question_id as reused
            from public.quiz_questions a
            join public.quiz_questions b on b.question_order = a.question_order
            where a.quiz_id = '20260602-history' and b.quiz_id = '20260603-history'
            """
        ).fetchall()
    assert {tuple(row["versions"]) for row in versions} == {(1, 2)}
    assert after_repeat == versioned_quizzes["countBeforeRepeat"]
    assert len(repeated_ids) == 10 and all(row["reused"] for row in repeated_ids)


def test_concurrent_generation_serializes_same_stem_versions(
    database_url: str, versioned_quizzes: dict
) -> None:
    first = deepcopy(versioned_quizzes["corrected"])
    second = deepcopy(versioned_quizzes["corrected"])
    first[0]["explanation"] = "সমসাময়িক সংস্করণ ক-এর যাচাইকৃত বাংলা ব্যাখ্যা।"
    second[0]["explanation"] = "সমসাময়িক সংস্করণ খ-এর যাচাইকৃত বাংলা ব্যাখ্যা।"
    barrier = threading.Barrier(2)

    def save(args: tuple[str, str, list[dict], str]) -> dict:
        barrier.wait()
        return save_quiz(database_url, args[0], args[1], args[2], worker_id=args[3])

    jobs = (
        ("20260604-history", "2026-06-04", first, "concurrent-worker-a"),
        ("20260605-history", "2026-06-05", second, "concurrent-worker-b"),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, jobs))
    stem_hash = atomic_rows(first)[0][0]["stem_hash"]
    with connect(database_url) as connection:
        versions = connection.execute(
            """
            select array_agg(content_version order by content_version) as versions
            from public.questions where stem_hash = %s
            """,
            (stem_hash,),
        ).fetchone()["versions"]
    assert all(result["ready"] for result in results)
    assert versions == [1, 2, 3, 4]


@pytest.fixture(scope="module")
def attempted_quiz(database_url: str, versioned_quizzes: dict) -> dict:
    del versioned_quizzes
    users = []
    with connect(database_url) as connection:
        for telegram_id, first_name in ((900001, "প্রথম"), (900002, "দ্বিতীয়")):
            users.append(
                connection.execute(
                    """
                    insert into public.users (telegram_id, first_name)
                    values (%s, %s) returning id
                    """,
                    (telegram_id, first_name),
                ).fetchone()["id"]
            )
    return {"quizId": "20260602-history", "users": users}


def submit_attempt(
    database_url: str,
    quiz_id: str,
    user_id: uuid.UUID,
    attempt_id: uuid.UUID,
    answers: list[int | None],
) -> dict:
    with connect(database_url) as connection:
        return connection.execute(
            """
            select public.submit_quiz_attempt_atomic(
                %s, %s, %s, %s, 120, null, null
            ) as result
            """,
            (quiz_id, user_id, attempt_id, Jsonb(answers)),
        ).fetchone()["result"]


def test_concurrent_duplicate_submission_is_idempotent(
    database_url: str, attempted_quiz: dict
) -> None:
    barrier = threading.Barrier(2)

    def submit_once() -> dict:
        barrier.wait()
        return submit_attempt(
            database_url,
            attempted_quiz["quizId"],
            attempted_quiz["users"][0],
            ATTEMPT_ID,
            [0] * 10,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: submit_once(), range(2)))
    with connect(database_url) as connection:
        count = connection.execute(
            """
            select count(*) as count from public.quiz_attempts
            where user_id = %s and client_attempt_uuid = %s
            """,
            (attempted_quiz["users"][0], ATTEMPT_ID),
        ).fetchone()["count"]
    assert count == 1
    assert {row["idempotentReplay"] for row in results} == {False, True}
    assert results[0]["attemptId"] == results[1]["attemptId"]


def test_attempt_result_recovery_is_scoped_to_the_authenticated_owner(
    database_url: str, attempted_quiz: dict
) -> None:
    with connect(database_url) as connection:
        owned = connection.execute(
            """
            select public.get_quiz_attempt_result_for_client(%s, %s, %s) as result
            """,
            (attempted_quiz["quizId"], attempted_quiz["users"][0], ATTEMPT_ID),
        ).fetchone()["result"]
        not_owned = connection.execute(
            """
            select public.get_quiz_attempt_result_for_client(%s, %s, %s) as result
            """,
            (attempted_quiz["quizId"], attempted_quiz["users"][1], ATTEMPT_ID),
        ).fetchone()["result"]
    assert owned["attemptId"] == str(ATTEMPT_ID)
    assert owned["quizId"] == attempted_quiz["quizId"]
    assert len(owned["review"]) == 10
    assert float(owned["netScore"]) == pytest.approx(
        owned["score"] - owned["incorrect"] * 0.25
    )
    assert float(owned["negativeMarks"]) == pytest.approx(
        owned["incorrect"] * 0.25
    )
    assert owned["markingScheme"] == {
        "rightMarks": 1,
        "wrongPenalty": 0.25,
        "blankMarks": 0,
        "negativeMarking": True,
    }
    assert not_owned is None


def test_retakes_are_new_but_do_not_replace_official_rank(
    database_url: str, attempted_quiz: dict
) -> None:
    second_attempt = submit_attempt(
        database_url,
        attempted_quiz["quizId"],
        attempted_quiz["users"][0],
        uuid.uuid4(),
        [1] * 10,
    )
    other_user = submit_attempt(
        database_url,
        attempted_quiz["quizId"],
        attempted_quiz["users"][1],
        uuid.uuid4(),
        [0, 1, 2, 3, 0, 1, 2, 3, 0, 1],
    )
    with connect(database_url) as connection:
        board = connection.execute(
            "select public.get_quiz_leaderboard_for_user(%s, %s, 1) as board",
            (attempted_quiz["quizId"], attempted_quiz["users"][0]),
        ).fetchone()["board"]
        first_score = connection.execute(
            """
            select score from public.quiz_attempts
            where quiz_id = %s and user_id = %s and attempt_number = 1
            """,
            (attempted_quiz["quizId"], attempted_quiz["users"][0]),
        ).fetchone()["score"]
        weekly = connection.execute(
            """
            select public.get_leaderboard_for_user(
                'weekly_accuracy', null, %s, 1, 0
            ) as board
            """,
            (attempted_quiz["users"][0],),
        ).fetchone()["board"]
        overall = connection.execute(
            """
            select public.get_leaderboard_for_user(
                'overall_rank', null, %s, 10, 0
            ) as board
            """,
            (attempted_quiz["users"][0],),
        ).fetchone()["board"]
    assert second_attempt["attemptNumber"] == 2
    assert other_user["attemptNumber"] == 1
    assert board["rankingScope"] == "first_attempt_only"
    assert board["retakesAffectOfficialRank"] is False
    assert board["markingScheme"]["negativeMarking"] is True
    assert float(board["markingScheme"]["wrongPenalty"]) == pytest.approx(0.25)
    assert board["currentUser"]["isCurrentUser"] is True
    assert float(board["currentUser"]["netScore"]) == pytest.approx(
        board["currentUser"]["score"]
        - board["currentUser"]["incorrect"] * 0.25
    )
    assert board["currentUser"]["rank"] == 2
    assert board["separatorRequired"] is True
    assert weekly["rankingScope"] == "official_first_attempt_only"
    assert weekly["retakesAffectOfficialRank"] is False
    assert weekly["practiceAffectsOfficialRank"] is False
    assert float(weekly["currentUser"]["value"]) == first_score * 10
    assert weekly["currentUser"]["rank"] == 2
    assert weekly["separatorRequired"] is True
    assert float(overall["currentUser"]["value"]) == first_score
    assert overall["currentUser"]["rank"] == 2


def test_public_leaderboards_enforce_reversible_identity_consent(
    database_url: str,
    versioned_quizzes: dict,
) -> None:
    del versioned_quizzes
    connection = connect(database_url)
    quiz_id = "20260603-history"
    private_values: set[str] = set()

    def submit(
        user_id: uuid.UUID,
        answers: list[int],
        duration_seconds: int,
    ) -> dict:
        return connection.execute(
            """
            select public.submit_quiz_attempt_atomic(
                %s, %s, %s, %s, %s, null, null
            ) as result
            """,
            (
                quiz_id,
                user_id,
                uuid.uuid4(),
                Jsonb(answers),
                duration_seconds,
            ),
        ).fetchone()["result"]

    def scalar_values(value: object) -> set[str]:
        if isinstance(value, dict):
            return {
                item for child in value.values() for item in scalar_values(child)
            }
        if isinstance(value, list):
            return {item for child in value for item in scalar_values(child)}
        if value is None or isinstance(value, bool):
            return set()
        return {str(value)}

    def keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return set(value) | {
                item for child in value.values() for item in keys(child)
            }
        if isinstance(value, list):
            return {item for child in value for item in keys(child)}
        return set()

    try:
        correct_rows = connection.execute(
            """
            select q.correct_option
            from public.quiz_questions qq
            join public.questions q on q.id = qq.question_id
            where qq.quiz_id = %s
            order by qq.question_order
            """,
            (quiz_id,),
        ).fetchall()
        correct = ["ABCD".index(row["correct_option"]) for row in correct_rows]
        assert len(correct) == 10

        board_types = (
            "overall_rank",
            "daily_accuracy",
            "weekly_accuracy",
            "monthly_accuracy",
            "subject_accuracy",
            "improvement",
            "consistency",
            "revision_completion",
        )
        baseline_typed_participants = {
            board_type: connection.execute(
                """
                select public.get_leaderboard_for_user(
                    %s, %s, null, 1, 0
                ) as board
                """,
                (
                    board_type,
                    "history" if board_type == "subject_accuracy" else None,
                ),
            ).fetchone()["board"]["participants"]
            for board_type in board_types
        }
        baseline_global_participants = connection.execute(
            "select public.get_global_leaderboard_page(1, 0) as board"
        ).fetchone()["board"]["participants"]

        user_specs = [
            {
                "key": "anonymous",
                "telegram_id": 9_100_000_001,
                "first_name": "PrivateAlpha",
                "last_name": "HiddenAlpha",
                "username": "private_alpha",
                "photo_url": "https://example.invalid/private-alpha.jpg",
                "public_display_name": None,
                "username_visible": False,
                "leaderboard_visible": True,
            },
            {
                "key": "display",
                "telegram_id": 9_100_000_002,
                "first_name": "PrivateBeta",
                "last_name": "HiddenBeta",
                "username": "private_beta",
                "photo_url": "https://example.invalid/private-beta.jpg",
                "public_display_name": "স্বেচ্ছায় দেওয়া নাম",
                "username_visible": False,
                "leaderboard_visible": True,
            },
            {
                "key": "username",
                "telegram_id": 9_100_000_003,
                "first_name": "PrivateGamma",
                "last_name": "HiddenGamma",
                "username": "chosen_user",
                "photo_url": "https://example.invalid/private-gamma.jpg",
                "public_display_name": None,
                "username_visible": True,
                "leaderboard_visible": True,
            },
            {
                "key": "hidden",
                "telegram_id": 9_100_000_004,
                "first_name": "PrivateDelta",
                "last_name": "HiddenDelta",
                "username": "private_delta",
                "photo_url": "https://example.invalid/private-delta.jpg",
                "public_display_name": "তালিকা থেকে বাদ",
                "username_visible": True,
                "leaderboard_visible": False,
            },
            {
                "key": "withdrawn",
                "telegram_id": 9_100_000_005,
                "first_name": "PrivateEpsilon",
                "last_name": "HiddenEpsilon",
                "username": "withdraw_user",
                "photo_url": "https://example.invalid/private-epsilon.jpg",
                "public_display_name": "আগের প্রকাশ্য নাম",
                "username_visible": True,
                "leaderboard_visible": True,
            },
        ]
        users: dict[str, uuid.UUID] = {}
        for spec in user_specs:
            user_id = connection.execute(
                """
                insert into public.users (
                    telegram_id, first_name, last_name, username, photo_url,
                    public_display_name, username_visible, leaderboard_visible
                ) values (%s, %s, %s, %s, %s, %s, %s, %s)
                returning id
                """,
                (
                    spec["telegram_id"],
                    spec["first_name"],
                    spec["last_name"],
                    spec["username"],
                    spec["photo_url"],
                    spec["public_display_name"],
                    spec["username_visible"],
                    spec["leaderboard_visible"],
                ),
            ).fetchone()["id"]
            users[str(spec["key"])] = user_id
            private_values.update(
                {
                    str(spec["first_name"]),
                    str(spec["last_name"]),
                    f"{spec['first_name']} {spec['last_name']}",
                    str(spec["photo_url"]),
                    str(user_id),
                    str(spec["telegram_id"]),
                }
            )
            if not spec["username_visible"]:
                private_values.add("@" + str(spec["username"]))

        answer_sets = {
            "anonymous": correct,
            "display": [
                (answer + 1) % 4 if index == 0 else answer
                for index, answer in enumerate(correct)
            ],
            "username": [
                (answer + 1) % 4 if index == 0 else answer
                for index, answer in enumerate(correct)
            ],
            "hidden": correct,
            "withdrawn": [
                (answer + 1) % 4 if index < 2 else answer
                for index, answer in enumerate(correct)
            ],
        }
        durations = {
            "anonymous": 180,
            "display": 200,
            "username": 100,
            "hidden": 60,
            "withdrawn": 150,
        }
        for key, user_id in users.items():
            first = submit(user_id, answer_sets[key], durations[key])
            assert first["attemptNumber"] == 1
            second = submit(user_id, correct, durations[key] + 20)
            assert second["attemptNumber"] == 2

        before_withdrawal = connection.execute(
            """
            select public.get_quiz_leaderboard_for_user_page(
                %s, %s, 10, 0
            ) as board
            """,
            (quiz_id, users["withdrawn"]),
        ).fetchone()["board"]
        assert before_withdrawal["currentUser"]["displayName"] == (
            "আগের প্রকাশ্য নাম"
        )
        assert before_withdrawal["currentUser"]["identitySource"] == (
            "public_display_name"
        )

        connection.execute(
            """
            update public.users
            set public_display_name = null, username_visible = false
            where id = %s
            """,
            (users["withdrawn"],),
        )
        private_values.add("@withdraw_user")

        quiz_board = connection.execute(
            """
            select public.get_quiz_leaderboard_for_user_page(
                %s, %s, 2, 1
            ) as board
            """,
            (quiz_id, users["anonymous"]),
        ).fetchone()["board"]
        quiz_board_again = connection.execute(
            """
            select public.get_quiz_leaderboard_for_user(
                %s, %s, 10
            ) as board
            """,
            (quiz_id, users["anonymous"]),
        ).fetchone()["board"]
        legacy_quiz_page = connection.execute(
            """
            select public.get_quiz_leaderboard_page(%s, 10, 0) as board
            """,
            (quiz_id,),
        ).fetchone()["board"]

        assert quiz_board["participants"] == 4
        assert quiz_board["limit"] == 2
        assert quiz_board["offset"] == 1
        assert [row["rank"] for row in quiz_board["rows"]] == [2, 3]
        assert quiz_board["currentUser"]["rank"] == 1
        assert quiz_board["separatorRequired"] is True
        assert quiz_board["markingScheme"] == {
            "rightMarks": 1,
            "wrongPenalty": 0.25,
            "blankMarks": 0,
            "negativeMarking": True,
        }
        assert float(quiz_board["rows"][0]["netScore"]) == pytest.approx(8.75)
        assert quiz_board["rows"][0]["displayName"] == "@chosen_user"
        assert quiz_board["rows"][1]["displayName"] == "স্বেচ্ছায় দেওয়া নাম"
        assert quiz_board_again["currentUser"]["displayName"] == (
            quiz_board["currentUser"]["displayName"]
        )
        assert ANONYMOUS_LEADER_ALIAS.fullmatch(
            quiz_board["currentUser"]["displayName"]
        )
        assert quiz_board["currentUser"]["initials"] == "শি"
        withdrawn_row = next(
            row
            for row in quiz_board_again["rows"]
            if row["rank"] == 4
        )
        assert withdrawn_row["identitySource"] == "anonymous"
        assert ANONYMOUS_LEADER_ALIAS.fullmatch(withdrawn_row["displayName"])
        assert withdrawn_row["initials"] == "শি"
        assert legacy_quiz_page["participants"] == 4

        typed_boards = []
        for board_type in board_types:
            board = connection.execute(
                """
                select public.get_leaderboard_for_user(
                    %s, %s, %s, 2, 0
                ) as board
                """,
                (
                    board_type,
                    "history" if board_type == "subject_accuracy" else None,
                    users["anonymous"],
                ),
            ).fetchone()["board"]
            typed_boards.append(board)
            assert board["type"] == board_type
            assert board["participants"] == (
                baseline_typed_participants[board_type] + 4
            )
            assert board["limit"] == 2
            assert board["offset"] == 0
            assert board["currentUser"]["isCurrentUser"] is True
            assert ANONYMOUS_LEADER_ALIAS.fullmatch(
                board["currentUser"]["displayName"]
            )

        global_page = connection.execute(
            "select public.get_global_leaderboard_page(2, 1) as board"
        ).fetchone()["board"]
        assert global_page["participants"] == baseline_global_participants + 4
        assert global_page["limit"] == 2
        assert global_page["offset"] == 1

        all_payloads = [
            quiz_board,
            quiz_board_again,
            legacy_quiz_page,
            global_page,
            *typed_boards,
        ]
        exposed_keys = {
            item for payload in all_payloads for item in keys(payload)
        }
        assert not exposed_keys.intersection(
            {
                "telegram_id",
                "telegramId",
                "user_id",
                "userId",
                "first_name",
                "firstName",
                "last_name",
                "lastName",
                "username",
                "photo_url",
                "profilePhotoUrl",
            }
        )
        exposed_values = {
            item for payload in all_payloads for item in scalar_values(payload)
        }
        assert not exposed_values.intersection(private_values)

        privacy_contract = connection.execute(
            "select public.get_leaderboard_privacy_contract() as contract"
        ).fetchone()["contract"]
        assert privacy_contract["ready"] is True
        assert privacy_contract["leaderboard_privacy_migration_version"] == (
            LEADERBOARD_PRIVACY_MIGRATION_VERSION
        )
        assert privacy_contract["missing_functions"] == []
        assert privacy_contract["unsafe_function_definitions"] == []
        assert privacy_contract["missing_identity_markers"] == []
        assert privacy_contract["function_configuration_failures"] == []
        assert privacy_contract["function_permission_failures"] == []
    finally:
        connection.rollback()
        connection.close()


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_public_roles_cannot_execute_leaderboard_privacy_rpcs(
    database_url: str,
    role: str,
) -> None:
    calls = (
        "select public.get_public_leaderboard_identity(null)",
        "select public.get_leaderboard_for_user('overall_rank', null, null, 1, 0)",
        "select public.get_quiz_leaderboard_for_user_page('test', null, 1, 0)",
        "select public.get_leaderboard_privacy_contract()",
    )
    for query in calls:
        with psycopg.connect(database_url, autocommit=True) as connection:
            connection.execute(f"set role {role}")
            try:
                with pytest.raises(psycopg.errors.InsufficientPrivilege):
                    connection.execute(query)
            finally:
                connection.execute("reset role")


def test_revision_schedule_and_idempotent_answer(
    database_url: str, attempted_quiz: dict
) -> None:
    with connect(database_url) as connection:
        question_id = connection.execute(
            """
            select question_id from public.quiz_questions
            where quiz_id = %s and question_order = 8
            """,
            (attempted_quiz["quizId"],),
        ).fetchone()["question_id"]

        revision_id = uuid.uuid4()
        wrong = connection.execute(
            """
            select public.submit_personal_practice_answer(
                %s, %s, %s, 0, 'due', 'revision', 12, false
            ) as result
            """,
            (attempted_quiz["users"][0], question_id, revision_id),
        ).fetchone()["result"]
        replay = connection.execute(
            """
            select public.submit_personal_practice_answer(
                %s, %s, %s, 0, 'due', 'revision', 12, false
            ) as result
            """,
            (attempted_quiz["users"][0], question_id, revision_id),
        ).fetchone()["result"]
        assert wrong["isCorrect"] is False
        assert replay["idempotentReplay"] is True

        # Question 8 has correct option D (index 3).
        intervals = []
        for _ in range(6):
            connection.execute(
                """
                select public.submit_personal_practice_answer(
                    %s, %s, %s, 3, 'due', 'revision', 8, false
                )
                """,
                (attempted_quiz["users"][0], question_id, uuid.uuid4()),
            )
            intervals.append(
                connection.execute(
                    """
                    select review_interval from public.personal_review_schedule
                    where user_id = %s and question_id = %s
                    """,
                    (attempted_quiz["users"][0], question_id),
                ).fetchone()["review_interval"]
            )
        wrong_queue = connection.execute(
            """
            select public.get_user_wrong_questions(%s, 'history', 100, 0) as queue
            """,
            (attempted_quiz["users"][0],),
        ).fetchone()["queue"]
    assert intervals == [1, 3, 7, 14, 30, 60]
    assert wrong_queue["mode"] == "revision"
    assert wrong_queue["sourceType"] == "weak_topic"
    assert question_id not in {
        uuid.UUID(row["questionId"]) for row in wrong_queue["rows"]
    }


def test_uncertified_posted_quiz_cannot_accept_an_attempt(
    database_url: str, attempted_quiz: dict
) -> None:
    with psycopg.connect(database_url, row_factory=dict_row, autocommit=True) as connection:
        connection.execute(
            """
            update public.quiz_runs
            set status = 'posted', integrity_verified = false
            where quiz_id = %s
            """,
            (attempted_quiz["quizId"],),
        )
        try:
            with pytest.raises(psycopg.errors.RaiseException, match="checksum-certified"):
                connection.execute(
                    """
                    select public.submit_quiz_attempt_atomic(
                        %s, %s, %s, %s, 60, null, null
                    )
                    """,
                    (
                        attempted_quiz["quizId"],
                        attempted_quiz["users"][0],
                        uuid.uuid4(),
                        Jsonb([0] * 10),
                    ),
                )
        finally:
            with psycopg.connect(database_url, autocommit=True) as restore:
                restore.execute(
                    """
                    update public.quiz_runs
                    set status = 'ready', integrity_verified = true
                    where quiz_id = %s
                    """,
                    (attempted_quiz["quizId"],),
                )


def test_reports_quarantine_after_distinct_credible_users(
    database_url: str, attempted_quiz: dict
) -> None:
    with connect(database_url) as connection:
        question_id = connection.execute(
            """
            select question_id from public.quiz_questions
            where quiz_id = %s and question_order = 9
            """,
            (attempted_quiz["quizId"],),
        ).fetchone()["question_id"]
        user_attempts = connection.execute(
            """
            select user_id, client_attempt_uuid from public.quiz_attempts
            where quiz_id = %s and attempt_number = 1 order by user_id
            """,
            (attempted_quiz["quizId"],),
        ).fetchall()
        outcomes = []
        for attempt in user_attempts:
            outcomes.append(
                connection.execute(
                    """
                    select public.submit_question_report(
                        %s, %s, %s, %s, 'ambiguous', 'দুটি উত্তর অস্পষ্ট।', 2
                    ) as result
                    """,
                    (
                        question_id,
                        attempted_quiz["quizId"],
                        attempt["user_id"],
                        attempt["client_attempt_uuid"],
                    ),
                ).fetchone()["result"]
            )
    assert outcomes[-1]["quarantined"] is True
    assert outcomes[-1]["credibleReportCount"] == 2


def test_revision_report_is_attempt_owned_and_idempotent(
    database_url: str, attempted_quiz: dict
) -> None:
    with connect(database_url) as connection:
        question_id = connection.execute(
            """
            select question_id from public.quiz_questions
            where quiz_id = %s and question_order = 7
            """,
            (attempted_quiz["quizId"],),
        ).fetchone()["question_id"]
        revision_id = uuid.uuid4()
        connection.execute(
            """
            select public.submit_personal_practice_answer(
                %s, %s, %s, 0, 'due', 'revision', 9, false
            )
            """,
            (attempted_quiz["users"][0], question_id, revision_id),
        )
        accepted = connection.execute(
            """
            select public.submit_practice_question_report(
                %s, %s, %s, 'broken_source', 'উৎসটি খোলা যাচ্ছে না।', 3
            ) as result
            """,
            (question_id, attempted_quiz["users"][0], revision_id),
        ).fetchone()["result"]
    assert accepted["status"] == "accepted"

    with psycopg.connect(
        database_url,
        row_factory=dict_row,
        autocommit=True,
    ) as connection, pytest.raises(
        psycopg.errors.RaiseException,
        match="already reported for this revision attempt",
    ):
        connection.execute(
            """
            select public.submit_practice_question_report(
                %s, %s, %s, 'broken_source', 'আবার পাঠানো।', 3
            )
            """,
            (question_id, attempted_quiz["users"][0], revision_id),
        )
