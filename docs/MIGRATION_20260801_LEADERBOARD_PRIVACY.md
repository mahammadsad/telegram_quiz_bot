# Leaderboard privacy migration — 20260801045552

Application: `7.2.3`

Migration:
`supabase/migrations/20260808140807_leaderboard_privacy_hotfix.sql`

## Deployment order

1. Run the complete CI suite against a clean PostgreSQL 17 database.
2. Record staging migration history and preservation counts without reading
   learner identities into logs.
3. Apply this one unapplied migration to staging through the normal Supabase
   migration workflow.
4. Deploy the exact CI-tested application commit to staging. Require
   `leaderboardPrivacy=true`, migration version `20260801045552`, and HTTP 200
   from readiness.
5. Run `scripts/check_leaderboard_privacy.py` logged out and, when safe test
   init data is available, authenticated. Only its four aggregate counters may
   enter logs; all must be zero.
6. Verify all eight typed boards, a recent quiz board, paging, current-user
   highlighting, Settings consent withdrawal, and the `−0.25` ordering.
7. Merge only after CI and review are green, then apply the exact migration to
   production before deploying the application.
8. Bypass or purge stale caches and verify the original canonical leaderboard
   URLs return the full no-store header set and zero aggregate privacy matches.

## Preservation and rollback contract

- The migration replaces function definitions and adds one identity helper,
  one paginated compatibility RPC, and one readiness RPC. It does not delete,
  anonymize, or rewrite any user, quiz, attempt, answer, ranking, or revision
  row.
- All functions remain `SECURITY INVOKER` with an empty search path. Execution
  is revoked from `PUBLIC`, `anon`, and `authenticated` and granted only to
  `service_role`; RLS and table policies are unchanged.
- Do not edit or reapply the migration after it has been applied. If an
  application rollback is needed, keep this database migration in place and
  fail closed for public leaderboards. Any database correction must be a new
  forward migration.

With the target URL and existing service-role credential configured in the
operator environment, the smoke command never prints response bodies or stored
identity values:

```bash
python scripts/check_leaderboard_privacy.py
```

Expected output:

```text
private_name_matches = 0
private_username_matches = 0
private_photo_matches = 0
raw_identifier_fields = 0
```
