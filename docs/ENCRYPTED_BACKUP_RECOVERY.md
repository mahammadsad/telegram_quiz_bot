# Encrypted backup recovery work

## Status and boundaries

**19 September verification:** protected workflow `34783767495`, at reviewed
exporter `c3f6f3bd1fabc21c93f85dbcff80de416fe2adbc`, successfully captured the
production application snapshot on 13 September and restored it in isolation.
All 75 application/ledger tables matched the shared source snapshot's row
fingerprints, effective privileges, RLS flags and application contracts. Only
the encrypted archive and bounded receipts were retained by GitHub (30 days).
The actual artifact was downloaded to the owner's private backup directory and
passed retained-key decryption, length, magic and checksum verification on
19 September, without creating a plaintext copy. Its receipts remain immutable;
an owner-local `OWNER-VERIFICATION.md` records the distinct custody check.

This proves the scoped export/restore/encryption pipeline on real data. It does
not make a six-day-old snapshot meet the 48-hour release gate, cover managed
services, or remove the need for independent key-loss recovery. A fresh capture
and release-gate provenance validation were the next requirements. No production
migration or gate bypass has been performed.

Fresh protected run `35450108411` at exporter `e4bb797295c5964f78e3b21c89f0a0b7c978a6bb`
succeeded on 19 September. Its capture time is `2026-09-19T14:54:13.696427Z`;
all 75 tables again passed isolated restore comparison. Artifact `10586058103`
was downloaded into the owner's private `production-run-35450108411` directory.
Retained-key decryption and integrity verification passed, repeated immediately
before `2026-09-19T15:11:54Z`. The unchanged receipt and owner-local
`owner-approval.json` distinguish the exporter restore from the owner custody
check. The GitHub artifact ZIP digest is
`8accc1b7c692d42f6dfd06fcbcce75007c364296a815dce86175a3f1ef560776`.

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
This job never calls migration apply or automatically approve a release.
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
and hosting configuration are excluded. The initial implementation preceded the
actual production verification recorded above.

1. Owner-held recipient pinning and the synthetic local key-custody round trip
   are complete. Define independent key-loss recovery and encrypted-archive
   retention; no production archive is represented by the synthetic fixture.
2. Inventory the exact application's dependencies read-only. Agree the backup
   scope explicitly: public application data and migration history are not a
   complete Supabase project backup. Managed Auth, Storage objects, extension
   configuration, role credentials, Vault keys/secrets, Cron jobs, Edge Functions
   and hosting configuration require separate recovery treatment as applicable.
3. The bounded read-only snapshot exporter is implemented and passed a real
   production capture. Refresh the snapshot before release, preserving exact
   project/TLS checks and the ciphertext-only upload allowlist.
4. The real isolated restore and retained-key decryption checks passed for the
   13 September snapshot. Repeat them for the fresh release snapshot. Never
   restore over production or staging as a test.
5. Bind a recovery receipt to exact project identity, exporting workflow and
   reviewed commit, snapshot age, artifact hash, successful restore and key-custody
   checks. Only then consider extending the release gate for this alternative.
   Do not introduce a generic `backup_verified=true` bypass or mistake the
   encryption manifest for a restore receipt.

## Narrow application-recovery release alternative

`scripts/verified_recovery_point.py` adds a deliberately one-release alternative
when the provider cannot show a fresh recovery point. It is **not** a general
replacement for provider backups or full-project disaster recovery:

- The production environment's `APP_RECOVERY_EVIDENCE` record is an operator
  attestation created only after actual retained-key verification. It embeds the
  unchanged exporter receipt, artifact ID/ZIP digest, owner verification time,
  and approved migration SHA-256. It contains no key or learner rows.
- The gate checks exact project, recipient, reviewed exporter commit, scope,
  restore result, table count, ordered timestamps and a maximum 48-hour age.
- GitHub read-only API requests independently check the successful manual run,
  exact repository/source, successful backup job, skipped plan job, and live,
  unexpired artifact identity and digest. Redirects and oversized responses are
  rejected; raw errors and credentials are not printed. The gate does not
  download/decrypt learner data or independently repeat the owner's custody check.
- The pinned 65-entry ledger source, all historical SQL checksums, exact pending
  queue-rotation migration SHA-256 and complete local SQL filename set must match.
  The actual linked CLI dry run must list **only** that reviewed migration.
  A missing/no-op/broader/changed plan fails closed. This alternative intentionally
  stops working after the ledger is advanced or a different migration is added.
- Both plan and apply jobs capture their own fresh dry run with `pipefail` and
  check the recovery evidence before any apply. The existing fresh provider
  backup/PITR path remains available. No generic boolean override is accepted.

Only after local verification and live provenance validation may the owner-local
approval record be installed as the production environment variable. Setting
that variable is not itself a migration or a successful release check. Run the
read-only production plan first; production apply, ledger readback, staging
verification and normal application release gates remain separate.

The application snapshot expires for release purposes at
`2026-09-21T14:54:13.696427Z`, even though GitHub retains its artifact for 30 days.
Do not change its capture/verification timestamps to make old evidence appear
fresh. Any refreshed record requires an actual new capture, restore, retained-key
check and independently verified run/artifact provenance.

The first actual backup attempts (`34783373716`, `34783553252`) produced no
artifact. Safe diagnostics on the second attempt identified a TLS CA failure
before source connection completed. The exporter now pins the **public**
Supabase Root 2021 CA from the download URL used by the official Studio
`apps/studio/hooks/custom-content/custom-content.json`. Its DER SHA-256 is
`807025ad50d4ed219d2c9c7d299c004f824eb00cf7f65afef607d07b72e6cafa`, expiry
26 April 2031. Both clients retain `verify-full`; the export container receives
only this public certificate through a read-only mount. The isolated restore
container still has no mounts or network. No server SSL setting was changed.

The synthetic scoped restore also found two verification issues: an empty
default `public` schema conflicting with the explicit-schema dump, and an
explicit default sequence ACL being represented as NULL after restore. The
drill now prepares only its fresh empty schema and compares canonical effective
privileges, including defaults; a real added `anon` grant still fails equality.
TCP readiness avoids the Docker image's temporary socket-only initialization
server. Protected CI `34783484054` passed all 78 encryption/snapshot/restore
cases, including the concurrent-edit test, before the CA follow-up.
No Supabase billing upgrade or new third-party storage service was used. The
real encrypted archive has 30-day GitHub retention plus a retained owner-local
copy. Recurring recovery-point freshness, independent private-key recovery and
complete managed-project disaster recovery are not completed audit items.

## Recovery/rollback of this code change

The change does not modify hosted data, migrations, roles, billing or deployment
versions. Remove `APP_RECOVERY_EVIDENCE` from the production environment to
disable the application alternative immediately; the existing provider backup
gate remains. Revert the scoped gate/workflow change if required. Never remove an actual owner's key
or archive as part of a code rollback. A failed sealing directory can be kept
for inspection; there is intentionally no broad automatic deletion command.

## References

- [Supabase backup and restore scope](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
- [PostgreSQL custom-format dumps and consistency](https://www.postgresql.org/docs/17/app-pgdump.html)
- [GnuPG key management and unattended-key protection](https://www.gnupg.org/documentation/manuals/gnupg/OpenPGP-Key-Management.html)
