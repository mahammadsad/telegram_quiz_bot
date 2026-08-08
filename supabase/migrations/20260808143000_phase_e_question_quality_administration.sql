-- Phase E4: abuse-resistant reports, authoritative quarantine, and a minimal
-- append-only question moderation workflow. Existing report reasons and APIs
-- remain valid; attempted question content remains immutable.

alter table public.question_reports
    drop constraint if exists question_reports_reason_check;
alter table public.question_reports add constraint question_reports_reason_check
    check (reason in (
        'wrong_answer','multiple_correct','ambiguous','incorrect_explanation',
        'language_spelling','outdated','outside_syllabus','broken_source',
        'duplicate_question','translation_error','other'
    ));

alter table public.question_reports add column if not exists credibility_status text
    not null default 'credible';
alter table public.question_reports add column if not exists abuse_signals jsonb
    not null default '[]'::jsonb;
alter table public.question_reports add column if not exists credibility_evaluated_at timestamptz;
alter table public.question_reports add column if not exists threshold_applied integer;
alter table public.question_reports
    drop constraint if exists question_reports_credibility_status_check;
alter table public.question_reports add constraint question_reports_credibility_status_check
    check (credibility_status in (
        'credible','discounted_risk','discounted_cluster','discounted_burst'
    ));
alter table public.question_reports
    drop constraint if exists question_reports_abuse_signals_check;
alter table public.question_reports add constraint question_reports_abuse_signals_check
    check (jsonb_typeof(abuse_signals) = 'array');
alter table public.question_reports
    drop constraint if exists question_reports_threshold_applied_check;
alter table public.question_reports add constraint question_reports_threshold_applied_check
    check (threshold_applied is null or threshold_applied between 2 and 10);

create index if not exists idx_question_reports_credible_moderation
    on public.question_reports (question_id, created_at desc, user_id)
    where credibility_status = 'credible'
      and status in ('open','under_review');

create table if not exists public.question_reporter_risk_profiles (
    user_id uuid primary key references public.users(id) on delete cascade,
    risk_state text not null default 'normal'
        check (risk_state in ('normal','suspicious','blocked')),
    abuse_cluster_key text,
    reason text,
    reviewed_by text,
    reviewed_at timestamptz,
    updated_at timestamptz not null default now(),
    check (abuse_cluster_key is null or abuse_cluster_key ~ '^[a-f0-9]{32,128}$'),
    check (reason is null or length(reason) <= 1000)
);

create index if not exists idx_question_reporter_risk_cluster
    on public.question_reporter_risk_profiles (abuse_cluster_key)
    where abuse_cluster_key is not null;

create table if not exists public.question_moderation_policies (
    singleton boolean primary key default true check (singleton),
    independent_report_threshold integer not null default 3
        check (independent_report_threshold between 2 and 10),
    burst_window interval not null default interval '10 minutes'
        check (burst_window between interval '1 minute' and interval '1 day'),
    credible_reports_per_burst integer not null default 2
        check (credible_reports_per_burst between 1 and 10),
    score_effect_policy text not null default 'preserve_historical'
        check (score_effect_policy in ('preserve_historical','recalculate_affected')),
    updated_at timestamptz not null default now(),
    updated_by text not null default 'migration'
);

insert into public.question_moderation_policies(singleton)
values (true) on conflict (singleton) do nothing;

create table if not exists public.question_moderation_cases (
    id uuid primary key default extensions.gen_random_uuid(),
    question_id uuid not null unique references public.questions(id) on delete restrict,
    status text not null default 'open' check (status in (
        'open','under_review','quarantined','resolved','dismissed',
        'superseded','reinstated'
    )),
    trigger_source text not null default 'learner_reports' check (trigger_source in (
        'learner_reports','deterministic_contradiction','authoritative_correction'
    )),
    credible_report_count integer not null default 0 check (credible_report_count >= 0),
    total_report_count integer not null default 0 check (total_report_count >= 0),
    threshold_applied integer check (threshold_applied between 2 and 10),
    quarantine_reason text,
    resolution text,
    superseding_question_id uuid references public.questions(id) on delete restrict,
    score_effect_policy text not null default 'preserve_historical'
        check (score_effect_policy in ('preserve_historical','recalculate_affected')),
    opened_at timestamptz not null default now(),
    quarantined_at timestamptz,
    reviewed_at timestamptz,
    reviewed_by text,
    closed_at timestamptz,
    updated_at timestamptz not null default now(),
    check (quarantine_reason is null or length(quarantine_reason) <= 2000),
    check (resolution is null or length(resolution) <= 2000),
    check (superseding_question_id is null or superseding_question_id <> question_id)
);

