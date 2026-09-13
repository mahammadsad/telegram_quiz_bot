# Encrypted backup recovery work

## Status and boundaries

The production provider check on 13 September 2026, workflow `34737305825`,
reported zero backup records, PITR disabled, and no recent recovery window.
Production still has 65 pinned migrations. The queue-rotation migration must
not be applied until a genuine recovery point and restore evidence exist.

`scripts/backup_archive.py` now implements a narrow, locally tested building
block: encrypt an existing PostgreSQL custom archive to a pinned public key,
then independently verify decryption, authenticated GPG completion, byte length,
and checksums using the owner's private key. Verification hashes the decrypted
stream without writing or printing plaintext. It does not export a database,
execute SQL, upload files, attest the source project, or prove database recovery.
Its manifest deliberately records `database_restore_verified: false`.

The `backup-archive-restore` CI job builds the complete repository migration
chain in a new disposable PostgreSQL database, adds synthetic Bengali/NULL rows,
exports it with PostgreSQL's custom archive format, encrypts it with a disposable
key, decrypts the encrypted artifact, and restores that artifact into a second
new disposable database. It verifies row preservation, migration count, schema
and platform readiness, and a service-only claim-function permission. This is
evidence for the synthetic pipeline, **not a production snapshot restore**.
The job has no production environment, hosted credentials, or artifact upload.

## File and key safeguards

- Plaintext input must be a regular owner-only `0600` file in an owner-only
  `0700` directory outside the repository. Output uses a new directory and
  refuses to overwrite an existing backup. Symlink/FIFO inputs are refused.
- Import only one armored public key into an isolated temporary keyring, and
  compare its full fingerprint with an independently pinned recipient. No
  keyserver lookup, default recipient, or personal GPG configuration is used.
- A completed manifest is written only after encryption succeeds. Partial
  ciphertext without a valid manifest is not a usable archive.
- Verification checks the actual GPG decryption-key fingerprint, not merely
  the manifest label. Child errors, paths, identifiers and plaintext are not
  echoed. Timeouts and corrupt/truncated archives fail closed.
- A manifest and checksums do not authenticate the exporting workflow: anyone
  possessing the public key can encrypt data. Trusted workflow/source-project
  provenance and a real restore receipt remain separate requirements.
- After the full synthetic CI restore passed, a dedicated RSA-3072 encryption
  key was generated in an owner-only `0700` keyring at
  `/home/mahammadsad/.local/share/citizen-affairs-backups/production-key-20260913`.
  It was not uploaded or read into chat. Only its public key is tracked at
  `config/backup-recipient.asc`; independently checked fingerprint:
  `39F3FC1CE7F58FAA4CCB823FCBC34F51F9DA20DC`, expiry 12 September 2028 UTC.
  A separate synthetic local encryption/decryption custody check passed.
  The project drive is `fuseblk`; do not assume `chmod` protects secrets there.
  The owner's home filesystem is `ext4`. The unattended private key relies on
  OS access control, **not a passphrase**. Losing the only private key makes every
  corresponding backup unrecoverable; an independent owner-controlled recovery
  copy is still needed. Do not delete or regenerate this key during code rollback.

Verification checkpoint: full local suite 941 passed / 62 skipped (local database
service absent); Ruff, mypy and all 65 source pins passed. Protected PR CI
`34751036976` at `c787b15` passed 1,002 Python/database tests (one separate-drill
skip), plus the dedicated **33-test real-GPG and full-schema restore job**.
The first drill attempt found an invalid empty libpq service option; it was
removed and inherited libpq settings explicitly cleared. Disposable database
names are also bounded below PostgreSQL's identifier truncation limit.

Read-only production scope discovery: PostgreSQL 17, 74 public tables, 65 ledger
rows, zero Auth users, Storage objects, foreign tables, large objects or public
pgsodium column labels. Public/ledger table owners are `postgres`. Managed
Cron/Net/Vault extensions remain outside the synthetic restore evidence; these
counts do not certify a complete project recovery strategy.

