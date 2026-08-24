from __future__ import annotations

import os
from datetime import date, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

pytestmark = pytest.mark.database_integration


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured")
    return value


def test_versioned_consent_idempotency_opt_out_and_private_metrics(database_url: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        user_id = connection.execute(
            """
            insert into public.users (telegram_id, first_name)
            values (980001, 'Reminder test') returning id
            """
        ).fetchone()["id"]

        consent = connection.execute(
            """
            select public.set_learner_reminder_consent(
                %s, true, 'reminder-consent-v1', 'settings', 'Asia/Kolkata',
                '19:00'::time, '21:00'::time, '08:00'::time, false
            ) as result
            """,
            (user_id,),
        ).fetchone()["result"]
        assert consent["enabled"] is True
        assert consent["deliveryAvailable"] is False

        logical_date = date.today()
        first = connection.execute(
            "select public.queue_learner_reminder(%s, %s, 'daily_study', now() - interval '1 second') as result",
            (user_id, logical_date),
        ).fetchone()["result"]
        replay = connection.execute(
            "select public.queue_learner_reminder(%s, %s, 'daily_study', now() - interval '1 second') as result",
            (user_id, logical_date),
        ).fetchone()["result"]
        assert replay["deliveryId"] == first["deliveryId"]
        assert connection.execute(
            "select count(*) as count from public.learner_reminder_deliveries where user_id = %s",
            (user_id,),
        ).fetchone()["count"] == 1

        claimed = connection.execute(
            "select public.claim_due_learner_reminders('integration-worker', 25) as result"
        ).fetchone()["result"]
        assert first["deliveryId"] in {row["deliveryId"] for row in claimed["items"]}

        with pytest.raises(psycopg.errors.RaiseException):
            with connection.transaction():
                connection.execute(
                    """
                    select public.complete_learner_reminder_delivery(
                        %s, 'integration-worker', 'retry_wait', null,
                        'rate_limited', 10
                    )
                    """,
                    (first["deliveryId"],),
                )

        retried = connection.execute(
            """
            select public.complete_learner_reminder_delivery(
                %s, 'integration-worker', 'retry_wait', null,
                'rate_limited', 30
            ) as result
            """,
            (first["deliveryId"],),
        ).fetchone()["result"]
        assert retried["state"] == "retry_wait"

        queued = connection.execute(
            "select public.queue_learner_reminder(%s, %s, 'daily_study', now()) as result",
            (user_id, logical_date + timedelta(days=1)),
        ).fetchone()["result"]
        disabled = connection.execute(
            """
            select public.set_learner_reminder_consent(
                %s, false, null, null, 'Asia/Kolkata',
                '19:00'::time, '21:00'::time, '08:00'::time, false
            ) as result
            """,
            (user_id,),
        ).fetchone()["result"]
        assert disabled["enabled"] is False
        states = connection.execute(
            "select id, state from public.learner_reminder_deliveries where user_id = %s",
            (user_id,),
        ).fetchall()
        assert {str(row["id"]): row["state"] for row in states}[queued["deliveryId"]] == "cancelled"
        assert {row["state"] for row in states} == {"cancelled"}

        metrics = connection.execute(
            "select public.get_learner_reminder_delivery_metrics(%s, %s) as result",
            (logical_date, logical_date + timedelta(days=1)),
        ).fetchone()["result"]
        assert metrics["rows"]
        assert "userId" not in str(metrics)
        assert "deliveryId" not in str(metrics)


def test_synthetic_scope_and_permanent_chat_suppression(database_url: str) -> None:
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        user_id = connection.execute(
            """
            insert into public.users (telegram_id, first_name)
            values (980002, 'Synthetic canary') returning id
            """
        ).fetchone()["id"]

        with pytest.raises(psycopg.errors.RaiseException):
            with connection.transaction():
                connection.execute(
                    """
                    select public.set_learner_reminder_consent(
                        %s, true, 'reminder-consent-v1', 'settings', 'Asia/Kolkata',
                        '19:00'::time, '21:00'::time, '08:00'::time, true
                    )
                    """,
                    (user_id,),
                )

        connection.execute(
            """
            select public.set_learner_reminder_consent(
                %s, true, 'reminder-consent-v1', 'synthetic_canary', 'Asia/Kolkata',
                '19:00'::time, '21:00'::time, '08:00'::time, true
            )
            """,
            (user_id,),
        )
        with pytest.raises(psycopg.errors.RaiseException):
            with connection.transaction():
                connection.execute(
                    "select public.queue_learner_reminder(%s, current_date, 'daily_study', now())",
                    (user_id,),
                )

        delivery = connection.execute(
            "select public.queue_learner_reminder(%s, current_date, 'synthetic_canary', now() - interval '1 second') as result",
            (user_id,),
        ).fetchone()["result"]
        connection.execute("select public.claim_due_learner_reminders('canary-worker', 25)")
        failed = connection.execute(
            """
            select public.complete_learner_reminder_delivery(
                %s, 'canary-worker', 'failed', null, 'telegram_blocked', null
            ) as result
            """,
            (delivery["deliveryId"],),
        ).fetchone()["result"]
        assert failed["state"] == "failed"
        consent = connection.execute(
            "select public.get_learner_reminder_consent(%s) as result",
            (user_id,),
        ).fetchone()["result"]
        assert consent["enabled"] is False

        contract = connection.execute(
            "select public.get_reminder_delivery_contract() as result"
        ).fetchone()["result"]
        assert contract == {
            "ready": True,
            "migrationVersion": "20260824033823",
            "consentPolicyVersion": "reminder-consent-v1",
            "deliveryEnabled": False,
            "answerFreePayload": True,
            "maxAttempts": 5,
            "maxClaimBatch": 100,
        }
