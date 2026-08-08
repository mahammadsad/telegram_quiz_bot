-- Phase E3: real previous-year provenance and a generalized timed test engine.
--
-- Existing daily-quiz submissions remain authoritative and unchanged. They are
-- mirrored into the shared attempt model so old and new tests use one analytics
-- shape without changing any historical quiz, attempt, or answer identifier.

alter table public.test_definitions
    drop constraint if exists test_definitions_test_type_check;
alter table public.test_definitions
    add constraint test_definitions_test_type_check check (test_type in (
        'daily_quick','chapter','subject','mixed','previous_year',
        'previous_year_style','sectional_mock','full_mock'
    ));

insert into public.test_definitions (
    definition_key, version, test_type, display_name, effective_from,
    lifecycle_status, rules
) values (
    'previous_year_style', 1, 'previous_year_style',
    'Generated previous-year-style practice', date '2026-08-08', 'draft',
    '{"actualPreviousYear":false,"requiresReviewedConfiguration":true}'::jsonb
)
on conflict (definition_key, version) do nothing;

create table if not exists public.previous_year_question_provenance (
    id uuid primary key default extensions.gen_random_uuid(),
    question_id uuid not null unique references public.questions(id) on delete restrict,
    exam_id uuid not null references public.exams(id) on delete restrict,
    exam_stage_id uuid not null references public.exam_stages(id) on delete restrict,
    exam_paper_id uuid not null references public.exam_papers(id) on delete restrict,
    exam_section_id uuid not null references public.exam_sections(id) on delete restrict,
    exam_year integer not null check (exam_year between 1900 and 2100),
    shift_label text not null check (length(btrim(shift_label)) >= 1),
    original_question_number integer not null check (original_question_number > 0),
    official_answer char(1) not null check (official_answer in ('A','B','C','D')),
    official_answer_status text not null default 'confirmed'
        check (official_answer_status in ('confirmed','corrected','withdrawn')),
    source_url text not null check (source_url ~ '^https://'),
    source_title text not null check (length(btrim(source_title)) >= 3),
    source_checksum text not null check (source_checksum ~ '^[0-9a-f]{64}$'),
    license_code text not null check (length(btrim(license_code)) >= 2),
    license_url text check (license_url is null or license_url ~ '^https://'),
    language text not null check (language in ('bn','hi','en','bilingual')),
    review_status text not null default 'draft'
        check (review_status in ('draft','verified','rejected','withdrawn')),
    reviewer_ref text,
    reviewed_at timestamptz,
    review_notes text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (
        exam_paper_id, exam_section_id, exam_year, shift_label,
        original_question_number, language
    ),
    check (review_status <> 'verified' or (
        reviewer_ref is not null and reviewed_at is not null
        and official_answer_status <> 'withdrawn'
    ))
);

create index if not exists idx_pyq_provenance_exam_year
    on public.previous_year_question_provenance (
        exam_id, exam_year desc, shift_label, original_question_number
    ) where review_status = 'verified';
create index if not exists idx_pyq_provenance_stage
    on public.previous_year_question_provenance (exam_stage_id);
create index if not exists idx_pyq_provenance_paper
    on public.previous_year_question_provenance (exam_paper_id);
create index if not exists idx_pyq_provenance_section
    on public.previous_year_question_provenance (exam_section_id);

create table if not exists public.previous_year_question_corrections (
    id bigint generated always as identity primary key,
    provenance_id uuid not null
        references public.previous_year_question_provenance(id) on delete restrict,
    superseding_question_id uuid not null unique
        references public.questions(id) on delete restrict,
    previous_official_answer char(1) not null
        check (previous_official_answer in ('A','B','C','D')),
    corrected_official_answer char(1) not null
        check (corrected_official_answer in ('A','B','C','D')),
    correction_source_url text not null check (correction_source_url ~ '^https://'),
    correction_source_checksum text not null
        check (correction_source_checksum ~ '^[0-9a-f]{64}$'),
    correction_reason text not null check (length(btrim(correction_reason)) >= 3),
    effective_at timestamptz not null,
    reviewer_ref text not null check (length(btrim(reviewer_ref)) >= 2),
    created_at timestamptz not null default now(),
    unique (provenance_id, effective_at),
    check (previous_official_answer <> corrected_official_answer)
);

create index if not exists idx_pyq_corrections_provenance
    on public.previous_year_question_corrections (
        provenance_id, effective_at desc, id desc
    );

create or replace function public.validate_previous_year_provenance()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_exam_id uuid;
    v_stage_id uuid;
    v_paper_id uuid;
    v_correct char(1);
    v_source text;
begin
    if tg_op = 'UPDATE' and old.review_status = 'verified' then
        if (to_jsonb(new) - array[
                'official_answer', 'official_answer_status', 'updated_at'
            ]) is distinct from (
                to_jsonb(old) - array[
                    'official_answer', 'official_answer_status', 'updated_at'
                ]
            ) then
            raise exception 'verified PYQ provenance is immutable';
        end if;
        if (
            new.official_answer is distinct from old.official_answer
            or new.official_answer_status is distinct from old.official_answer_status
        ) and not (
            new.official_answer_status = 'corrected'
            and exists (
                select 1
                from public.previous_year_question_corrections correction
                where correction.provenance_id = old.id
                  and correction.corrected_official_answer = new.official_answer
                  and correction.id = (
                      select latest.id
                      from public.previous_year_question_corrections latest
                      where latest.provenance_id = old.id
                      order by latest.effective_at desc, latest.id desc
                      limit 1
                  )
            )
        ) then
            raise exception 'verified PYQ answers change only through correction audit';
        end if;
    end if;

    select stage.exam_id into v_exam_id
    from public.exam_stages stage where stage.id = new.exam_stage_id;
    select paper.exam_stage_id into v_stage_id
    from public.exam_papers paper where paper.id = new.exam_paper_id;
    select section.exam_paper_id into v_paper_id
    from public.exam_sections section where section.id = new.exam_section_id;

    if v_exam_id is distinct from new.exam_id
       or v_stage_id is distinct from new.exam_stage_id
       or v_paper_id is distinct from new.exam_paper_id then
        raise exception 'previous-year hierarchy is inconsistent';
    end if;

    if new.review_status = 'verified' then
        select question.correct_option, question.source
        into v_correct, v_source
        from public.questions question where question.id = new.question_id;
        -- A confirmed row is anchored to the original reviewed question.
        -- Corrected rows are anchored by the append-only correction trigger to
        -- an explicit superseding question version instead.
        if new.official_answer_status = 'confirmed'
           and v_correct is distinct from new.official_answer then
            raise exception 'verified official answer must match the reviewed question version';
        end if;
        if lower(coalesce(v_source, '')) ~ '(gemini|generated|synthetic|style)' then
            raise exception 'generated or style content cannot be verified as an actual PYQ';
        end if;
    end if;
    new.updated_at := now();
    return new;
end;
$$;

drop trigger if exists validate_previous_year_provenance_row
    on public.previous_year_question_provenance;
