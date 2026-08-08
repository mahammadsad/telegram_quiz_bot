-- Phase C: additive knowledge identity, atomic evidence, immutable variants,
-- and append-only verification/usage records. Existing question and quiz IDs
-- are intentionally preserved; every new relationship starts nullable.

create table if not exists public.knowledge_points (
    id uuid primary key default extensions.gen_random_uuid(),
    knowledge_key text not null unique
        check (knowledge_key ~ '^[0-9a-f]{64}$'),
    subject_key text not null
        references public.quiz_subjects(subject_key) on delete restrict,
    micro_topic_id uuid
        references public.quiz_micro_topics(id) on delete restrict,
    canonical_claim text not null check (length(btrim(canonical_claim)) >= 3),
    entity_key text not null check (length(btrim(entity_key)) >= 1),
    relation_key text not null check (length(btrim(relation_key)) >= 1),
    answer_value text not null check (length(btrim(answer_value)) >= 1),
    time_scope text not null default 'timeless',
    syllabus_location text,
    syllabus_status text not null default 'mapped'
        check (syllabus_status in ('unmapped','mapped','review_required','retired')),
    status text not null default 'active'
        check (status in ('draft','active','quarantined','retired')),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_knowledge_points_micro_topic
    on public.knowledge_points (micro_topic_id)
    where micro_topic_id is not null;
create index if not exists idx_knowledge_points_active_subject
    on public.knowledge_points (subject_key, time_scope, created_at)
    where status = 'active' and syllabus_status = 'mapped';

create table if not exists public.source_facts (
    id uuid primary key default extensions.gen_random_uuid(),
    source_document_id uuid not null
        references public.source_documents(id) on delete restrict,
    fact_checksum text not null check (fact_checksum ~ '^[0-9a-f]{64}$'),
    canonical_fact text not null check (length(btrim(canonical_fact)) >= 3),
    evidence_span text not null check (length(btrim(evidence_span)) >= 3),
    document_version text not null check (length(btrim(document_version)) >= 1),
    source_event_at timestamptz,
    effective_from timestamptz,
    effective_until timestamptz,
    expires_at timestamptz,
    review_required boolean not null default true,
    verification_status text not null default 'draft'
        check (verification_status in ('draft','verified','rejected','stale','quarantined')),
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    unique (source_document_id, fact_checksum),
    check (effective_until is null or effective_from is null or effective_until > effective_from),
    check (verification_status <> 'verified' or verified_at is not null)
);

create index if not exists idx_source_facts_document
    on public.source_facts (source_document_id);
create index if not exists idx_source_facts_verified_current
    on public.source_facts (expires_at, effective_until, created_at)
    where verification_status = 'verified' and not review_required;

create table if not exists public.knowledge_point_evidence (
    id bigint generated always as identity primary key,
    knowledge_point_id uuid not null
        references public.knowledge_points(id) on delete restrict,
    source_fact_id uuid not null
        references public.source_facts(id) on delete restrict,
    support_type text not null default 'supports'
        check (support_type in ('supports','contradicts','supersedes')),
    confidence numeric not null check (confidence between 0 and 1),
    is_primary boolean not null default false,
    created_at timestamptz not null default now(),
    unique (knowledge_point_id, source_fact_id, support_type)
);

create index if not exists idx_knowledge_point_evidence_fact
    on public.knowledge_point_evidence (source_fact_id);
create index if not exists idx_knowledge_point_evidence_primary
    on public.knowledge_point_evidence (knowledge_point_id, confidence desc)
    where support_type = 'supports';

alter table public.questions add column if not exists knowledge_point_id uuid
    references public.knowledge_points(id) on delete restrict;
alter table public.questions add column if not exists variant_fingerprint text;
alter table public.questions add column if not exists question_form text not null default 'mcq';
alter table public.questions add column if not exists inventory_status text not null default 'legacy';
alter table public.questions add column if not exists eligible_at timestamptz;

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'questions_variant_fingerprint_check'
          and conrelid = 'public.questions'::regclass
    ) then
        alter table public.questions add constraint questions_variant_fingerprint_check
            check (variant_fingerprint is null or variant_fingerprint ~ '^[0-9a-f]{64}$');
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'questions_inventory_status_check'
          and conrelid = 'public.questions'::regclass
    ) then
        alter table public.questions add constraint questions_inventory_status_check
            check (inventory_status in (
                'legacy','candidate','verified','quarantined','rejected','used','superseded'
            ));
    end if;
