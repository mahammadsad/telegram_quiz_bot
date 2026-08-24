-- Production integrity contract v2
--
-- Corrects stem-only question identity, verifies persisted quiz checksums,
-- requires UUID attempt idempotency keys, and exposes one authoritative schema
-- contract. This migration is additive with respect to user and quiz history.
-- Historical question versions and attempts are never deleted.

create extension if not exists pgcrypto;

-- ---------------------------------------------------------------------------
-- Immutable question identity
-- ---------------------------------------------------------------------------

alter table public.questions add column if not exists stem_hash text;
alter table public.questions add column if not exists content_hash text;
alter table public.questions add column if not exists content_version integer;
alter table public.questions add column if not exists supersedes_question_id uuid
    references public.questions(id) on delete restrict;
alter table public.questions add column if not exists language text not null default 'bn';
alter table public.questions add column if not exists source_kind text;
alter table public.questions add column if not exists evidence_summary text;

alter table public.questions drop constraint if exists questions_language_check;
alter table public.questions add constraint questions_language_check
    check (language in ('bn', 'en', 'bn-en'));
alter table public.questions drop constraint if exists questions_content_version_check;
alter table public.questions add constraint questions_content_version_check
    check (content_version is null or content_version > 0);

create or replace function public.question_stem_hash(p_question_text text)
returns text
language sql
immutable
strict
security invoker
set search_path = ''
as $$
    select encode(
        extensions.digest(
            convert_to(
                btrim(regexp_replace(
                    regexp_replace(
                        lower(btrim(coalesce(p_question_text, ''))),
                        $punct$[।,.!?"'‘’“”:;()\[\]{}—–-]+$punct$,
                        ' ',
                        'g'
                    ),
                    '[[:space:]]+',
                    ' ',
                    'g'
                )),
                'UTF8'
            ),
            'sha256'
        ),
        'hex'
    );
$$;

create or replace function public.content_hash_part(p_name text, p_value text)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    select coalesce(p_name, '') || ':'
        || octet_length(coalesce(p_value, ''))::text || ':'
        || coalesce(p_value, '') || E'\n';
$$;

create or replace function public.canonical_content_text(p_value text)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    select btrim(regexp_replace(coalesce(p_value, ''), '[[:space:]]+', ' ', 'g'));
$$;

create or replace function public.canonical_content_timestamp(p_value text)
returns text
language plpgsql
stable
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(coalesce(p_value, '')), '') is null then
        return '';
    end if;
    return to_char(
        p_value::timestamptz at time zone 'UTC',
        'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
    );
exception when invalid_datetime_format or datetime_field_overflow then
    raise exception 'invalid content timestamp';
end;
$$;

create or replace function public.canonical_content_score(p_value text)
returns text
language plpgsql
immutable
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(coalesce(p_value, '')), '') is null then
        return '';
    end if;
    return to_char(p_value::numeric, 'FM0.000000');
exception when invalid_text_representation or numeric_value_out_of_range then
    raise exception 'invalid verification score';
end;
$$;

create or replace function public.question_content_hash(p_question jsonb)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
    select encode(extensions.digest(convert_to(
        public.content_hash_part('question_text', public.canonical_content_text(p_question ->> 'question_text'))
        || public.content_hash_part('option_a', public.canonical_content_text(p_question ->> 'option_a'))
        || public.content_hash_part('option_b', public.canonical_content_text(p_question ->> 'option_b'))
        || public.content_hash_part('option_c', public.canonical_content_text(p_question ->> 'option_c'))
        || public.content_hash_part('option_d', public.canonical_content_text(p_question ->> 'option_d'))
        || public.content_hash_part('correct_option', upper(btrim(coalesce(p_question ->> 'correct_option', ''))))
        || public.content_hash_part('explanation', public.canonical_content_text(p_question ->> 'explanation'))
        || public.content_hash_part('detailed_explanation', public.canonical_content_text(p_question ->> 'detailed_explanation'))
        || public.content_hash_part('subject', lower(btrim(coalesce(p_question ->> 'subject', ''))))
        || public.content_hash_part('topic', public.canonical_content_text(p_question ->> 'topic'))
        || public.content_hash_part('micro_topic_key', lower(btrim(coalesce(p_question ->> 'micro_topic_key', ''))))
        || public.content_hash_part('difficulty', lower(btrim(coalesce(p_question ->> 'difficulty', ''))))
        || public.content_hash_part('language', lower(btrim(coalesce(p_question ->> 'language', 'bn'))))
        || public.content_hash_part('source_document_id', lower(btrim(coalesce(p_question ->> 'source_document_id', ''))))
        || public.content_hash_part('source_url', btrim(coalesce(p_question ->> 'source_url', '')))
        || public.content_hash_part('source_title', public.canonical_content_text(p_question ->> 'source_title'))
        || public.content_hash_part('source_domain', lower(btrim(coalesce(p_question ->> 'source_domain', ''))))
        || public.content_hash_part('source_kind', lower(btrim(coalesce(p_question ->> 'source_kind', ''))))
        || public.content_hash_part('source_published_at', public.canonical_content_timestamp(p_question ->> 'source_published_at'))
        || public.content_hash_part('source_accessed_at', public.canonical_content_timestamp(p_question ->> 'source_accessed_at'))
        || public.content_hash_part('evidence_summary', public.canonical_content_text(p_question ->> 'evidence_summary'))
        || public.content_hash_part('fact_version', public.canonical_content_text(p_question ->> 'fact_version'))
        || public.content_hash_part('verification_status', lower(btrim(coalesce(p_question ->> 'verification_status', ''))))
        || public.content_hash_part('verification_score', public.canonical_content_score(p_question ->> 'verification_score'))
        || public.content_hash_part('verification_notes', public.canonical_content_text(p_question ->> 'verification_notes'))
        || public.content_hash_part('verified_at', public.canonical_content_timestamp(p_question ->> 'verified_at'))
        || public.content_hash_part('verification_model', public.canonical_content_text(p_question ->> 'verification_model')),
        'UTF8'
    ), 'sha256'), 'hex');
$$;

