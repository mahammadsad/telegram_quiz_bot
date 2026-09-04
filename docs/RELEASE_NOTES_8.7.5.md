# 8.7.5

- Retries recoverable durable quiz failures inside the active dispatcher run,
  instead of always waiting for the next 15-minute scheduler heartbeat.
- Uses the database-authored `next_retry_at` timestamp, the existing atomic
  claim/lease RPC and Telegram posting idempotency; blocked, dead-letter and
  unknown-delivery jobs are never retried by this loop.
- Limits one heartbeat to four total passes and a 15-minute retry-start window
  so provider incidents still fail closed and hand control back to the normal
  durable scheduler.
