"""Full migrated-schema round trip on a credential-free disposable CI service.

Not a hosted restore drill. The only accepted connection is the fixed local
GitHub Actions test service; no environment-provided database URL is consumed.
"""

import os
import re
import subprocess
import tempfile
import uuid

import psycopg
import pytest
from psycopg import sql

from scripts import backup_archive as backup
from scripts import backup_snapshot as snapshot
from scripts.apply_test_database import rebuild


def test_migrated_database_encryption_decryption_and_disposable_restore(tmp_path, monkeypatch):
    container = os.environ.get("BACKUP_TEST_POSTGRES_CONTAINER", "")
    if not container:
        pytest.skip("Dedicated disposable PostgreSQL backup-drill service is not configured")
    assert re.fullmatch(r"[a-f0-9]{64}", container), "Expected the CI service container ID"
    # Never inherit a database service file, connection override, remote Docker
    # endpoint, or hosted password from the developer's environment.
    for name in tuple(os.environ):
        if name.startswith("PG"):
            monkeypatch.delenv(name)
    environment = {"PATH": os.environ["PATH"], "LANG": "C.UTF-8"}
    docker = ["docker", "--host", "unix:///var/run/docker.sock", "exec", "-i", container]
    # Stay under PostgreSQL's 63-byte identifier limit (no silent truncation).
    suffix = uuid.uuid4().hex[:16]
    source_name = f"telegram_quiz_test_backup_source_{suffix}"
    restore_name = f"telegram_quiz_test_backup_restore_{suffix}"
    connection_options = dict(host="127.0.0.1", hostaddr="127.0.0.1", port=5432,
                              user="postgres", password="postgres", dbname="telegram_quiz_test",
                              connect_timeout=10, options="")
    key_home = tmp_path / "disposable-key"
    key_home.mkdir(mode=0o700)
    created = []
    with psycopg.connect(**connection_options, autocommit=True) as admin:
        try:
            for name in (source_name, restore_name):
                admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
                created.append(name)
            rebuild(psycopg.conninfo.make_conninfo(**(connection_options | {"dbname": source_name})))
            with psycopg.connect(**(connection_options | {"dbname": source_name})) as source:
                source.execute("CREATE TABLE public.backup_drill_fixture (id integer primary key, text_value text)")
                source.execute("INSERT INTO public.backup_drill_fixture VALUES (1, %s), (2, NULL)",
                               ("বাংলা synthetic recovery fixture",))
                ledger_count = source.execute("SELECT count(*) FROM supabase_migrations.schema_migrations").fetchone()[0]
                source.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions')
            # Exercise the production exporter and network-isolated restore with
            # the same full migrated schema, but no hosted connection or data.
            snapshot.command([*snapshot.DOCKER, "pull", snapshot.IMAGE], stdout=subprocess.DEVNULL, timeout=120)
            scoped_dump = tmp_path / "scoped-synthetic.dump"
            original_command = snapshot.command

            def dump_then_change_source(arguments, **kwargs):
                result = original_command(arguments, **kwargs)
                # Commit a concurrent change after pg_dump but before inventory.
                # The exported transaction must still see the original value.
                if "pg_dump" in arguments:
                    with psycopg.connect(**(connection_options | {"dbname": source_name})) as writer:
                        writer.execute("UPDATE public.backup_drill_fixture SET text_value='changed concurrently' WHERE id=1")
                return result

            with monkeypatch.context() as scoped:
                scoped.setattr(snapshot, "command", dump_then_change_source)
                with psycopg.connect(**(connection_options | {"dbname": source_name}), autocommit=True) as source:
                    expected = snapshot.export_snapshot(
                        source, scoped_dump, [*docker, "pg_dump", "--username=postgres", f"--dbname={source_name}"], environment)
            original_run = subprocess.run
            original_inventory = snapshot.inventory

            def synthetic_inventory_diagnostics(query):
                actual = original_inventory(query)
                differences = {
                    field: [(old, new) for old, new in zip(expected[field], actual[field], strict=True)
                            if old != new][:5]
                    for field in ("tables", "security") if expected[field] != actual[field]
                }
                assert not differences, differences
                # NULL ACL means default privileges, not no privileges. After
                # canonicalizing that representation, a genuine new public
                # grant must still fail equality and revocation must restore it.
                query("GRANT SELECT ON public.backup_drill_fixture TO anon;")
                assert query(snapshot.SECURITY_SQL) != expected["security"]
                query("REVOKE SELECT ON public.backup_drill_fixture FROM anon;")
                assert query(snapshot.SECURITY_SQL) == expected["security"]
                return actual

            def synthetic_restore_diagnostics(arguments, **kwargs):
                # This fixture is hardwired to the synthetic local service. Do
                # not add an equivalent log switch to the production exporter.
                if "pg_restore" in arguments:
                    kwargs["stderr"] = subprocess.PIPE
                    result = original_run(arguments, **kwargs)
                    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")
                    return result
                return original_run(arguments, **kwargs)

            with monkeypatch.context() as scoped:
                scoped.setattr(subprocess, "run", synthetic_restore_diagnostics)
                scoped.setattr(snapshot, "inventory", synthetic_inventory_diagnostics)
                snapshot.restore_and_compare(scoped_dump, expected)
            with psycopg.connect(**(connection_options | {"dbname": source_name})) as source:
                source.execute("UPDATE public.backup_drill_fixture SET text_value=%s WHERE id=1",
                               ("বাংলা synthetic recovery fixture",))
            dump = tmp_path / "synthetic.dump"
            descriptor = os.open(dump, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as destination:
                result = subprocess.run([
                    *docker, "pg_dump", "--username=postgres", f"--dbname={source_name}",
                    "--format=custom", "--lock-wait-timeout=5s", "--no-password",
                ], env=environment, stdout=destination, stderr=subprocess.DEVNULL, timeout=120, check=False)
                assert result.returncode == 0, "Synthetic database export failed"
            backup.run_gpg(key_home, [
                "--pinentry-mode", "loopback", "--passphrase", "", "--quick-generate-key",
                "Disposable CI restore key", "rsa2048", "encr", "1d",
            ], stdout=subprocess.DEVNULL)
            listing = backup.run_gpg(key_home, ["--with-colons", "--list-keys"], stdout=subprocess.PIPE)
            fingerprint = next(line.split(b":")[9].decode() for line in listing.splitlines()
                               if line.startswith(b"fpr:"))
            public_key = tmp_path / "public.asc"
            public_key.write_bytes(backup.run_gpg(key_home, ["--armor", "--export", fingerprint],
                                                  stdout=subprocess.PIPE))
            sealed = tmp_path / "sealed"
            backup.seal(dump, public_key, fingerprint, sealed)
            backup.verify(sealed / backup.ARCHIVE_NAME, sealed / backup.MANIFEST_NAME, key_home, fingerprint)
            # Only synthetic rows reach this temporary plaintext descriptor.
            # Restore the DECRYPTED artifact, never the original dump, so the
            # test covers the complete byte path through encryption and storage.
            with tempfile.TemporaryFile() as decrypted, (sealed / backup.ARCHIVE_NAME).open("rb") as encrypted:
                backup.run_gpg(key_home, ["--decrypt"], stdin=encrypted, stdout=decrypted)
                decrypted.seek(0)
                result = subprocess.run([
                    *docker, "pg_restore", "--username=postgres", f"--dbname={restore_name}",
                    "--exit-on-error", "--single-transaction", "--no-owner", "--no-password",
                ], env=environment, stdin=decrypted, stdout=subprocess.DEVNULL,
                   stderr=subprocess.DEVNULL, timeout=120, check=False)
                assert result.returncode == 0, "Synthetic decrypted database restore failed"
            with psycopg.connect(**(connection_options | {"dbname": restore_name})) as restored:
                assert restored.execute("SELECT * FROM public.backup_drill_fixture ORDER BY id").fetchall() == [
                    (1, "বাংলা synthetic recovery fixture"), (2, None),
                ]
                assert restored.execute("SELECT count(*) FROM supabase_migrations.schema_migrations").fetchone()[0] == ledger_count
                assert restored.execute("SELECT public.get_application_schema_contract()").fetchone()[0]["ready"] is True
                assert restored.execute("SELECT public.get_platform_contract_v1()").fetchone()[0]["ready"] is True
                assert restored.execute(
                    "SELECT has_function_privilege('anon', "
                    "'public.claim_content_replenishment_jobs(text,timestamptz,integer,integer)', 'EXECUTE')"
                ).fetchone()[0] is False
        finally:
            for name in reversed(created):
                assert re.fullmatch(r"telegram_quiz_test_backup_(source|restore)_[a-f0-9]{16}", name)
                admin.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(name)))
            subprocess.run(["gpgconf", "--homedir", str(key_home), "--kill", "gpg-agent"],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)
