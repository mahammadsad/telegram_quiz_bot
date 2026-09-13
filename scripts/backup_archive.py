"""Seal a PostgreSQL custom archive; verify decryption without writing plaintext.

This is an encryption/integrity primitive, NOT a database exporter, restore drill,
source attestation, or permission to bypass the production migration backup gate.
It never connects to a database or uploads an artifact. Keep plaintext and secret
keys outside the repository on an owner-private, permission-capable filesystem.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import selectors
import stat
import subprocess
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 8 * 1024**3
TIMEOUT = 180
FINGERPRINT = re.compile(r"[A-F0-9]{40}")
DIGEST = re.compile(r"[a-f0-9]{64}")
MAGIC = b"PGDMP"
ARCHIVE_NAME = "database.dump.gpg"
MANIFEST_NAME = "manifest.json"
MANIFEST_FIELDS = {
    "format", "sealed_at", "recipient_fingerprint", "plaintext_bytes",
    "plaintext_sha256", "ciphertext_sha256", "database_restore_verified",
}


class ArchiveError(Exception):
    """Only fixed, non-sensitive diagnostics may cross the CLI boundary."""


def private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or stat.S_IMODE(info.st_mode) != 0o700
        or info.st_uid != os.getuid()
        or path.resolve().is_relative_to(ROOT)
    ):
        raise ArchiveError("A private 0700 directory outside the repository is required.")


def open_regular(path: Path, *, private: bool = False):
    # Open once, without following a final symlink; use this descriptor throughout.
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    info = os.fstat(descriptor)
    if not stat.S_ISREG(info.st_mode) or (
        private and (info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) != 0o600)
    ):
        os.close(descriptor)
        raise ArchiveError("Expected a regular file with safe access permissions.")
    return os.fdopen(descriptor, "rb")


def digest_file(stream) -> tuple[str, int]:
    digest = hashlib.sha256()
    total = 0
    while chunk := stream.read(1024 * 1024):
        total += len(chunk)
        if total > MAX_BYTES:
            raise ArchiveError("Archive exceeds the supported size limit.")
        digest.update(chunk)
    return digest.hexdigest(), total


def gpg_command(home: Path) -> list[str]:
    return [
        "gpg", "--no-options", "--homedir", str(home), "--batch", "--no-tty",
        "--no-auto-key-retrieve", "--auto-key-locate", "clear",
    ]


def run_gpg(home: Path, arguments: list[str], **kwargs) -> bytes:
    result = subprocess.run(
        [*gpg_command(home), *arguments], stderr=subprocess.DEVNULL,
        timeout=TIMEOUT, check=False, **kwargs,
    )
    if result.returncode:
        raise ArchiveError("Encryption tool failed; no recovery evidence was accepted.")
    return result.stdout or b""


def import_recipient(home: Path, public_key: Path, fingerprint: str) -> None:
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ArchiveError("An exact uppercase 40-character recipient fingerprint is required.")
    with open_regular(public_key) as stream:
        key = stream.read(64 * 1024 + 1)
    if (
        len(key) > 64 * 1024
        or not key.startswith(b"-----BEGIN PGP PUBLIC KEY BLOCK-----")
        or b"PRIVATE KEY" in key
        or key.count(b"-----BEGIN PGP PUBLIC KEY BLOCK-----") != 1
        or not key.rstrip().endswith(b"-----END PGP PUBLIC KEY BLOCK-----")
    ):
        raise ArchiveError("Only a single armored public key is accepted.")
    records = run_gpg(
        home, ["--with-colons", "--import-options", "show-only", "--import"],
        input=key, stdout=subprocess.PIPE,
    ).decode("utf-8").splitlines()
    fields = [line.split(":") for line in records]
    primaries = [row for row in fields if row[0] == "pub"]
    fingerprints = [row[9] for row in fields if row[0] == "fpr" and len(row) > 9]
    if (
        len(primaries) != 1 or not fingerprints or fingerprints[0] != fingerprint
        or any(row[0] in {"sec", "ssb"} for row in fields)
    ):
        raise ArchiveError("The public key does not match the pinned recipient.")
    run_gpg(home, ["--import"], input=key, stdout=subprocess.DEVNULL)


def seal(dump: Path, public_key: Path, fingerprint: str, output: Path) -> dict:
    private_directory(dump.parent)
    private_directory(output.parent)
    # Never reuse/overwrite an earlier backup, including after a partial failure.
    output.mkdir(mode=0o700)
    private_directory(output)
    with open_regular(dump, private=True) as source, tempfile.TemporaryDirectory() as key_home:
        if source.read(len(MAGIC)) != MAGIC:
            raise ArchiveError("Expected a PostgreSQL custom-format archive.")
        source.seek(0)
        plaintext_digest, plaintext_size = digest_file(source)
        source.seek(0)
        home = Path(key_home)
        private_directory(home)
        import_recipient(home, public_key, fingerprint)
        # The child receives the archive through stdin, never a sensitive filename.
        # Only ciphertext is written in the output directory; no plaintext copy.
        descriptor = os.open(output / ARCHIVE_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "wb") as destination:
            run_gpg(
                home, ["--trust-model", "always", "--no-encrypt-to", "--recipient", fingerprint,
                       "--cipher-algo", "AES256", "--compress-algo", "none",
                       "--set-filename", "", "--encrypt"],
                stdin=source, stdout=destination,
            )
        # Detect a source change while sealing. Decryption verifies the same hash
        # independently; encryption alone is intentionally not a recovery proof.
        source.seek(0)
        if digest_file(source) != (plaintext_digest, plaintext_size):
            raise ArchiveError("Source changed while sealing; archive is not verified.")
    with open_regular(output / ARCHIVE_NAME) as stream:
        ciphertext_digest, _ = digest_file(stream)
    manifest = {
        "format": "citizen-affairs-pg-custom-gpg-v1",
        "sealed_at": datetime.now(timezone.utc).isoformat(),
        "recipient_fingerprint": fingerprint,
        "plaintext_bytes": plaintext_size,
        "plaintext_sha256": plaintext_digest,
        "ciphertext_sha256": ciphertext_digest,
        "database_restore_verified": False,
    }
    # Publish the completion marker LAST. A partial .gpg without it is unusable.
    descriptor = os.open(output / MANIFEST_NAME, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
        json.dump(manifest, stream, sort_keys=True)
        stream.write("\n")
    return manifest


def read_manifest(path: Path, fingerprint: str) -> dict:
    if not FINGERPRINT.fullmatch(fingerprint):
        raise ArchiveError("An exact uppercase 40-character recipient fingerprint is required.")
    with open_regular(path) as stream:
        raw = stream.read(4097)
    if len(raw) > 4096:
        raise ArchiveError("Archive manifest is invalid.")
    manifest = json.loads(raw)
    if (
        not isinstance(manifest, dict) or set(manifest) != MANIFEST_FIELDS
        or manifest["format"] != "citizen-affairs-pg-custom-gpg-v1"
        or manifest["recipient_fingerprint"] != fingerprint
        or manifest["database_restore_verified"] is not False
        or type(manifest["plaintext_bytes"]) is not int
        or not len(MAGIC) <= manifest["plaintext_bytes"] <= MAX_BYTES
        or not all(isinstance(manifest[name], str) and DIGEST.fullmatch(manifest[name])
                   for name in ("plaintext_sha256", "ciphertext_sha256"))
        or not isinstance(manifest["sealed_at"], str)
        or datetime.fromisoformat(manifest["sealed_at"]).tzinfo is None
    ):
        raise ArchiveError("Archive manifest is invalid.")
    return manifest


def verify(archive: Path, manifest_path: Path, key_home: Path, fingerprint: str) -> None:
    private_directory(key_home)
    manifest = read_manifest(manifest_path, fingerprint)
    with open_regular(archive) as ciphertext, tempfile.TemporaryFile() as status_stream:
        if digest_file(ciphertext)[0] != manifest["ciphertext_sha256"]:
            raise ArchiveError("Encrypted archive checksum does not match.")
        ciphertext.seek(0)
        # Never restore SQL or emit decrypted rows. Drain bounded chunks into a
        # digest and enforce a deadline even if the child stalls without output.
        with subprocess.Popen(
            [*gpg_command(key_home), "--status-fd", str(status_stream.fileno()), "--decrypt"],
            stdin=ciphertext, pass_fds=(status_stream.fileno(),),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ) as child:
            deadline = time.monotonic() + TIMEOUT
            digest = hashlib.sha256()
            size = 0
            magic = b""
            try:
                output_stream = child.stdout
                if output_stream is None:
                    raise ArchiveError("Decryption output pipe is unavailable.")
                with selectors.DefaultSelector() as selector:
                    selector.register(output_stream, selectors.EVENT_READ)
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0 or not selector.select(remaining):
                            raise ArchiveError("Archive verification timed out.")
                        chunk = os.read(output_stream.fileno(), 1024 * 1024)
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > manifest["plaintext_bytes"]:
                            raise ArchiveError("Decrypted archive exceeds its declared size.")
                        magic = (magic + chunk)[:len(MAGIC)]
                        digest.update(chunk)
                result = child.wait(timeout=max(0.01, deadline - time.monotonic()))
                status_stream.seek(0)
                status_lines = status_stream.read(65537).decode("utf-8").splitlines()
                decryption_keys = [line.split() for line in status_lines
                                   if line.startswith("[GNUPG:] DECRYPTION_KEY ")]
                if (
                    result != 0 or size != manifest["plaintext_bytes"] or magic != MAGIC
                    or digest.hexdigest() != manifest["plaintext_sha256"]
                    or len(decryption_keys) != 1 or len(decryption_keys[0]) < 4
                    or decryption_keys[0][3] != fingerprint
                    or "[GNUPG:] DECRYPTION_OKAY" not in status_lines
                ):
                    raise ArchiveError("Decryption or archive integrity verification failed.")
            finally:
                if child.poll() is None:
                    child.kill()
                    child.wait()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    encrypt = commands.add_parser("seal")
    encrypt.add_argument("--dump", type=Path, required=True)
    encrypt.add_argument("--public-key", type=Path, required=True)
    encrypt.add_argument("--output", type=Path, required=True)
    decrypt = commands.add_parser("verify")
    decrypt.add_argument("--archive", type=Path, required=True)
    decrypt.add_argument("--manifest", type=Path, required=True)
    decrypt.add_argument("--key-home", type=Path, required=True)
    for command in (encrypt, decrypt):
        command.add_argument("--fingerprint", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "seal":
            seal(args.dump, args.public_key, args.fingerprint, args.output)
            print("Archive sealed. Decryption and a database restore drill are still required.")
        else:
            verify(args.archive, args.manifest, args.key_home, args.fingerprint)
            print("Archive decryption and integrity verified. Database restore is NOT verified.")
    except (ArchiveError, OSError, ValueError, subprocess.SubprocessError):
        # Tool errors may contain paths, user IDs, rows or credentials. Never echo
        # exceptions, child stderr, or a raw manifest to terminal/CI logs.
        print("Backup archive operation failed; no recovery evidence was accepted.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
