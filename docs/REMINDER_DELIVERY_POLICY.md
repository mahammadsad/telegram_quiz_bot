# Reminder delivery release policy

Daily Telegram reminders are disabled. The visible control is disabled, the
browser always submits `false`, and the authenticated API rejects a crafted
`true` value. No user should appear opted in before private-message delivery is
safe and operational.

Reminder delivery may be enabled only after an additive, reviewed data contract
provides all of these controls:

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

The current production migration ledger is not reconciled, so the required
durable consent and delivery schema must not be added or applied as a shortcut.
The reminder remains unavailable until that prerequisite and a reliable
scheduler are both resolved.
