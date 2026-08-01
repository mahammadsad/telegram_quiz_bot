# Release notes — 7.2.3 leaderboard privacy hotfix

Version 7.2.3 keeps public rankings useful while making public identity
explicit-consent-only.

## Privacy behavior

- A saved, trimmed public display name is shown first.
- An opted-in Telegram `@username` is shown only when username visibility is
  enabled.
- Every other visible participant receives a stable opaque Bengali learner
  alias. Telegram first/last names, private usernames, photos, Telegram IDs,
  and internal user UUIDs are excluded from public leaderboard projections.
- Disabling leaderboard participation removes the learner from public rows.
  Clearing a public name or disabling username visibility restores anonymity
  immediately without changing private dashboard data.

## Defence in depth

- All leaderboard-producing RPCs use one service-role-only, security-invoker
  identity projection and expose an internal identity-source marker for server
  validation.
- FastAPI allowlists public leaderboard fields, strips the internal marker,
  and substitutes a neutral anonymous label for unclassified identities.
- Every leaderboard success and error response is explicitly `no-store`; the
  Mini App also bypasses stale caches for this release.
- Readiness fails closed until migration `20260801045552` and its restrictive
  function permissions are present.

Rank calculations, pagination, first-attempt competition, improvement and
revision scopes, Settings, practice, revision, and the `−0.25` negative-marking
rule are unchanged.