-- Source facts already are immutable. Snapshot their evidence into historical
-- questions so later source lifecycle changes cannot alter question provenance.
update public.questions q
set source_kind = coalesce(q.source_kind, source.source_kind),
    evidence_summary = coalesce(q.evidence_summary, source.fact_summary)
from public.source_documents source
where source.id = q.source_document_id
  and (q.source_kind is null or q.evidence_summary is null);

update public.questions
set stem_hash = public.question_stem_hash(question_text)
where stem_hash is null;

update public.questions
set language = case
        when subject = 'english' then 'bn-en'
        else 'bn'
    end
where language is null or language not in ('bn', 'en', 'bn-en');

update public.questions
set content_hash = public.question_content_hash(to_jsonb(questions))
where content_hash is null;

with versions as (
    select id,
           row_number() over (
               partition by stem_hash order by created_at, id
           )::integer as version_number,
           lag(id) over (
               partition by stem_hash order by created_at, id
           ) as previous_id
    from public.questions
)
update public.questions q
set content_version = versions.version_number,
    supersedes_question_id = coalesce(q.supersedes_question_id, versions.previous_id)
from versions
where versions.id = q.id
  and q.content_version is null;

-- The original global unique constraint encoded stem identity as content
-- identity. Remove only that constraint, retaining the legacy column as a
-- compatibility alias for stem_hash.
do $$
declare
    constraint_name text;
begin
    for constraint_name in
        select con.conname
        from pg_catalog.pg_constraint con
        join pg_catalog.pg_class rel on rel.oid = con.conrelid
        join pg_catalog.pg_namespace ns on ns.oid = rel.relnamespace
        where ns.nspname = 'public'
          and rel.relname = 'questions'
          and con.contype = 'u'
          and pg_get_constraintdef(con.oid) = 'UNIQUE (question_hash)'
    loop
        execute format('alter table public.questions drop constraint %I', constraint_name);
    end loop;
end;
$$;

alter table public.questions alter column stem_hash set not null;
alter table public.questions alter column content_hash set not null;
alter table public.questions alter column content_version set not null;

create unique index if not exists idx_questions_content_hash_unique
    on public.questions (content_hash);
create unique index if not exists idx_questions_stem_content_version_unique
    on public.questions (stem_hash, content_version);
create index if not exists idx_questions_stem_versions
    on public.questions (stem_hash, content_version desc);

alter table public.questions drop constraint if exists questions_status_check;
alter table public.questions add constraint questions_status_check check (
    status in (
        'draft','generated','verified','active','reported','under_review',
        'quarantined','rejected','archived'
    )
);

create or replace function public.protect_immutable_question_version()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.question_text is distinct from old.question_text
       or new.option_a is distinct from old.option_a
       or new.option_b is distinct from old.option_b
       or new.option_c is distinct from old.option_c
       or new.option_d is distinct from old.option_d
       or new.correct_option is distinct from old.correct_option
       or new.explanation is distinct from old.explanation
       or new.detailed_explanation is distinct from old.detailed_explanation
       or new.subject is distinct from old.subject
       or new.topic is distinct from old.topic
       or new.micro_topic_id is distinct from old.micro_topic_id
       or new.micro_topic_key is distinct from old.micro_topic_key
       or new.difficulty is distinct from old.difficulty
       or new.language is distinct from old.language
       or new.source_document_id is distinct from old.source_document_id
       or new.source_url is distinct from old.source_url
       or new.source_title is distinct from old.source_title
       or new.source_domain is distinct from old.source_domain
       or new.source_kind is distinct from old.source_kind
       or new.source_published_at is distinct from old.source_published_at
       or new.source_accessed_at is distinct from old.source_accessed_at
       or new.evidence_summary is distinct from old.evidence_summary
       or new.fact_version is distinct from old.fact_version
       or new.verification_status is distinct from old.verification_status
       or new.verification_score is distinct from old.verification_score
       or new.verification_notes is distinct from old.verification_notes
       or new.verified_at is distinct from old.verified_at
       or new.verification_model is distinct from old.verification_model
       or new.stem_hash is distinct from old.stem_hash
       or new.content_hash is distinct from old.content_hash
       or new.content_version is distinct from old.content_version
       or new.supersedes_question_id is distinct from old.supersedes_question_id
       or new.question_hash is distinct from old.question_hash
       or new.normalized_text is distinct from old.normalized_text then
        raise exception 'question versions are immutable; insert a new content version';
    end if;
    return new;
end;
$$;

drop trigger if exists protect_immutable_question_version on public.questions;
create trigger protect_immutable_question_version
before update on public.questions
for each row execute function public.protect_immutable_question_version();

-- ---------------------------------------------------------------------------
-- Generated-versus-persisted quiz checksums
-- ---------------------------------------------------------------------------

alter table public.quiz_runs add column if not exists generated_checksum text;
alter table public.quiz_runs add column if not exists persisted_checksum text;
alter table public.quiz_runs add column if not exists checksum_contract_version integer
    not null default 1;
alter table public.quiz_runs add column if not exists integrity_verified boolean
    not null default false;
alter table public.quiz_runs add column if not exists ready_at timestamptz;
alter table public.quiz_runs add column if not exists integrity_diagnostic_code text;

alter table public.quiz_runs drop constraint if exists quiz_runs_status_check;
alter table public.quiz_runs add constraint quiz_runs_status_check check (
    status in (
        'pending', 'generating', 'generated', 'ready', 'posting', 'posted',
        'generation_failed', 'integrity_failed', 'posting_failed',
        'posting_unknown'
    )
);

create or replace function public.quiz_pack_checksum(p_quiz_id text)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
    select encode(extensions.digest(convert_to(
        public.content_hash_part('quiz_id', r.quiz_id)
        || public.content_hash_part('subject_key', lower(btrim(r.subject_key)))
        || public.content_hash_part('chapter', public.canonical_content_text(r.chapter))
        || coalesce((
            select string_agg(
                public.content_hash_part(
                    'question_' || qq.question_order::text,
                    public.question_content_hash(to_jsonb(q))
                ),
                '' order by qq.question_order
            )
            from public.quiz_questions qq
            join public.questions q on q.id = qq.question_id
            where qq.quiz_id = r.quiz_id
        ), ''),
        'UTF8'
    ), 'sha256'), 'hex')
    from public.quiz_runs r
    where r.quiz_id = p_quiz_id
      and (select count(*) from public.quiz_questions qq where qq.quiz_id = r.quiz_id) = 10;
