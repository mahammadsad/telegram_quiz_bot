from __future__ import annotations

import os
from datetime import datetime, timezone

import psycopg
import pytest
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row

pytestmark = pytest.mark.database_integration


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


def test_replenishment_claims_rotate_across_subject_backlogs(database_url: str) -> None:
    subjects = ("bengali", "computer", "english", "history", "mathematics", "reasoning")
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        for offset, subject in enumerate(subjects):
            connection.execute(
                """
                insert into public.content_replenishment_jobs (
                    logical_date, subject_key, micro_topic_id, due_at
                ) values (date '2001-01-01' + %s, %s, null, %s - interval '1 day')
                """,
                (offset, subject, now),
            )

        first = connection.execute(
            "select * from public.claim_content_replenishment_jobs(%s, %s, 20, 3)",
            ("fairness-worker-1", now),
        ).fetchall()
        first_subjects = {str(row["subject_key"]) for row in first}
        assert len(first_subjects) == 3

        connection.execute(
            """
            update public.content_replenishment_jobs
            set status = 'due', worker_id = null, claimed_at = null,
                lease_expires_at = null
            where worker_id = 'fairness-worker-1'
            """
        )
        second = connection.execute(
            "select * from public.claim_content_replenishment_jobs(%s, %s, 20, 3)",
            ("fairness-worker-2", now),
        ).fetchall()
        second_subjects = {str(row["subject_key"]) for row in second}

        assert len(second_subjects) == 3
        assert first_subjects.isdisjoint(second_subjects)
        assert first_subjects | second_subjects == set(subjects)
        connection.rollback()


def test_only_one_open_replenishment_job_exists_per_target(database_url: str) -> None:
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """
            insert into public.content_replenishment_jobs (
                logical_date, subject_key, micro_topic_id, due_at
            ) values (date '2041-01-01', 'computer', null, %s)
            """,
            (now,),
        )
        with pytest.raises(UniqueViolation):
            with connection.transaction():
                connection.execute(
                    """
                    insert into public.content_replenishment_jobs (
                        logical_date, subject_key, micro_topic_id, due_at
                    ) values (date '2041-01-02', 'computer', null, %s)
                    """,
                    (now,),
                )
        index_ready, duplicate_count = connection.execute(
            """
            select
                to_regclass('public.idx_content_replenishment_one_open_target') is not null,
                count(*)
            from (
                select 1
                from public.content_replenishment_jobs
                where status in ('due', 'claimed', 'running', 'retry_wait')
                group by subject_key, micro_topic_id
                having count(*) > 1
            ) duplicates
            """
        ).fetchone()
        assert index_ready is True
        assert duplicate_count == 0
        connection.rollback()