## Remaining production steps (not performed by this change)

The next implementation is `scripts/backup_snapshot.py`, exposed only by the
manual migration-plan workflow's separate `operation=backup` job. Its exact
acknowledgement is `BACKUP APPLICATION SCHEMAS FOR tizxodkcpglmxgtwepor`.
This job never calls migration apply and does not change the provider-only gate.
It uses the linked session pooler with exact project username, port 5432,
verified TLS and read-only transactions. One exported repeatable-read snapshot
is shared by `pg_dump` and source row fingerprints; locks/statements/transactions
and subprocesses have bounded timeouts. The synthetic CI drill deliberately
commits a concurrent source edit between export and verification.

The actual archive is restored in a random, disposable PostgreSQL 17 container
with no network, bind mounts, hosted credentials or Docker log collection.
It compares every public/ledger table's row count and sorted row hashes,
table/view/sequence ACLs and RLS flags, application/platform readiness and the
claim RPC's service-only permissions. MD5 row fingerprints detect accidental
data changes; they are not an authenticity signature. Sequences are not MVCC
snapshot data; their restored state is not independently compared. Restore
uses `--no-owner` and local no-login role placeholders, not managed role passwords
or a proof of managed-service ownership parity.

Only ciphertext, the encryption manifest and an allowlisted restore receipt may
be uploaded, with 30-day GitHub artifact retention. The receipt distinguishes an
isolated plaintext archive restore from the still-required owner-key decryption
check. This is an application recovery point, not full project disaster recovery:
private scheduler records, Cron/Net/Vault, managed Auth/Storage, role credentials
and hosting configuration are excluded. No actual production export or restore
has yet been verified at this implementation checkpoint.

1. Owner-held recipient pinning and the synthetic local key-custody round trip
   are complete. Define independent key-loss recovery and encrypted-archive
   retention; no production archive is represented by the synthetic fixture.
2. Inventory the exact application's dependencies read-only. Agree the backup
   scope explicitly: public application data and migration history are not a
   complete Supabase project backup. Managed Auth, Storage objects, extension
   configuration, role credentials, Vault keys/secrets, Cron jobs, Edge Functions
   and hosting configuration require separate recovery treatment as applicable.
3. Implement a bounded, read-only, consistent production snapshot export in the
   protected project workflow. Use a verified exact project connection; never
   print connection strings, rows or raw export/restore error output. Upload
   only an explicitly allowlisted encrypted artifact, never a working directory.
4. Restore the actual snapshot in an isolated disposable environment, verify
   application contracts, data integrity and permissions, download the encrypted
   archive, and verify decryption with the owner's retained key. Never restore
   over production or staging as a test.
5. Bind a recovery receipt to exact project identity, exporting workflow and
   reviewed commit, snapshot age, artifact hash, successful restore and key-custody
   checks. Only then consider extending the release gate for this alternative.
   Do not introduce a generic `backup_verified=true` bypass or mistake the
   encryption manifest for a restore receipt.

The provider-only migration gate is unchanged and continues to fail closed.
No Supabase billing upgrade or new third-party storage service is needed for
the synthetic work above. Retention, durable storage and the actual production
restore are not yet completed or represented as completed audit items.

## Recovery/rollback of this code change

The change does not modify hosted data, migrations, roles, billing or deployment
versions. Reverting its commit removes the helper, tests, CI job and this guide;
the existing provider backup gate remains. Never remove an actual owner's key
or archive as part of a code rollback. A failed sealing directory can be kept
for inspection; there is intentionally no broad automatic deletion command.

## References

- [Supabase backup and restore scope](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
- [PostgreSQL custom-format dumps and consistency](https://www.postgresql.org/docs/17/app-pgdump.html)
- [GnuPG key management and unattended-key protection](https://www.gnupg.org/documentation/manuals/gnupg/OpenPGP-Key-Management.html)
