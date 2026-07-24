from __future__ import annotations

import os
import uuid

import psycopg
import pytest

pytestmark = pytest.mark.database_integration


@pytest.fixture(scope="module")
def database_url() -> str:
    value = os.getenv("TEST_DATABASE_URL", "")
    if not value:
        pytest.skip("TEST_DATABASE_URL is not configured for the database integration suite")
    return value


def test_durable_limiter_rejects_after_the_persisted_window_limit(
    database_url: str,
) -> None:
    actor = f"integration:{uuid.uuid4()}"
    with psycopg.connect(database_url, autocommit=True) as connection:
        connection.execute(
            "select public.enforce_write_rate_limit('bookmark', %s, 2, 3600)",
            (actor,),
        )
        connection.execute(
            "select public.enforce_write_rate_limit('bookmark', %s, 2, 3600)",
            (actor,),
        )
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="bookmark rate limit exceeded",
        ):
            connection.execute(
                "select public.enforce_write_rate_limit('bookmark', %s, 2, 3600)",
                (actor,),
            )


def test_durable_limiter_objects_are_private_and_contract_gated(
    database_url: str,
) -> None:
    with psycopg.connect(database_url) as connection:
        row = connection.execute(
            """
            select
                relrowsecurity,
                has_table_privilege(
                    'anon', 'public.write_rate_limit_buckets',
                    'SELECT,INSERT,UPDATE,DELETE'
                ) as anon_table,
                has_table_privilege(
                    'authenticated', 'public.write_rate_limit_buckets',
                    'SELECT,INSERT,UPDATE,DELETE'
                ) as authenticated_table,
                has_function_privilege(
                    'anon',
                    'public.enforce_write_rate_limit(text,text,integer,integer)',
                    'EXECUTE'
                ) as anon_function,
                public.get_application_schema_contract() as contract
            from pg_catalog.pg_class
            where oid = 'public.write_rate_limit_buckets'::regclass
            """
        ).fetchone()

    assert row is not None
    assert row[0] is True
    assert row[1:4] == (False, False, False)
    assert row[4]["ready"] is True
    assert row[4]["required_migration_version"] == "20260724212939"