$$;

create or replace function public.claim_quiz_run(
    p_quiz_id text,
    p_worker_id text,
    p_target_status text,
    p_claim_timeout_minutes integer default 20,
    p_allow_completed boolean default false
)
returns setof public.quiz_runs
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(p_quiz_id), '') is null
       or nullif(btrim(p_worker_id), '') is null then
        raise exception 'quiz_id and worker_id are required';
    end if;
    if p_target_status not in ('generating', 'posting') then
        raise exception 'invalid claim target status';
    end if;

    return query
    update public.quiz_runs r
    set worker_id = p_worker_id,
        claimed_at = now(),
        claim_expires_at = now() + make_interval(
            mins => greatest(5, least(coalesce(p_claim_timeout_minutes, 20), 120))
        ),
        processing_started_at = coalesce(r.processing_started_at, now()),
        status = p_target_status,
        updated_at = now()
    where r.quiz_id = p_quiz_id
      and (p_allow_completed or r.status <> 'posted')
      and (
          p_target_status <> 'posting'
          or (
              r.integrity_verified
              and r.checksum_contract_version = 2
              and r.generated_checksum is not null
              and r.generated_checksum = r.persisted_checksum
              and r.status in ('ready', 'posting_failed', 'posted')
          )
      )
      and (
          r.worker_id is null
          or r.worker_id = p_worker_id
          or r.claim_expires_at is null
          or r.claim_expires_at <= now()
      )
    returning r.*;
end;
$$;

create table if not exists public.quiz_pack_integrity_failures (
    id uuid primary key default extensions.gen_random_uuid(),
    quiz_id text not null references public.quiz_runs(quiz_id) on delete restrict,
    worker_id text not null,
    generated_checksum text not null,
    persisted_checksum text,
    question_ids uuid[] not null default '{}',
    question_count integer not null check (question_count between 0 and 10),
    diagnostic_code text not null,
    created_at timestamptz not null default now()
);

create index if not exists idx_quiz_pack_integrity_failures_quiz
    on public.quiz_pack_integrity_failures (quiz_id, created_at desc);

