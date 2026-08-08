-- Phase E2: versioned exam configuration and a shared test model.
--
-- This migration is deliberately additive. Existing quiz IDs, ordered quiz
-- mappings, attempt IDs, answer rows, and the ten-question API remain intact.
-- Every legacy daily quiz is represented as a daily_quick test instance, and
-- triggers keep future daily quizzes in the shared model automatically.

create table if not exists public.exams (
    id uuid primary key default extensions.gen_random_uuid(),
    exam_key text not null references public.exam_catalogue(exam_key) on delete restrict,
    version integer not null check (version > 0),
    display_name text not null check (length(btrim(display_name)) >= 2),
    authority text,
    jurisdiction text,
    effective_from date not null,
    effective_to date,
    lifecycle_status text not null default 'draft'
        check (lifecycle_status in ('draft','published','retired')),
    configuration jsonb not null default '{}'::jsonb
        check (jsonb_typeof(configuration) = 'object'),
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (exam_key, version),
    check (effective_to is null or effective_to >= effective_from),
    check (lifecycle_status <> 'published' or published_at is not null)
);

create index if not exists idx_exams_effective
    on public.exams (exam_key, lifecycle_status, effective_from, effective_to);

create table if not exists public.exam_stages (
    id uuid primary key default extensions.gen_random_uuid(),
    exam_id uuid not null references public.exams(id) on delete restrict,
    stage_key text not null check (stage_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    version integer not null default 1 check (version > 0),
    display_name text not null check (length(btrim(display_name)) >= 1),
    stage_kind text not null default 'stage'
        check (stage_kind in ('preliminary','mains','tier','interview','stage')),
    display_order integer not null check (display_order > 0),
    effective_from date not null,
    effective_to date,
    rules jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (exam_id, stage_key, version),
    unique (exam_id, display_order),
    check (effective_to is null or effective_to >= effective_from)
);

create index if not exists idx_exam_stages_exam
    on public.exam_stages (exam_id, display_order);

create table if not exists public.exam_papers (
    id uuid primary key default extensions.gen_random_uuid(),
    exam_stage_id uuid not null references public.exam_stages(id) on delete restrict,
    paper_key text not null check (paper_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    version integer not null default 1 check (version > 0),
    display_name text not null check (length(btrim(display_name)) >= 1),
    display_order integer not null check (display_order > 0),
    total_questions integer not null check (total_questions > 0),
    total_marks numeric(8,2) not null check (total_marks > 0),
    time_limit_seconds integer not null check (time_limit_seconds > 0),
    language_policy text not null default 'configured',
    effective_from date not null,
    effective_to date,
    rules jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (exam_stage_id, paper_key, version),
    unique (exam_stage_id, display_order),
    check (effective_to is null or effective_to >= effective_from)
);

create index if not exists idx_exam_papers_stage
    on public.exam_papers (exam_stage_id, display_order);

create table if not exists public.exam_sections (
    id uuid primary key default extensions.gen_random_uuid(),
    exam_paper_id uuid not null references public.exam_papers(id) on delete restrict,
    section_key text not null check (section_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    version integer not null default 1 check (version > 0),
    display_name text not null check (length(btrim(display_name)) >= 1),
    display_order integer not null check (display_order > 0),
    question_count integer not null check (question_count > 0),
    marks_per_correct numeric(8,2) not null check (marks_per_correct > 0),
    negative_marks_per_wrong numeric(8,2) not null default 0
        check (negative_marks_per_wrong >= 0),
    total_marks numeric(8,2) not null check (total_marks > 0),
    time_limit_seconds integer check (time_limit_seconds is null or time_limit_seconds > 0),
    cutoff_marks numeric(8,2) check (cutoff_marks is null or cutoff_marks >= 0),
    navigation_policy text not null default 'free'
        check (navigation_policy in ('free','forward_only','locked_until_submit')),
    allow_mark_for_review boolean not null default true,
    auto_submit boolean not null default true,
    effective_from date not null,
    effective_to date,
    rules jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (exam_paper_id, section_key, version),
    unique (exam_paper_id, display_order),
    check (effective_to is null or effective_to >= effective_from),
    check (total_marks >= question_count * marks_per_correct)
);

create index if not exists idx_exam_sections_paper
    on public.exam_sections (exam_paper_id, display_order);

create table if not exists public.exam_syllabus_weights (
    id uuid primary key default extensions.gen_random_uuid(),
    exam_section_id uuid not null references public.exam_sections(id) on delete restrict,
    subject_key text not null references public.quiz_subjects(subject_key) on delete restrict,
    chapter_id uuid references public.quiz_chapters(id) on delete restrict,
    micro_topic_id uuid references public.quiz_micro_topics(id) on delete restrict,
    knowledge_point_id uuid references public.knowledge_points(id) on delete restrict,
    weight numeric(8,4) not null check (weight > 0),
    minimum_questions integer not null default 0 check (minimum_questions >= 0),
    maximum_questions integer check (
        maximum_questions is null or maximum_questions >= minimum_questions
    ),
    effective_from date not null,
    effective_to date,
    rules jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (effective_to is null or effective_to >= effective_from)
);

create unique index if not exists idx_exam_syllabus_weight_scope_unique
    on public.exam_syllabus_weights (
        exam_section_id,
        subject_key,
        coalesce(chapter_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(micro_topic_id, '00000000-0000-0000-0000-000000000000'::uuid),
        coalesce(knowledge_point_id, '00000000-0000-0000-0000-000000000000'::uuid),
        effective_from
    );
create index if not exists idx_exam_syllabus_weights_section
    on public.exam_syllabus_weights (exam_section_id, effective_from, effective_to);
create index if not exists idx_exam_syllabus_weights_chapter
    on public.exam_syllabus_weights (chapter_id) where chapter_id is not null;
create index if not exists idx_exam_syllabus_weights_micro_topic
    on public.exam_syllabus_weights (micro_topic_id) where micro_topic_id is not null;
create index if not exists idx_exam_syllabus_weights_knowledge_point
    on public.exam_syllabus_weights (knowledge_point_id) where knowledge_point_id is not null;

create table if not exists public.test_definitions (
    id uuid primary key default extensions.gen_random_uuid(),
    definition_key text not null check (definition_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    version integer not null check (version > 0),
    test_type text not null check (test_type in (
        'daily_quick','chapter','subject','mixed','previous_year',
        'sectional_mock','full_mock'
    )),
    display_name text not null check (length(btrim(display_name)) >= 2),
    exam_id uuid references public.exams(id) on delete restrict,
    exam_paper_id uuid references public.exam_papers(id) on delete restrict,
    subject_key text references public.quiz_subjects(subject_key) on delete restrict,
    chapter_id uuid references public.quiz_chapters(id) on delete restrict,
    question_count integer check (question_count is null or question_count > 0),
    total_marks numeric(8,2) check (total_marks is null or total_marks > 0),
    time_limit_seconds integer check (time_limit_seconds is null or time_limit_seconds > 0),
    navigation_policy text not null default 'free'
        check (navigation_policy in ('free','forward_only','section_locked')),
    allow_mark_for_review boolean not null default true,
    auto_submit boolean not null default true,
    rank_cohort text not null default 'same_definition_and_version',
    effective_from date not null,
    effective_to date,
    lifecycle_status text not null default 'draft'
        check (lifecycle_status in ('draft','published','retired')),
    rules jsonb not null default '{}'::jsonb check (jsonb_typeof(rules) = 'object'),
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (definition_key, version),
    check (effective_to is null or effective_to >= effective_from),
    check (lifecycle_status <> 'published' or (
        published_at is not null and question_count is not null
    ))
);

create index if not exists idx_test_definitions_effective
    on public.test_definitions (test_type, lifecycle_status, effective_from, effective_to);
create index if not exists idx_test_definitions_exam
    on public.test_definitions (exam_id) where exam_id is not null;
create index if not exists idx_test_definitions_paper
    on public.test_definitions (exam_paper_id) where exam_paper_id is not null;
create index if not exists idx_test_definitions_subject
    on public.test_definitions (subject_key) where subject_key is not null;
create index if not exists idx_test_definitions_chapter
    on public.test_definitions (chapter_id) where chapter_id is not null;

create table if not exists public.test_instances (
    id uuid primary key default extensions.gen_random_uuid(),
    test_definition_id uuid not null references public.test_definitions(id) on delete restrict,
    legacy_quiz_id text unique references public.quiz_runs(quiz_id) on delete restrict,
    title text not null check (length(btrim(title)) >= 1),
    lifecycle_status text not null default 'draft'
        check (lifecycle_status in ('draft','published','open','closed','cancelled')),
    scheduled_start_at timestamptz,
    scheduled_end_at timestamptz,
    question_count integer not null default 0 check (question_count >= 0),
    total_marks numeric(8,2) not null default 0 check (total_marks >= 0),
    time_limit_seconds integer check (time_limit_seconds is null or time_limit_seconds > 0),
    definition_version integer not null check (definition_version > 0),
    config_snapshot jsonb not null default '{}'::jsonb
        check (jsonb_typeof(config_snapshot) = 'object'),
    published_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (scheduled_end_at is null or scheduled_start_at is null
        or scheduled_end_at > scheduled_start_at)
);

create index if not exists idx_test_instances_definition
    on public.test_instances (test_definition_id, lifecycle_status, scheduled_start_at desc);

create table if not exists public.test_section_instances (
    id uuid primary key default extensions.gen_random_uuid(),
    test_instance_id uuid not null references public.test_instances(id) on delete cascade,
    exam_section_id uuid references public.exam_sections(id) on delete restrict,
    section_key text not null check (section_key ~ '^[a-z0-9][a-z0-9_-]*$'),
    display_name text not null check (length(btrim(display_name)) >= 1),
    section_order integer not null check (section_order > 0),
    question_count integer not null default 0 check (question_count >= 0),
    marks_per_correct numeric(8,2) not null default 1 check (marks_per_correct > 0),
    negative_marks_per_wrong numeric(8,2) not null default 0
        check (negative_marks_per_wrong >= 0),
    total_marks numeric(8,2) not null default 0 check (total_marks >= 0),
    time_limit_seconds integer check (time_limit_seconds is null or time_limit_seconds > 0),
    cutoff_marks numeric(8,2) check (cutoff_marks is null or cutoff_marks >= 0),
    navigation_policy text not null default 'free'
        check (navigation_policy in ('free','forward_only','locked_until_submit')),
    allow_mark_for_review boolean not null default true,
    auto_submit boolean not null default true,
    config_snapshot jsonb not null default '{}'::jsonb
        check (jsonb_typeof(config_snapshot) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (test_instance_id, section_key),
    unique (test_instance_id, section_order),
    unique (id, test_instance_id)
);

create index if not exists idx_test_section_instances_exam_section
    on public.test_section_instances (exam_section_id) where exam_section_id is not null;

create table if not exists public.test_instance_questions (
    id uuid primary key default extensions.gen_random_uuid(),
    test_instance_id uuid not null references public.test_instances(id) on delete cascade,
    section_instance_id uuid not null,
    question_id uuid not null references public.questions(id) on delete restrict,
    legacy_quiz_question_id uuid unique
        references public.quiz_questions(id) on delete cascade,
    global_order integer not null check (global_order > 0),
    section_order integer not null check (section_order > 0),
    marks_for_correct numeric(8,2) not null default 1 check (marks_for_correct > 0),
    negative_marks_for_wrong numeric(8,2) not null default 0
        check (negative_marks_for_wrong >= 0),
    required boolean not null default true,
    mapping_source text not null default 'assembled'
        check (mapping_source in ('legacy_daily_quick','assembled','previous_year')),
    created_at timestamptz not null default now(),
    unique (test_instance_id, global_order),
    unique (section_instance_id, section_order),
    unique (test_instance_id, question_id),
    foreign key (section_instance_id, test_instance_id)
        references public.test_section_instances(id, test_instance_id) on delete cascade
);

create index if not exists idx_test_instance_questions_question
    on public.test_instance_questions (question_id);
create index if not exists idx_test_instance_questions_section
    on public.test_instance_questions (section_instance_id, section_order);

alter table public.quiz_attempts
    add column if not exists test_instance_id uuid
        references public.test_instances(id) on delete restrict;
alter table public.quiz_attempt_answers
    add column if not exists test_section_instance_id uuid
        references public.test_section_instances(id) on delete restrict;

create index if not exists idx_quiz_attempts_test_instance
    on public.quiz_attempts (test_instance_id, completed_at desc)
    where test_instance_id is not null;
create index if not exists idx_quiz_attempt_answers_test_section
    on public.quiz_attempt_answers (test_section_instance_id)
    where test_section_instance_id is not null;

-- Preserve the preference catalogue as draft version-one exam identities. No
-- unreviewed authority, jurisdiction, paper, timing, or marking facts are
-- invented by this migration.
insert into public.exams (
    exam_key, version, display_name, effective_from, lifecycle_status
)
select exam_key, 1, display_name, date '2026-08-08', 'draft'
from public.exam_catalogue
on conflict (exam_key, version) do nothing;

-- The one production behaviour that already exists is represented exactly:
-- a ten-question daily_quick definition. Other types are explicit draft
-- templates until reviewed exam rules are entered as new versions.
insert into public.test_definitions (
    id, definition_key, version, test_type, display_name, question_count,
    total_marks, navigation_policy, allow_mark_for_review, auto_submit,
    rank_cohort, effective_from, lifecycle_status, rules, published_at
) values (
    '00000000-0000-4000-8000-000000000001',
    'daily_quick', 1, 'daily_quick', 'Daily ten-question quiz', 10, 10,
    'free', true, false, 'same_legacy_quiz_first_attempt', date '2026-07-01',
    'published',
    '{"legacyApi":"/api/quiz/{quiz_id}","legacyIdsPreserved":true,"marksPerCorrect":1}'::jsonb,
    now()
)
on conflict (definition_key, version) do nothing;

insert into public.test_definitions (
    definition_key, version, test_type, display_name, effective_from,
    lifecycle_status, rules
)
select template.test_type, 1, template.test_type, template.display_name,
       date '2026-08-08', 'draft',
       jsonb_build_object('requiresReviewedConfiguration', true)
from (values
    ('chapter', 'Chapter test'),
    ('subject', 'Subject test'),
    ('mixed', 'Mixed practice test'),
    ('previous_year', 'Previous-year paper'),
    ('sectional_mock', 'Sectional mock'),
    ('full_mock', 'Full mock')
) template(test_type, display_name)
on conflict (definition_key, version) do nothing;

-- Backfill every historical and current ten-question run without changing its
-- quiz_id or any legacy relationship.
insert into public.test_instances (
    test_definition_id, legacy_quiz_id, title, lifecycle_status,
    scheduled_start_at, question_count, total_marks, definition_version,
    config_snapshot, published_at, created_at, updated_at
)
select
    definition.id,
    run.quiz_id,
    run.subject_display_name || ' — ' || run.chapter,
    case when run.status in ('ready','posting','posted','posting_failed')
         then 'published' else 'draft' end,
    run.quiz_date::timestamp at time zone 'Asia/Kolkata',
    run.question_count,
    run.question_count,
    definition.version,
    jsonb_build_object(
        'legacyQuizId', run.quiz_id,
        'subjectKey', run.subject_key,
        'chapter', run.chapter,
        'negativeMarksPerWrong', coalesce(run.negative_mark_penalty, 0)
    ),
    case when run.status in ('ready','posting','posted','posting_failed')
         then coalesce(run.ready_at, run.posted_at, run.generated_at, run.created_at)
         else null end,
    run.created_at,
    run.updated_at
from public.quiz_runs run
cross join lateral (
    select id, version from public.test_definitions
    where definition_key = 'daily_quick' and version = 1
) definition
on conflict (legacy_quiz_id) do nothing;

insert into public.test_section_instances (
    test_instance_id, section_key, display_name, section_order,
    question_count, marks_per_correct, negative_marks_per_wrong,
    total_marks, navigation_policy, allow_mark_for_review, auto_submit,
    config_snapshot, created_at, updated_at
)
select
    instance.id,
    'daily',
    run.subject_display_name,
    1,
    run.question_count,
    1,
    coalesce(run.negative_mark_penalty, 0),
    run.question_count,
    'free',
    true,
    false,
    jsonb_build_object('legacyQuizId', run.quiz_id, 'chapter', run.chapter),
    run.created_at,
    run.updated_at
from public.test_instances instance
join public.quiz_runs run on run.quiz_id = instance.legacy_quiz_id
on conflict (test_instance_id, section_key) do nothing;

insert into public.test_instance_questions (
    test_instance_id, section_instance_id, question_id,
    legacy_quiz_question_id, global_order, section_order,
    marks_for_correct, negative_marks_for_wrong, mapping_source, created_at
)
select
    instance.id,
    section.id,
    mapping.question_id,
    mapping.id,
    mapping.question_order,
    mapping.question_order,
    1,
    coalesce(run.negative_mark_penalty, 0),
    'legacy_daily_quick',
    mapping.created_at
from public.quiz_questions mapping
join public.quiz_runs run on run.quiz_id = mapping.quiz_id
join public.test_instances instance on instance.legacy_quiz_id = run.quiz_id
join public.test_section_instances section
  on section.test_instance_id = instance.id and section.section_key = 'daily'
on conflict (legacy_quiz_question_id) do nothing;

update public.quiz_attempts attempt
set test_instance_id = instance.id
from public.test_instances instance
where attempt.test_instance_id is null
  and instance.legacy_quiz_id = attempt.quiz_id;

update public.quiz_attempt_answers answer
set test_section_instance_id = mapping.section_instance_id
from public.quiz_attempts attempt
join public.test_instance_questions mapping
  on mapping.test_instance_id = attempt.test_instance_id
where answer.test_section_instance_id is null
  and answer.attempt_id = attempt.id
  and answer.question_id = mapping.question_id;

create or replace function public.validate_exam_syllabus_weight()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_subject text;
    v_chapter uuid;
    v_micro_topic uuid;
begin
    if new.chapter_id is not null then
        select chapter.subject_key into v_subject
        from public.quiz_chapters chapter where chapter.id = new.chapter_id;
        if v_subject is distinct from new.subject_key then
            raise exception 'chapter does not belong to syllabus subject';
        end if;
    end if;

    if new.micro_topic_id is not null then
        select topic.chapter_id, chapter.subject_key
        into v_chapter, v_subject
        from public.quiz_micro_topics topic
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        where topic.id = new.micro_topic_id;
        if v_subject is distinct from new.subject_key
           or (new.chapter_id is not null and v_chapter is distinct from new.chapter_id) then
            raise exception 'micro-topic does not belong to syllabus scope';
        end if;
    end if;

    if new.knowledge_point_id is not null then
        select point.subject_key, point.micro_topic_id
        into v_subject, v_micro_topic
        from public.knowledge_points point where point.id = new.knowledge_point_id;
        if v_subject is distinct from new.subject_key
           or (new.micro_topic_id is not null
               and v_micro_topic is distinct from new.micro_topic_id) then
            raise exception 'knowledge point does not belong to syllabus scope';
        end if;
    end if;
    return new;
end;
$$;

drop trigger if exists validate_exam_syllabus_weight_scope
    on public.exam_syllabus_weights;
create trigger validate_exam_syllabus_weight_scope
before insert or update on public.exam_syllabus_weights
for each row execute function public.validate_exam_syllabus_weight();

create or replace function public.reject_overlapping_exam_version()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.lifecycle_status <> 'published' then
        return new;
    end if;
    perform pg_advisory_xact_lock(hashtextextended('exam:' || new.exam_key, 0));
    if exists (
        select 1 from public.exams existing
        where existing.exam_key = new.exam_key
          and existing.id <> new.id
          and existing.lifecycle_status = 'published'
          and existing.effective_from <= coalesce(new.effective_to, 'infinity'::date)
          and new.effective_from <= coalesce(existing.effective_to, 'infinity'::date)
    ) then
        raise exception 'published exam versions must not overlap';
    end if;
    return new;
end;
$$;

drop trigger if exists reject_overlapping_exam_version on public.exams;
create trigger reject_overlapping_exam_version
before insert or update on public.exams
for each row execute function public.reject_overlapping_exam_version();

create or replace function public.reject_overlapping_test_definition_version()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.lifecycle_status <> 'published' then
        return new;
    end if;
    perform pg_advisory_xact_lock(
        hashtextextended('test-definition:' || new.definition_key, 0)
    );
    if exists (
        select 1 from public.test_definitions existing
        where existing.definition_key = new.definition_key
          and existing.id <> new.id
          and existing.lifecycle_status = 'published'
          and existing.effective_from <= coalesce(new.effective_to, 'infinity'::date)
          and new.effective_from <= coalesce(existing.effective_to, 'infinity'::date)
    ) then
        raise exception 'published test definition versions must not overlap';
    end if;
    return new;
end;
$$;

drop trigger if exists reject_overlapping_test_definition_version
    on public.test_definitions;
create trigger reject_overlapping_test_definition_version
before insert or update on public.test_definitions
for each row execute function public.reject_overlapping_test_definition_version();

create or replace function public.sync_daily_quick_instance_from_quiz_run()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_definition public.test_definitions;
    v_instance_id uuid;
begin
    select * into v_definition
    from public.test_definitions definition
    where definition.definition_key = 'daily_quick'
      and definition.version = 1;

    insert into public.test_instances (
        test_definition_id, legacy_quiz_id, title, lifecycle_status,
        scheduled_start_at, question_count, total_marks, definition_version,
        config_snapshot, published_at, created_at, updated_at
    ) values (
        v_definition.id,
        new.quiz_id,
        new.subject_display_name || ' — ' || new.chapter,
        case when new.status in ('ready','posting','posted','posting_failed')
             then 'published' else 'draft' end,
        new.quiz_date::timestamp at time zone 'Asia/Kolkata',
        new.question_count,
        new.question_count,
        v_definition.version,
        jsonb_build_object(
            'legacyQuizId', new.quiz_id,
            'subjectKey', new.subject_key,
            'chapter', new.chapter,
            'negativeMarksPerWrong', coalesce(new.negative_mark_penalty, 0)
        ),
        case when new.status in ('ready','posting','posted','posting_failed')
             then coalesce(new.ready_at, new.posted_at, new.generated_at, now())
             else null end,
        new.created_at,
        new.updated_at
    )
    on conflict (legacy_quiz_id) do update set
        title = excluded.title,
        lifecycle_status = excluded.lifecycle_status,
        question_count = excluded.question_count,
        total_marks = excluded.total_marks,
        config_snapshot = excluded.config_snapshot,
        published_at = coalesce(public.test_instances.published_at, excluded.published_at),
        updated_at = excluded.updated_at
    returning id into v_instance_id;

    insert into public.test_section_instances (
        test_instance_id, section_key, display_name, section_order,
        question_count, marks_per_correct, negative_marks_per_wrong,
        total_marks, navigation_policy, allow_mark_for_review, auto_submit,
        config_snapshot, created_at, updated_at
    ) values (
        v_instance_id, 'daily', new.subject_display_name, 1,
        new.question_count, 1, coalesce(new.negative_mark_penalty, 0),
        new.question_count, 'free', true, false,
        jsonb_build_object('legacyQuizId', new.quiz_id, 'chapter', new.chapter),
        new.created_at, new.updated_at
    )
    on conflict (test_instance_id, section_key) do update set
        display_name = excluded.display_name,
        question_count = excluded.question_count,
        negative_marks_per_wrong = excluded.negative_marks_per_wrong,
        total_marks = excluded.total_marks,
        config_snapshot = excluded.config_snapshot,
        updated_at = excluded.updated_at;
    return new;
end;
$$;

drop trigger if exists sync_daily_quick_instance on public.quiz_runs;
create trigger sync_daily_quick_instance
after insert or update of status, question_count, negative_mark_penalty,
    subject_display_name, chapter on public.quiz_runs
for each row execute function public.sync_daily_quick_instance_from_quiz_run();

create or replace function public.sync_daily_quick_question_mapping()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_instance_id uuid;
    v_section_id uuid;
    v_penalty numeric;
begin
    select instance.id, section.id, section.negative_marks_per_wrong
    into v_instance_id, v_section_id, v_penalty
    from public.test_instances instance
    join public.test_section_instances section
      on section.test_instance_id = instance.id and section.section_key = 'daily'
    where instance.legacy_quiz_id = new.quiz_id;

    if v_instance_id is null then
        raise exception 'daily_quick instance is missing for quiz %', new.quiz_id;
    end if;

    insert into public.test_instance_questions (
        test_instance_id, section_instance_id, question_id,
        legacy_quiz_question_id, global_order, section_order,
        marks_for_correct, negative_marks_for_wrong, mapping_source, created_at
    ) values (
        v_instance_id, v_section_id, new.question_id, new.id,
        new.question_order, new.question_order, 1, coalesce(v_penalty, 0),
        'legacy_daily_quick', new.created_at
    )
    on conflict (legacy_quiz_question_id) do nothing;
    return new;
end;
$$;

drop trigger if exists sync_daily_quick_question on public.quiz_questions;
create trigger sync_daily_quick_question
after insert on public.quiz_questions
for each row execute function public.sync_daily_quick_question_mapping();

create or replace function public.attach_test_instance_to_quiz_attempt()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.test_instance_id is null then
        select instance.id into new.test_instance_id
        from public.test_instances instance
        where instance.legacy_quiz_id = new.quiz_id;
    end if;
    return new;
end;
$$;

drop trigger if exists attach_test_instance_to_quiz_attempt
    on public.quiz_attempts;
create trigger attach_test_instance_to_quiz_attempt
before insert on public.quiz_attempts
for each row execute function public.attach_test_instance_to_quiz_attempt();

create or replace function public.attach_test_section_to_quiz_answer()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.test_section_instance_id is null then
        select mapping.section_instance_id into new.test_section_instance_id
        from public.quiz_attempts attempt
        join public.test_instance_questions mapping
          on mapping.test_instance_id = attempt.test_instance_id
         and mapping.question_id = new.question_id
        where attempt.id = new.attempt_id;
    end if;
    return new;
end;
$$;

drop trigger if exists attach_test_section_to_quiz_answer
    on public.quiz_attempt_answers;
create trigger attach_test_section_to_quiz_answer
before insert on public.quiz_attempt_answers
for each row execute function public.attach_test_section_to_quiz_answer();

create or replace function public.get_exam_configuration_catalog(
    p_as_of date default current_date,
    p_exam_key text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with filtered as (
    select exam.*
    from public.exams exam
    where exam.lifecycle_status = 'published'
      and exam.effective_from <= coalesce(p_as_of, current_date)
      and (exam.effective_to is null or exam.effective_to >= coalesce(p_as_of, current_date))
      and (p_exam_key is null or exam.exam_key = p_exam_key)
), page as (
    select * from filtered
    order by exam_key, version desc
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'asOf', coalesce(p_as_of, current_date),
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'examId', exam.id,
        'examKey', exam.exam_key,
        'version', exam.version,
        'displayName', exam.display_name,
        'authority', exam.authority,
        'jurisdiction', exam.jurisdiction,
        'effectiveFrom', exam.effective_from,
        'effectiveTo', exam.effective_to,
        'stages', coalesce((
            select jsonb_agg(jsonb_build_object(
                'stageId', stage.id,
                'stageKey', stage.stage_key,
                'version', stage.version,
                'displayName', stage.display_name,
                'stageKind', stage.stage_kind,
                'order', stage.display_order,
                'effectiveFrom', stage.effective_from,
                'effectiveTo', stage.effective_to,
                'papers', coalesce((
                    select jsonb_agg(jsonb_build_object(
                        'paperId', paper.id,
                        'paperKey', paper.paper_key,
                        'version', paper.version,
                        'displayName', paper.display_name,
                        'order', paper.display_order,
                        'totalQuestions', paper.total_questions,
                        'totalMarks', paper.total_marks,
                        'timeLimitSeconds', paper.time_limit_seconds,
                        'languagePolicy', paper.language_policy,
                        'effectiveFrom', paper.effective_from,
                        'effectiveTo', paper.effective_to,
                        'sections', coalesce((
                            select jsonb_agg(jsonb_build_object(
                                'sectionId', section.id,
                                'sectionKey', section.section_key,
                                'version', section.version,
                                'displayName', section.display_name,
                                'order', section.display_order,
                                'questionCount', section.question_count,
                                'marksPerCorrect', section.marks_per_correct,
                                'negativeMarksPerWrong', section.negative_marks_per_wrong,
                                'totalMarks', section.total_marks,
                                'timeLimitSeconds', section.time_limit_seconds,
                                'cutoffMarks', section.cutoff_marks,
                                'navigationPolicy', section.navigation_policy,
                                'allowMarkForReview', section.allow_mark_for_review,
                                'autoSubmit', section.auto_submit,
                                'weights', coalesce((
                                    select jsonb_agg(jsonb_build_object(
                                        'subjectKey', weight.subject_key,
                                        'chapterId', weight.chapter_id,
                                        'microTopicId', weight.micro_topic_id,
                                        'knowledgePointId', weight.knowledge_point_id,
                                        'weight', weight.weight,
                                        'minimumQuestions', weight.minimum_questions,
                                        'maximumQuestions', weight.maximum_questions,
                                        'effectiveFrom', weight.effective_from,
                                        'effectiveTo', weight.effective_to
                                    ) order by weight.weight desc, weight.subject_key)
                                    from public.exam_syllabus_weights weight
                                    where weight.exam_section_id = section.id
                                      and weight.effective_from <= coalesce(p_as_of, current_date)
                                      and (weight.effective_to is null
                                           or weight.effective_to >= coalesce(p_as_of, current_date))
                                ), '[]'::jsonb)
                            ) order by section.display_order)
                            from public.exam_sections section
                            where section.exam_paper_id = paper.id
                              and section.effective_from <= coalesce(p_as_of, current_date)
                              and (section.effective_to is null
                                   or section.effective_to >= coalesce(p_as_of, current_date))
                        ), '[]'::jsonb)
                    ) order by paper.display_order)
                    from public.exam_papers paper
                    where paper.exam_stage_id = stage.id
                      and paper.effective_from <= coalesce(p_as_of, current_date)
                      and (paper.effective_to is null
                           or paper.effective_to >= coalesce(p_as_of, current_date))
                ), '[]'::jsonb)
            ) order by stage.display_order)
            from public.exam_stages stage
            where stage.exam_id = exam.id
              and stage.effective_from <= coalesce(p_as_of, current_date)
              and (stage.effective_to is null
                   or stage.effective_to >= coalesce(p_as_of, current_date))
        ), '[]'::jsonb)
    ) order by exam.exam_key, exam.version desc) from page exam), '[]'::jsonb)
);
$$;

create or replace function public.get_test_definition_catalog(
    p_as_of date default current_date,
    p_test_type text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with filtered as (
    select definition.*
    from public.test_definitions definition
    where definition.lifecycle_status = 'published'
      and definition.effective_from <= coalesce(p_as_of, current_date)
      and (definition.effective_to is null
           or definition.effective_to >= coalesce(p_as_of, current_date))
      and (p_test_type is null or definition.test_type = p_test_type)
), page as (
    select * from filtered
    order by test_type, definition_key, version desc
    limit greatest(1, least(coalesce(p_limit, 20), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'asOf', coalesce(p_as_of, current_date),
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 20), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'testDefinitionId', definition.id,
        'definitionKey', definition.definition_key,
        'version', definition.version,
        'testType', definition.test_type,
        'displayName', definition.display_name,
        'examId', definition.exam_id,
        'paperId', definition.exam_paper_id,
        'subjectKey', definition.subject_key,
        'chapterId', definition.chapter_id,
        'questionCount', definition.question_count,
        'totalMarks', definition.total_marks,
        'timeLimitSeconds', definition.time_limit_seconds,
        'navigationPolicy', definition.navigation_policy,
        'allowMarkForReview', definition.allow_mark_for_review,
        'autoSubmit', definition.auto_submit,
        'rankCohort', definition.rank_cohort,
        'effectiveFrom', definition.effective_from,
        'effectiveTo', definition.effective_to,
        'rules', definition.rules
    ) order by definition.test_type, definition.definition_key, definition.version desc)
    from page definition), '[]'::jsonb)
);
$$;

create or replace function public.get_public_test_instance(p_test_instance_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'testInstanceId', instance.id,
    'legacyQuizId', instance.legacy_quiz_id,
    'title', instance.title,
    'status', instance.lifecycle_status,
    'testType', definition.test_type,
    'definitionKey', definition.definition_key,
    'definitionVersion', instance.definition_version,
    'questionCount', instance.question_count,
    'totalMarks', instance.total_marks,
    'timeLimitSeconds', instance.time_limit_seconds,
    'scheduledStartAt', instance.scheduled_start_at,
    'scheduledEndAt', instance.scheduled_end_at,
    'rankCohort', definition.rank_cohort,
    'sections', coalesce((
        select jsonb_agg(jsonb_build_object(
            'sectionInstanceId', section.id,
            'sectionKey', section.section_key,
            'displayName', section.display_name,
            'order', section.section_order,
            'questionCount', section.question_count,
            'marksPerCorrect', section.marks_per_correct,
            'negativeMarksPerWrong', section.negative_marks_per_wrong,
            'totalMarks', section.total_marks,
            'timeLimitSeconds', section.time_limit_seconds,
            'cutoffMarks', section.cutoff_marks,
            'navigationPolicy', section.navigation_policy,
            'allowMarkForReview', section.allow_mark_for_review,
            'autoSubmit', section.auto_submit,
            'questions', coalesce((
                select jsonb_agg(jsonb_build_object(
                    'questionId', question.id,
                    'order', mapping.global_order,
                    'sectionOrder', mapping.section_order,
                    'question', question.question_text,
                    'options', jsonb_build_array(
                        question.option_a, question.option_b,
                        question.option_c, question.option_d
                    ),
                    'subjectKey', public.canonical_subject_key(question.subject),
                    'topic', question.topic,
                    'targetDifficulty', question.difficulty,
                    'marksForCorrect', mapping.marks_for_correct,
                    'negativeMarksForWrong', mapping.negative_marks_for_wrong,
                    'required', mapping.required
                ) order by mapping.section_order)
                from public.test_instance_questions mapping
                join public.questions question on question.id = mapping.question_id
                where mapping.section_instance_id = section.id
            ), '[]'::jsonb)
        ) order by section.section_order)
        from public.test_section_instances section
        where section.test_instance_id = instance.id
    ), '[]'::jsonb)
)
from public.test_instances instance
join public.test_definitions definition on definition.id = instance.test_definition_id
where instance.id = p_test_instance_id
  and instance.lifecycle_status in ('published','open','closed');
$$;

alter table public.exams enable row level security;
alter table public.exam_stages enable row level security;
alter table public.exam_papers enable row level security;
alter table public.exam_sections enable row level security;
alter table public.exam_syllabus_weights enable row level security;
alter table public.test_definitions enable row level security;
alter table public.test_instances enable row level security;
alter table public.test_section_instances enable row level security;
alter table public.test_instance_questions enable row level security;

revoke all on table public.exams from public, anon, authenticated;
revoke all on table public.exam_stages from public, anon, authenticated;
revoke all on table public.exam_papers from public, anon, authenticated;
revoke all on table public.exam_sections from public, anon, authenticated;
revoke all on table public.exam_syllabus_weights from public, anon, authenticated;
revoke all on table public.test_definitions from public, anon, authenticated;
revoke all on table public.test_instances from public, anon, authenticated;
revoke all on table public.test_section_instances from public, anon, authenticated;
revoke all on table public.test_instance_questions from public, anon, authenticated;

grant select, insert, update on table public.exams to service_role;
grant select, insert, update on table public.exam_stages to service_role;
grant select, insert, update on table public.exam_papers to service_role;
grant select, insert, update on table public.exam_sections to service_role;
grant select, insert, update on table public.exam_syllabus_weights to service_role;
grant select, insert, update on table public.test_definitions to service_role;
grant select, insert, update on table public.test_instances to service_role;
grant select, insert, update, delete on table public.test_section_instances to service_role;
grant select, insert, update, delete on table public.test_instance_questions to service_role;

create or replace function public.get_phase_e_exam_configuration_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with required_functions(signature) as (values
    ('get_exam_configuration_catalog(date,text,integer,integer)'),
    ('get_test_definition_catalog(date,text,integer,integer)'),
    ('get_public_test_instance(uuid)'),
    ('get_phase_e_exam_configuration_contract()')
), function_permission_failures as (
    select role_name || ':' || signature as failure
    from required_functions
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
    union all
    select 'service_role:' || signature from required_functions
    where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
), required_tables(name) as (values
    ('exams'), ('exam_stages'), ('exam_papers'), ('exam_sections'),
    ('exam_syllabus_weights'), ('test_definitions'), ('test_instances'),
    ('test_section_instances'), ('test_instance_questions')
), table_permission_failures as (
    select role_name || ':' || name as failure
    from required_tables
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_table_privilege(role_name, 'public.' || name, 'SELECT')
       or has_table_privilege(role_name, 'public.' || name, 'INSERT')
       or has_table_privilege(role_name, 'public.' || name, 'UPDATE')
       or has_table_privilege(role_name, 'public.' || name, 'DELETE')
), expected_types(test_type) as (values
    ('daily_quick'), ('chapter'), ('subject'), ('mixed'), ('previous_year'),
    ('sectional_mock'), ('full_mock')
), missing_types as (
    select expected.test_type
    from expected_types expected
    where not exists (
        select 1 from public.test_definitions definition
        where definition.test_type = expected.test_type
    )
), legacy_gaps as (
    select
        (select count(*) from public.quiz_runs run
         where not exists (
             select 1 from public.test_instances instance
             where instance.legacy_quiz_id = run.quiz_id
         )) as runs,
        (select count(*) from public.quiz_questions question
         where not exists (
             select 1 from public.test_instance_questions mapping
             where mapping.legacy_quiz_question_id = question.id
         )) as questions,
        (select count(*) from public.quiz_attempts attempt
         where attempt.test_instance_id is null) as attempts,
        (select count(*) from public.quiz_attempt_answers answer
         where answer.test_section_instance_id is null) as answers
)
select jsonb_build_object(
    'phase_e_exam_configuration_migration_version', '20260808123000',
    'ready',
        to_regclass('public.exams') is not null
        and to_regclass('public.exam_sections') is not null
        and to_regclass('public.exam_syllabus_weights') is not null
        and to_regclass('public.test_instances') is not null
        and to_regclass('public.test_instance_questions') is not null
        and not exists (select 1 from missing_types)
        and (select runs = 0 and questions = 0 and attempts = 0 and answers = 0
             from legacy_gaps)
        and not exists (select 1 from function_permission_failures)
        and not exists (select 1 from table_permission_failures),
    'versioned_exam_hierarchy', true,
    'effective_dating', true,
    'syllabus_weights', true,
    'shared_test_instances', true,
    'daily_quick_definition', exists (
        select 1 from public.test_definitions
        where definition_key = 'daily_quick'
          and test_type = 'daily_quick'
          and question_count = 10
          and lifecycle_status = 'published'
    ),
    'historical_ids_preserved', (select runs = 0 and questions = 0 from legacy_gaps),
    'attempt_links_backfilled', (select attempts = 0 and answers = 0 from legacy_gaps),
    'missing_test_types', coalesce(
        (select jsonb_agg(test_type order by test_type) from missing_types), '[]'::jsonb
    ),
    'function_permission_failures', coalesce(
        (select jsonb_agg(failure order by failure) from function_permission_failures),
        '[]'::jsonb
    ),
    'table_permission_failures', coalesce(
        (select jsonb_agg(failure order by failure) from table_permission_failures),
        '[]'::jsonb
    )
);
$$;

revoke execute on function public.validate_exam_syllabus_weight()
    from public, anon, authenticated;
revoke execute on function public.reject_overlapping_exam_version()
    from public, anon, authenticated;
revoke execute on function public.reject_overlapping_test_definition_version()
    from public, anon, authenticated;
revoke execute on function public.sync_daily_quick_instance_from_quiz_run()
    from public, anon, authenticated;
revoke execute on function public.sync_daily_quick_question_mapping()
    from public, anon, authenticated;
revoke execute on function public.attach_test_instance_to_quiz_attempt()
    from public, anon, authenticated;
revoke execute on function public.attach_test_section_to_quiz_answer()
    from public, anon, authenticated;
revoke execute on function public.get_exam_configuration_catalog(date,text,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_test_definition_catalog(date,text,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_public_test_instance(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_phase_e_exam_configuration_contract()
    from public, anon, authenticated;

grant execute on function public.validate_exam_syllabus_weight() to service_role;
grant execute on function public.reject_overlapping_exam_version() to service_role;
grant execute on function public.reject_overlapping_test_definition_version() to service_role;
grant execute on function public.sync_daily_quick_instance_from_quiz_run() to service_role;
grant execute on function public.sync_daily_quick_question_mapping() to service_role;
grant execute on function public.attach_test_instance_to_quiz_attempt() to service_role;
grant execute on function public.attach_test_section_to_quiz_answer() to service_role;
grant execute on function public.get_exam_configuration_catalog(date,text,integer,integer)
    to service_role;
grant execute on function public.get_test_definition_catalog(date,text,integer,integer)
    to service_role;
grant execute on function public.get_public_test_instance(uuid) to service_role;
grant execute on function public.get_phase_e_exam_configuration_contract()
    to service_role;