create trigger validate_previous_year_provenance_row
before insert or update on public.previous_year_question_provenance
for each row execute function public.validate_previous_year_provenance();

create or replace function public.validate_previous_year_correction()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_provenance public.previous_year_question_provenance;
    v_current_question_id uuid;
    v_supersedes uuid;
    v_correct char(1);
begin
    select * into v_provenance
    from public.previous_year_question_provenance provenance
    where provenance.id = new.provenance_id
    for update;

    if v_provenance.review_status <> 'verified'
       or v_provenance.official_answer_status = 'withdrawn' then
        raise exception 'only a verified active PYQ can be corrected';
    end if;
    if new.effective_at > now() then
        raise exception 'future-dated PYQ corrections are not permitted';
    end if;
    if v_provenance.official_answer is distinct from new.previous_official_answer then
        raise exception 'correction previous answer does not match current provenance';
    end if;

    select coalesce((
        select correction.superseding_question_id
        from public.previous_year_question_corrections correction
        where correction.provenance_id = new.provenance_id
        order by correction.effective_at desc, correction.id desc
        limit 1
    ), v_provenance.question_id) into v_current_question_id;

    select question.supersedes_question_id, question.correct_option
    into v_supersedes, v_correct
    from public.questions question where question.id = new.superseding_question_id;
    if v_supersedes is distinct from v_current_question_id then
        raise exception 'correction must use an explicit superseding question version';
    end if;
    if v_correct is distinct from new.corrected_official_answer then
        raise exception 'superseding question answer does not match correction';
    end if;

    return new;
end;
$$;

drop trigger if exists validate_previous_year_correction_row
    on public.previous_year_question_corrections;
create trigger validate_previous_year_correction_row
before insert on public.previous_year_question_corrections
for each row execute function public.validate_previous_year_correction();

create or replace function public.apply_previous_year_correction()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    update public.previous_year_question_provenance
    set official_answer = new.corrected_official_answer,
        official_answer_status = 'corrected',
        updated_at = now()
    where id = new.provenance_id;
    return new;
end;
$$;

drop trigger if exists apply_previous_year_correction_row
    on public.previous_year_question_corrections;
create trigger apply_previous_year_correction_row
after insert on public.previous_year_question_corrections
for each row execute function public.apply_previous_year_correction();

drop trigger if exists protect_previous_year_corrections_append_only
    on public.previous_year_question_corrections;
create trigger protect_previous_year_corrections_append_only
before update or delete on public.previous_year_question_corrections
for each row execute function public.reject_append_only_content_mutation();

create table if not exists public.test_attempts (
    id uuid primary key default extensions.gen_random_uuid(),
    test_instance_id uuid not null references public.test_instances(id) on delete restrict,
    user_id uuid not null references public.users(id) on delete cascade,
    client_attempt_id uuid not null,
    legacy_quiz_attempt_id uuid unique
        references public.quiz_attempts(id) on delete restrict,
    status text not null default 'in_progress'
        check (status in (
            'in_progress','submitted','auto_submitted','abandoned','invalidated'
        )),
    current_section_instance_id uuid
        references public.test_section_instances(id) on delete restrict,
    attempt_number integer not null check (attempt_number > 0),
    started_at timestamptz not null default now(),
    deadline_at timestamptz,
    submitted_at timestamptz,
    duration_seconds integer check (duration_seconds is null or duration_seconds >= 0),
    question_count integer not null check (question_count > 0),
    answered_count integer not null default 0 check (answered_count >= 0),
    correct_count integer not null default 0 check (correct_count >= 0),
    wrong_count integer not null default 0 check (wrong_count >= 0),
    skipped_count integer not null default 0 check (skipped_count >= 0),
    marked_for_review_count integer not null default 0
        check (marked_for_review_count >= 0),
    positive_marks numeric(10,2) not null default 0,
    negative_marks numeric(10,2) not null default 0,
    net_marks numeric(10,2) not null default 0,
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (test_instance_id, user_id, client_attempt_id),
    unique (test_instance_id, user_id, attempt_number),
    check (deadline_at is null or deadline_at > started_at),
    check (status = 'in_progress' or submitted_at is not null)
);

create index if not exists idx_test_attempts_user_history
    on public.test_attempts (user_id, submitted_at desc, started_at desc);
create index if not exists idx_test_attempts_instance_rank
    on public.test_attempts (
        test_instance_id, net_marks desc, correct_count desc,
        duration_seconds asc, submitted_at asc
    ) where status in ('submitted','auto_submitted') and attempt_number = 1;
create index if not exists idx_test_attempts_due_auto_submit
    on public.test_attempts (deadline_at, id)
    where status = 'in_progress' and deadline_at is not null;
create index if not exists idx_test_attempts_current_section
    on public.test_attempts (current_section_instance_id)
    where current_section_instance_id is not null;

create table if not exists public.test_attempt_section_states (
    attempt_id uuid not null references public.test_attempts(id) on delete cascade,
    section_instance_id uuid not null
        references public.test_section_instances(id) on delete restrict,
    section_order integer not null check (section_order > 0),
    status text not null default 'locked'
        check (status in ('locked','open','completed','expired')),
    opened_at timestamptz,
    deadline_at timestamptz,
    completed_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    primary key (attempt_id, section_instance_id),
    unique (attempt_id, section_order),
    check (deadline_at is null or opened_at is null or deadline_at > opened_at)
);

create index if not exists idx_test_attempt_section_states_section
    on public.test_attempt_section_states (section_instance_id);
create index if not exists idx_test_attempt_section_states_due
    on public.test_attempt_section_states (deadline_at, attempt_id)
    where status = 'open' and deadline_at is not null;

create table if not exists public.test_attempt_responses (
    id uuid primary key default extensions.gen_random_uuid(),
    attempt_id uuid not null references public.test_attempts(id) on delete cascade,
    test_instance_question_id uuid not null
        references public.test_instance_questions(id) on delete restrict,
    legacy_quiz_answer_id uuid unique
        references public.quiz_attempt_answers(id) on delete restrict,
    selected_option smallint check (selected_option between 0 and 3),
    is_correct boolean,
    response_time_seconds numeric
        check (response_time_seconds is null or response_time_seconds >= 0),
    marked_for_review boolean not null default false,
    awarded_marks numeric(10,2) not null default 0,
    deducted_marks numeric(10,2) not null default 0,
    net_marks numeric(10,2) not null default 0,
    saved_at timestamptz not null default now(),
    finalized_at timestamptz,
    unique (attempt_id, test_instance_question_id)
);

create index if not exists idx_test_attempt_responses_mapping
    on public.test_attempt_responses (test_instance_question_id);
create index if not exists idx_test_attempt_responses_attempt_correctness
    on public.test_attempt_responses (attempt_id, is_correct);

