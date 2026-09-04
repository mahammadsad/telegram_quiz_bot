# 8.7.3

- Prioritizes bounded content-generation work for subjects below the configured
  15-day verified-question reserve.
- Preserves per-subject round-robin fairness, non-blocking queue claims, short
  database transactions, and service-role-only access.
- Advances the fail-closed platform contract to `1.2.0`; the application
  cannot report ready until migration `20260904164836` is applied.
- Adds migration contract tests, staging rollback verification, and operator
  verification/rollback instructions.