create or replace function public.save_quiz_pack_atomic(
    p_quiz_id text,
    p_worker_id text,
    p_questions jsonb,
    p_content_checksum text,
    p_replace boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_effective_item jsonb;
    v_order integer;
    v_question_id uuid;
    v_existing public.questions%rowtype;
    v_previous public.questions%rowtype;
    v_source public.source_documents%rowtype;
    v_micro_topic public.quiz_micro_topics%rowtype;
    v_mapping_count integer;
    v_stem_hash text;
    v_content_hash text;
    v_content_version integer;
    v_persisted_checksum text;
    v_ready boolean;
begin
    if nullif(btrim(coalesce(p_quiz_id, '')), '') is null
       or nullif(btrim(coalesce(p_worker_id, '')), '') is null then
        raise exception 'quiz_id and worker_id are required';
    end if;
    if jsonb_typeof(p_questions) <> 'array'
       or jsonb_array_length(p_questions) <> 10 then
        raise exception 'quiz pack must contain exactly 10 questions';
    end if;
    if coalesce(p_content_checksum, '') !~ '^[0-9a-f]{64}$' then
        raise exception 'a valid content checksum is required';
    end if;
    if not exists (
        select 1 from public.quiz_runs r
        where r.quiz_id = p_quiz_id
          and r.worker_id = p_worker_id
          and r.claim_expires_at > now()
    ) then
        raise exception 'quiz run is not owned by this worker';
    end if;

    -- A complete existing pack is reused only if its database checksum matches
    -- the newly supplied generated checksum. A mismatched pack remains mapped
    -- and is recorded for operator diagnosis.
    select count(*) into v_mapping_count
    from public.quiz_questions qq
    where qq.quiz_id = p_quiz_id;

    if v_mapping_count = 10 and not p_replace then
        v_persisted_checksum := public.quiz_pack_checksum(p_quiz_id);
        v_ready := v_persisted_checksum = p_content_checksum;
        if v_ready then
            update public.quiz_runs
            set status = 'ready',
                question_count = 10,
                content_checksum = p_content_checksum,
                generated_checksum = p_content_checksum,
                persisted_checksum = v_persisted_checksum,
                checksum_contract_version = 2,
                integrity_verified = true,
                integrity_diagnostic_code = null,
                generated_at = coalesce(generated_at, now()),
                ready_at = coalesce(ready_at, now()),
                updated_at = now()
            where quiz_id = p_quiz_id and worker_id = p_worker_id;
        else
            insert into public.quiz_pack_integrity_failures (
                quiz_id, worker_id, generated_checksum, persisted_checksum,
                question_ids, question_count, diagnostic_code
            )
            select p_quiz_id, p_worker_id, p_content_checksum,
                   v_persisted_checksum,
                   coalesce(array_agg(qq.question_id order by qq.question_order), '{}'),
                   count(*)::integer,
                   'existing_pack_checksum_mismatch'
            from public.quiz_questions qq
            where qq.quiz_id = p_quiz_id;

            update public.quiz_runs
            set status = 'integrity_failed',
                question_count = 10,
                generated_checksum = p_content_checksum,
                persisted_checksum = v_persisted_checksum,
                checksum_contract_version = 2,
                integrity_verified = false,
                integrity_diagnostic_code = 'existing_pack_checksum_mismatch',
                last_error_category = 'database_integrity_error',
                last_error_at = now(),
                worker_id = null,
                claimed_at = null,
                claim_expires_at = null,
                updated_at = now()
            where quiz_id = p_quiz_id and worker_id = p_worker_id;
        end if;
        return jsonb_build_object(
            'quiz_id', p_quiz_id,
            'question_count', 10,
            'reused', true,
            'ready', v_ready,
            'generated_checksum', p_content_checksum,
            'persisted_checksum', v_persisted_checksum
        );
    end if;

    if v_mapping_count > 0 and not p_replace then
        raise exception 'existing quiz pack is incomplete; explicit replacement is required';
    end if;

    if p_replace then
        delete from public.quiz_questions where quiz_id = p_quiz_id;
    end if;

    v_order := 0;
    for v_item in
        select value from jsonb_array_elements(p_questions)
    loop
        v_order := v_order + 1;
        if nullif(btrim(v_item ->> 'question_text'), '') is null
           or nullif(btrim(v_item ->> 'option_a'), '') is null
           or nullif(btrim(v_item ->> 'option_b'), '') is null
           or nullif(btrim(v_item ->> 'option_c'), '') is null
           or nullif(btrim(v_item ->> 'option_d'), '') is null
           or nullif(btrim(v_item ->> 'subject'), '') is null
           or nullif(btrim(v_item ->> 'topic'), '') is null
           or v_item ->> 'correct_option' not in ('A', 'B', 'C', 'D')
           or v_item ->> 'verification_status' <> 'verified'
           or coalesce((v_item ->> 'verification_score')::numeric, 0) < 0.85
           or nullif(btrim(v_item ->> 'verification_notes'), '') is null
           or nullif(btrim(v_item ->> 'verified_at'), '') is null
           or coalesce(v_item ->> 'stem_hash', '') !~ '^[0-9a-f]{64}$'
           or coalesce(v_item ->> 'content_hash', '') !~ '^[0-9a-f]{64}$' then
            raise exception 'question % is missing required verified version fields', v_order;
        end if;

        select * into v_micro_topic
        from public.quiz_micro_topics mt
        where mt.id = (v_item ->> 'micro_topic_id')::uuid
          and mt.key = v_item ->> 'micro_topic_key'
          and mt.active;
        if not found then
            raise exception 'question % has an invalid micro-topic', v_order;
        end if;
        if not exists (
            select 1 from public.quiz_chapters c
            where c.id = v_micro_topic.chapter_id
              and c.subject_key = v_item ->> 'subject'
              and c.name = v_item ->> 'topic'
              and c.active
        ) then
            raise exception 'question % micro-topic does not belong to its active chapter', v_order;
        end if;

        select * into v_source
        from public.source_documents source
        where source.id = (v_item ->> 'source_document_id')::uuid
          and source.micro_topic_id = v_micro_topic.id
          and source.verification_status = 'verified'
          and not source.review_required
          and (source.expires_at is null or source.expires_at >= now());
        if not found then
            raise exception 'question % does not cite a current verified source', v_order;
        end if;
        if v_item ->> 'subject' = 'current-affairs'
           and (
               v_source.source_kind not in ('official', 'primary')
               or v_source.source_published_at is null
               or v_source.source_published_at::date < current_date - 45
               or v_source.source_published_at::date > current_date
           ) then
            raise exception 'current-affairs question % has no recent primary source', v_order;
        end if;

        -- Provenance comes from the verified database row, not from model text.
        v_effective_item := v_item || jsonb_build_object(
            'source_url', v_source.source_url,
            'source_title', v_source.source_title,
            'source_domain', v_source.source_domain,
            'source_kind', v_source.source_kind,
            'source_published_at', v_source.source_published_at,
            'source_accessed_at', v_source.source_accessed_at,
            'evidence_summary', v_source.fact_summary,
            'fact_version', v_source.fact_version,
            'language', coalesce(nullif(v_item ->> 'language', ''), 'bn')
        );

        v_stem_hash := public.question_stem_hash(v_item ->> 'question_text');
        v_content_hash := public.question_content_hash(v_effective_item);
        if v_stem_hash <> v_item ->> 'stem_hash'
           or v_stem_hash <> v_item ->> 'question_hash' then
            raise exception 'question % stem hash does not match normalized text', v_order;
        end if;
        if v_content_hash <> v_item ->> 'content_hash' then
            raise exception 'question % content hash does not match complete content', v_order;
        end if;

        -- Serialize versions of one stem even when two independent quiz workers
        -- save different content concurrently.
        perform pg_advisory_xact_lock(hashtextextended('question-stem:' || v_stem_hash, 0));

        select * into v_existing
        from public.questions q
        where q.content_hash = v_content_hash
        limit 1;

        if found then
            if v_existing.stem_hash <> v_stem_hash
               or v_existing.subject <> v_item ->> 'subject'
               or v_existing.topic <> v_item ->> 'topic' then
                raise exception 'question content identity collision at position %', v_order;
            end if;
            if v_existing.status in (
                'reported', 'under_review', 'quarantined', 'rejected', 'archived'
            ) or v_existing.review_required then
                raise exception 'moderated question version cannot be reused at position %', v_order;
            end if;
            v_question_id := v_existing.id;
        else
            select * into v_previous
            from public.questions q
            where q.stem_hash = v_stem_hash
            order by q.content_version desc, q.created_at desc, q.id desc
            limit 1;

            if found then
                v_content_version := v_previous.content_version + 1;
            else
                v_content_version := 1;
                v_previous.id := null;
            end if;

            insert into public.questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, explanation, detailed_explanation, subject,
                topic, difficulty, gemini_model, source, week_number, bot_type,
                question_hash, normalized_text, status, micro_topic_id,
                micro_topic_key, source_document_id, source_url, source_title,
                source_domain, source_kind, source_published_at,
                source_accessed_at, evidence_summary, verified_at,
                verification_status, verification_notes, verification_score,
                verification_model, fact_version, expires_at, review_required,
                stem_hash, content_hash, content_version,
                supersedes_question_id, language
            ) values (
                v_item ->> 'question_text', v_item ->> 'option_a',
                v_item ->> 'option_b', v_item ->> 'option_c',
                v_item ->> 'option_d', v_item ->> 'correct_option',
                v_item ->> 'explanation', v_item ->> 'detailed_explanation',
                v_item ->> 'subject', v_item ->> 'topic',
                lower(coalesce(nullif(v_item ->> 'difficulty', ''), 'medium')),
                nullif(v_item ->> 'gemini_model', ''),
                coalesce(nullif(v_item ->> 'source', ''), 'verified_source'),
                nullif(v_item ->> 'week_number', '')::integer,
                coalesce(nullif(v_item ->> 'bot_type', ''), 'mock_test'),
                v_stem_hash, v_item ->> 'normalized_text', 'active',
                v_micro_topic.id, v_micro_topic.key, v_source.id,
                v_source.source_url, v_source.source_title,
                v_source.source_domain, v_source.source_kind,
                v_source.source_published_at, v_source.source_accessed_at,
                v_source.fact_summary, (v_item ->> 'verified_at')::timestamptz,
                'verified', v_item ->> 'verification_notes',
                (v_item ->> 'verification_score')::numeric,
                nullif(v_item ->> 'verification_model', ''),
                v_source.fact_version, v_source.expires_at, false,
                v_stem_hash, v_content_hash, v_content_version,
                v_previous.id,
                coalesce(nullif(v_item ->> 'language', ''), 'bn')
            ) returning id into v_question_id;

            -- Keep old versions readable through historical quiz mappings while
            -- removing superseded active versions from future scheduling.
            if v_previous.id is not null
               and v_previous.status in ('draft', 'generated', 'verified', 'active') then
                update public.questions
                set status = 'archived'
                where id = v_previous.id;
            end if;
        end if;

        insert into public.question_verifications (
            question_id, source_document_id, verifier_model, verdict,
            confidence, checks, notes, checked_at
        ) values (
            v_question_id, v_source.id,
            nullif(v_item ->> 'verification_model', ''),
            'verified', (v_item ->> 'verification_score')::numeric,
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes',
            (v_item ->> 'verified_at')::timestamptz
        );

        insert into public.quiz_questions (quiz_id, question_id, question_order)
        values (p_quiz_id, v_question_id, v_order);
    end loop;

    select count(*) into v_mapping_count
    from public.quiz_questions
    where quiz_id = p_quiz_id;
    if v_mapping_count <> 10 then
        raise exception 'atomic quiz save did not produce exactly 10 mappings';
    end if;

    -- This is intentionally calculated from rows read back through the ordered
    -- mapping after every insert/reuse has completed.
    v_persisted_checksum := public.quiz_pack_checksum(p_quiz_id);
    v_ready := v_persisted_checksum = p_content_checksum;

    if not v_ready then
        insert into public.quiz_pack_integrity_failures (
            quiz_id, worker_id, generated_checksum, persisted_checksum,
            question_ids, question_count, diagnostic_code
        )
        select p_quiz_id, p_worker_id, p_content_checksum,
               v_persisted_checksum,
               coalesce(array_agg(qq.question_id order by qq.question_order), '{}'),
               count(*)::integer,
               'saved_pack_checksum_mismatch'
        from public.quiz_questions qq
        where qq.quiz_id = p_quiz_id;

        update public.quiz_runs
        set status = 'integrity_failed',
            question_count = v_mapping_count,
            generated_checksum = p_content_checksum,
            persisted_checksum = v_persisted_checksum,
            checksum_contract_version = 2,
            integrity_verified = false,
            integrity_diagnostic_code = 'saved_pack_checksum_mismatch',
            last_error_category = 'database_integrity_error',
            last_error_at = now(),
            worker_id = null,
            claimed_at = null,
            claim_expires_at = null,
            updated_at = now()
        where quiz_id = p_quiz_id and worker_id = p_worker_id;
    else
        update public.quiz_runs
        set status = 'ready',
            question_count = 10,
            content_checksum = p_content_checksum,
            generated_checksum = p_content_checksum,
            persisted_checksum = v_persisted_checksum,
            checksum_contract_version = 2,
            integrity_verified = true,
            integrity_diagnostic_code = null,
            last_error_category = null,
            generated_at = coalesce(generated_at, now()),
            ready_at = now(),
            updated_at = now()
        where quiz_id = p_quiz_id and worker_id = p_worker_id;
    end if;

    return jsonb_build_object(
        'quiz_id', p_quiz_id,
        'question_count', v_mapping_count,
        'reused', false,
        'ready', v_ready,
        'generated_checksum', p_content_checksum,
        'persisted_checksum', v_persisted_checksum
    );
