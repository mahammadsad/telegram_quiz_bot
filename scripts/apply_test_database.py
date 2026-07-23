"""Build a disposable PostgreSQL database from bootstrap plus every migration.

This command is intentionally destructive and refuses to run unless the target
database name starts with ``telegram_quiz_test``. It is for local/CI databases
only; hosted staging and production migrations use the Supabase migration tool.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import psycopg

from database.contract import REQUIRED_MIGRATION_VERSION

ROOT = Path(__file__).resolve().parents[1]
BOOTSTRAP = ROOT / "database" / "schema.sql"
DATABASE_MIGRATIONS = ROOT / "database" / "migrations"
SUPABASE_MIGRATIONS = ROOT / "supabase" / "migrations"
SAFE_DATABASE_PREFIX = "telegram_quiz_test"


def migration_files() -> list[Path]:
    legacy = sorted(DATABASE_MIGRATIONS.glob("*.sql"))
    supabase = sorted(SUPABASE_MIGRATIONS.glob("*.sql"))
    return [BOOTSTRAP, *legacy, *supabase]


def _migration_identity(path: Path) -> tuple[str, str] | None:
    if path.parent != SUPABASE_MIGRATIONS:
        return None
    version, name = path.stem.split("_", 1)
    return version, name


def _reset_schemas(connection: psycopg.Connection) -> None:
    database_name = connection.execute("select current_database()").fetchone()[0]
    if not str(database_name).startswith(SAFE_DATABASE_PREFIX):
        raise RuntimeError(
            f"Refusing destructive test reset for database {database_name!r}; "
            f"its name must start with {SAFE_DATABASE_PREFIX!r}."
        )
    connection.execute("drop schema if exists public cascade")
    connection.execute("drop schema if exists extensions cascade")
    connection.execute("drop schema if exists supabase_migrations cascade")
    connection.execute("create schema public")
    connection.execute("create schema extensions")
    connection.execute("create schema supabase_migrations")


def _prepare_roles_and_extensions(connection: psycopg.Connection) -> None:
    connection.execute(
        """
        do $$
        begin
            if not exists (select 1 from pg_roles where rolname = 'anon') then
                create role anon nologin;
            end if;
            if not exists (select 1 from pg_roles where rolname = 'authenticated') then
                create role authenticated nologin;
            end if;
            if not exists (select 1 from pg_roles where rolname = 'service_role') then
                create role service_role nologin bypassrls;
            end if;
        end;
        $$;
        """
    )
    connection.execute("create extension pgcrypto with schema public")
    connection.execute("create extension pg_trgm with schema public")
    # Supabase exposes pgcrypto through extensions, while one historical
    # migration references pg_trgm from public. Support both applied contracts.
    connection.execute(
        """
        create function extensions.digest(bytea, text)
        returns bytea language sql immutable strict parallel safe
        as 'select public.digest($1, $2)';
        create function extensions.digest(text, text)
        returns bytea language sql immutable strict parallel safe
        as 'select public.digest($1, $2)';
        create function extensions.gen_random_uuid()
        returns uuid language sql volatile parallel safe
        as 'select public.gen_random_uuid()';
        """
    )
    connection.execute(
        """
        create table supabase_migrations.schema_migrations (
            version text primary key,
            statements text[],
            name text
        );
        """
    )


def rebuild(database_url: str) -> dict:
    files = migration_files()
    latest_supabase = next(
        path for path in reversed(files) if path.parent == SUPABASE_MIGRATIONS
    )
    identity = _migration_identity(latest_supabase)
    if not identity or identity[0] != REQUIRED_MIGRATION_VERSION:
        raise RuntimeError(
            "The application-required migration does not match the latest migration file."
        )

    with psycopg.connect(database_url, autocommit=True) as connection:
        _reset_schemas(connection)
        _prepare_roles_and_extensions(connection)
        for path in files:
            try:
                with connection.transaction():
                    connection.execute(path.read_text(encoding="utf-8"))
                    identity = _migration_identity(path)
                    if identity:
                        connection.execute(
                            """
                            insert into supabase_migrations.schema_migrations
                                (version, statements, name)
                            values (%s, array[%s], %s)
                            """,
                            (identity[0], path.name, identity[1]),
                        )
            except Exception as exc:
                raise RuntimeError(f"Migration failed: {path.relative_to(ROOT)}") from exc

        contract = connection.execute(
            "select public.get_application_schema_contract()"
        ).fetchone()[0]
        if not contract.get("ready"):
            raise RuntimeError("Disposable database contract is not ready after migrations.")
        return contract


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--database-url",
        default=os.getenv("TEST_DATABASE_URL", ""),
        help="Disposable PostgreSQL connection URL (or set TEST_DATABASE_URL).",
    )
    args = parser.parse_args()
    if not args.database_url:
        parser.error("--database-url or TEST_DATABASE_URL is required")
    contract = rebuild(args.database_url)
    print(
        "Disposable database ready: "
        f"contract={contract['contract_version']} "
        f"migration={contract['required_migration_version']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
