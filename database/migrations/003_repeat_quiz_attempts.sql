-- Allow intentional Mini App retakes while keeping network retries idempotent.
-- Safe to re-run; existing submissions remain as each user's first attempt.

alter table quiz_submissions
    drop constraint if exists quiz_submissions_quiz_id_user_id_key;

alter table quiz_submissions
    add column if not exists client_attempt_id text;

create unique index if not exists idx_quiz_submissions_client_attempt
    on quiz_submissions (quiz_id, user_id, client_attempt_id)
    where client_attempt_id is not null;

create index if not exists idx_quiz_submissions_user_history
    on quiz_submissions (quiz_id, user_id, completed_at desc);