end;
$$;

create index if not exists idx_questions_knowledge_point
    on public.questions (knowledge_point_id)
    where knowledge_point_id is not null;
create unique index if not exists idx_questions_variant_fingerprint_unique
    on public.questions (variant_fingerprint)
    where variant_fingerprint is not null;
create index if not exists idx_questions_verified_inventory_eligible
    on public.questions (subject, eligible_at, last_used_at, created_at)
    where status = 'active'
      and verification_status = 'verified'
      and inventory_status in ('verified','used')
      and not review_required;

create table if not exists public.question_generation_contexts (
    id uuid primary key default extensions.gen_random_uuid(),
    quiz_id text references public.quiz_runs(quiz_id) on delete restrict,
    subject_key text not null
        references public.quiz_subjects(subject_key) on delete restrict,
    micro_topic_id uuid
        references public.quiz_micro_topics(id) on delete restrict,
    prompt_hash text not null check (prompt_hash ~ '^[0-9a-f]{64}$'),
    provider text not null,
    model text not null,
    latency_ms integer check (latency_ms is null or latency_ms >= 0),
    input_tokens integer check (input_tokens is null or input_tokens >= 0),
    output_tokens integer check (output_tokens is null or output_tokens >= 0),
    source_document_ids uuid[] not null default '{}',
    candidate_count integer not null default 0 check (candidate_count >= 0),
    accepted_count integer not null default 0 check (accepted_count >= 0),
    rejection_codes text[] not null default '{}',
    novelty_metrics jsonb not null default '{}'::jsonb
        check (jsonb_typeof(novelty_metrics) = 'object'),
    created_at timestamptz not null default now()
);

create index if not exists idx_generation_contexts_quiz
    on public.question_generation_contexts (quiz_id)
    where quiz_id is not null;
create index if not exists idx_generation_contexts_subject_created
    on public.question_generation_contexts (subject_key, created_at desc);
create index if not exists idx_generation_contexts_micro_topic
    on public.question_generation_contexts (micro_topic_id)
    where micro_topic_id is not null;

create table if not exists public.content_verification_artifacts (
    id bigint generated always as identity primary key,
    knowledge_point_id uuid
        references public.knowledge_points(id) on delete restrict,
    question_id uuid references public.questions(id) on delete restrict,
    source_fact_id uuid references public.source_facts(id) on delete restrict,
    verdict text not null check (verdict in ('verified','rejected','quarantined','stale')),
    confidence numeric check (confidence is null or confidence between 0 and 1),
    verifier_type text not null,
    verifier_ref text,
    checks jsonb not null default '{}'::jsonb check (jsonb_typeof(checks) = 'object'),
    notes text,
    checked_at timestamptz not null default now(),
    check (num_nonnulls(knowledge_point_id, question_id, source_fact_id) >= 1)
);

create index if not exists idx_content_verification_knowledge_point
    on public.content_verification_artifacts (knowledge_point_id, checked_at desc)
    where knowledge_point_id is not null;
create index if not exists idx_content_verification_question
    on public.content_verification_artifacts (question_id, checked_at desc)
    where question_id is not null;
create index if not exists idx_content_verification_source_fact
    on public.content_verification_artifacts (source_fact_id, checked_at desc)
    where source_fact_id is not null;

create table if not exists public.content_usage_events (
    id bigint generated always as identity primary key,
    question_id uuid not null references public.questions(id) on delete restrict,
    knowledge_point_id uuid
        references public.knowledge_points(id) on delete restrict,
    quiz_id text references public.quiz_runs(quiz_id) on delete restrict,
    event_type text not null check (event_type in ('selected','posted','answered','retired')),
    usage_scope text not null default 'daily_mcq',
    relaxed_constraints text[] not null default '{}',
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    occurred_at timestamptz not null default now()
);

create index if not exists idx_content_usage_question
    on public.content_usage_events (question_id, occurred_at desc);