create index if not exists idx_question_moderation_queue
    on public.question_moderation_cases (status, updated_at desc, id);
create index if not exists idx_question_moderation_superseding
    on public.question_moderation_cases (superseding_question_id)
    where superseding_question_id is not null;

create table if not exists public.question_moderation_events (
    id bigint generated always as identity primary key,
    case_id uuid not null references public.question_moderation_cases(id) on delete restrict,
    question_id uuid not null references public.questions(id) on delete restrict,
    report_id uuid references public.question_reports(id) on delete restrict,
    event_type text not null check (event_type in (
        'report_received','case_reopened','threshold_quarantine',
        'authoritative_quarantine','review_started','resolved',
        'dismissed','superseded','reinstated','risk_adjusted'
    )),
    actor_type text not null check (actor_type in ('system','administrator')),
    actor_key text not null,
    reason text,
    resolution text,
    superseding_question_id uuid references public.questions(id) on delete restrict,
    score_effect_policy text not null default 'preserve_historical'
        check (score_effect_policy in ('preserve_historical','recalculate_affected')),
    metadata jsonb not null default '{}'::jsonb check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    check (reason is null or length(reason) <= 2000),
    check (resolution is null or length(resolution) <= 2000)
);

create index if not exists idx_question_moderation_events_case
    on public.question_moderation_events (case_id, created_at, id);
create index if not exists idx_question_moderation_events_question
    on public.question_moderation_events (question_id, created_at desc, id desc);
create index if not exists idx_question_moderation_events_report
    on public.question_moderation_events (report_id)
    where report_id is not null;

create or replace function public.protect_question_moderation_events_append_only()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    raise exception 'question moderation events are append-only';
end;
$$;

drop trigger if exists protect_question_moderation_events_append_only
    on public.question_moderation_events;
create trigger protect_question_moderation_events_append_only
before update or delete on public.question_moderation_events
for each row execute function public.protect_question_moderation_events_append_only();