-- Mirror all historical official quiz attempts into the shared engine. The
-- generic attempt uses the same UUID as the legacy attempt.
insert into public.test_attempts (
    id, test_instance_id, user_id, client_attempt_id,
    legacy_quiz_attempt_id, status, current_section_instance_id,
    attempt_number, started_at, submitted_at, duration_seconds,
    question_count, answered_count, correct_count, wrong_count,
    skipped_count, marked_for_review_count, positive_marks,
    negative_marks, net_marks, metadata, created_at, updated_at
)
select
    attempt.id,
    attempt.test_instance_id,
    attempt.user_id,
    coalesce(attempt.client_attempt_uuid, md5('legacy:' || attempt.id::text)::uuid),
    attempt.id,
    'submitted',
    section.id,
    attempt.attempt_number,
    coalesce(attempt.started_at, attempt.completed_at),
    attempt.completed_at,
    attempt.duration_seconds,
    attempt.total,
    attempt.answered,
    attempt.score,
    attempt.answered - attempt.score,
    attempt.total - attempt.answered,
    (select count(*) from public.quiz_attempt_answers answer
     where answer.attempt_id = attempt.id and answer.marked_for_review),
    attempt.score,
    (attempt.answered - attempt.score) * attempt.negative_mark_penalty,
    attempt.net_score,
    jsonb_build_object('legacyQuizId', attempt.quiz_id, 'mirrored', true),
    attempt.created_at,
    attempt.completed_at
from public.quiz_attempts attempt
join public.test_section_instances section
  on section.test_instance_id = attempt.test_instance_id
 and section.section_order = 1
where attempt.test_instance_id is not null
on conflict (id) do nothing;

insert into public.test_attempt_section_states (
    attempt_id, section_instance_id, section_order, status,
    opened_at, completed_at, created_at, updated_at
)
select
    attempt.id, section.id, section.section_order, 'completed',
    attempt.started_at, attempt.submitted_at, attempt.created_at, attempt.updated_at
from public.test_attempts attempt
join public.test_section_instances section
  on section.test_instance_id = attempt.test_instance_id
where attempt.legacy_quiz_attempt_id is not null
on conflict (attempt_id, section_instance_id) do nothing;

insert into public.test_attempt_responses (
    id, attempt_id, test_instance_question_id, legacy_quiz_answer_id,
    selected_option, is_correct, response_time_seconds, marked_for_review,
    awarded_marks, deducted_marks, net_marks, saved_at, finalized_at
)
select
    answer.id,
    answer.attempt_id,
    mapping.id,
    answer.id,
    answer.selected_option,
    answer.is_correct,
    answer.response_time_seconds,
    answer.marked_for_review,
    case when answer.is_correct is true then mapping.marks_for_correct else 0 end,
    case when answer.is_correct is false then mapping.negative_marks_for_wrong else 0 end,
    case
        when answer.is_correct is true then mapping.marks_for_correct
        when answer.is_correct is false then -mapping.negative_marks_for_wrong
        else 0
    end,
    answer.created_at,
    coalesce(answer.answered_at, answer.created_at)
from public.quiz_attempt_answers answer
join public.test_attempts attempt on attempt.id = answer.attempt_id
join public.test_instance_questions mapping
  on mapping.test_instance_id = attempt.test_instance_id
 and mapping.question_id = answer.question_id
on conflict (id) do nothing;

create or replace function public.mirror_quiz_attempt_to_shared_test()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_section_id uuid;
begin
    if new.test_instance_id is null then
        return new;
    end if;
    select section.id into v_section_id
    from public.test_section_instances section
    where section.test_instance_id = new.test_instance_id
    order by section.section_order
    limit 1;

    insert into public.test_attempts (
        id, test_instance_id, user_id, client_attempt_id,
        legacy_quiz_attempt_id, status, current_section_instance_id,
        attempt_number, started_at, submitted_at, duration_seconds,
        question_count, answered_count, correct_count, wrong_count,
        skipped_count, positive_marks, negative_marks, net_marks,
        metadata, created_at, updated_at
    ) values (
        new.id, new.test_instance_id, new.user_id,
        coalesce(new.client_attempt_uuid, md5('legacy:' || new.id::text)::uuid),
        new.id, 'submitted', v_section_id, new.attempt_number,
        coalesce(new.started_at, new.completed_at), new.completed_at,
        new.duration_seconds, new.total, new.answered, new.score,
        new.answered - new.score, new.total - new.answered,
        new.score, (new.answered - new.score) * new.negative_mark_penalty,
        new.net_score,
        jsonb_build_object('legacyQuizId', new.quiz_id, 'mirrored', true),
        new.created_at, new.completed_at
    ) on conflict (id) do nothing;

    insert into public.test_attempt_section_states (
        attempt_id, section_instance_id, section_order, status,
        opened_at, completed_at, created_at, updated_at
    )
    select new.id, section.id, section.section_order, 'completed',
           coalesce(new.started_at, new.completed_at), new.completed_at,
           new.created_at, new.completed_at
    from public.test_section_instances section
    where section.test_instance_id = new.test_instance_id
    on conflict (attempt_id, section_instance_id) do nothing;
    return new;
end;
$$;

drop trigger if exists mirror_quiz_attempt_to_shared_test on public.quiz_attempts;
create trigger mirror_quiz_attempt_to_shared_test
after insert on public.quiz_attempts
for each row execute function public.mirror_quiz_attempt_to_shared_test();

create or replace function public.mirror_quiz_answer_to_shared_test()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_mapping public.test_instance_questions;
begin
    select mapping.* into v_mapping
    from public.test_attempts attempt
    join public.test_instance_questions mapping
      on mapping.test_instance_id = attempt.test_instance_id
     and mapping.question_id = new.question_id
    where attempt.id = new.attempt_id;

    if v_mapping.id is null then
        return new;
    end if;
    insert into public.test_attempt_responses (
        id, attempt_id, test_instance_question_id, legacy_quiz_answer_id,
        selected_option, is_correct, response_time_seconds, marked_for_review,
        awarded_marks, deducted_marks, net_marks, saved_at, finalized_at
    ) values (
        new.id, new.attempt_id, v_mapping.id, new.id,
        new.selected_option, new.is_correct, new.response_time_seconds,
        new.marked_for_review,
        case when new.is_correct is true then v_mapping.marks_for_correct else 0 end,
        case when new.is_correct is false then v_mapping.negative_marks_for_wrong else 0 end,
        case
            when new.is_correct is true then v_mapping.marks_for_correct
            when new.is_correct is false then -v_mapping.negative_marks_for_wrong
            else 0
        end,
        new.created_at, coalesce(new.answered_at, new.created_at)
    ) on conflict (id) do nothing;

    update public.test_attempts
    set marked_for_review_count = (
            select count(*) from public.test_attempt_responses response
            where response.attempt_id = new.attempt_id and response.marked_for_review
        ),
        updated_at = now()
    where id = new.attempt_id;
    return new;
end;
$$;

drop trigger if exists mirror_quiz_answer_to_shared_test
    on public.quiz_attempt_answers;
create trigger mirror_quiz_answer_to_shared_test
after insert on public.quiz_attempt_answers
for each row execute function public.mirror_quiz_answer_to_shared_test();

