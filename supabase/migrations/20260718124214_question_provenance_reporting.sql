-- Normalized quiz taxonomy, fail-closed source provenance, independent
-- verification evidence, and authenticated question-report moderation.
-- This migration is stacked on 20260718015054_atomic_quiz_integrity.sql.

create extension if not exists pgcrypto;

create table if not exists public.quiz_subjects (
    subject_key text primary key,
    display_name text not null,
    internal_name text not null,
    exam_relevance text[] not null default '{}',
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create table if not exists public.quiz_chapters (
    id uuid primary key default extensions.gen_random_uuid(),
    subject_key text not null references public.quiz_subjects(subject_key) on delete restrict,
    name text not null,
    normalized_name text not null,
    display_order integer not null check (display_order > 0),
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (subject_key, name),
    unique (subject_key, display_order)
);

create table if not exists public.quiz_micro_topics (
    id uuid primary key default extensions.gen_random_uuid(),
    chapter_id uuid not null references public.quiz_chapters(id) on delete restrict,
    key text not null unique check (key = lower(key) and key !~ '[[:space:]]'),
    name text not null,
    normalized_name text not null,
    exam_relevance text[] not null default '{}',
    difficulty_targets jsonb not null default '{"easy":3,"medium":5,"hard":2}'::jsonb,
    target_coverage smallint not null default 10 check (target_coverage between 1 and 100),
    last_used_at timestamptz,
    mastery_relevance numeric not null default 1.0 check (mastery_relevance between 0 and 10),
    active boolean not null default true,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (chapter_id, name)
);

create index if not exists idx_quiz_micro_topics_rotation
    on public.quiz_micro_topics (chapter_id, active, last_used_at);

insert into public.quiz_subjects (subject_key, display_name, internal_name, exam_relevance)
values
    ('computer', 'কম্পিউটার শিক্ষা', 'Computer Education', array['WBCS','WBPSC','WBP','SSC','Railway']),
    ('bengali', 'বাংলা', 'Bengali', array['WBCS','WBPSC','WBP','TET']),
    ('reasoning', 'রিজনিং', 'Reasoning', array['WBP','SSC','Railway','Banking']),
    ('mathematics', 'গণিত', 'Mathematics', array['WBP','SSC','Railway','Banking','TET']),
    ('english', 'ইংরেজি', 'English', array['WBCS','WBPSC','WBP','SSC','Railway','Banking']),
    ('miscellaneous', 'বিবিধ', 'Miscellaneous General Knowledge', array['WBCS','WBPSC','WBP','SSC']),
    ('polity', 'সংবিধান ও প্রশাসন', 'Indian Constitution, Polity and Governance', array['WBCS','WBPSC','WBP','SSC']),
    ('geography', 'ভূগোল', 'Geography', array['WBCS','WBPSC','WBP','SSC','TET']),
    ('science', 'বিজ্ঞান', 'General Science', array['WBCS','WBPSC','WBP','SSC','Railway','TET']),
    ('economics', 'অর্থনীতি', 'Economics', array['WBCS','WBPSC','Banking']),
    ('history', 'ইতিহাস', 'History', array['WBCS','WBPSC','WBP','SSC','TET']),
    ('environment', 'পরিবেশ', 'Environment and Ecology', array['WBCS','WBPSC','TET']),
    ('current-affairs', 'কারেন্ট অ্যাফেয়ার্স', 'Current Affairs', array['WBCS','WBPSC','WBP','SSC','Railway','Banking'])
on conflict (subject_key) do update set
    display_name = excluded.display_name,
    internal_name = excluded.internal_name,
    exam_relevance = excluded.exam_relevance,
    updated_at = now();

do $$
declare
    subject_row record;
    chapter_name text;
    chapter_order integer;
    chapter_id uuid;
begin
    for subject_row in
        select * from jsonb_each('{
          "computer":["কম্পিউটারের মৌলিক ধারণা","হার্ডওয়্যার ও সফটওয়্যার","অপারেটিং সিস্টেম","ইন্টারনেট ও নেটওয়ার্ক","MS Office","ডেটাবেস","সাইবার নিরাপত্তা"],
          "bengali":["সন্ধি","সমাস","কারক ও বিভক্তি","বাগধারা","শুদ্ধ বানান","সমার্থক ও বিপরীতার্থক শব্দ","বাংলা সাহিত্য"],
          "reasoning":["সংখ্যা ও বর্ণ সিরিজ","অ্যানালজি","কোডিং-ডিকোডিং","রক্তের সম্পর্ক","দিক নির্ণয়","সিলজিজম","বসার বিন্যাস"],
          "mathematics":["সংখ্যা পদ্ধতি","শতকরা","লাভ-ক্ষতি","অনুপাত ও সমানুপাত","সময় ও কাজ","সময় ও দূরত্ব","সরল ও চক্রবৃদ্ধি সুদ"],
          "english":["Synonym and Antonym","Idioms and Phrases","Preposition","Article","Voice Change","Narration","Subject-Verb Agreement"],
          "miscellaneous":["ভারতের জাতীয় প্রতীক","গুরুত্বপূর্ণ দিবস","পুরস্কার ও সম্মান","বই ও লেখক","ক্রীড়া সাধারণ জ্ঞান","ভারতীয় সংস্কৃতি","আবিষ্কার ও আবিষ্কারক"],
          "polity":["সংবিধানের বৈশিষ্ট্য","মৌলিক অধিকার ও কর্তব্য","রাষ্ট্র পরিচালনার নির্দেশমূলক নীতি","রাষ্ট্রপতি ও উপরাষ্ট্রপতি","সংসদ","সুপ্রিম কোর্ট ও হাইকোর্ট","সাংবিধানিক সংস্থা"],
          "geography":["ভারতের ভৌগোলিক অবস্থান","পশ্চিমবঙ্গের ভূগোল","নদী ও জলসম্পদ","জলবায়ু","মাটি ও কৃষি","খনিজ ও শিল্প","বিশ্ব ভূগোল"],
          "science":["পদার্থবিদ্যা","রসায়ন","জীববিদ্যা","মানবদেহ","রোগ ও পুষ্টি","দৈনন্দিন জীবনে বিজ্ঞান","মহাকাশ ও প্রযুক্তি"],
          "economics":["জাতীয় আয়","ব্যাংকিং ও RBI","মুদ্রাস্ফীতি","কেন্দ্রীয় বাজেট","করব্যবস্থা","দারিদ্র্য ও বেকারত্ব","ভারতের অর্থনৈতিক পরিকল্পনা"],
          "history":["প্রাচীন ভারত","মধ্যযুগীয় ভারত","আধুনিক ভারত","বাংলার ইতিহাস","ভারতের জাতীয় আন্দোলন","গভর্নর জেনারেল ও ভাইসরয়","সামাজিক-ধর্মীয় সংস্কার আন্দোলন"],
          "environment":["বাস্তুতন্ত্র","জীববৈচিত্র্য","দূষণ","জলবায়ু পরিবর্তন","সংরক্ষিত এলাকা","পরিবেশ আইন","নবায়নযোগ্য শক্তি"],
          "current-affairs":["জাতীয় সাম্প্রতিক ঘটনা","আন্তর্জাতিক সাম্প্রতিক ঘটনা","পশ্চিমবঙ্গের সাম্প্রতিক ঘটনা","পুরস্কার ও নিয়োগ","খেলাধুলা","বিজ্ঞান ও প্রযুক্তি","সরকারি প্রকল্প"]
        }'::jsonb)
    loop
        chapter_order := 0;
        for chapter_name in select jsonb_array_elements_text(subject_row.value)
        loop
            chapter_order := chapter_order + 1;
            insert into public.quiz_chapters (
                subject_key, name, normalized_name, display_order
            ) values (
                subject_row.key, chapter_name, lower(btrim(chapter_name)), chapter_order
            )
            on conflict (subject_key, name) do update set
                normalized_name = excluded.normalized_name,
                display_order = excluded.display_order,
                updated_at = now()
            returning id into chapter_id;

            insert into public.quiz_micro_topics (
                chapter_id, key, name, normalized_name,
                exam_relevance, target_coverage, mastery_relevance
            ) values (
                chapter_id,
                subject_row.key || ':' || left(encode(extensions.digest(chapter_name, 'sha256'), 'hex'), 12) || ':core',
                chapter_name || ' — মূল ধারণা',
                lower(btrim(chapter_name || ' — মূল ধারণা')),
                (select exam_relevance from public.quiz_subjects where subject_key = subject_row.key),
                10,
                1.0
            )
            on conflict (key) do update set
                name = excluded.name,
                normalized_name = excluded.normalized_name,
                exam_relevance = excluded.exam_relevance,
                updated_at = now();
        end loop;
    end loop;
end;
$$;

create table if not exists public.source_documents (
    id uuid primary key default extensions.gen_random_uuid(),
    micro_topic_id uuid not null references public.quiz_micro_topics(id) on delete restrict,
    source_url text not null check (source_url ~ '^https://'),
    source_title text not null,
    source_domain text not null check (
        source_domain = lower(source_domain) and source_domain !~ '[/:[:space:]]'
    ),
    source_kind text not null default 'official'
        check (source_kind in ('official','primary','secondary')),
    source_published_at timestamptz,
    source_accessed_at timestamptz not null,
    fact_summary text not null check (length(btrim(fact_summary)) >= 40),
    verification_status text not null default 'draft'
        check (verification_status in ('draft','verified','rejected','archived')),
    verification_notes text,
    fact_version text not null,
    expires_at timestamptz,
    review_required boolean not null default true,
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (micro_topic_id, source_url, fact_version),
    check (expires_at is null or expires_at > source_accessed_at),
    check (verification_status <> 'verified' or verified_at is not null)
);

create or replace function public.protect_verified_source_facts()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if old.verification_status = 'verified' and (
        new.micro_topic_id is distinct from old.micro_topic_id
        or new.source_url is distinct from old.source_url
        or new.source_title is distinct from old.source_title
        or new.source_domain is distinct from old.source_domain
        or new.source_kind is distinct from old.source_kind
        or new.source_published_at is distinct from old.source_published_at
        or new.fact_summary is distinct from old.fact_summary
        or new.fact_version is distinct from old.fact_version
        or new.expires_at is distinct from old.expires_at
    ) then
        raise exception 'verified source facts are immutable; insert a new fact version';
    end if;
    return new;
end;
$$;

drop trigger if exists protect_verified_source_facts on public.source_documents;
create trigger protect_verified_source_facts
before update on public.source_documents
for each row execute function public.protect_verified_source_facts();

create index if not exists idx_source_documents_grounding
    on public.source_documents (micro_topic_id, verification_status, expires_at);
create index if not exists idx_source_documents_current
    on public.source_documents (source_published_at desc)
    where verification_status = 'verified';

alter table public.questions add column if not exists micro_topic_id uuid
    references public.quiz_micro_topics(id) on delete restrict;
alter table public.questions add column if not exists micro_topic_key text;
alter table public.questions add column if not exists source_document_id uuid
    references public.source_documents(id) on delete restrict;
alter table public.questions add column if not exists source_url text;
alter table public.questions add column if not exists source_title text;
alter table public.questions add column if not exists source_domain text;
alter table public.questions add column if not exists source_published_at timestamptz;
alter table public.questions add column if not exists source_accessed_at timestamptz;
alter table public.questions add column if not exists verified_at timestamptz;
alter table public.questions add column if not exists verification_status text not null default 'unverified';
alter table public.questions add column if not exists verification_notes text;
alter table public.questions add column if not exists verification_score numeric;
alter table public.questions add column if not exists verification_model text;
alter table public.questions add column if not exists fact_version text;
alter table public.questions add column if not exists expires_at timestamptz;
alter table public.questions add column if not exists review_required boolean not null default true;

alter table public.questions drop constraint if exists questions_status_check;
alter table public.questions add constraint questions_status_check check (
    status in ('draft','generated','verified','active','reported','under_review','rejected','archived')
);
alter table public.questions drop constraint if exists questions_verification_status_check;
alter table public.questions add constraint questions_verification_status_check check (
    verification_status in ('unverified','generated','verified','rejected','expired')
);
alter table public.questions drop constraint if exists questions_verification_score_check;
alter table public.questions add constraint questions_verification_score_check check (
    verification_score is null or verification_score between 0 and 1
);

create index if not exists idx_questions_micro_topic
    on public.questions (micro_topic_id, status, verification_status);
create index if not exists idx_questions_source_document
    on public.questions (source_document_id);

create or replace function public.find_similar_questions(
    query_normalized text,
    query_bot_type text default 'daily_mcq',
    sim_threshold double precision default 0.35,
    match_count integer default 5
)
returns table (id uuid, question_text text, similarity real)
language sql
stable
security invoker
set search_path = ''
as $$
    select q.id, q.question_text,
           public.similarity(q.normalized_text, query_normalized) as similarity
    from public.questions q
    where q.bot_type = query_bot_type
      and q.status = 'active'
      and q.verification_status = 'verified'
      and not q.review_required
      and (q.expires_at is null or q.expires_at >= now())
      and public.similarity(q.normalized_text, query_normalized) >= sim_threshold
    order by public.similarity(q.normalized_text, query_normalized) desc
    limit greatest(1, least(match_count, 20));
$$;

create table if not exists public.question_verifications (
    id uuid primary key default extensions.gen_random_uuid(),
    question_id uuid not null references public.questions(id) on delete cascade,
    source_document_id uuid not null references public.source_documents(id) on delete restrict,
    verifier_model text,
    verdict text not null check (verdict in ('verified','rejected')),
    confidence numeric not null check (confidence between 0 and 1),
    checks jsonb not null check (jsonb_typeof(checks) = 'object'),
    notes text not null,
    checked_at timestamptz not null default now()
);

create index if not exists idx_question_verifications_question
    on public.question_verifications (question_id, checked_at desc);
create index if not exists idx_question_verifications_source_document
    on public.question_verifications (source_document_id);

create table if not exists public.question_generation_audits (
    id uuid primary key default extensions.gen_random_uuid(),
    quiz_id text not null references public.quiz_runs(quiz_id) on delete restrict,
    subject_key text not null references public.quiz_subjects(subject_key) on delete restrict,
    chapter text not null,
    micro_topic_id uuid not null references public.quiz_micro_topics(id) on delete restrict,
    source_document_ids uuid[] not null,
    generated_questions jsonb not null check (jsonb_typeof(generated_questions) = 'array'),
    verifier_output jsonb,
    verifier_raw_text text,
    verdict text not null check (verdict in ('verified','rejected')),
    rejection_reasons text[] not null default '{}',
    verifier_provider text,
    verifier_model text,
    created_at timestamptz not null default now()
);

create index if not exists idx_question_generation_audits_quiz
    on public.question_generation_audits (quiz_id, created_at desc);
create index if not exists idx_question_generation_audits_rejected
    on public.question_generation_audits (created_at desc)
    where verdict = 'rejected';
create index if not exists idx_question_generation_audits_subject
    on public.question_generation_audits (subject_key);
create index if not exists idx_question_generation_audits_micro_topic
    on public.question_generation_audits (micro_topic_id);

create table if not exists public.question_reports (
    id uuid primary key default extensions.gen_random_uuid(),
    question_id uuid not null references public.questions(id) on delete restrict,
    quiz_id text not null references public.quiz_runs(quiz_id) on delete restrict,
    user_id uuid not null references public.users(id) on delete cascade,
    attempt_id uuid not null references public.quiz_attempts(id) on delete cascade,
    reason text not null check (reason in (
        'wrong_answer','multiple_correct','ambiguous','incorrect_explanation',
        'language_spelling','outdated','outside_syllabus','broken_source','other'
    )),
    details text check (details is null or length(details) <= 1000),
    status text not null default 'open'
        check (status in ('open','under_review','resolved','dismissed')),
    created_at timestamptz not null default now(),
    reviewed_at timestamptz,
    reviewed_by bigint,
    resolution text,
    unique (question_id, user_id, attempt_id)
);

create index if not exists idx_question_reports_moderation
    on public.question_reports (question_id, status, created_at desc);
create index if not exists idx_question_reports_user_rate
    on public.question_reports (user_id, created_at desc);
create index if not exists idx_question_reports_quiz
    on public.question_reports (quiz_id);
create index if not exists idx_question_reports_attempt
    on public.question_reports (attempt_id);

create or replace function public.get_grounding_bundle(
    p_subject_key text,
    p_chapter text,
    p_target_date date,
    p_limit integer default 8
)
returns table (
    source_document_id uuid,
    micro_topic_id uuid,
    micro_topic_key text,
    micro_topic_name text,
    source_url text,
    source_title text,
    source_domain text,
    source_kind text,
    source_published_at timestamptz,
    source_accessed_at timestamptz,
    fact_summary text,
    fact_version text,
    expires_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
with selected_topic as (
    select mt.id
    from public.quiz_micro_topics mt
    join public.quiz_chapters c on c.id = mt.chapter_id
    where c.subject_key = p_subject_key
      and c.name = p_chapter
      and c.active and mt.active
      and exists (
          select 1 from public.source_documents candidate
          where candidate.micro_topic_id = mt.id
            and candidate.verification_status = 'verified'
            and not candidate.review_required
            and (candidate.expires_at is null or candidate.expires_at::date >= p_target_date)
            and (
                p_subject_key <> 'current-affairs'
                or (
                    candidate.source_kind in ('official','primary')
                    and candidate.source_published_at::date
                        between p_target_date - 45 and p_target_date
                )
            )
      )
    order by mt.last_used_at asc nulls first, mt.target_coverage desc, mt.key
    limit 1
)
select
    source.id,
    mt.id,
    mt.key,
    mt.name,
    source.source_url,
    source.source_title,
    source.source_domain,
    source.source_kind,
    source.source_published_at,
    source.source_accessed_at,
    source.fact_summary,
    source.fact_version,
    source.expires_at
from selected_topic chosen
join public.quiz_micro_topics mt on mt.id = chosen.id
join public.source_documents source on source.micro_topic_id = mt.id
where source.verification_status = 'verified'
  and not source.review_required
  and (source.expires_at is null or source.expires_at::date >= p_target_date)
  and (
      p_subject_key <> 'current-affairs'
      or (
          source.source_kind in ('official','primary')
          and source.source_published_at::date between p_target_date - 45 and p_target_date
      )
  )
order by source.source_published_at desc nulls last, source.verified_at desc, source.id
limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

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
    v_order integer;
    v_question_id uuid;
    v_existing public.questions%rowtype;
    v_source public.source_documents%rowtype;
    v_micro_topic public.quiz_micro_topics%rowtype;
    v_mapping_count integer;
begin
    if jsonb_typeof(p_questions) <> 'array'
       or jsonb_array_length(p_questions) <> 10 then
        raise exception 'quiz pack must contain exactly 10 questions';
    end if;
    if nullif(btrim(p_content_checksum), '') is null then
        raise exception 'content checksum is required';
    end if;
    if not exists (
        select 1 from public.quiz_runs r
        where r.quiz_id = p_quiz_id
          and r.worker_id = p_worker_id
          and r.claim_expires_at > now()
    ) then
        raise exception 'quiz run is not owned by this worker';
    end if;

    select count(*) into v_mapping_count
    from public.quiz_questions qq where qq.quiz_id = p_quiz_id;
    if v_mapping_count = 10 and not p_replace then
        return jsonb_build_object('quiz_id', p_quiz_id, 'question_count', 10, 'reused', true);
    end if;
    if v_mapping_count > 0 and not p_replace then
        raise exception 'existing quiz pack is incomplete; explicit replacement is required';
    end if;
    if p_replace then
        delete from public.quiz_questions where quiz_id = p_quiz_id;
    end if;

    v_order := 0;
    for v_item in select value from jsonb_array_elements(p_questions)
    loop
        v_order := v_order + 1;
        if nullif(btrim(v_item ->> 'question_hash'), '') is null
           or nullif(btrim(v_item ->> 'question_text'), '') is null
           or nullif(btrim(v_item ->> 'subject'), '') is null
           or nullif(btrim(v_item ->> 'topic'), '') is null
           or v_item ->> 'correct_option' not in ('A', 'B', 'C', 'D')
           or v_item ->> 'verification_status' <> 'verified'
           or coalesce((v_item ->> 'verification_score')::numeric, 0) < 0.5
           or nullif(btrim(v_item ->> 'verification_notes'), '') is null
           or nullif(btrim(v_item ->> 'verified_at'), '') is null then
            raise exception 'question % is missing required verified fields', v_order;
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
            raise exception 'question % micro-topic does not belong to its chapter', v_order;
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
           and (v_source.source_kind not in ('official','primary')
                or v_source.source_published_at is null
                or v_source.source_published_at::date < current_date - 45
                or v_source.source_published_at::date > current_date) then
            raise exception 'current-affairs question % has no recent dated source', v_order;
        end if;

        if v_item ? 'reuse_question_id' then
            select * into v_existing from public.questions q
            where q.id = (v_item ->> 'reuse_question_id')::uuid limit 1;
            if not found then
                raise exception 'requested reusable question does not exist at position %', v_order;
            end if;
        else
            select * into v_existing from public.questions q
            where q.question_hash = v_item ->> 'question_hash' limit 1;
        end if;

        if found then
            if v_existing.subject <> v_item ->> 'subject'
               or v_existing.topic <> v_item ->> 'topic' then
                raise exception 'question classification collision at position %', v_order;
            end if;
            if v_existing.status in ('reported','under_review','rejected','archived') then
                raise exception 'moderated question cannot be reused at position %', v_order;
            end if;
            v_question_id := v_existing.id;
            update public.questions set
                micro_topic_id = v_micro_topic.id,
                micro_topic_key = v_micro_topic.key,
                source_document_id = v_source.id,
                source_url = v_source.source_url,
                source_title = v_source.source_title,
                source_domain = v_source.source_domain,
                source_published_at = v_source.source_published_at,
                source_accessed_at = v_source.source_accessed_at,
                verified_at = (v_item ->> 'verified_at')::timestamptz,
                verification_status = 'verified',
                verification_notes = v_item ->> 'verification_notes',
                verification_score = (v_item ->> 'verification_score')::numeric,
                verification_model = nullif(v_item ->> 'verification_model', ''),
                fact_version = v_source.fact_version,
                expires_at = v_source.expires_at,
                review_required = false,
                status = 'active'
            where id = v_question_id;
        else
            insert into public.questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, explanation, detailed_explanation, subject,
                topic, difficulty, gemini_model, source, week_number, bot_type,
                question_hash, normalized_text, status, micro_topic_id,
                micro_topic_key, source_document_id, source_url, source_title,
                source_domain, source_published_at, source_accessed_at,
                verified_at, verification_status, verification_notes,
                verification_score, verification_model, fact_version,
                expires_at, review_required
            ) values (
                v_item ->> 'question_text', v_item ->> 'option_a',
                v_item ->> 'option_b', v_item ->> 'option_c',
                v_item ->> 'option_d', v_item ->> 'correct_option',
                v_item ->> 'explanation', v_item ->> 'detailed_explanation',
                v_item ->> 'subject', v_item ->> 'topic',
                coalesce(nullif(v_item ->> 'difficulty', ''), 'medium'),
                nullif(v_item ->> 'gemini_model', ''),
                coalesce(nullif(v_item ->> 'source', ''), 'verified_source'),
                nullif(v_item ->> 'week_number', '')::integer,
                coalesce(nullif(v_item ->> 'bot_type', ''), 'mock_test'),
                v_item ->> 'question_hash', v_item ->> 'normalized_text', 'active',
                v_micro_topic.id, v_micro_topic.key, v_source.id,
                v_source.source_url, v_source.source_title, v_source.source_domain,
                v_source.source_published_at, v_source.source_accessed_at,
                (v_item ->> 'verified_at')::timestamptz, 'verified',
                v_item ->> 'verification_notes',
                (v_item ->> 'verification_score')::numeric,
                nullif(v_item ->> 'verification_model', ''),
                v_source.fact_version, v_source.expires_at, false
            ) returning id into v_question_id;
        end if;

        insert into public.question_verifications (
            question_id, source_document_id, verifier_model, verdict,
            confidence, checks, notes, checked_at
        ) values (
            v_question_id, v_source.id, nullif(v_item ->> 'verification_model', ''),
            'verified', (v_item ->> 'verification_score')::numeric,
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes', (v_item ->> 'verified_at')::timestamptz
        );

        insert into public.quiz_questions (quiz_id, question_id, question_order)
        values (p_quiz_id, v_question_id, v_order);
    end loop;

    if (select count(*) from public.quiz_questions where quiz_id = p_quiz_id) <> 10 then
        raise exception 'atomic quiz save did not produce exactly 10 mappings';
    end if;
    update public.quiz_runs set
        status = 'generated', question_count = 10,
        content_checksum = p_content_checksum,
        generated_at = coalesce(generated_at, now()), updated_at = now()
    where quiz_id = p_quiz_id and worker_id = p_worker_id;
    return jsonb_build_object('quiz_id', p_quiz_id, 'question_count', 10, 'reused', false);
end;
$$;

create or replace function public.quiz_attempt_result(p_attempt_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with target as (
    select * from public.quiz_attempts where id = p_attempt_id and is_completed
), review as (
    select coalesce(jsonb_agg(
        jsonb_build_object(
            'questionId', aa.question_id,
            'q', q.question_text,
            'o', jsonb_build_array(q.option_a, q.option_b, q.option_c, q.option_d),
            'selectedIndex', aa.selected_option,
            'correctIndex', aa.correct_option,
            'isCorrect', aa.is_correct,
            'explanation', coalesce(q.detailed_explanation, q.explanation, ''),
            'difficulty', q.difficulty,
            'chapter', q.topic,
            'microTopic', q.micro_topic_key,
            'sourceTitle', q.source_title,
            'sourceUrl', q.source_url,
            'sourcePublishedAt', q.source_published_at
        ) order by aa.question_order
    ), '[]'::jsonb) as rows
    from public.quiz_attempt_answers aa
    join public.questions q on q.id = aa.question_id
    where aa.attempt_id = p_attempt_id
), latest as (
    select distinct on (a.user_id)
        a.user_id, a.score, a.answered, a.duration_seconds, a.completed_at, a.id
    from public.quiz_attempts a
    join target t on t.quiz_id = a.quiz_id
    where a.is_completed
    order by a.user_id, a.completed_at desc, a.id desc
), ranked as (
    select l.user_id, row_number() over (
        order by l.score desc, l.answered desc, l.duration_seconds asc nulls last,
                 l.completed_at asc, l.id
    ) as rank
    from latest l
)
select jsonb_build_object(
    'quiz_id', t.quiz_id,
    'score', t.score,
    'best_score', (select max(a.score) from public.quiz_attempts a
        where a.quiz_id = t.quiz_id and a.user_id = t.user_id and a.is_completed),
    'total', t.total,
    'answered', t.answered,
    'attempt_number', t.attempt_number,
    'rank', (select r.rank from ranked r where r.user_id = t.user_id),
    'participants', (select count(*) from latest),
    'duration_seconds', t.duration_seconds,
    'review', review.rows
)
from target t cross join review;
$$;

create or replace function public.submit_question_report(
    p_question_id uuid,
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id text,
    p_reason text,
    p_details text default null,
    p_threshold integer default 3
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt_id uuid;
    v_report_id uuid;
    v_open_reports integer;
    v_question_status text;
begin
    if p_reason not in (
        'wrong_answer','multiple_correct','ambiguous','incorrect_explanation',
        'language_spelling','outdated','outside_syllabus','broken_source','other'
    ) then
        raise exception 'invalid report reason';
    end if;
    if length(coalesce(p_details, '')) > 1000 then
        raise exception 'report details are too long';
    end if;
    if p_reason = 'other' and nullif(btrim(p_details), '') is null then
        raise exception 'other reports require details';
    end if;
    perform pg_advisory_xact_lock(hashtextextended('report-rate:' || p_user_id::text, 0));
    if (
        select count(*) from public.question_reports
        where user_id = p_user_id and created_at >= now() - interval '1 hour'
    ) >= 5 then
        raise exception 'report rate limit exceeded';
    end if;

    select a.id into v_attempt_id
    from public.quiz_attempts a
    join public.quiz_attempt_answers aa on aa.attempt_id = a.id
    where a.quiz_id = p_quiz_id
      and a.user_id = p_user_id
      and a.client_attempt_id = p_client_attempt_id
      and a.is_completed
      and aa.question_id = p_question_id
    limit 1;
    if not found then
        raise exception 'question report is not linked to this completed attempt';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(p_question_id::text, 0));
    insert into public.question_reports (
        question_id, quiz_id, user_id, attempt_id, reason, details
    ) values (
        p_question_id, p_quiz_id, p_user_id, v_attempt_id, p_reason,
        nullif(btrim(p_details), '')
    ) returning id into v_report_id;

    select count(distinct user_id)::integer into v_open_reports
    from public.question_reports
    where question_id = p_question_id and status in ('open','under_review');

    if v_open_reports >= greatest(2, p_threshold) then
        update public.question_reports set status = 'under_review'
        where question_id = p_question_id and status = 'open';
        update public.questions set status = 'under_review', review_required = true
        where id = p_question_id and status not in ('rejected','archived');
    elseif v_open_reports > 0 then
        update public.questions set status = 'reported'
        where id = p_question_id and status = 'active';
    end if;

    select status into v_question_status from public.questions where id = p_question_id;
    return jsonb_build_object(
        'report_id', v_report_id,
        'status', 'accepted',
        'credible_report_count', v_open_reports,
        'question_status', v_question_status
    );
exception
    when unique_violation then
        raise exception 'this question was already reported for this attempt';
end;
$$;

alter table public.quiz_subjects enable row level security;
alter table public.quiz_chapters enable row level security;
alter table public.quiz_micro_topics enable row level security;
alter table public.source_documents enable row level security;
alter table public.question_verifications enable row level security;
alter table public.question_generation_audits enable row level security;
alter table public.question_reports enable row level security;

revoke all on table public.quiz_subjects, public.quiz_chapters,
    public.quiz_micro_topics, public.source_documents,
    public.question_verifications, public.question_generation_audits,
    public.question_reports
    from public, anon, authenticated;
grant select, insert, update, delete on table public.quiz_subjects,
    public.quiz_chapters, public.quiz_micro_topics, public.source_documents,
    public.question_verifications, public.question_generation_audits,
    public.question_reports to service_role;

revoke execute on function public.get_grounding_bundle(text, text, date, integer)
    from public, anon, authenticated;
revoke execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean)
    from public, anon, authenticated;
revoke execute on function public.quiz_attempt_result(uuid)
    from public, anon, authenticated;
revoke execute on function public.submit_question_report(uuid, text, uuid, text, text, text, integer)
    from public, anon, authenticated;
revoke execute on function public.protect_verified_source_facts()
    from public, anon, authenticated;

grant execute on function public.get_grounding_bundle(text, text, date, integer)
    to service_role;
grant execute on function public.save_quiz_pack_atomic(text, text, jsonb, text, boolean)
    to service_role;
grant execute on function public.quiz_attempt_result(uuid) to service_role;
grant execute on function public.submit_question_report(uuid, text, uuid, text, text, text, integer)
    to service_role;
grant execute on function public.protect_verified_source_facts() to service_role;