create index if not exists idx_content_usage_knowledge_point
    on public.content_usage_events (knowledge_point_id, occurred_at desc)
    where knowledge_point_id is not null;
create index if not exists idx_content_usage_quiz
    on public.content_usage_events (quiz_id)
    where quiz_id is not null;

create or replace function public.reject_append_only_content_mutation()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    raise exception '% is append-only', tg_table_name;
end;
$$;

drop trigger if exists protect_content_verification_artifacts_append_only
    on public.content_verification_artifacts;
create trigger protect_content_verification_artifacts_append_only
before update or delete on public.content_verification_artifacts
for each row execute function public.reject_append_only_content_mutation();

drop trigger if exists protect_content_usage_events_append_only
    on public.content_usage_events;
create trigger protect_content_usage_events_append_only
before update or delete on public.content_usage_events
for each row execute function public.reject_append_only_content_mutation();

drop trigger if exists protect_question_generation_contexts_append_only
    on public.question_generation_contexts;
create trigger protect_question_generation_contexts_append_only
before update or delete on public.question_generation_contexts
for each row execute function public.reject_append_only_content_mutation();

alter table public.knowledge_points enable row level security;
alter table public.source_facts enable row level security;
alter table public.knowledge_point_evidence enable row level security;
alter table public.question_generation_contexts enable row level security;
alter table public.content_verification_artifacts enable row level security;
alter table public.content_usage_events enable row level security;

revoke all on table public.knowledge_points from public, anon, authenticated;
revoke all on table public.source_facts from public, anon, authenticated;
revoke all on table public.knowledge_point_evidence from public, anon, authenticated;
revoke all on table public.question_generation_contexts from public, anon, authenticated;
revoke all on table public.content_verification_artifacts from public, anon, authenticated;
revoke all on table public.content_usage_events from public, anon, authenticated;
revoke all on sequence public.knowledge_point_evidence_id_seq from public, anon, authenticated;
revoke all on sequence public.content_verification_artifacts_id_seq from public, anon, authenticated;
revoke all on sequence public.content_usage_events_id_seq from public, anon, authenticated;

grant select, insert, update on table public.knowledge_points to service_role;
grant select, insert, update on table public.source_facts to service_role;
grant select, insert on table public.knowledge_point_evidence to service_role;
grant select, insert on table public.question_generation_contexts to service_role;
grant select, insert on table public.content_verification_artifacts to service_role;
grant select, insert on table public.content_usage_events to service_role;
grant usage, select on sequence public.knowledge_point_evidence_id_seq to service_role;
grant usage, select on sequence public.content_verification_artifacts_id_seq to service_role;
grant usage, select on sequence public.content_usage_events_id_seq to service_role;

create or replace function public.get_phase_c_content_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'ready',
        to_regclass('public.knowledge_points') is not null
        and to_regclass('public.source_facts') is not null
        and to_regclass('public.knowledge_point_evidence') is not null
        and to_regclass('public.content_verification_artifacts') is not null
        and to_regclass('public.content_usage_events') is not null
        and exists (
            select 1 from pg_attribute
            where attrelid = 'public.questions'::regclass
              and attname = 'variant_fingerprint' and not attisdropped
        ),
    'knowledge_points', to_regclass('public.knowledge_points') is not null,
    'atomic_source_facts', to_regclass('public.source_facts') is not null,
    'question_variants', exists (
        select 1 from pg_attribute
        where attrelid = 'public.questions'::regclass
          and attname = 'knowledge_point_id' and not attisdropped
    ),
    'append_only_verification',
        to_regclass('public.content_verification_artifacts') is not null,
    'append_only_usage', to_regclass('public.content_usage_events') is not null
);
$$;

revoke all on function public.reject_append_only_content_mutation() from public, anon, authenticated;
revoke all on function public.get_phase_c_content_contract() from public, anon, authenticated;
grant execute on function public.get_phase_c_content_contract() to service_role;

comment on column public.questions.knowledge_point_id is
    'Nullable Phase C link: existing historical question IDs remain valid.';
comment on column public.questions.variant_fingerprint is
    'Stable normalized stem/options/answer/language identity; excludes mutable verification and usage metadata.';