create or replace function public.get_test_attempt_progress_for_user(
    p_attempt_id uuid,
    p_user_id uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'attemptId', attempt.id,
    'testInstanceId', attempt.test_instance_id,
    'status', attempt.status,
    'attemptNumber', attempt.attempt_number,
    'startedAt', attempt.started_at,
    'deadlineAt', attempt.deadline_at,
    'currentSectionInstanceId', attempt.current_section_instance_id,
    'sections', coalesce((
        select jsonb_agg(jsonb_build_object(
            'sectionInstanceId', state.section_instance_id,
            'order', state.section_order,
            'status', state.status,
            'openedAt', state.opened_at,
            'deadlineAt', state.deadline_at,
            'completedAt', state.completed_at
        ) order by state.section_order)
        from public.test_attempt_section_states state
        where state.attempt_id = attempt.id
    ), '[]'::jsonb),
    'responses', coalesce((
        select jsonb_agg(jsonb_build_object(
            'questionId', mapping.question_id,
            'selectedIndex', response.selected_option,
            'markedForReview', response.marked_for_review,
            'responseTimeSeconds', response.response_time_seconds,
            'savedAt', response.saved_at
        ) order by mapping.global_order)
        from public.test_attempt_responses response
        join public.test_instance_questions mapping
          on mapping.id = response.test_instance_question_id
        where response.attempt_id = attempt.id
    ), '[]'::jsonb)
)
from public.test_attempts attempt
where attempt.id = p_attempt_id and attempt.user_id = p_user_id;
$$;