create or replace function public.process_question_report_moderation(
    p_report_id uuid,
    p_threshold integer
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_report public.question_reports%rowtype;
    v_policy public.question_moderation_policies%rowtype;
    v_profile public.question_reporter_risk_profiles%rowtype;
    v_credibility text := 'credible';
    v_signals jsonb := '[]'::jsonb;
    v_cluster_key text;
    v_burst_count integer;
    v_credible_count integer;
    v_total_count integer;
    v_threshold integer := greatest(2, least(10, coalesce(p_threshold, 3)));
    v_case_id uuid;
    v_old_case_status text;
    v_question_status text;
begin
    select * into strict v_report
    from public.question_reports where id = p_report_id for update;
    select * into strict v_policy
    from public.question_moderation_policies where singleton;
    select * into v_profile
    from public.question_reporter_risk_profiles where user_id = v_report.user_id;

    if found and v_profile.risk_state <> 'normal' then
        v_credibility := 'discounted_risk';
        v_signals := jsonb_build_array('reporter_' || v_profile.risk_state);
    else
        v_cluster_key := coalesce(v_profile.abuse_cluster_key, v_report.user_id::text);
        if exists (
            select 1
            from public.question_reports prior
            left join public.question_reporter_risk_profiles risk
              on risk.user_id = prior.user_id
            where prior.question_id = v_report.question_id
              and prior.id <> v_report.id
              and prior.credibility_status = 'credible'
              and prior.status in ('open','under_review')
              and coalesce(risk.abuse_cluster_key, prior.user_id::text) = v_cluster_key
        ) then
            v_credibility := 'discounted_cluster';
            v_signals := jsonb_build_array('shared_abuse_cluster');
        else
            select count(*)::integer into v_burst_count
            from public.question_reports prior
            where prior.question_id = v_report.question_id
              and prior.id <> v_report.id
              and prior.credibility_status = 'credible'
              and prior.status in ('open','under_review')
              and prior.created_at >= v_report.created_at - v_policy.burst_window;
            if v_burst_count >= v_policy.credible_reports_per_burst then
                v_credibility := 'discounted_burst';
                v_signals := jsonb_build_array('question_report_burst');
            end if;
        end if;
    end if;

    update public.question_reports
    set credibility_status = v_credibility,
        abuse_signals = v_signals,
        credibility_evaluated_at = now(),
        threshold_applied = v_threshold
    where id = v_report.id;

    select count(distinct report.user_id)::integer,
           count(*)::integer
    into v_credible_count, v_total_count
    from public.question_reports report
    where report.question_id = v_report.question_id
      and report.status in ('open','under_review')
      and (report.credibility_status = 'credible' or report.id = v_report.id)
      and (report.credibility_status = 'credible' or v_credibility = 'credible');

    select status into v_old_case_status
    from public.question_moderation_cases
    where question_id = v_report.question_id for update;

    insert into public.question_moderation_cases (
        question_id, status, trigger_source, credible_report_count,
        total_report_count, threshold_applied, score_effect_policy
    ) values (
        v_report.question_id, 'open', 'learner_reports', v_credible_count,
        (select count(*) from public.question_reports where question_id = v_report.question_id),
        v_threshold, v_policy.score_effect_policy
    )
    on conflict (question_id) do update set
        status = case
            when public.question_moderation_cases.status in (
                'resolved','dismissed','reinstated'
            ) then 'open'
            else public.question_moderation_cases.status
        end,
        trigger_source = case
            when public.question_moderation_cases.status in (
                'resolved','dismissed','reinstated'
            ) then 'learner_reports'
            else public.question_moderation_cases.trigger_source
        end,
        credible_report_count = excluded.credible_report_count,
        total_report_count = excluded.total_report_count,
        threshold_applied = excluded.threshold_applied,
        closed_at = case
            when public.question_moderation_cases.status in (
                'resolved','dismissed','reinstated'
            ) then null
            else public.question_moderation_cases.closed_at
        end,
        updated_at = now()
    returning id into v_case_id;

    if v_old_case_status in ('resolved','dismissed','reinstated') then
        insert into public.question_moderation_events (
            case_id, question_id, event_type, actor_type, actor_key, metadata
        ) values (
            v_case_id, v_report.question_id, 'case_reopened', 'system',
            'report-policy', jsonb_build_object('previousStatus', v_old_case_status)
        );
    end if;

    insert into public.question_moderation_events (
        case_id, question_id, report_id, event_type, actor_type, actor_key, metadata
    ) values (
        v_case_id, v_report.question_id, v_report.id, 'report_received',
        'system', 'report-policy',
        jsonb_build_object(
            'reason', v_report.reason,
            'credibilityStatus', v_credibility,
            'credibleReportCount', v_credible_count,
            'threshold', v_threshold,
            'abuseSignals', v_signals
        )
    );

    if v_credible_count >= v_threshold then
        update public.question_reports set status = 'under_review'
        where question_id = v_report.question_id and status = 'open';
        update public.questions set status = 'quarantined', review_required = true
        where id = v_report.question_id and status not in ('rejected','archived');
        update public.question_moderation_cases
        set status = 'quarantined', quarantined_at = coalesce(quarantined_at, now()),
            quarantine_reason = coalesce(
                quarantine_reason,
                'Independent credible report threshold reached'
            ),
            updated_at = now()
        where id = v_case_id and status <> 'quarantined';
        if found then
            insert into public.question_moderation_events (
                case_id, question_id, event_type, actor_type, actor_key,
                reason, score_effect_policy, metadata
            ) values (
                v_case_id, v_report.question_id, 'threshold_quarantine',
                'system', 'report-policy',
                'Independent credible report threshold reached',
                v_policy.score_effect_policy,
                jsonb_build_object(
                    'credibleReportCount', v_credible_count,
                    'threshold', v_threshold
                )
            );
        end if;
    elsif v_credible_count > 0 then
        update public.questions set status = 'reported'
        where id = v_report.question_id and status = 'active';
    end if;

    select status into v_question_status
    from public.questions where id = v_report.question_id;
    return jsonb_build_object(
        'reportId', v_report.id,
        'caseId', v_case_id,
        'status', 'accepted',
        'credibilityStatus', v_credibility,
        'credibleReportCount', v_credible_count,
        'questionStatus', v_question_status,
        'quarantined', v_question_status = 'quarantined'
    );
end;
$$;

create or replace function public.submit_question_report(
    p_question_id uuid,
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid,
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
begin
    if p_reason not in (
        'wrong_answer','multiple_correct','ambiguous','incorrect_explanation',
        'language_spelling','outdated','outside_syllabus','broken_source',
        'duplicate_question','translation_error','other'
    ) then raise exception 'invalid report reason'; end if;
    if length(coalesce(p_details, '')) > 1000 then
        raise exception 'report details are too long';
    end if;
    if p_reason = 'other' and nullif(btrim(p_details), '') is null then
        raise exception 'other reports require details';
    end if;
    if p_client_attempt_id is null then
        raise exception 'a completed UUID attempt identifier is required';
    end if;
    perform pg_advisory_xact_lock(hashtextextended('report-rate:' || p_user_id::text, 0));
    if (select count(*) from public.question_reports
        where user_id = p_user_id and created_at >= now() - interval '1 hour') >= 5
    then raise exception 'report rate limit exceeded'; end if;
    select attempt.id into v_attempt_id
    from public.quiz_attempts attempt
    join public.quiz_attempt_answers answer on answer.attempt_id = attempt.id
    where attempt.quiz_id = p_quiz_id and attempt.user_id = p_user_id
      and attempt.client_attempt_uuid = p_client_attempt_id
      and attempt.is_completed and answer.question_id = p_question_id
    limit 1;
    if not found then
        raise exception 'question report is not linked to this completed attempt';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(p_question_id::text, 0));
    insert into public.question_reports(
        question_id, quiz_id, user_id, attempt_id, reason, details
    ) values (
        p_question_id, p_quiz_id, p_user_id, v_attempt_id, p_reason,
        nullif(btrim(p_details), '')
    ) returning id into v_report_id;
    return public.process_question_report_moderation(v_report_id, p_threshold);
exception when unique_violation then
    raise exception 'this question was already reported for this attempt';
end;
$$;

create or replace function public.submit_practice_question_report(
    p_question_id uuid,
    p_user_id uuid,
    p_client_attempt_id uuid,
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
    v_practice_attempt_id uuid;
    v_report_id uuid;
begin
    if p_reason not in (
        'wrong_answer','multiple_correct','ambiguous','incorrect_explanation',
        'language_spelling','outdated','outside_syllabus','broken_source',
        'duplicate_question','translation_error','other'
    ) then raise exception 'invalid report reason'; end if;
    if length(coalesce(p_details, '')) > 1000 then
        raise exception 'report details are too long';
    end if;
    if p_reason = 'other' and nullif(btrim(p_details), '') is null then
        raise exception 'other reports require details';
    end if;
    if p_client_attempt_id is null then
        raise exception 'a completed UUID revision attempt identifier is required';
    end if;
    perform pg_advisory_xact_lock(hashtextextended('report-rate:' || p_user_id::text, 0));
    if (select count(*) from public.question_reports
        where user_id = p_user_id and created_at >= now() - interval '1 hour') >= 5
    then raise exception 'report rate limit exceeded'; end if;
    select answer.id into v_practice_attempt_id
    from public.personal_practice_answers answer
    where answer.user_id = p_user_id and answer.question_id = p_question_id
      and answer.client_attempt_id = p_client_attempt_id
      and answer.mode = 'revision'
    limit 1;
    if not found then
        raise exception 'question report is not linked to this completed revision attempt';
    end if;
    perform pg_advisory_xact_lock(hashtextextended(p_question_id::text, 0));
    insert into public.question_reports(
        question_id, quiz_id, user_id, attempt_id, practice_attempt_id,
        reason, details
    ) values (
        p_question_id, null, p_user_id, null, v_practice_attempt_id,
        p_reason, nullif(btrim(p_details), '')
    ) returning id into v_report_id;
    return public.process_question_report_moderation(v_report_id, p_threshold);
exception when unique_violation then
    raise exception 'this question was already reported for this revision attempt';
end;
$$;

create or replace function public.quarantine_question_authoritatively(
    p_question_id uuid,
    p_trigger text,
    p_actor text,
    p_reason text,
    p_superseding_question_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case_id uuid;
    v_policy text;
    v_replacement public.questions%rowtype;
begin
    if p_trigger not in ('deterministic_contradiction','authoritative_correction') then
        raise exception 'invalid authoritative quarantine trigger';
    end if;
    if nullif(btrim(p_actor), '') is null or nullif(btrim(p_reason), '') is null then
        raise exception 'actor and reason are required';
    end if;
    if length(p_reason) > 2000 then raise exception 'quarantine reason is too long'; end if;
    perform 1 from public.questions where id = p_question_id for update;
    if not found then raise exception 'question not found'; end if;
    if p_trigger = 'authoritative_correction' then
        if p_superseding_question_id is null then
            raise exception 'authoritative correction requires a superseding question';
        end if;
        select * into v_replacement from public.questions
        where id = p_superseding_question_id;
        if not found or v_replacement.supersedes_question_id is distinct from p_question_id then
            raise exception 'correction must use an explicit superseding question version';
        end if;
    elsif p_superseding_question_id is not null then
        raise exception 'deterministic contradiction does not accept a replacement';
    end if;
    select score_effect_policy into v_policy
    from public.question_moderation_policies where singleton;
    insert into public.question_moderation_cases(
        question_id, status, trigger_source, quarantine_reason,
        superseding_question_id, score_effect_policy, quarantined_at
    ) values (
        p_question_id, 'quarantined', p_trigger, btrim(p_reason),
        p_superseding_question_id, v_policy, now()
    ) on conflict (question_id) do update set
        status = 'quarantined', trigger_source = excluded.trigger_source,
        quarantine_reason = excluded.quarantine_reason,
        superseding_question_id = excluded.superseding_question_id,
        score_effect_policy = excluded.score_effect_policy,
        quarantined_at = now(), closed_at = null, updated_at = now()
    returning id into v_case_id;
    update public.questions set status = 'quarantined', review_required = true
    where id = p_question_id and status not in ('rejected','archived');
    update public.question_reports set status = 'under_review'
    where question_id = p_question_id and status = 'open';
    insert into public.question_moderation_events(
        case_id, question_id, event_type, actor_type, actor_key, reason,
        superseding_question_id, score_effect_policy,
        metadata
    ) values (
        v_case_id, p_question_id, 'authoritative_quarantine', 'administrator',
        btrim(p_actor), btrim(p_reason), p_superseding_question_id, v_policy,
        jsonb_build_object('trigger', p_trigger)
    );
    return jsonb_build_object(
        'caseId', v_case_id, 'questionId', p_question_id,
        'status', 'quarantined', 'trigger', p_trigger,
        'scoreEffectPolicy', v_policy
    );
end;
$$;

create or replace function public.review_question_moderation_case(
    p_case_id uuid,
    p_decision text,
    p_actor text,
    p_resolution text,
    p_superseding_question_id uuid default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_case public.question_moderation_cases%rowtype;
    v_replacement public.questions%rowtype;
    v_event text;
    v_status text;
begin
    if p_decision not in (
        'start_review','resolve_confirmed','dismiss','supersede','reinstate'
    ) then raise exception 'invalid question review decision'; end if;
    if nullif(btrim(p_actor), '') is null or nullif(btrim(p_resolution), '') is null then
        raise exception 'actor and resolution are required';
    end if;
    if length(p_resolution) > 2000 then raise exception 'review resolution is too long'; end if;
    select * into strict v_case from public.question_moderation_cases
    where id = p_case_id for update;
    if p_decision = 'supersede' then
        if p_superseding_question_id is null then
            raise exception 'superseding question is required';
        end if;
        select * into v_replacement from public.questions
        where id = p_superseding_question_id;
        if not found or v_replacement.supersedes_question_id is distinct from v_case.question_id then
            raise exception 'replacement must explicitly supersede the reviewed question';
        end if;
    elsif p_superseding_question_id is not null then
        raise exception 'superseding question is only valid for supersede';
    end if;

    if p_decision = 'start_review' then
        v_status := 'under_review'; v_event := 'review_started';
        update public.questions set status = 'under_review', review_required = true
        where id = v_case.question_id and status not in ('rejected','archived');
    elsif p_decision = 'resolve_confirmed' then
        v_status := 'resolved'; v_event := 'resolved';
        update public.questions set status = 'quarantined', review_required = true
        where id = v_case.question_id and status not in ('rejected','archived');
        update public.question_reports set status = 'resolved', reviewed_at = now(),
            resolution = btrim(p_resolution)
        where question_id = v_case.question_id and status in ('open','under_review');
    elsif p_decision = 'dismiss' then
        v_status := 'dismissed'; v_event := 'dismissed';
        update public.questions set status = 'active', review_required = false
        where id = v_case.question_id and status in ('reported','under_review','quarantined');
        update public.question_reports set status = 'dismissed', reviewed_at = now(),
            resolution = btrim(p_resolution)
        where question_id = v_case.question_id and status in ('open','under_review');
    elsif p_decision = 'supersede' then
        v_status := 'superseded'; v_event := 'superseded';
        update public.questions set status = 'archived', review_required = true
        where id = v_case.question_id;
        update public.questions set status = 'active', review_required = false
        where id = p_superseding_question_id and status not in ('rejected','archived');
        update public.question_reports set status = 'resolved', reviewed_at = now(),
            resolution = btrim(p_resolution)
        where question_id = v_case.question_id and status in ('open','under_review');
    else
        if v_case.status = 'superseded' then
            raise exception 'a superseded question cannot be reinstated';
        end if;
        v_status := 'reinstated'; v_event := 'reinstated';
        update public.questions set status = 'active', review_required = false
        where id = v_case.question_id and status in ('reported','under_review','quarantined');
        update public.question_reports set status = 'resolved', reviewed_at = now(),
            resolution = btrim(p_resolution)
        where question_id = v_case.question_id and status in ('open','under_review');
    end if;

    update public.question_moderation_cases set
        status = v_status,
        resolution = btrim(p_resolution),
        superseding_question_id = p_superseding_question_id,
        reviewed_at = now(), reviewed_by = btrim(p_actor),
        closed_at = case when v_status = 'under_review' then null else now() end,
        updated_at = now()
    where id = p_case_id;
    insert into public.question_moderation_events(
        case_id, question_id, event_type, actor_type, actor_key,
        resolution, superseding_question_id, score_effect_policy,
        metadata
    ) values (
        p_case_id, v_case.question_id, v_event, 'administrator', btrim(p_actor),
        btrim(p_resolution), p_superseding_question_id, v_case.score_effect_policy,
        jsonb_build_object('decision', p_decision)
    );
    return jsonb_build_object(
        'caseId', p_case_id, 'questionId', v_case.question_id,
        'status', v_status, 'decision', p_decision,
        'supersedingQuestionId', p_superseding_question_id,
        'scoreEffectPolicy', v_case.score_effect_policy
    );
end;
$$;

create or replace function public.get_question_moderation_queue(
    p_status text default null,
    p_limit integer default 50,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
with filtered as (
    select moderation.*, question.question_text, question.option_a,
           question.option_b, question.option_c, question.option_d,
           question.correct_option, question.explanation, question.subject,
           question.topic, question.content_version, question.status as question_status,
           question.verification_status, question.source_url
    from public.question_moderation_cases moderation
    join public.questions question on question.id = moderation.question_id
    where p_status is null or moderation.status = p_status
), page as (
    select * from filtered
    order by case when status in ('quarantined','under_review') then 0 else 1 end,
             updated_at desc, id
    limit greatest(1, least(coalesce(p_limit, 50), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'items', coalesce(jsonb_agg(jsonb_build_object(
        'caseId', page.id,
        'questionId', page.question_id,
        'caseStatus', page.status,
        'questionStatus', page.question_status,
        'triggerSource', page.trigger_source,
        'credibleReportCount', page.credible_report_count,
        'totalReportCount', page.total_report_count,
        'thresholdApplied', page.threshold_applied,
        'quarantineReason', page.quarantine_reason,
        'resolution', page.resolution,
        'supersedingQuestionId', page.superseding_question_id,
        'scoreEffectPolicy', page.score_effect_policy,
        'question', jsonb_build_object(
            'text', page.question_text,
            'options', jsonb_build_array(
                page.option_a, page.option_b, page.option_c, page.option_d
            ),
            'correctOption', page.correct_option,
            'explanation', page.explanation,
            'subject', page.subject,
            'topic', page.topic,
            'contentVersion', page.content_version,
            'verificationStatus', page.verification_status,
            'sourceUrl', page.source_url
        ),
        'reports', coalesce((
            select jsonb_agg(jsonb_build_object(
                'reportId', report.id,
                'reason', report.reason,
                'details', report.details,
                'status', report.status,
                'credibilityStatus', report.credibility_status,
                'abuseSignals', report.abuse_signals,
                'createdAt', report.created_at
            ) order by report.created_at, report.id)
            from public.question_reports report
            where report.question_id = page.question_id
        ), '[]'::jsonb),
        'history', coalesce((
            select jsonb_agg(jsonb_build_object(
                'eventId', event.id,
                'type', event.event_type,
                'actorType', event.actor_type,
                'actorKey', event.actor_key,
                'reason', event.reason,
                'resolution', event.resolution,
                'supersedingQuestionId', event.superseding_question_id,
                'scoreEffectPolicy', event.score_effect_policy,
                'metadata', event.metadata,
                'createdAt', event.created_at
            ) order by event.created_at, event.id)
            from public.question_moderation_events event
            where event.case_id = page.id
        ), '[]'::jsonb)
    ) order by case when page.status in ('quarantined','under_review') then 0 else 1 end,
               page.updated_at desc, page.id), '[]'::jsonb),
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 50), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'answerVisibility', 'administrator_only'
)
from page;
$$;

-- Preserve existing moderation state and begin the audit trail without changing
-- historical question identifiers or learner scores.
insert into public.question_moderation_cases(
    question_id, status, trigger_source, credible_report_count,
    total_report_count, threshold_applied, quarantine_reason
)
select question.id,
       case when question.status = 'quarantined' then 'quarantined'
            when question.status = 'under_review' then 'under_review'
            else 'open' end,
       'learner_reports',
       count(distinct report.user_id) filter (
           where report.status in ('open','under_review')
       )::integer,
       count(report.id)::integer,
       3,
       case when question.status = 'quarantined'
            then 'Backfilled existing report quarantine' end
from public.questions question
join public.question_reports report on report.question_id = question.id
where question.status in ('reported','under_review','quarantined')
group by question.id, question.status
on conflict (question_id) do nothing;

insert into public.question_moderation_events(
    case_id, question_id, event_type, actor_type, actor_key, reason, metadata
)
select moderation.id, moderation.question_id,
       case when moderation.status = 'quarantined'
            then 'threshold_quarantine' else 'report_received' end,
       'system', 'phase-e4-backfill',
       case when moderation.status = 'quarantined'
            then 'Backfilled existing report quarantine' end,
       jsonb_build_object('backfilled', true, 'reportCount', moderation.total_report_count)
from public.question_moderation_cases moderation
where not exists (
    select 1 from public.question_moderation_events event
    where event.case_id = moderation.id
);

alter table public.question_reporter_risk_profiles enable row level security;
alter table public.question_moderation_policies enable row level security;
alter table public.question_moderation_cases enable row level security;
alter table public.question_moderation_events enable row level security;

revoke all on table public.question_reporter_risk_profiles,
    public.question_moderation_policies, public.question_moderation_cases,
    public.question_moderation_events
    from public, anon, authenticated, service_role;
revoke all on sequence public.question_moderation_events_id_seq
    from public, anon, authenticated, service_role;
grant select on table public.question_reporter_risk_profiles,
    public.question_moderation_policies, public.question_moderation_cases,
    public.question_moderation_events to service_role;

create or replace function public.get_phase_e_question_quality_contract()
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
with required_functions(signature) as (values
    ('process_question_report_moderation(uuid,integer)'),
    ('submit_question_report(uuid,text,uuid,uuid,text,text,integer)'),
    ('submit_practice_question_report(uuid,uuid,uuid,text,text,integer)'),
    ('quarantine_question_authoritatively(uuid,text,text,text,uuid)'),
    ('review_question_moderation_case(uuid,text,text,text,uuid)'),
    ('get_question_moderation_queue(text,integer,integer)'),
    ('get_phase_e_question_quality_contract()')
), function_permission_failures as (
    select role_name || ':' || signature as failure
    from required_functions
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
    union all
    select 'service_role:' || signature from required_functions
    where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
), required_tables(name) as (values
    ('question_reporter_risk_profiles'),
    ('question_moderation_policies'),
    ('question_moderation_cases'),
    ('question_moderation_events')
), table_permission_failures as (
    select role_name || ':' || name as failure
    from required_tables
    cross join (values ('anon'), ('authenticated')) roles(role_name)
    where has_table_privilege(role_name, 'public.' || name, 'SELECT')
       or has_table_privilege(role_name, 'public.' || name, 'INSERT')
       or has_table_privilege(role_name, 'public.' || name, 'UPDATE')
       or has_table_privilege(role_name, 'public.' || name, 'DELETE')
), reason_contract as (
    select pg_get_constraintdef(constraint_row.oid) as definition
    from pg_catalog.pg_constraint constraint_row
    join pg_catalog.pg_class relation on relation.oid = constraint_row.conrelid
    join pg_catalog.pg_namespace namespace on namespace.oid = relation.relnamespace
    where namespace.nspname = 'public'
      and relation.relname = 'question_reports'
      and constraint_row.conname = 'question_reports_reason_check'
), immutable_contract as (
    select exists (
        select 1 from pg_catalog.pg_trigger trigger_row
        join pg_catalog.pg_class relation on relation.oid = trigger_row.tgrelid
        join pg_catalog.pg_namespace namespace on namespace.oid = relation.relnamespace
        where namespace.nspname = 'public' and relation.relname = 'questions'
          and trigger_row.tgname = 'protect_immutable_question_version'
          and not trigger_row.tgisinternal
    ) as ready
)
select jsonb_build_object(
    'phase_e_question_quality_migration_version', '20260808143000',
    'ready',
        to_regclass('public.question_moderation_cases') is not null
        and to_regclass('public.question_moderation_events') is not null
        and to_regprocedure('public.get_question_moderation_queue(text,integer,integer)') is not null
        and (select definition like '%duplicate_question%translation_error%' from reason_contract)
        and (select ready from immutable_contract)
        and not exists (select 1 from function_permission_failures)
        and not exists (select 1 from table_permission_failures),
    'legacy_report_reasons_retained', true,
    'new_report_reasons', true,
    'independent_report_threshold', true,
    'abuse_resistance', true,
    'authoritative_quarantine', true,
    'append_only_history', true,
    'explicit_supersession', true,
    'score_effect_policy', true,
    'protected_admin_queue', true,
    'silent_edit_protection', (select ready from immutable_contract),
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

revoke execute on function public.protect_question_moderation_events_append_only()
    from public, anon, authenticated;
revoke execute on function public.process_question_report_moderation(uuid,integer)
    from public, anon, authenticated;
revoke execute on function public.submit_question_report(uuid,text,uuid,uuid,text,text,integer)
    from public, anon, authenticated;
revoke execute on function public.submit_practice_question_report(uuid,uuid,uuid,text,text,integer)
    from public, anon, authenticated;
revoke execute on function public.quarantine_question_authoritatively(uuid,text,text,text,uuid)
    from public, anon, authenticated;
revoke execute on function public.review_question_moderation_case(uuid,text,text,text,uuid)
    from public, anon, authenticated;
revoke execute on function public.get_question_moderation_queue(text,integer,integer)
    from public, anon, authenticated;
revoke execute on function public.get_phase_e_question_quality_contract()
    from public, anon, authenticated;

grant execute on function public.protect_question_moderation_events_append_only()
    to service_role;
grant execute on function public.process_question_report_moderation(uuid,integer)
    to service_role;
grant execute on function public.submit_question_report(uuid,text,uuid,uuid,text,text,integer)
    to service_role;
grant execute on function public.submit_practice_question_report(uuid,uuid,uuid,text,text,integer)
    to service_role;
grant execute on function public.quarantine_question_authoritatively(uuid,text,text,text,uuid)
    to service_role;
grant execute on function public.review_question_moderation_case(uuid,text,text,text,uuid)
    to service_role;
grant execute on function public.get_question_moderation_queue(text,integer,integer)
    to service_role;
grant execute on function public.get_phase_e_question_quality_contract()
    to service_role;
