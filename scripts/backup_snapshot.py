"""Read-only application snapshot and isolated restore; not a release-gate bypass.

Only public application objects, portable extensions and the migration ledger are
included. Managed Supabase services, credentials and private scheduler state are
NOT included. No private decryption key is available to this workflow.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import psycopg
from psycopg import sql

from scripts import backup_archive as archive

PROJECT = "tizxodkcpglmxgtwepor"
RECIPIENT = "39F3FC1CE7F58FAA4CCB823FCBC34F51F9DA20DC"
IMAGE = "postgres:17@sha256:67f41722b7a8cbdb868a44a4995c846eddfdc2973bccb291ce937dce88ad5675"
DOCKER = ["docker", "--host", "unix:///var/run/docker.sock"]
SCHEMAS = ("public", "supabase_migrations", "extensions")
EXTENSIONS = ("pgcrypto", "pg_trgm", "uuid-ossp")
OPTIONS = ("-c default_transaction_read_only=on -c statement_timeout=30000 "
           "-c lock_timeout=5000 -c idle_in_transaction_session_timeout=360000 "
           "-c timezone=UTC -c datestyle=ISO -c extra_float_digits=3")
RESTORE_OPTIONS = "-c statement_timeout=30000 -c timezone=UTC -c datestyle=ISO -c extra_float_digits=3"
TABLES_SQL = """
SELECT coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname) ORDER BY n.nspname,c.relname),'[]')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('public','supabase_migrations') AND c.relkind='r'
"""
CONTRACT_SQL = """
SELECT jsonb_build_object(
 'application', public.get_application_schema_contract()->'ready',
 'platform', public.get_platform_contract_v1()->'ready',
 'anon_claim', has_function_privilege('anon',
   'public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)', 'EXECUTE'),
 'authenticated_claim', has_function_privilege('authenticated',
   'public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)', 'EXECUTE'),
 'service_claim', has_function_privilege('service_role',
   'public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)', 'EXECUTE'))
"""
EXPECTED_CONTRACT = {"application": True, "platform": True, "anon_claim": False,
                     "authenticated_claim": False, "service_claim": True}
SECURITY_SQL = """
SELECT coalesce(jsonb_agg(jsonb_build_array(n.nspname,c.relname,c.relrowsecurity,
 c.relforcerowsecurity,c.relacl::text) ORDER BY n.nspname,c.relname),'[]')
FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
WHERE n.nspname IN ('public','supabase_migrations') AND c.relkind IN ('r','v','S')
"""


class SnapshotError(Exception):
    """Never expose provider errors, connection strings or row values."""


def clean_environment() -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "LANG": "C.UTF-8"}


def command(arguments, *, timeout=180, **kwargs):
    result = subprocess.run(arguments, env=kwargs.pop("env", clean_environment()),
                            stderr=subprocess.DEVNULL, timeout=timeout, check=False, **kwargs)
    if result.returncode:
        raise SnapshotError("Backup subprocess failed; recovery evidence was not accepted.")
    return result.stdout


def production_connection(uri: str, project_ref: str, password: str) -> dict:
    """Accept only CLI-linked session pooling, never arbitrary libpq parameters."""
    parsed = urlsplit(uri)
    if (project_ref != PROJECT or not password or parsed.scheme != "postgresql"
        or parsed.username != f"postgres.{PROJECT}" or parsed.password is not None
        or parsed.port != 5432 or parsed.path != "/postgres" or parsed.query or parsed.fragment
        or not re.fullmatch(r"aws-[0-9]+-[a-z0-9-]+\.pooler\.supabase\.com", parsed.hostname or "")):
        raise SnapshotError("The exact production session-pooler identity is required.")
    return {"host": parsed.hostname, "port": 5432, "dbname": "postgres",
            "user": parsed.username, "password": password, "connect_timeout": 10,
            "sslmode": "verify-full", "sslrootcert": "/etc/ssl/certs/ca-certificates.crt",
            "options": OPTIONS, "application_name": "citizen-affairs-readonly-backup"}


def workflow_identity(environment) -> dict:
    if (environment.get("GITHUB_ACTIONS") != "true"
        or environment.get("GITHUB_REPOSITORY") != "mahammadsad/telegram_quiz_bot"
        or environment.get("EXPECTED_SUPABASE_PROJECT_REF") != PROJECT
        or environment.get("INPUT_SAFETY_ACK") != f"BACKUP APPLICATION SCHEMAS FOR {PROJECT}"
        or not re.fullmatch(r"[a-f0-9]{40}", environment.get("GITHUB_SHA", ""))
        or not re.fullmatch(r"[1-9][0-9]*", environment.get("GITHUB_RUN_ID", ""))):
        raise SnapshotError("Protected backup workflow identity is not exact.")
    return {"project_ref": PROJECT, "exporter_commit": environment["GITHUB_SHA"],
            "workflow_run_id": environment["GITHUB_RUN_ID"]}


def row_fingerprint_query(schema: str, table: str) -> str:
    # Rows are hashed on the database server; plaintext is never returned to logs
    # or Python. Sorting hashes preserves duplicate and NULL row multiplicity.
    return sql.SQL("SELECT jsonb_build_array(count(*), md5(coalesce("
                   "string_agg(h, '' ORDER BY h COLLATE \"C\"), ''))) FROM "
                   "(SELECT md5(row_to_json(t)::text) h FROM {} t) hashed").format(
                       sql.Identifier(schema, table)).as_string()


def inventory(query) -> dict:
    tables = query(TABLES_SQL)
    if not isinstance(tables, list) or not 1 <= len(tables) <= 200:
        raise SnapshotError("Unexpected application table scope.")
    rows = []
    for pair in tables:
        if (not isinstance(pair, list) or len(pair) != 2 or pair[0] not in SCHEMAS[:2]
            or not isinstance(pair[1], str)):
            raise SnapshotError("Unexpected application table identity.")
        fingerprint = query(row_fingerprint_query(*pair))
        if (not isinstance(fingerprint, list) or len(fingerprint) != 2
            or type(fingerprint[0]) is not int or not 0 <= fingerprint[0] <= 1_000_000
            or not isinstance(fingerprint[1], str) or not re.fullmatch(r"[a-f0-9]{32}", fingerprint[1])):
            raise SnapshotError("Application data fingerprint is invalid.")
        rows.append([*pair, *fingerprint])
    contract = query(CONTRACT_SQL)
    if contract != EXPECTED_CONTRACT:
        raise SnapshotError("Application recovery contracts did not pass.")
    return {"tables": rows, "security": query(SECURITY_SQL), "contract": contract}


@contextmanager
def isolated_restore():
    """No network, bind mounts, hosted secrets or Docker/service log collection."""
    name = "quiz-backup-restore-" + uuid.uuid4().hex
    container = None
    try:
        container = command([
            *DOCKER, "run", "--detach", "--name", name, "--network", "none", "--log-driver", "none",
            "--memory", "1g", "--cpus", "2", "--pids-limit", "256",
            "--security-opt", "no-new-privileges", "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
            IMAGE, "postgres", "-c", "log_statement=none", "-c", "log_min_messages=panic",
            "-c", "log_min_error_statement=panic", "-c", "log_error_verbosity=terse",
        ], stdout=subprocess.PIPE, timeout=60).decode().strip()
        if not re.fullmatch(r"[a-f0-9]{64}", container):
            raise SnapshotError("Disposable restore container identity is invalid.")
        for _ in range(30):
            ready = subprocess.run([*DOCKER, "exec", container, "pg_isready", "-U", "postgres"],
                                   env=clean_environment(), stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL, timeout=5, check=False)
            if ready.returncode == 0:
                break
            time.sleep(1)
        else:
            raise SnapshotError("Disposable restore database did not become ready.")

        def execute(statement: str):
            result = command([*DOCKER, "exec", "-i", "--env", f"PGOPTIONS={RESTORE_OPTIONS}", container,
                              "psql", "-X", "-qAt", "-U", "postgres", "-d", "postgres",
                              "--set", "ON_ERROR_STOP=1"], input=statement.encode(), stdout=subprocess.PIPE,
                             timeout=40)
            return json.loads(result) if result.strip() else None

        # No role passwords or global production grants are exported. These are
        # disconnected local identities for restoring application ACLs only.
        execute("CREATE ROLE anon NOLOGIN; CREATE ROLE authenticated NOLOGIN; "
                "CREATE ROLE service_role NOLOGIN BYPASSRLS; CREATE ROLE supabase_admin NOLOGIN; "
                "CREATE ROLE dashboard_user NOLOGIN; CREATE ROLE supabase_auth_admin NOLOGIN; "
                "CREATE ROLE supabase_storage_admin NOLOGIN;")
        yield container, execute
    finally:
        # Only the random exact container created by this invocation is removed.
        if container and re.fullmatch(r"[a-f0-9]{64}", container):
            command([*DOCKER, "rm", "--force", "--volumes", container], stdout=subprocess.DEVNULL, timeout=30)


def restore_and_compare(dump: Path, expected: dict) -> None:
    with isolated_restore() as (container, query), archive.open_regular(dump, private=True) as source:
        command([*DOCKER, "exec", "-i", container, "pg_restore", "-U", "postgres", "-d", "postgres",
                 "--exit-on-error", "--single-transaction", "--no-owner", "--no-password"],
                stdin=source, stdout=subprocess.DEVNULL, timeout=180)
        if inventory(query) != expected:
            raise SnapshotError("Restored data or security differs from the source snapshot.")


def export_snapshot(connection, dump: Path, dump_command: list[str], dump_environment: dict) -> dict:
    """Caller supplies a fresh connection; the exported snapshot is held briefly."""
    archive.private_directory(dump.parent)
    with connection.transaction():
        connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        connection.execute("SET LOCAL statement_timeout='30s'")
        connection.execute("SET LOCAL lock_timeout='5s'")
        connection.execute("SET LOCAL idle_in_transaction_session_timeout='360s'")
        connection.execute("SET LOCAL transaction_timeout='300s'")
        connection.execute("SET LOCAL timezone='UTC'")
        connection.execute("SET LOCAL datestyle='ISO'")
        connection.execute("SET LOCAL extra_float_digits=3")
        snapshot = connection.execute("SELECT pg_export_snapshot()").fetchone()[0]
        if not re.fullmatch(r"[A-Fa-f0-9]+-[A-Fa-f0-9]+-[0-9]+", snapshot):
            raise SnapshotError("Exported snapshot identity is invalid.")
        descriptor = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            command([*dump_command, "--format=custom", "--no-password", "--lock-wait-timeout=5s",
                     f"--snapshot={snapshot}", *[f"--schema={s}" for s in SCHEMAS],
                     *[f"--extension={e}" for e in EXTENSIONS]],
                    env=dump_environment, stdout=output, timeout=180)
        expected = inventory(lambda statement: connection.execute(statement).fetchone()[0])
    return expected


def main() -> int:
    phase = "identity"
    try:
        identity = workflow_identity(os.environ)
        linked = archive.ROOT / "supabase" / ".temp"
        connection_options = production_connection(
            (linked / "pooler-url").read_text().strip(),
            (linked / "project-ref").read_text().strip(), os.environ.get("SUPABASE_DB_PASSWORD", ""))
        # Environment overrides/service files must not change libpq routing.
        for name in tuple(os.environ):
            if name.startswith("PG"):
                os.environ.pop(name)
        command([*DOCKER, "pull", IMAGE], stdout=subprocess.DEVNULL, timeout=120)
        with tempfile.TemporaryDirectory(prefix="quiz-private-snapshot-") as work:
            directory = Path(work)
            dump = directory / "application.dump"
            pg_environment = clean_environment() | {
                "PGHOST": connection_options["host"], "PGPORT": "5432", "PGDATABASE": "postgres",
                "PGUSER": connection_options["user"], "PGPASSWORD": connection_options["password"],
                "PGSSLMODE": "verify-full", "PGSSLROOTCERT": "/etc/ssl/certs/ca-certificates.crt",
                "PGOPTIONS": OPTIONS, "PGCONNECT_TIMEOUT": "10",
            }
            dump_command = [*DOCKER, "run", "--rm", "--log-driver", "none", "--memory", "512m",
                            "--security-opt", "no-new-privileges"]
            for name in pg_environment:
                if name.startswith("PG"):
                    dump_command.extend(["--env", name])
            dump_command.extend([IMAGE, "pg_dump"])
            phase = "read-only snapshot"
            captured_at = datetime.now(timezone.utc).isoformat()
            with psycopg.connect(**connection_options, autocommit=True) as connection:
                expected = export_snapshot(connection, dump, dump_command, pg_environment)
            phase = "isolated restore"
            restore_and_compare(dump, expected)
            phase = "encryption"
            output = Path(os.environ["RUNNER_TEMP"]) / f"application-backup-{identity['workflow_run_id']}"
            # RUNNER_TEMP is normally 0755. Use a new owner-private parent.
            output.mkdir(mode=0o700)
            sealed = output / "sealed"
            manifest = archive.seal(dump, archive.ROOT / "config/backup-recipient.asc", RECIPIENT, sealed)
            receipt = identity | {
                "format": "citizen-affairs-application-snapshot-v1", "captured_at": captured_at,
                "scope": list(SCHEMAS), "managed_services_included": False,
                "isolated_plaintext_restore_verified": True, "owner_decryption_verified": False,
                "source_inventory_sha256": hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest(),
                "plaintext_sha256": manifest["plaintext_sha256"],
                "ciphertext_sha256": manifest["ciphertext_sha256"], "table_count": len(expected["tables"]),
                "recipient_fingerprint": RECIPIENT,
            }
            descriptor = os.open(sealed / "restore-receipt.json", os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as stream:
                json.dump(receipt, stream, sort_keys=True)
            print("Application snapshot restored and encrypted. Owner decryption and release approval remain separate.")
        return 0
    except (SnapshotError, archive.ArchiveError, psycopg.Error, OSError, ValueError,
            KeyError, subprocess.SubprocessError):
        print(f"Application backup stopped at {phase}; no production write or recovery-gate bypass was performed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
