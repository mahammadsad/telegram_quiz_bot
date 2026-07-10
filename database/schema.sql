-- ============================================================================
-- WB Exam Learning Platform — Shared Database Schema
-- Target:  Supabase PostgreSQL (Free Tier)
-- Shared by: Daily MCQ Bot (this repo), Mock Test Bot, Website Dashboard,
--            Android App, AI Recommendation Engine
--
-- How to apply:
--   Supabase Dashboard -> SQL Editor -> New query -> paste this whole file
--   -> Run. Safe to re-run: every statement is idempotent (IF NOT EXISTS /
--   OR REPLACE), so applying it again after a future migration file will
--   not error out or duplicate anything.
-- ============================================================================

-- --------------------------------------------------------------------------
-- Extensions
-- --------------------------------------------------------------------------
create extension if not exists pgcrypto;   -- gen_random_uuid()
create extension if not exists pg_trgm;    -- trigram similarity for fuzzy duplicate detection


-- ============================================================================
-- 1. QUESTIONS — the permanent question bank. One row per unique MCQ, shared
--    across every bot and surface (Daily MCQ, Mock Test, Website, App).
-- ============================================================================
create table if not exists questions (
    id                      uuid primary key default gen_random_uuid(),

    -- ---- content ----
    question_text           text not null,
    option_a                text not null,
    option_b                text not null,
    option_c                text not null,
    option_d                text not null,
    correct_option          char(1) not null check (correct_option in ('A', 'B', 'C', 'D')),
    explanation              text,             -- short (<=200 chars): Telegram quiz lamp-icon popup
    detailed_explanation     text,             -- longer: separate spoiler follow-up message

    -- ---- classification ----
    subject                 text not null,
    topic                   text not null,     -- "subtopic" in the original script
    difficulty              text not null default 'medium'
                                 check (difficulty in ('easy', 'medium', 'hard')),

    -- ---- provenance ----
    gemini_model            text,
    source                  text not null default 'gemini_generated',
    week_number             int,               -- ISO week number at creation time
    bot_type                text not null default 'daily_mcq'
                                 check (bot_type in ('daily_mcq', 'mock_test')),
    created_at              timestamptz not null default now(),

    -- ---- duplicate detection (layers 1 & 2; layer 3 is find_similar_questions() below) ----
    question_hash            text not null unique,   -- sha256(normalized_text) -> O(1) exact-dup rejection
    normalized_text           text not null,           -- lowercased/punctuation-stripped, feeds pg_trgm

    -- ---- lifecycle ----
    status                   text not null default 'active'
                                 check (status in ('active', 'archived')),

    -- ---- Global Question Scheduler metadata (System 1 — see scheduler/question_scheduler.py) ----
    last_used_at             timestamptz,             -- null = never posted
    usage_count               int not null default 0,
    next_global_review        date,                    -- earliest date this question is eligible for reuse
    selection_weight          numeric not null default 1.0,   -- manual boost/penalty multiplier
    quality_score             numeric not null default 1.0    -- manual/automatic quality multiplier
);

create index if not exists idx_questions_subject        on questions (subject);
create index if not exists idx_questions_topic          on questions (topic);
create index if not exists idx_questions_status         on questions (status);
create index if not exists idx_questions_bot_type       on questions (bot_type);
create index if not exists idx_questions_scheduler_pool
    on questions (bot_type, status, subject, next_global_review, last_used_at);
create index if not exists idx_questions_normalized_trgm
    on questions using gin (normalized_text gin_trgm_ops);


-- Layer 3 of duplicate detection: fuzzy near-duplicate search.
-- Called from generator/duplicate_detector.py via supabase.rpc(...).
-- Doing this in Postgres (with the trigram GIN index above) instead of
-- pulling every question into Python is what keeps this fast as the
-- question bank grows into the thousands.
create or replace function find_similar_questions(
    query_normalized  text,
    query_bot_type    text default 'daily_mcq',
    sim_threshold     float default 0.35,
    match_count       int default 5
)
returns table (
    id              uuid,
    question_text   text,
    similarity      real
)
language sql
stable
as $$
    select q.id, q.question_text, similarity(q.normalized_text, query_normalized) as similarity
    from questions q
    where q.bot_type = query_bot_type
      and q.status = 'active'
      and q.normalized_text % query_normalized     -- pg_trgm operator, uses the GIN index
    order by similarity desc
    limit match_count;
$$;


-- ============================================================================
-- 2. POLLS — every Telegram poll ever sent, for any bot.
-- ============================================================================
create table if not exists polls (
    id                       uuid primary key default gen_random_uuid(),
    telegram_poll_id          text not null unique,     -- Telegram's own poll.id string
    telegram_message_id       bigint not null,
    telegram_chat_id          bigint not null,
    posted_at                 timestamptz not null default now(),
    question_id               uuid not null references questions(id) on delete restrict,
    session_id                uuid not null,             -- groups every poll from one run together
    bot_type                  text not null default 'daily_mcq'
                                  check (bot_type in ('daily_mcq', 'mock_test')),
    run_slot                  text                       -- 'morning' | 'evening' | 'manual' (daily bot only)
);

create index if not exists idx_polls_question_id on polls (question_id);
create index if not exists idx_polls_session_id  on polls (session_id);
create index if not exists idx_polls_posted_at   on polls (posted_at);


-- ============================================================================
-- 3. USERS — anyone who has interacted with a poll (shared across bots).
-- ============================================================================
create table if not exists users (
    id             uuid primary key default gen_random_uuid(),
    telegram_id     bigint not null unique,
    username        text,
    first_name      text,
    last_name       text,
    join_date       timestamptz not null default now(),
    last_active     timestamptz not null default now()
);

