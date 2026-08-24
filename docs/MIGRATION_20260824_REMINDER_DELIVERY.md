# Durable reminder consent and delivery migration

Migration: `20260824033823_durable_reminder_consent_delivery.sql`

This additive migration creates a service-role-only consent and delivery job
contract. It does not enable reminders, schedule a worker, or send Telegram
messages. The contract is deliberately answer-free and stores no message body
or learner performance details.

## Preflight

1. Run the full disposable-database CI migration chain.
2. Confirm the production migration plan contains only this reviewed file.
3. Confirm the reminder UI remains disabled and the API still rejects opt-in.
4. Take the normal Supabase production checkpoint before applying.

## Verification

After applying, call `public.get_reminder_delivery_contract()` with the service
role. It must report the exact migration and consent-policy versions,
`ready: true`, `deliveryEnabled: false`, a five-attempt ceiling, and a maximum
claim batch of 100. Security advisors must have no warning/error regression.

## Rollback

Application rollback requires no database rollback because delivery remains
disabled. If the unused schema must later be removed, first prove that both
tables are empty, disable every worker, take a checkpoint, and use a new
reviewed forward migration. Do not edit or mark this migration reverted after
it has been applied.
