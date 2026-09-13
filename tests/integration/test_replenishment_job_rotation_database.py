"""Queue fairness in rollback-only disposable PostgreSQL transactions."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.database_integration


@pytest.fixture
def queue():
    url = os.getenv("TEST_DATABASE_URL", "")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    now = datetime.now(timezone.utc)
    with psycopg.connect(url, row_factory=dict_row) as conn:
        chapter = conn.execute("""
            insert into public.quiz_chapters (subject_key, name, normalized_name, display_order)
            values ('mathematics', 'Queue rotation test', 'queue rotation test', 99002)
            returning id
        """).fetchone()["id"]
        jobs = []
        for index in range(4):
            topic = conn.execute("""
                insert into public.quiz_micro_topics (chapter_id, key, name, normalized_name)
                values (%s, %s, %s, %s) returning id
            """, (chapter, f"mathematics:rotation-test:{index}", f"Topic {index}", f"topic {index}"))
            job = conn.execute("""
                insert into public.content_replenishment_jobs
                    (logical_date, subject_key, micro_topic_id, due_at)
                values (%s, 'mathematics', %s, %s) returning id
            """, (now.date(), topic.fetchone()["id"], now - timedelta(days=5-index)))
            jobs.append(job.fetchone()["id"])
        try:
            yield conn, now, jobs
        finally:
            conn.rollback()


def _claim(conn, now, limit=1):
    return conn.execute(
        "select * from public.claim_content_replenishment_jobs('rotation-test', %s, 20, %s)",
        (now, limit),
    ).fetchall()


def _reject(conn, job_id, now):
    conn.execute("""
        select public.complete_content_replenishment_batch(
            %s, 'rotation-test', 0, 5, array['answer_not_unique'], 'content_rejected', %s)
    """, (job_id, now - timedelta(seconds=1)))


@pytest.mark.parametrize("legacy", [False, True])
def test_rejected_oldest_job_does_not_repeat_before_other_eligible_targets(queue, legacy):
    conn, now, jobs = queue
    if legacy:
        # Install the pinned old function only inside this rollback-only test
        # transaction. Exclude its unrelated platform-contract migration.
        source = Path(__file__).resolve().parents[2] / "supabase/migrations/20260904172137_reserve_tier_round_robin_claims.sql"
        conn.execute(source.read_text().split("\nalter function public.get_platform_contract_v1()")[0])
    observed = []
    for _ in range(8):
        job = _claim(conn, now)[0]
        observed.append(job["id"])
        _reject(conn, job["id"], now)
    # All event timestamps are equal in this transaction. Durable event IDs
    # must break the tie, including the second complete rotation.
    assert observed == ([jobs[0]] * 8 if legacy else jobs + jobs)
    rows = conn.execute("""
        select retry_count, rejected_count from public.content_replenishment_jobs
        where id = any(%s)
    """, (jobs,)).fetchall()
    if not legacy:
        assert all(row == {"retry_count": 2, "rejected_count": 10} for row in rows)


def test_claim_history_survives_completion_clearing_claim_timestamp(queue):
    conn, now, jobs = queue
    first = _claim(conn, now)[0]
    _reject(conn, first["id"], now)
    assert conn.execute(
        "select claimed_at from public.content_replenishment_jobs where id = %s", (jobs[0],)
    ).fetchone()["claimed_at"] is None
    assert _claim(conn, now)[0]["id"] == jobs[1]


def test_rotation_keeps_future_retries_due_times_and_active_leases_out(queue):
    conn, now, jobs = queue
    conn.execute("""
        update public.content_replenishment_jobs set status='retry_wait', next_retry_at=%s
        where id=%s
    """, (now + timedelta(hours=1), jobs[0]))
    conn.execute("""
        update public.content_replenishment_jobs set status='claimed', worker_id='other',
            claimed_at=%s, lease_expires_at=%s where id=%s
    """, (now, now + timedelta(minutes=20), jobs[1]))
    conn.execute(
        "update public.content_replenishment_jobs set due_at=%s where id=%s",
        (now + timedelta(hours=1), jobs[2]),
    )
    assert [row["id"] for row in _claim(conn, now, 25)] == [jobs[3]]


def test_expired_claim_is_still_recoverable(queue):
    conn, now, jobs = queue
    conn.execute("""
        update public.content_replenishment_jobs set status='claimed', worker_id='old',
            claimed_at=%s, lease_expires_at=%s where id=%s
    """, (now - timedelta(hours=1), now - timedelta(minutes=1), jobs[0]))
    recovered = _claim(conn, now)[0]
    assert recovered["id"] == jobs[0]
    assert recovered["worker_id"] == "rotation-test"
    assert recovered["lease_expires_at"] == now + timedelta(minutes=20)


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_rotation_rpc_remains_private(queue, role):
    conn, _, _ = queue
    assert not conn.execute("""
        select has_function_privilege(%s,
            'public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)',
            'EXECUTE') as allowed
    """, (role,)).fetchone()["allowed"]
