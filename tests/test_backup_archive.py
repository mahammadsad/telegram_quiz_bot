"""Real GPG round trips with disposable keys; never production database data."""

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import backup_archive as backup


@pytest.fixture(scope="module")
def recipients(tmp_path_factory):
    if not shutil.which("gpg"):
        pytest.skip("GnuPG is required for real backup encryption regressions")
    directory = tmp_path_factory.mktemp("backup-test-keys")
    homes = []
    for index in range(2):
        home = directory / f"key-{index}"
        home.mkdir(mode=0o700)
        backup.run_gpg(home, [
            "--pinentry-mode", "loopback", "--passphrase", "",
            "--quick-generate-key", f"Disposable backup test {index}", "rsa2048", "encr", "1d",
        ], stdout=subprocess.DEVNULL)
        listing = backup.run_gpg(home, ["--with-colons", "--list-keys"], stdout=subprocess.PIPE)
        fingerprint = next(line.split(b":")[9].decode() for line in listing.splitlines()
                           if line.startswith(b"fpr:"))
        key = directory / f"public-{index}.asc"
        key.write_bytes(backup.run_gpg(home, ["--armor", "--export", fingerprint], stdout=subprocess.PIPE))
        homes.append((home, key, fingerprint))
    yield homes
    for home, _, _ in homes:
        # Stop only the disposable fixture's agent before pytest removes its home.
        subprocess.run(["gpgconf", "--homedir", str(home), "--kill", "gpg-agent"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10, check=False)


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "private-source.dump"
    # This exercises the envelope only: a magic-prefixed payload isn't a restore.
    path.write_bytes(backup.MAGIC + b"synthetic learner data must never be logged\n" * 1000)
    path.chmod(0o600)
    return path


def make_archive(source, recipients, output_name="sealed"):
    home, key, fingerprint = recipients[0]
    directory = source.parent / output_name
    manifest = backup.seal(source, key, fingerprint, directory)
    return directory, manifest, home, fingerprint


def test_real_gpg_round_trip_has_only_ciphertext_and_non_restore_manifest(source, recipients, capsys):
    directory, manifest, home, fingerprint = make_archive(source, recipients)
    assert {path.name for path in directory.iterdir()} == {backup.ARCHIVE_NAME, backup.MANIFEST_NAME}
    assert manifest["database_restore_verified"] is False
    assert manifest["plaintext_sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()
    assert b"synthetic learner" not in (directory / backup.ARCHIVE_NAME).read_bytes()
    assert backup.main([
        "verify", "--archive", str(directory / backup.ARCHIVE_NAME),
        "--manifest", str(directory / backup.MANIFEST_NAME),
        "--key-home", str(home), "--fingerprint", fingerprint,
    ]) == 0
    assert "Database restore is NOT verified" in capsys.readouterr().out
    assert sorted(path.name for path in source.parent.iterdir()) == ["private-source.dump", "sealed"]


def test_wrong_public_fingerprint_stops_before_a_completion_marker(source, recipients):
    _, key, _ = recipients[0]
    with pytest.raises(backup.ArchiveError, match="pinned recipient"):
        backup.seal(source, key, recipients[1][2], source.parent / "failed")
    assert not (source.parent / "failed" / backup.MANIFEST_NAME).exists()


@pytest.mark.parametrize("fingerprint", ["", "A" * 16, "a" * 40, "A" * 39, "G" * 40, "--help"])
def test_short_or_unpinned_recipient_is_refused(source, recipients, fingerprint):
    with pytest.raises(backup.ArchiveError, match="fingerprint"):
        backup.seal(source, recipients[0][1], fingerprint, source.parent / "failed")


def test_missing_secret_key_cannot_verify(source, recipients):
    directory, _, _, fingerprint = make_archive(source, recipients)
    with pytest.raises(backup.ArchiveError, match="integrity"):
        backup.verify(directory / backup.ARCHIVE_NAME, directory / backup.MANIFEST_NAME,
                      recipients[1][0], fingerprint)


def test_manifest_cannot_relabel_actual_decryption_recipient(source, recipients):
    directory, manifest, home, _ = make_archive(source, recipients)
    manifest["recipient_fingerprint"] = recipients[1][2]
    (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(backup.ArchiveError, match="integrity"):
        backup.verify(directory / backup.ARCHIVE_NAME, directory / backup.MANIFEST_NAME,
                      home, recipients[1][2])


@pytest.mark.parametrize("change", ["truncate", "checksum", "size", "plaintext_hash"])
def test_corruption_cannot_pass_even_with_updated_ciphertext_hash(source, recipients, change):
    directory, manifest, home, fingerprint = make_archive(source, recipients)
    archive = directory / backup.ARCHIVE_NAME
    if change == "truncate":
        archive.write_bytes(archive.read_bytes()[:-24])
        manifest["ciphertext_sha256"] = hashlib.sha256(archive.read_bytes()).hexdigest()
    elif change == "checksum":
        archive.write_bytes(archive.read_bytes() + b"damage")
    elif change == "size":
        manifest["plaintext_bytes"] -= 1
    else:
        manifest["plaintext_sha256"] = "0" * 64
    (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(backup.ArchiveError):
        backup.verify(archive, directory / backup.MANIFEST_NAME, home, fingerprint)


@pytest.mark.parametrize("field,value", [
    ("database_restore_verified", True), ("database_restore_verified", 0),
    ("plaintext_bytes", True), ("plaintext_bytes", 0), ("plaintext_bytes", backup.MAX_BYTES + 1),
    ("plaintext_sha256", None), ("ciphertext_sha256", "bad"),
    ("sealed_at", "2026-09-13"), ("format", "unknown"), ("filename", "../../secret"),
])
def test_malformed_or_overclaiming_manifest_fails_closed(source, recipients, field, value):
    directory, manifest, _, fingerprint = make_archive(source, recipients)
    manifest[field] = value
    (directory / backup.MANIFEST_NAME).write_text(json.dumps(manifest))
    with pytest.raises(backup.ArchiveError):
        backup.read_manifest(directory / backup.MANIFEST_NAME, fingerprint)


def test_source_must_be_private_custom_archive(source, recipients):
    source.chmod(0o644)
    with pytest.raises(backup.ArchiveError, match="permissions"):
        backup.seal(source, recipients[0][1], recipients[0][2], source.parent / "bad-mode")
    source.chmod(0o600)
    source.write_bytes(b"private plain SQL must not leak")
    with pytest.raises(backup.ArchiveError, match="custom-format"):
        backup.seal(source, recipients[0][1], recipients[0][2], source.parent / "bad-format")


def test_existing_backup_is_never_overwritten(source, recipients):
    directory, _, _, _ = make_archive(source, recipients)
    original = (directory / backup.ARCHIVE_NAME).read_bytes()
    with pytest.raises(FileExistsError):
        make_archive(source, recipients)
    assert (directory / backup.ARCHIVE_NAME).read_bytes() == original


def test_symlink_or_fifo_input_is_refused_without_blocking(source, recipients):
    linked = source.parent / "linked.dump"
    linked.symlink_to(source)
    with pytest.raises(OSError):
        backup.open_regular(linked)
    pipe = source.parent / "pipe.dump"
    os.mkfifo(pipe, mode=0o600)
    with pytest.raises(backup.ArchiveError):
        backup.open_regular(pipe)


def test_unsafe_or_repository_directory_is_refused(tmp_path):
    tmp_path.chmod(0o755)
    with pytest.raises(backup.ArchiveError):
        backup.private_directory(tmp_path)
    tmp_path.chmod(0o700)
    with patch.object(backup, "ROOT", tmp_path):
        with pytest.raises(backup.ArchiveError):
            backup.private_directory(tmp_path)


def test_private_key_input_is_refused_before_import(source, recipients):
    key = source.parent / "not-a-public-key.asc"
    key.write_text("-----BEGIN PGP PRIVATE KEY BLOCK-----\nprivate fixture\n")
    with pytest.raises(backup.ArchiveError, match="public key"):
        backup.seal(source, key, recipients[0][2], source.parent / "failed")


def test_child_failure_does_not_publish_manifest_or_print_secrets(source, recipients, capsys):
    with patch.object(backup, "run_gpg", side_effect=OSError("sensitive child stderr")):
        assert backup.main([
            "seal", "--dump", str(source), "--public-key", str(recipients[0][1]),
            "--fingerprint", recipients[0][2], "--output", str(source.parent / "failed"),
        ]) == 1
    output = capsys.readouterr().out
    assert "sensitive" not in output and str(source) not in output
    assert not (source.parent / "failed" / backup.MANIFEST_NAME).exists()


def test_verification_deadline_kills_child_and_does_not_hang(source, recipients):
    directory, _, home, fingerprint = make_archive(source, recipients)
    with patch.object(backup, "TIMEOUT", 0):
        with pytest.raises(backup.ArchiveError, match="timed out"):
            backup.verify(directory / backup.ARCHIVE_NAME, directory / backup.MANIFEST_NAME,
                          home, fingerprint)


def test_encryption_does_not_relax_production_gate():
    workflow = Path(".github/workflows/supabase-migrations.yml").read_text()
    assert "python scripts/check_production_backup.py" in workflow
    assert "backup_archive" not in workflow


def test_tracked_public_recipient_matches_independently_pinned_owner_key(tmp_path):
    if not shutil.which("gpg"):
        pytest.skip("GnuPG is required to validate the public recipient")
    backup.import_recipient(
        tmp_path, Path("config/backup-recipient.asc"),
        "39F3FC1CE7F58FAA4CCB823FCBC34F51F9DA20DC",
    )