end;
$$;

-- ---------------------------------------------------------------------------
-- Mandatory UUID idempotency keys and official first-attempt scoring
-- ---------------------------------------------------------------------------

alter table public.quiz_attempts add column if not exists client_attempt_uuid uuid;

update public.quiz_attempts
set client_attempt_uuid = client_attempt_id::uuid
where client_attempt_uuid is null
  and client_attempt_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$';

create unique index if not exists idx_quiz_attempts_client_uuid_unique
    on public.quiz_attempts (quiz_id, user_id, client_attempt_uuid)
    where client_attempt_uuid is not null;

create or replace function public.require_quiz_attempt_uuid()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.client_attempt_uuid is null then
        raise exception 'a client-generated UUID attempt identifier is required';
    end if;
    if new.client_attempt_id <> new.client_attempt_uuid::text then
        raise exception 'attempt identifier representations do not match';
    end if;
    return new;
end;
$$;

drop trigger if exists require_quiz_attempt_uuid on public.quiz_attempts;
create trigger require_quiz_attempt_uuid
before insert on public.quiz_attempts
for each row execute function public.require_quiz_attempt_uuid();

create or replace function public.quiz_attempt_result(p_attempt_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with target as (
    select *
    from public.quiz_attempts
    where id = p_attempt_id and is_completed
), review as (
    select coalesce(jsonb_agg(
        jsonb_build_object(
            'questionId', aa.question_id,
            'questionVersion', q.content_version,
            'contentHash', q.content_hash,
            'q', q.question_text,
            'o', jsonb_build_array(q.option_a, q.option_b, q.option_c, q.option_d),
            'selectedIndex', aa.selected_option,
            'correctIndex', aa.correct_option,
            'isCorrect', aa.is_correct,
            'explanation', coalesce(nullif(q.detailed_explanation, ''), q.explanation, ''),
            'difficulty', q.difficulty,
            'chapter', q.topic,
            'microTopic', q.micro_topic_key,
            'sourceTitle', q.source_title,
            'sourceUrl', q.source_url,
            'sourcePublishedAt', q.source_published_at,
            'verifiedAt', q.verified_at,
            'factVersion', q.fact_version
        ) order by aa.question_order
    ), '[]'::jsonb) as rows
    from public.quiz_attempt_answers aa
    join public.questions q on q.id = aa.question_id
    where aa.attempt_id = p_attempt_id
), official as (
    select a.*
    from public.quiz_attempts a
    join target t on t.quiz_id = a.quiz_id
    where a.is_completed and a.attempt_number = 1
), ranked as (
    select
        o.*,
        row_number() over (
            order by o.score desc, o.answered desc,
                     o.duration_seconds asc nulls last,
                     o.completed_at asc, o.id
        ) as official_rank
    from official o
), current_official as (
    select ranked.*
    from ranked
    join target t on t.user_id = ranked.user_id
), totals as (
    select count(*)::integer as participants from official
)
select jsonb_build_object(
    'quizId', t.quiz_id,
    'attemptId', t.client_attempt_uuid,
    'score', t.score,
    'bestScore', (
        select max(a.score) from public.quiz_attempts a
        where a.quiz_id = t.quiz_id and a.user_id = t.user_id and a.is_completed
    ),
    'total', t.total,
    'answered', t.answered,
    'correct', t.score,
    'incorrect', t.answered - t.score,
    'unanswered', t.total - t.answered,
    'accuracy', round(100.0 * t.score / nullif(t.total, 0), 2),
    'attemptNumber', t.attempt_number,
    'isOfficialAttempt', t.attempt_number = 1,
    'rank', current_official.official_rank,
    'participants', totals.participants,
    'percentile', case
        when totals.participants <= 1 then 100.00
        else round(
            100.0 * (totals.participants - current_official.official_rank)
            / (totals.participants - 1),
            2
        )
    end,
    'durationSeconds', t.duration_seconds,
    'rankMovement', null,
    'review', review.rows
)
from target t
cross join review
cross join totals
left join current_official on true;
$$;

drop function if exists public.submit_quiz_attempt_atomic(
    text, uuid, text, jsonb, integer, jsonb, jsonb
);

create function public.submit_quiz_attempt_atomic(
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid,
    p_answers jsonb,
    p_duration_seconds integer default null,
    p_response_times jsonb default null,
    p_marked_for_review jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt_id uuid;
    v_existing_answers jsonb;
    v_score integer;
    v_answered integer;
    v_attempt_number integer;
    v_result jsonb;
begin
    if p_client_attempt_id is null then
        raise exception 'a client-generated UUID attempt identifier is required';
    end if;
    if not exists (select 1 from public.users where id = p_user_id) then
        raise exception 'authenticated user does not exist';
    end if;
    if (select count(*) from public.quiz_questions where quiz_id = p_quiz_id) <> 10 then
        raise exception 'quiz must contain exactly 10 ordered questions';
    end if;
    if not exists (
        select 1 from public.quiz_runs r
        where r.quiz_id = p_quiz_id
          and (r.integrity_verified or r.status = 'posted')
    ) then
        raise exception 'quiz is not ready for submission';
    end if;
    if jsonb_typeof(p_answers) <> 'array'
       or jsonb_array_length(p_answers) <> 10 then
        raise exception 'answers must contain exactly 10 entries';
    end if;
    if exists (
        select 1 from jsonb_array_elements(p_answers) answer(value)
        where jsonb_typeof(answer.value) <> 'null'
          and not (
              jsonb_typeof(answer.value) = 'number'
              and (answer.value #>> '{}') ~ '^[0-3]$'
          )
    ) then
        raise exception 'each answer must be 0, 1, 2, 3, or null';
    end if;
    if p_duration_seconds is not null
       and p_duration_seconds not between 0 and 86400 then
        raise exception 'duration must be between 0 and 86400 seconds';
    end if;

    -- Serialize the idempotency check and attempt-number allocation per user
    -- and quiz. Concurrent retries cannot pass this point independently.
    perform pg_advisory_xact_lock(
        hashtextextended(p_quiz_id || ':' || p_user_id::text, 0)
    );

    select id, answers into v_attempt_id, v_existing_answers
    from public.quiz_attempts
    where quiz_id = p_quiz_id
      and user_id = p_user_id
      and client_attempt_uuid = p_client_attempt_id;
    if found then
        if v_existing_answers <> p_answers then
            raise exception 'attempt identifier was already used with different answers';
        end if;
        v_result := public.quiz_attempt_result(v_attempt_id);
        return v_result || jsonb_build_object('idempotentReplay', true);
    end if;

    if (
        select count(*)
        from public.quiz_attempts
        where user_id = p_user_id
          and created_at >= now() - interval '1 hour'
    ) >= 20 then
        raise exception 'quiz submission rate limit exceeded';
    end if;

    select
        count(*) filter (where jsonb_typeof(answer.value) <> 'null'),
        count(*) filter (
            where jsonb_typeof(answer.value) <> 'null'
              and (answer.value #>> '{}')::integer
                  = strpos('ABCD', q.correct_option) - 1
        )
    into v_answered, v_score
    from public.quiz_questions qq
    join public.questions q on q.id = qq.question_id
    join lateral jsonb_array_elements(p_answers)
        with ordinality answer(value, ordinality)
      on answer.ordinality = qq.question_order
    where qq.quiz_id = p_quiz_id;

    select coalesce(max(attempt_number), 0) + 1
    into v_attempt_number
    from public.quiz_attempts
    where quiz_id = p_quiz_id and user_id = p_user_id;

    insert into public.quiz_attempts (
        quiz_id, user_id, client_attempt_id, client_attempt_uuid,
        answers, answer_checksum, score, total, answered, started_at,
        completed_at, duration_seconds, attempt_number, is_completed
    ) values (
        p_quiz_id, p_user_id, p_client_attempt_id::text, p_client_attempt_id,
        p_answers, encode(extensions.digest(p_answers::text, 'sha256'), 'hex'),
        v_score, 10, v_answered,
        case when p_duration_seconds is null then null
             else now() - make_interval(secs => p_duration_seconds) end,
        now(), p_duration_seconds, v_attempt_number, true
    ) returning id into v_attempt_id;

    insert into public.quiz_attempt_answers (
        attempt_id, question_id, question_order, selected_option,
        correct_option, is_correct, response_time_seconds,
        marked_for_review, answered_at
    )
    select
        v_attempt_id,
        qq.question_id,
        qq.question_order,
        case when jsonb_typeof(answer.value) = 'null' then null
             else (answer.value #>> '{}')::smallint end,
        (strpos('ABCD', q.correct_option) - 1)::smallint,
        case when jsonb_typeof(answer.value) = 'null' then null
             else (answer.value #>> '{}')::integer
                  = strpos('ABCD', q.correct_option) - 1 end,
        case
            when jsonb_typeof(p_response_times) = 'array'
             and jsonb_array_length(p_response_times) = 10
             and jsonb_typeof(p_response_times -> (qq.question_order - 1)) = 'number'
            then greatest(0, (p_response_times ->> (qq.question_order - 1))::numeric)
            else null
        end,
        case
            when jsonb_typeof(p_marked_for_review) = 'array'
             and jsonb_array_length(p_marked_for_review) = 10
            then coalesce(
                (p_marked_for_review ->> (qq.question_order - 1))::boolean,
                false
            )
            else false
        end,
        case when jsonb_typeof(answer.value) = 'null' then null else now() end
    from public.quiz_questions qq
    join public.questions q on q.id = qq.question_id
    join lateral jsonb_array_elements(p_answers)
        with ordinality answer(value, ordinality)
      on answer.ordinality = qq.question_order
    where qq.quiz_id = p_quiz_id;

    v_result := public.quiz_attempt_result(v_attempt_id);
    return v_result || jsonb_build_object('idempotentReplay', false);
end;
$$;

-- ---------------------------------------------------------------------------
-- One authoritative, machine-readable database contract
-- ---------------------------------------------------------------------------

create table if not exists public.application_schema_contract (
    contract_key text primary key,
    contract_version text not null,
    required_migration_version text not null,
    verification_threshold numeric not null
        check (verification_threshold between 0 and 1),
    applied_at timestamptz not null default now()
);

insert into public.application_schema_contract (
    contract_key, contract_version, required_migration_version,
    verification_threshold, applied_at
) values (
    'telegram_quiz_api', '2.0.0', '20260718220112', 0.85, now()
)
on conflict (contract_key) do update set
    contract_version = excluded.contract_version,
    required_migration_version = excluded.required_migration_version,
    verification_threshold = excluded.verification_threshold,
    applied_at = now();

create or replace function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_contract public.application_schema_contract%rowtype;
    v_migration_applied boolean := false;
    v_missing_tables jsonb;
    v_missing_columns jsonb;
    v_missing_functions jsonb;
    v_function_permission_failures jsonb;
    v_missing_rls jsonb;
    v_table_permission_failures jsonb;
begin
    select * into v_contract
    from public.application_schema_contract
    where contract_key = 'telegram_quiz_api';

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute
            'select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = $1
                   or name = ''production_integrity_contract_v2''
            )'
        into v_migration_applied
        using v_contract.required_migration_version;
    end if;

    with required(table_name) as (
        values
            ('questions'), ('quiz_runs'), ('quiz_questions'),
            ('quiz_attempts'), ('quiz_attempt_answers'), ('users'),
            ('personal_review_schedule'), ('personal_practice_answers'),
            ('user_preferences'), ('question_reports'), ('source_documents'),
            ('quiz_subjects'), ('quiz_chapters'), ('quiz_micro_topics'),
            ('application_schema_contract'), ('quiz_pack_integrity_failures')
    )
    select coalesce(jsonb_agg(table_name order by table_name), '[]'::jsonb)
    into v_missing_tables
    from required
    where to_regclass('public.' || table_name) is null;

    with required(table_name, column_name) as (
        values
            ('questions','stem_hash'), ('questions','content_hash'),
            ('questions','content_version'), ('questions','supersedes_question_id'),
            ('questions','language'), ('questions','evidence_summary'),
            ('questions','fact_version'), ('questions','verified_at'),
            ('quiz_runs','generated_checksum'), ('quiz_runs','persisted_checksum'),
            ('quiz_runs','checksum_contract_version'),
            ('quiz_runs','integrity_verified'), ('quiz_runs','ready_at'),
            ('quiz_attempts','client_attempt_uuid'),
            ('quiz_attempts','attempt_number'),
            ('personal_review_schedule','next_review'),
            ('user_preferences','leaderboard_visible')
    )
    select coalesce(jsonb_agg(
        table_name || '.' || column_name order by table_name, column_name
    ), '[]'::jsonb)
    into v_missing_columns
    from required
    where not exists (
        select 1
        from information_schema.columns c
        where c.table_schema = 'public'
          and c.table_name = required.table_name
          and c.column_name = required.column_name
    );

    with required(signature) as (
        values
            ('public.claim_quiz_run(text,text,text,integer,boolean)'),
            ('public.save_quiz_pack_atomic(text,text,jsonb,text,boolean)'),
            ('public.quiz_pack_checksum(text)'),
            ('public.question_content_hash(jsonb)'),
            ('public.submit_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)'),
            ('public.quiz_attempt_result(uuid)'),
            ('public.get_grounding_bundle(text,text,date,integer)'),
            ('public.submit_question_report(uuid,text,uuid,text,text,text,integer)'),
            ('public.get_user_learning_dashboard(uuid)'),
            ('public.get_user_due_reviews(uuid,integer,integer)'),
            ('public.get_user_wrong_questions(uuid,text,integer,integer)'),
            ('public.submit_personal_practice_answer(uuid,uuid,integer,text,numeric,boolean)'),
            ('public.get_user_preferences(uuid)'),
            ('public.get_application_schema_contract()')
    )
    select coalesce(jsonb_agg(signature order by signature), '[]'::jsonb)
    into v_missing_functions
    from required
    where to_regprocedure(signature) is null;

    with required(signature) as (
        values
            ('public.claim_quiz_run(text,text,text,integer,boolean)'),
            ('public.save_quiz_pack_atomic(text,text,jsonb,text,boolean)'),
            ('public.quiz_pack_checksum(text)'),
            ('public.question_content_hash(jsonb)'),
            ('public.submit_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)'),
            ('public.quiz_attempt_result(uuid)'),
            ('public.get_grounding_bundle(text,text,date,integer)'),
            ('public.submit_question_report(uuid,text,uuid,text,text,text,integer)'),
            ('public.get_user_learning_dashboard(uuid)'),
            ('public.get_user_due_reviews(uuid,integer,integer)'),
            ('public.get_user_wrong_questions(uuid,text,integer,integer)'),
            ('public.submit_personal_practice_answer(uuid,uuid,integer,text,numeric,boolean)'),
            ('public.get_user_preferences(uuid)'),
            ('public.get_application_schema_contract()')
    )
    select coalesce(jsonb_agg(signature order by signature), '[]'::jsonb)
    into v_function_permission_failures
    from required
    where to_regprocedure(signature) is not null
      and (
          not has_function_privilege('service_role', to_regprocedure(signature), 'EXECUTE')
          or has_function_privilege('anon', to_regprocedure(signature), 'EXECUTE')
          or has_function_privilege('authenticated', to_regprocedure(signature), 'EXECUTE')
      );

    with required(table_name) as (
        values
            ('questions'), ('quiz_runs'), ('quiz_questions'),
            ('quiz_attempts'), ('quiz_attempt_answers'), ('users'),
            ('personal_review_schedule'), ('personal_practice_answers'),
            ('user_preferences'), ('question_reports'), ('source_documents'),
            ('application_schema_contract'), ('quiz_pack_integrity_failures')
    )
    select coalesce(jsonb_agg(table_name order by table_name), '[]'::jsonb)
    into v_missing_rls
    from required
    join pg_catalog.pg_class rel on rel.relname = required.table_name
    join pg_catalog.pg_namespace ns on ns.oid = rel.relnamespace
    where ns.nspname = 'public' and not rel.relrowsecurity;

    with required(table_name) as (
        values
            ('questions'), ('quiz_runs'), ('quiz_questions'),
            ('quiz_attempts'), ('quiz_attempt_answers'), ('users'),
            ('personal_review_schedule'), ('personal_practice_answers'),
            ('user_preferences'), ('question_reports'), ('source_documents'),
            ('application_schema_contract'), ('quiz_pack_integrity_failures')
    )
    select coalesce(jsonb_agg(table_name order by table_name), '[]'::jsonb)
    into v_table_permission_failures
    from required
    where has_table_privilege('anon', 'public.' || table_name, 'SELECT,INSERT,UPDATE,DELETE')
       or has_table_privilege('authenticated', 'public.' || table_name, 'SELECT,INSERT,UPDATE,DELETE')
       or not has_table_privilege('service_role', 'public.' || table_name, 'SELECT');

    return jsonb_build_object(
        'contract_key', v_contract.contract_key,
        'contract_version', v_contract.contract_version,
        'required_migration_version', v_contract.required_migration_version,
        'migration_applied', v_migration_applied,
        'verification_threshold', v_contract.verification_threshold,
        'missing_tables', v_missing_tables,
        'missing_columns', v_missing_columns,
        'missing_functions', v_missing_functions,
        'function_permission_failures', v_function_permission_failures,
        'missing_rls', v_missing_rls,
        'table_permission_failures', v_table_permission_failures,
        'ready',
            v_contract.contract_version = '2.0.0'
            and v_contract.required_migration_version = '20260718220112'
            and v_contract.verification_threshold = 0.85
            and v_migration_applied
            and v_missing_tables = '[]'::jsonb
            and v_missing_columns = '[]'::jsonb
            and v_missing_functions = '[]'::jsonb
            and v_function_permission_failures = '[]'::jsonb
            and v_missing_rls = '[]'::jsonb
            and v_table_permission_failures = '[]'::jsonb
    );
end;
$$;

alter table public.application_schema_contract enable row level security;
alter table public.quiz_pack_integrity_failures enable row level security;

revoke all on table public.application_schema_contract,
    public.quiz_pack_integrity_failures
    from public, anon, authenticated;
grant select, insert, update, delete on table public.application_schema_contract,
    public.quiz_pack_integrity_failures to service_role;

revoke execute on function public.question_stem_hash(text)
    from public, anon, authenticated;
revoke execute on function public.content_hash_part(text, text)
    from public, anon, authenticated;
revoke execute on function public.canonical_content_text(text)
    from public, anon, authenticated;
revoke execute on function public.canonical_content_timestamp(text)
    from public, anon, authenticated;
revoke execute on function public.canonical_content_score(text)
    from public, anon, authenticated;
revoke execute on function public.question_content_hash(jsonb)
    from public, anon, authenticated;
revoke execute on function public.quiz_pack_checksum(text)
    from public, anon, authenticated;
revoke execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean)
    from public, anon, authenticated;
revoke execute on function public.require_quiz_attempt_uuid()
    from public, anon, authenticated;
revoke execute on function public.quiz_attempt_result(uuid)
    from public, anon, authenticated;
revoke execute on function public.submit_quiz_attempt_atomic(
    text, uuid, uuid, jsonb, integer, jsonb, jsonb
) from public, anon, authenticated;
revoke execute on function public.protect_immutable_question_version()
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;

grant execute on function public.question_stem_hash(text) to service_role;
grant execute on function public.content_hash_part(text, text) to service_role;
grant execute on function public.canonical_content_text(text) to service_role;
grant execute on function public.canonical_content_timestamp(text) to service_role;
grant execute on function public.canonical_content_score(text) to service_role;
grant execute on function public.question_content_hash(jsonb) to service_role;
grant execute on function public.quiz_pack_checksum(text) to service_role;
grant execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean)
    to service_role;
grant execute on function public.require_quiz_attempt_uuid() to service_role;
grant execute on function public.quiz_attempt_result(uuid) to service_role;
grant execute on function public.submit_quiz_attempt_atomic(
    text, uuid, uuid, jsonb, integer, jsonb, jsonb
) to service_role;
grant execute on function public.protect_immutable_question_version()
    to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;

comment on column public.questions.question_hash is
    'Legacy compatibility alias for stem_hash; it is intentionally not unique.';
comment on column public.questions.content_hash is
    'SHA-256 of the complete immutable content and provenance snapshot.';
comment on table public.quiz_pack_integrity_failures is
    'Sanitized checksum evidence retained when a generated pack cannot be marked ready.';