create index if not exists idx_users_telegram_id on users (telegram_id);


-- ============================================================================
-- 4. USER_ATTEMPTS — every raw answer event. This is the table the future
--    Mock Test Bot, Dashboard, and Analytics Engine will all read from.
--    No calculated values (accuracy/score/rank) are ever stored here or
--    anywhere else — see the views at the bottom for dynamic calculation.
-- ============================================================================
create table if not exists user_attempts (
    id                       uuid primary key default gen_random_uuid(),
    user_id                   uuid not null references users(id) on delete cascade,
    question_id               uuid not null references questions(id) on delete cascade,
    poll_id                   uuid references polls(id) on delete set null,
    selected_option            char(1) not null check (selected_option in ('A', 'B', 'C', 'D')),
    is_correct                 boolean not null,
    answered_at                timestamptz not null default now(),
    response_time_seconds      numeric,        -- answered_at - polls.posted_at, computed at write time
    session_type               text not null default 'daily_mcq'
                                   check (session_type in ('daily_mcq', 'mock_test', 'practice')),

    -- Telegram quiz-type polls lock a user's vote after their first answer,
    -- so one attempt per user per poll is the correct real-world constraint.
    unique (user_id, poll_id)
);

create index if not exists idx_attempts_user_id     on user_attempts (user_id);
create index if not exists idx_attempts_question_id on user_attempts (question_id);
create index if not exists idx_attempts_poll_id     on user_attempts (poll_id);
create index if not exists idx_attempts_answered_at on user_attempts (answered_at);


-- ============================================================================
-- 5. BOT_STATE — tiny operational key/value store. Replaces the old
--    quiz_history.json file for anything that isn't a "learning" record —
--    right now, just the Telegram getUpdates offset used by the poll-answer
--    sync job (telegram/updates.py).
-- ============================================================================
create table if not exists bot_state (
    key           text primary key,
    value         text,
    updated_at    timestamptz not null default now()
);


-- ============================================================================
-- 6. PERSONAL_REVIEW_SCHEDULE — reserved for future personalized spaced
--    repetition (System 2). Created now so the schema never needs to change
--    when the Revision Bot / Dashboard / App is built, but NOT read or
--    written by the Daily MCQ Bot today — today's group polls are chosen
--    entirely by the Global Question Scheduler (System 1) in `questions`.
-- ============================================================================
create table if not exists personal_review_schedule (
    id                  uuid primary key default gen_random_uuid(),
    user_id              uuid not null references users(id) on delete cascade,
    question_id          uuid not null references questions(id) on delete cascade,
    ease_factor           numeric not null default 2.5,
    review_interval        int not null default 0,     -- days
    next_review            date,
    repetition_count        int not null default 0,
    last_review             timestamptz,
    learning_stage           text not null default 'new'
                                check (learning_stage in ('new', 'learning', 'review', 'mastered')),

    unique (user_id, question_id)
);


-- ============================================================================
-- Views — dynamic analytics only. Nothing above stores a calculated value;
-- these views compute everything fresh on every read, per the project's
-- "never store calculated values" rule. Free for the Dashboard/Website to
-- query directly once they exist.
-- ============================================================================

create or replace view v_user_stats as
select
    u.id                                                     as user_id,
    u.telegram_id,
    u.username,
    count(a.id)                                               as total_attempts,
    count(a.id) filter (where a.is_correct)                    as correct_attempts,
    round(
        100.0 * count(a.id) filter (where a.is_correct) / nullif(count(a.id), 0), 2
    )                                                          as accuracy_pct,
    avg(a.response_time_seconds)                               as avg_response_time_seconds,
    max(a.answered_at)                                          as last_attempt_at
from users u
left join user_attempts a on a.user_id = u.id
group by u.id, u.telegram_id, u.username;

create or replace view v_question_stats as
select
    q.id                                                       as question_id,
    q.subject,
    q.topic,
    q.difficulty,
    q.usage_count,
    count(a.id)                                                 as total_attempts,
    count(a.id) filter (where a.is_correct)                      as correct_attempts,
    round(
        100.0 * count(a.id) filter (where a.is_correct) / nullif(count(a.id), 0), 2
    )                                                            as correct_pct
from questions q
left join user_attempts a on a.question_id = q.id
group by q.id, q.subject, q.topic, q.difficulty, q.usage_count;

create or replace view v_subject_recent_usage as
select
    subject,
    count(*)                                                     as total_questions,
    count(*) filter (where last_used_at >= now() - interval '30 days') as used_last_30_days,
    max(last_used_at)                                             as most_recent_use
from questions
group by subject;

-- ============================================================================
-- 7. SUBJECT QUIZ RUNS, CHAPTER HISTORY, AND IMMUTABLE SUBMISSIONS
-- ============================================================================
create table if not exists quiz_runs (
    quiz_id text primary key,
    quiz_date date not null,
    subject_key text not null,
    subject_display_name text not null,
    internal_subject text not null,
    chapter text not null,
    status text not null check (status in ('pending','generating','generated','posting','posted','generation_failed','posting_failed')),
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
create index if not exists idx_chapter_history_subject_date on chapter_history (subject_key, selected_for desc);

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
create index if not exists idx_quiz_submissions_leaderboard on quiz_submissions (quiz_id, score desc, completed_at asc);
create index if not exists idx_polls_run_slot on polls (bot_type, run_slot);