create or replace function public.start_test_attempt_atomic(
    p_test_instance_id uuid,
    p_user_id uuid,
    p_client_attempt_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_instance public.test_instances;
    v_attempt_id uuid;
    v_attempt_number integer;
    v_first_section public.test_section_instances;
    v_deadline timestamptz;
begin
    if p_client_attempt_id is null then
        raise exception 'a client-generated UUID attempt identifier is required';
    end if;
    perform pg_advisory_xact_lock(
        hashtextextended(p_test_instance_id::text || ':' || p_user_id::text, 0)
    );

    select * into v_instance from public.test_instances instance
    where instance.id = p_test_instance_id
      and instance.lifecycle_status in ('published','open');
    if v_instance.id is null then
        raise exception 'test instance is not available';
    end if;
    if v_instance.scheduled_start_at is not null and v_instance.scheduled_start_at > now() then
        raise exception 'test has not started';
    end if;
    if v_instance.scheduled_end_at is not null and v_instance.scheduled_end_at <= now() then
        raise exception 'test is closed';
    end if;
    if v_instance.question_count <= 0 or (
        select count(*) from public.test_instance_questions mapping
        where mapping.test_instance_id = v_instance.id
    ) <> v_instance.question_count then
        raise exception 'test question mapping is incomplete';
    end if;

    select id into v_attempt_id from public.test_attempts attempt
    where attempt.test_instance_id = p_test_instance_id
      and attempt.user_id = p_user_id
      and attempt.client_attempt_id = p_client_attempt_id;
    if v_attempt_id is not null then
        return public.get_test_attempt_progress_for_user(v_attempt_id, p_user_id);
    end if;

    select * into v_first_section
    from public.test_section_instances section
    where section.test_instance_id = v_instance.id
    order by section.section_order
    limit 1;
    if v_first_section.id is null then
        raise exception 'test has no sections';
    end if;

    select coalesce(max(attempt_number), 0) + 1 into v_attempt_number
    from public.test_attempts
    where test_instance_id = p_test_instance_id and user_id = p_user_id;
    v_deadline := case when v_instance.time_limit_seconds is null then null
        else now() + make_interval(secs => v_instance.time_limit_seconds) end;

    insert into public.test_attempts (
        test_instance_id, user_id, client_attempt_id, status,
        current_section_instance_id, attempt_number, started_at, deadline_at,
        question_count, metadata
    ) values (
        p_test_instance_id, p_user_id, p_client_attempt_id, 'in_progress',
        v_first_section.id, v_attempt_number, now(), v_deadline,
        v_instance.question_count,
        jsonb_build_object('definitionVersion', v_instance.definition_version)
    ) returning id into v_attempt_id;

    insert into public.test_attempt_section_states (
        attempt_id, section_instance_id, section_order, status,
        opened_at, deadline_at
    )
    select
        v_attempt_id,
        section.id,
        section.section_order,
        case when section.id = v_first_section.id then 'open' else 'locked' end,
        case when section.id = v_first_section.id then now() else null end,
        case when section.id = v_first_section.id then least(
            v_deadline,
            case when section.time_limit_seconds is null then null
                 else now() + make_interval(secs => section.time_limit_seconds) end
        ) else null end
    from public.test_section_instances section
    where section.test_instance_id = v_instance.id
    order by section.section_order;

    return public.get_test_attempt_progress_for_user(v_attempt_id, p_user_id);
end;
$$;

create or replace function public.save_test_attempt_progress_atomic(
    p_attempt_id uuid,
    p_user_id uuid,
    p_responses jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt public.test_attempts;
    v_item jsonb;
    v_mapping public.test_instance_questions;
    v_section_state public.test_attempt_section_states;
    v_selected integer;
    v_response_time numeric;
    v_marked boolean;
begin
    if jsonb_typeof(p_responses) <> 'array'
       or jsonb_array_length(p_responses) > 500 then
        raise exception 'responses must be a bounded array';
    end if;
    select * into v_attempt from public.test_attempts attempt
    where attempt.id = p_attempt_id and attempt.user_id = p_user_id
    for update;
    if v_attempt.id is null then
        raise exception 'attempt not found';
    end if;
    if v_attempt.status <> 'in_progress' then
        raise exception 'attempt is already finalized';
    end if;
    if v_attempt.deadline_at is not null and v_attempt.deadline_at <= now() then
        raise exception 'test deadline has passed';
    end if;

    for v_item in select value from jsonb_array_elements(p_responses)
    loop
        if not (v_item ? 'questionId') then
            raise exception 'questionId is required';
        end if;
        select mapping.* into v_mapping
        from public.test_instance_questions mapping
        where mapping.test_instance_id = v_attempt.test_instance_id
          and mapping.question_id = (v_item ->> 'questionId')::uuid;
        if v_mapping.id is null then
            raise exception 'response question does not belong to test';
        end if;
        select state.* into v_section_state
        from public.test_attempt_section_states state
        where state.attempt_id = v_attempt.id
          and state.section_instance_id = v_mapping.section_instance_id;
        if v_section_state.status <> 'open' then
            raise exception 'response section is not open';
        end if;
        if v_section_state.deadline_at is not null
           and v_section_state.deadline_at <= now() then
            raise exception 'section deadline has passed';
        end if;

        v_selected := case when jsonb_typeof(v_item -> 'selectedIndex') = 'null'
            or not (v_item ? 'selectedIndex') then null
            else (v_item ->> 'selectedIndex')::integer end;
        if v_selected is not null and v_selected not between 0 and 3 then
            raise exception 'selectedIndex must be between 0 and 3 or null';
        end if;
        v_response_time := case when not (v_item ? 'responseTimeSeconds')
            or jsonb_typeof(v_item -> 'responseTimeSeconds') = 'null' then null
            else (v_item ->> 'responseTimeSeconds')::numeric end;
        if v_response_time is not null and (v_response_time < 0 or v_response_time > 86400) then
            raise exception 'invalid response time';
        end if;
        v_marked := coalesce((v_item ->> 'markedForReview')::boolean, false);

        insert into public.test_attempt_responses (
            attempt_id, test_instance_question_id, selected_option,
            response_time_seconds, marked_for_review, saved_at
        ) values (
            v_attempt.id, v_mapping.id, v_selected,
            v_response_time, v_marked, now()
        )
        on conflict (attempt_id, test_instance_question_id) do update set
            selected_option = excluded.selected_option,
            response_time_seconds = excluded.response_time_seconds,
            marked_for_review = excluded.marked_for_review,
            saved_at = now();
    end loop;

    update public.test_attempts
    set answered_count = (
            select count(*) from public.test_attempt_responses response
            where response.attempt_id = p_attempt_id
              and response.selected_option is not null
        ),
        marked_for_review_count = (
            select count(*) from public.test_attempt_responses response
            where response.attempt_id = p_attempt_id and response.marked_for_review
        ),
        updated_at = now()
    where id = p_attempt_id;
    return public.get_test_attempt_progress_for_user(p_attempt_id, p_user_id);
end;
$$;

create or replace function public.advance_test_attempt_section_atomic(
    p_attempt_id uuid,
    p_user_id uuid,
    p_next_section_instance_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt public.test_attempts;
    v_current public.test_attempt_section_states;
    v_next public.test_attempt_section_states;
    v_section public.test_section_instances;
begin
    select * into v_attempt from public.test_attempts attempt
    where attempt.id = p_attempt_id and attempt.user_id = p_user_id
    for update;
    if v_attempt.id is null or v_attempt.status <> 'in_progress' then
        raise exception 'active attempt not found';
    end if;
    select * into v_current from public.test_attempt_section_states state
    where state.attempt_id = p_attempt_id
      and state.section_instance_id = v_attempt.current_section_instance_id
    for update;
    select * into v_next from public.test_attempt_section_states state
    where state.attempt_id = p_attempt_id
      and state.section_instance_id = p_next_section_instance_id
    for update;
    if v_current.status <> 'open' or v_next.status <> 'locked'
       or v_next.section_order <> v_current.section_order + 1 then
        raise exception 'section transition must move to the exact next section';
    end if;

    update public.test_attempt_section_states
    set status = case when deadline_at is not null and deadline_at <= now()
                      then 'expired' else 'completed' end,
        completed_at = now(), updated_at = now()
    where attempt_id = p_attempt_id
      and section_instance_id = v_current.section_instance_id;

    select * into v_section from public.test_section_instances section
    where section.id = p_next_section_instance_id;
    update public.test_attempt_section_states
    set status = 'open', opened_at = now(),
        deadline_at = least(
            v_attempt.deadline_at,
            case when v_section.time_limit_seconds is null then null
                 else now() + make_interval(secs => v_section.time_limit_seconds) end
        ),
        updated_at = now()
    where attempt_id = p_attempt_id
      and section_instance_id = p_next_section_instance_id;
    update public.test_attempts
    set current_section_instance_id = p_next_section_instance_id,
        updated_at = now()
    where id = p_attempt_id;
    return public.get_test_attempt_progress_for_user(p_attempt_id, p_user_id);
end;
$$;

create or replace function public.get_test_attempt_result_for_user(
    p_attempt_id uuid,
    p_user_id uuid
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with target as (
    select attempt.* from public.test_attempts attempt
    where attempt.id = p_attempt_id
      and attempt.user_id = p_user_id
      and attempt.status in ('submitted','auto_submitted')
), official as (
    select
        attempt.id,
        row_number() over (
            order by attempt.net_marks desc, attempt.correct_count desc,
                     attempt.duration_seconds asc nulls last, attempt.submitted_at, attempt.id
        )::integer as rank,
        count(*) over ()::integer as cohort_size
    from public.test_attempts attempt
    join target on target.test_instance_id = attempt.test_instance_id
    where attempt.status in ('submitted','auto_submitted')
      and attempt.attempt_number = 1
), target_rank as (
    select official.* from official join target on target.id = official.id
), response_rows as (
    select
        response.*,
        mapping.section_instance_id,
        mapping.question_id,
        mapping.global_order,
        question.subject,
        question.topic,
        question.knowledge_point_id
    from public.test_attempt_responses response
    join target on target.id = response.attempt_id
    join public.test_instance_questions mapping
      on mapping.id = response.test_instance_question_id
    join public.questions question on question.id = mapping.question_id
)
select jsonb_build_object(
    'attemptId', target.id,
    'testInstanceId', target.test_instance_id,
    'status', target.status,
    'attemptNumber', target.attempt_number,
    'startedAt', target.started_at,
    'submittedAt', target.submitted_at,
    'durationSeconds', target.duration_seconds,
    'questionCount', target.question_count,
    'answered', target.answered_count,
    'correct', target.correct_count,
    'wrong', target.wrong_count,
    'skipped', target.skipped_count,
    'markedForReview', target.marked_for_review_count,
    'positiveMarks', target.positive_marks,
    'negativeMarks', target.negative_marks,
    'netMarks', target.net_marks,
    'rankCohort', jsonb_build_object(
        'definition', 'first submitted attempt per learner on the same test instance',
        'eligible', target.attempt_number = 1,
        'rank', rank.rank,
        'size', rank.cohort_size,
        'percentile', case
            when rank.rank is null then null
            when rank.cohort_size <= 1 then 100
            else round(100.0 * (rank.cohort_size - rank.rank)
                       / (rank.cohort_size - 1), 2)
        end
    ),
    'sections', coalesce((
        select jsonb_agg(jsonb_build_object(
            'sectionInstanceId', section_row.id,
            'sectionKey', section_row.section_key,
            'displayName', section_row.display_name,
            'order', section_row.section_order,
            'answered', section_row.answered,
            'correct', section_row.correct,
            'wrong', section_row.wrong,
            'skipped', section_row.skipped,
            'positiveMarks', section_row.positive_marks,
            'negativeMarks', section_row.negative_marks,
            'netMarks', section_row.net_marks
        ) order by section_row.section_order)
        from (
            select
                section.id,
                section.section_key,
                section.display_name,
                section.section_order,
                count(rows.id) filter (where rows.selected_option is not null) as answered,
                count(rows.id) filter (where rows.is_correct is true) as correct,
                count(rows.id) filter (where rows.is_correct is false) as wrong,
                count(rows.id) filter (where rows.selected_option is null) as skipped,
                coalesce(sum(rows.awarded_marks), 0) as positive_marks,
                coalesce(sum(rows.deducted_marks), 0) as negative_marks,
                coalesce(sum(rows.net_marks), 0) as net_marks
            from public.test_section_instances section
            left join response_rows rows on rows.section_instance_id = section.id
            where section.test_instance_id = target.test_instance_id
            group by section.id, section.section_key, section.display_name,
                     section.section_order
        ) section_row
    ), '[]'::jsonb),
    'subjectAnalysis', coalesce((
        select jsonb_agg(jsonb_build_object(
            'subjectKey', subject_key,
            'answered', answered,
            'correct', correct,
            'wrong', wrong,
            'skipped', skipped,
            'netMarks', net_marks
        ) order by subject_key)
        from (
            select public.canonical_subject_key(subject) as subject_key,
                   count(*) filter (where selected_option is not null) as answered,
                   count(*) filter (where is_correct is true) as correct,
                   count(*) filter (where is_correct is false) as wrong,
                   count(*) filter (where selected_option is null) as skipped,
                   coalesce(sum(net_marks), 0) as net_marks
            from response_rows group by public.canonical_subject_key(subject)
        ) subject_rows
    ), '[]'::jsonb),
    'topicAnalysis', coalesce((
        select jsonb_agg(jsonb_build_object(
            'subjectKey', subject_key,
            'topic', topic,
            'answered', answered,
            'correct', correct,
            'wrong', wrong,
            'skipped', skipped,
            'netMarks', net_marks
        ) order by subject_key, topic)
        from (
            select public.canonical_subject_key(subject) as subject_key, topic,
                   count(*) filter (where selected_option is not null) as answered,
                   count(*) filter (where is_correct is true) as correct,
                   count(*) filter (where is_correct is false) as wrong,
                   count(*) filter (where selected_option is null) as skipped,
                   coalesce(sum(net_marks), 0) as net_marks
            from response_rows group by public.canonical_subject_key(subject), topic
        ) topic_rows
    ), '[]'::jsonb),
    'knowledgePointAnalysis', coalesce((
        select jsonb_agg(jsonb_build_object(
            'knowledgePointId', knowledge_point_id,
            'answered', answered,
            'correct', correct,
            'wrong', wrong,
            'skipped', skipped,
            'netMarks', net_marks
        ) order by knowledge_point_id)
        from (
            select knowledge_point_id,
                   count(*) filter (where selected_option is not null) as answered,
                   count(*) filter (where is_correct is true) as correct,
                   count(*) filter (where is_correct is false) as wrong,
                   count(*) filter (where selected_option is null) as skipped,
                   coalesce(sum(net_marks), 0) as net_marks
            from response_rows where knowledge_point_id is not null
            group by knowledge_point_id
        ) kp_rows
    ), '[]'::jsonb),
    'review', coalesce((
        select jsonb_agg(jsonb_build_object(
            'questionId', rows.question_id,
            'order', rows.global_order,
            'selectedIndex', rows.selected_option,
            'correctIndex', strpos('ABCD', question.correct_option) - 1,
            'isCorrect', rows.is_correct,
            'markedForReview', rows.marked_for_review,
            'awardedMarks', rows.awarded_marks,
            'deductedMarks', rows.deducted_marks,
            'netMarks', rows.net_marks,
            'explanation', question.explanation,
            'detailedExplanation', question.detailed_explanation
        ) order by rows.global_order)
        from response_rows rows
        join public.questions question on question.id = rows.question_id
    ), '[]'::jsonb)
)
from target
left join target_rank rank on rank.id = target.id;
$$;

create or replace function public.submit_test_attempt_atomic(
    p_attempt_id uuid,
    p_user_id uuid,
    p_auto_submit boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt public.test_attempts;
    v_now timestamptz := now();
    v_auto boolean;
    v_effective_end timestamptz;
begin
    select * into v_attempt from public.test_attempts attempt
    where attempt.id = p_attempt_id and attempt.user_id = p_user_id
    for update;
    if v_attempt.id is null then
        raise exception 'attempt not found';
    end if;
    if v_attempt.status in ('submitted','auto_submitted') then
        return public.get_test_attempt_result_for_user(p_attempt_id, p_user_id);
    end if;
    if v_attempt.status <> 'in_progress' then
        raise exception 'attempt cannot be submitted';
    end if;
    v_auto := coalesce(p_auto_submit, false)
        or (v_attempt.deadline_at is not null and v_attempt.deadline_at <= v_now)
        or exists (
            select 1 from public.test_attempt_section_states state
            where state.attempt_id = p_attempt_id and state.status = 'open'
              and state.deadline_at is not null and state.deadline_at <= v_now
        );
    v_effective_end := v_now;
    if v_auto then
        select least(
            v_now,
            v_attempt.deadline_at,
            min(state.deadline_at) filter (
                where state.status = 'open'
                  and state.deadline_at is not null
                  and state.deadline_at <= v_now
            )
        )
        into v_effective_end
        from public.test_attempt_section_states state
        where state.attempt_id = p_attempt_id;
    end if;

    insert into public.test_attempt_responses (
        attempt_id, test_instance_question_id, selected_option,
        marked_for_review, saved_at
    )
    select p_attempt_id, mapping.id, null, false, v_now
    from public.test_instance_questions mapping
    where mapping.test_instance_id = v_attempt.test_instance_id
    on conflict (attempt_id, test_instance_question_id) do nothing;

    update public.test_attempt_responses response
    set is_correct = case when response.selected_option is null then null
                          else response.selected_option = strpos('ABCD', question.correct_option) - 1 end,
        awarded_marks = case
            when response.selected_option = strpos('ABCD', question.correct_option) - 1
            then mapping.marks_for_correct else 0 end,
        deducted_marks = case
            when response.selected_option is not null
             and response.selected_option <> strpos('ABCD', question.correct_option) - 1
            then mapping.negative_marks_for_wrong else 0 end,
        net_marks = case
            when response.selected_option = strpos('ABCD', question.correct_option) - 1
            then mapping.marks_for_correct
            when response.selected_option is not null
            then -mapping.negative_marks_for_wrong
            else 0 end,
        finalized_at = v_now
    from public.test_instance_questions mapping
    join public.questions question on question.id = mapping.question_id
    where response.attempt_id = p_attempt_id
      and mapping.id = response.test_instance_question_id;

    update public.test_attempt_section_states
    set status = case when deadline_at is not null and deadline_at <= v_now
                      then 'expired' else 'completed' end,
        completed_at = coalesce(completed_at, v_now), updated_at = v_now
    where attempt_id = p_attempt_id and status in ('open','locked');

    update public.test_attempts attempt
    set status = case when v_auto then 'auto_submitted' else 'submitted' end,
        submitted_at = v_now,
        duration_seconds = greatest(
            0,
            extract(epoch from (v_effective_end - started_at))::integer
        ),
        answered_count = aggregate.answered,
        correct_count = aggregate.correct,
        wrong_count = aggregate.wrong,
        skipped_count = aggregate.skipped,
        marked_for_review_count = aggregate.marked,
        positive_marks = aggregate.positive,
        negative_marks = aggregate.negative,
        net_marks = aggregate.net,
        updated_at = v_now
    from (
        select
            count(*) filter (where selected_option is not null)::integer as answered,
            count(*) filter (where is_correct is true)::integer as correct,
            count(*) filter (where is_correct is false)::integer as wrong,
            count(*) filter (where selected_option is null)::integer as skipped,
            count(*) filter (where marked_for_review)::integer as marked,
            coalesce(sum(awarded_marks), 0) as positive,
            coalesce(sum(deducted_marks), 0) as negative,
            coalesce(sum(test_attempt_responses.net_marks), 0) as net
        from public.test_attempt_responses where attempt_id = p_attempt_id
    ) aggregate
    where attempt.id = p_attempt_id;

    return public.get_test_attempt_result_for_user(p_attempt_id, p_user_id);
end;
$$;

create or replace function public.get_test_attempt_for_user(
    p_attempt_id uuid,
    p_user_id uuid
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_status text;
begin
    select attempt.status into v_status
    from public.test_attempts attempt
    where attempt.id = p_attempt_id and attempt.user_id = p_user_id;
    if v_status in ('submitted', 'auto_submitted') then
        return public.get_test_attempt_result_for_user(p_attempt_id, p_user_id);
    end if;
    if v_status = 'in_progress' then
        return public.get_test_attempt_progress_for_user(p_attempt_id, p_user_id);
    end if;
    return null;
end;
$$;

create or replace function public.auto_submit_due_test_attempts(p_limit integer default 100)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_attempt record;
    v_count integer := 0;
begin
    for v_attempt in
        select attempt.id, attempt.user_id
        from public.test_attempts attempt
        where attempt.status = 'in_progress'
          and (
              (attempt.deadline_at is not null and attempt.deadline_at <= now())
              or exists (
                  select 1 from public.test_attempt_section_states state
                  where state.attempt_id = attempt.id and state.status = 'open'
                    and state.deadline_at is not null and state.deadline_at <= now()
              )
          )
        order by attempt.deadline_at nulls last, attempt.id
        for update skip locked
        limit greatest(1, least(coalesce(p_limit, 100), 500))
    loop
        perform public.submit_test_attempt_atomic(v_attempt.id, v_attempt.user_id, true);
        v_count := v_count + 1;
    end loop;
    return jsonb_build_object('autoSubmitted', v_count);
end;
$$;

create or replace function public.validate_previous_year_test_mapping()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_test_type text;
begin
    select definition.test_type into v_test_type
    from public.test_instances instance
    join public.test_definitions definition on definition.id = instance.test_definition_id
    where instance.id = new.test_instance_id;

    if v_test_type = 'previous_year' then
        if new.mapping_source <> 'previous_year' then
            raise exception 'actual previous-year tests require previous_year mappings';
        end if;
        if not exists (
            select 1
            from public.previous_year_question_provenance provenance
            left join lateral (
                select correction.superseding_question_id
                from public.previous_year_question_corrections correction
                where correction.provenance_id = provenance.id
                  and correction.effective_at <= now()
                order by correction.effective_at desc, correction.id desc
                limit 1
            ) latest on true
            where provenance.review_status = 'verified'
              and provenance.official_answer_status <> 'withdrawn'
              and coalesce(latest.superseding_question_id, provenance.question_id)
                  = new.question_id
        ) then
            raise exception 'actual previous-year mapping lacks verified provenance';
        end if;
    elsif v_test_type = 'previous_year_style'
          and new.mapping_source = 'previous_year' then
        raise exception 'style content cannot be labelled as an actual PYQ';
    end if;
    return new;
end;
$$;

drop trigger if exists validate_previous_year_test_mapping_row
    on public.test_instance_questions;
create trigger validate_previous_year_test_mapping_row
before insert or update on public.test_instance_questions
for each row execute function public.validate_previous_year_test_mapping();

create or replace function public.get_previous_year_question_catalog(
    p_exam_key text default null,
    p_exam_year integer default null,
    p_language text default null,
    p_limit integer default 50,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with verified as (
    select
        provenance.*,
        exam.exam_key,
        stage.stage_key,
        paper.paper_key,
        section.section_key,
        coalesce(latest.superseding_question_id, provenance.question_id) as current_question_id,
        latest.effective_at as corrected_at
    from public.previous_year_question_provenance provenance
    join public.exams exam on exam.id = provenance.exam_id
    join public.exam_stages stage on stage.id = provenance.exam_stage_id
    join public.exam_papers paper on paper.id = provenance.exam_paper_id
    join public.exam_sections section on section.id = provenance.exam_section_id
    left join lateral (
        select correction.superseding_question_id, correction.effective_at
        from public.previous_year_question_corrections correction
        where correction.provenance_id = provenance.id
          and correction.effective_at <= now()
        order by correction.effective_at desc, correction.id desc
        limit 1
    ) latest on true
    where provenance.review_status = 'verified'
      and provenance.official_answer_status <> 'withdrawn'
      and (p_exam_key is null or exam.exam_key = p_exam_key)
      and (p_exam_year is null or provenance.exam_year = p_exam_year)
      and (p_language is null or provenance.language = p_language)
), page as (
    select * from verified
    order by exam_year desc, exam_key, shift_label, original_question_number
    limit greatest(1, least(coalesce(p_limit, 50), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from verified),
    'limit', greatest(1, least(coalesce(p_limit, 50), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'provenanceId', page.id,
        'questionId', page.current_question_id,
        'examKey', page.exam_key,
        'stageKey', page.stage_key,
        'paperKey', page.paper_key,
        'sectionKey', page.section_key,
        'year', page.exam_year,
        'shift', page.shift_label,
        'originalQuestionNumber', page.original_question_number,
        'language', page.language,
        'sourceUrl', page.source_url,
        'sourceTitle', page.source_title,
        'licenseCode', page.license_code,
        'licenseUrl', page.license_url,
        'answerStatus', page.official_answer_status,
        'correctedAt', page.corrected_at,
        'humanReviewed', true,
        'question', question.question_text,
        'options', jsonb_build_array(
            question.option_a, question.option_b,
            question.option_c, question.option_d
        )
    ) order by page.exam_year desc, page.exam_key,
               page.shift_label, page.original_question_number)
    from page join public.questions question on question.id = page.current_question_id),
    '[]'::jsonb)
);
$$;

alter table public.previous_year_question_provenance enable row level security;
alter table public.previous_year_question_corrections enable row level security;
alter table public.test_attempts enable row level security;
alter table public.test_attempt_section_states enable row level security;
alter table public.test_attempt_responses enable row level security;

revoke all on table public.previous_year_question_provenance
    from public, anon, authenticated;
revoke all on table public.previous_year_question_corrections
    from public, anon, authenticated;
revoke all on table public.test_attempts from public, anon, authenticated;
revoke all on table public.test_attempt_section_states
    from public, anon, authenticated;
revoke all on table public.test_attempt_responses
    from public, anon, authenticated;
revoke all on sequence public.previous_year_question_corrections_id_seq
    from public, anon, authenticated;

grant select, insert on table public.previous_year_question_provenance
    to service_role;
grant select, insert on table public.previous_year_question_corrections
    to service_role;
grant usage, select on sequence public.previous_year_question_corrections_id_seq
    to service_role;
grant select, insert, update on table public.test_attempts to service_role;
grant select, insert, update on table public.test_attempt_section_states
    to service_role;
grant select, insert, update on table public.test_attempt_responses
    to service_role;

create or replace function public.get_phase_e_previous_year_mock_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with required_functions(signature) as (values
    ('validate_previous_year_provenance()'),
    ('validate_previous_year_correction()'),
    ('apply_previous_year_correction()'),
    ('mirror_quiz_attempt_to_shared_test()'),
    ('mirror_quiz_answer_to_shared_test()'),
    ('validate_previous_year_test_mapping()'),
    ('start_test_attempt_atomic(uuid,uuid,uuid)'),
    ('save_test_attempt_progress_atomic(uuid,uuid,jsonb)'),
    ('advance_test_attempt_section_atomic(uuid,uuid,uuid)'),
    ('submit_test_attempt_atomic(uuid,uuid,boolean)'),
    ('get_test_attempt_progress_for_user(uuid,uuid)'),
    ('get_test_attempt_result_for_user(uuid,uuid)'),
    ('get_test_attempt_for_user(uuid,uuid)'),
    ('auto_submit_due_test_attempts(integer)'),
    ('get_previous_year_question_catalog(text,integer,text,integer,integer)'),
    ('get_phase_e_previous_year_mock_contract()')
), function_permission_failures as (
    select role_name || ':' || signature as failure
    from required_functions
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
    union all
    select 'service_role:' || signature from required_functions
    where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
), required_tables(name) as (values
    ('previous_year_question_provenance'),
    ('previous_year_question_corrections'),
    ('test_attempts'),
    ('test_attempt_section_states'),
    ('test_attempt_responses')
), table_permission_failures as (
    select role_name || ':' || name as failure
    from required_tables
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_table_privilege(role_name, 'public.' || name, 'SELECT')
       or has_table_privilege(role_name, 'public.' || name, 'INSERT')
       or has_table_privilege(role_name, 'public.' || name, 'UPDATE')
       or has_table_privilege(role_name, 'public.' || name, 'DELETE')
), legacy_gaps as (
    select
        (select count(*) from public.quiz_attempts legacy
         where not exists (
             select 1 from public.test_attempts attempt
             where attempt.legacy_quiz_attempt_id = legacy.id
         )) as attempts,
        (select count(*) from public.quiz_attempt_answers legacy
         where not exists (
             select 1 from public.test_attempt_responses response
             where response.legacy_quiz_answer_id = legacy.id
         )) as answers
)
select jsonb_build_object(
    'phase_e_previous_year_mock_migration_version', '20260808133000',
    'ready',
        to_regclass('public.previous_year_question_provenance') is not null
        and to_regclass('public.previous_year_question_corrections') is not null
        and to_regclass('public.test_attempts') is not null
        and to_regprocedure('public.submit_test_attempt_atomic(uuid,uuid,boolean)') is not null
        and (select attempts = 0 and answers = 0 from legacy_gaps)
        and not exists (select 1 from function_permission_failures)
        and not exists (select 1 from table_permission_failures),
    'real_pyq_provenance', true,
    'correction_audit', true,
    'generated_style_separation', exists (
        select 1 from public.test_definitions
        where test_type = 'previous_year_style'
    ),
    'timed_sections', true,
    'section_transitions', true,
    'mark_for_review', true,
    'idempotent_attempts', true,
    'section_specific_marking', true,
    'auto_submit', true,
    'rank_cohort', true,
    'topic_and_knowledge_analysis', true,
    'legacy_attempts_mirrored', (select attempts = 0 and answers = 0 from legacy_gaps),
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

revoke execute on function public.validate_previous_year_provenance()
    from public, anon, authenticated;
revoke execute on function public.validate_previous_year_correction()
    from public, anon, authenticated;
revoke execute on function public.apply_previous_year_correction()
    from public, anon, authenticated;
revoke execute on function public.mirror_quiz_attempt_to_shared_test()
    from public, anon, authenticated;
revoke execute on function public.mirror_quiz_answer_to_shared_test()
    from public, anon, authenticated;
revoke execute on function public.get_test_attempt_progress_for_user(uuid,uuid)
    from public, anon, authenticated;
revoke execute on function public.start_test_attempt_atomic(uuid,uuid,uuid)
    from public, anon, authenticated;
revoke execute on function public.save_test_attempt_progress_atomic(uuid,uuid,jsonb)
    from public, anon, authenticated;
revoke execute on function public.advance_test_attempt_section_atomic(uuid,uuid,uuid)
    from public, anon, authenticated;
revoke execute on function public.get_test_attempt_result_for_user(uuid,uuid)
    from public, anon, authenticated;
revoke execute on function public.get_test_attempt_for_user(uuid,uuid)
    from public, anon, authenticated;
revoke execute on function public.submit_test_attempt_atomic(uuid,uuid,boolean)
    from public, anon, authenticated;
revoke execute on function public.auto_submit_due_test_attempts(integer)
    from public, anon, authenticated;
revoke execute on function public.validate_previous_year_test_mapping()
    from public, anon, authenticated;
revoke execute on function public.get_previous_year_question_catalog(
    text,integer,text,integer,integer
) from public, anon, authenticated;
revoke execute on function public.get_phase_e_previous_year_mock_contract()
    from public, anon, authenticated;

grant execute on function public.validate_previous_year_provenance() to service_role;
grant execute on function public.validate_previous_year_correction() to service_role;
grant execute on function public.apply_previous_year_correction() to service_role;
grant execute on function public.mirror_quiz_attempt_to_shared_test() to service_role;
grant execute on function public.mirror_quiz_answer_to_shared_test() to service_role;
grant execute on function public.get_test_attempt_progress_for_user(uuid,uuid)
    to service_role;
grant execute on function public.start_test_attempt_atomic(uuid,uuid,uuid)
    to service_role;
grant execute on function public.save_test_attempt_progress_atomic(uuid,uuid,jsonb)
    to service_role;
grant execute on function public.advance_test_attempt_section_atomic(uuid,uuid,uuid)
    to service_role;
grant execute on function public.get_test_attempt_result_for_user(uuid,uuid)
    to service_role;
grant execute on function public.get_test_attempt_for_user(uuid,uuid)
    to service_role;
grant execute on function public.submit_test_attempt_atomic(uuid,uuid,boolean)
    to service_role;
grant execute on function public.auto_submit_due_test_attempts(integer)
    to service_role;
grant execute on function public.validate_previous_year_test_mapping()
    to service_role;
grant execute on function public.get_previous_year_question_catalog(
    text,integer,text,integer,integer
) to service_role;
grant execute on function public.get_phase_e_previous_year_mock_contract()
    to service_role;
