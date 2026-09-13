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
- No production private key has been generated or uploaded by this change.
  The project drive is `fuseblk`; do not assume `chmod` protects secrets there.
  The owner's `/home/mahammadsad` filesystem is `ext4`. A dedicated `0700`
  directory there is the candidate key-custody location, outside this repository.
  An unattended unpassphrased key would rely on OS access control, not password
  protection. Losing the only private key makes every corresponding backup
  unrecoverable; an independent owner-controlled recovery copy is still needed.

## Remaining production steps (not performed by this change)

1. Pin an owner-held recipient, prove local key custody with a synthetic round
   trip, and define key-loss recovery and encrypted-archive retention.
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
