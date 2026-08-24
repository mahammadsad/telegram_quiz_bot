# Reminder delivery release policy

Daily Telegram reminders are disabled. The visible control is disabled, the
browser always submits `false`, and the authenticated API rejects a crafted
`true` value. No user should appear opted in before private-message delivery is
safe and operational.

Migration `20260824033823_durable_reminder_consent_delivery.sql` now provides
the durable data contract and keeps `deliveryEnabled: false`. It includes:

- explicit opt-in timestamp, policy version, source, and immediate opt-out;
- learner timezone plus quiet-hour start/end, with a conservative default;
- one durable delivery job per learner and logical date with a database unique
  key, lease, retry ceiling, terminal state, and Telegram receipt metadata;
- no notification content containing answers, private performance details, or
  sensitive profile data;
- permanent-chat-error suppression and safe rate-limit backoff;
- a settings unsubscribe path that takes effect before the next claim;
- aggregate sent/delivered/failed/opt-out metrics without message bodies;
- a dry-run, synthetic-account canary and alerting before any real-user send.

The reminder remains unavailable in the UI and API until the migration is
deployed, a reliable scheduler is funded and selected, the worker implements
the lease/completion contract, and a synthetic private-message canary passes.
No real-user delivery may be enabled merely because the schema exists.
