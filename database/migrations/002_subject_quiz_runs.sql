-- Subject-scoped quiz lifecycle, chapter history, and immutable submissions.
-- Safe to re-run; no existing rows or tables are removed.

create table if not exists quiz_runs (
    quiz_id text primary key,
    quiz_date date not null,
    subject_key text not null,
    subject_display_name text not null,
    internal_subject text not null,
    chapter text not null,
    status text not null check (status in (
        'pending', 'generating', 'generated', 'posting', 'posted',
        'generation_failed', 'posting_failed'
    )),
    question_count integer not null default 0 check (question_count between 0 and 10),
    content_checksum text,
    generation_provider text,
    generation_model text,
    providers_attempted text[] not null default '{}',
    generation_attempt_count integer not null default 0,
    retryable boolean,
    generated_at timestamptz,
    posted_at timestamptz,
    telegram_chat_id bigint,
    telegram_thread_id bigint,
    telegram_message_id bigint,
    last_error_category text,
    last_error_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (quiz_date, subject_key)
);

alter table quiz_runs add column if not exists providers_attempted text[] not null default '{}';
alter table quiz_runs add column if not exists generation_attempt_count integer not null default 0;
alter table quiz_runs add column if not exists retryable boolean;

create index if not exists idx_quiz_runs_recovery on quiz_runs (quiz_date, status);
create index if not exists idx_quiz_runs_subject_date on quiz_runs (subject_key, quiz_date desc);

create table if not exists chapter_history (
    id uuid primary key default gen_random_uuid(),
    subject_key text not null,
    chapter text not null,
    selected_for date not null,
    quiz_id text not null,
    created_at timestamptz not null default now(),
    unique (subject_key, selected_for)
);

create index if not exists idx_chapter_history_subject_date
    on chapter_history (subject_key, selected_for desc);

create table if not exists quiz_submissions (
    id uuid primary key default gen_random_uuid(),
    quiz_id text not null,
    user_id uuid not null references users(id) on delete cascade,
    answers jsonb not null,
    score integer not null check (score >= 0),
    total integer not null check (total = 10),
    answered integer not null check (answered between 0 and 10),
    completed_at timestamptz not null default now(),
    unique (quiz_id, user_id)
);

create index if not exists idx_quiz_submissions_leaderboard
    on quiz_submissions (quiz_id, score desc, completed_at asc);
create index if not exists idx_polls_run_slot on polls (bot_type, run_slot);
