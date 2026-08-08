-- Phase C: durable replenishment jobs, verified inventory reads, and atomic
-- usage history. These are server-only Data API surfaces.

create unique index if not exists idx_content_usage_posted_once
    on public.content_usage_events (question_id, quiz_id, event_type)
    where quiz_id is not null and event_type = 'posted';

create or replace function public.record_content_usage_on_quiz_post()
returns trigger
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if new.status = 'posted' and old.status is distinct from new.status then
        insert into public.content_usage_events (
            question_id, knowledge_point_id, quiz_id, event_type,
            usage_scope, metadata, occurred_at
        )
        select
            question.id,
            question.knowledge_point_id,
            new.quiz_id,
            'posted',
            question.bot_type,
            jsonb_build_object(
                'chapter', question.topic,
                'topic_key', question.micro_topic_key,
                'micro_topic_id', question.micro_topic_id,
                'source_document_id', question.source_document_id,
                'variant_fingerprint', question.variant_fingerprint
            ),
            coalesce(new.posted_at, new.telegram_acknowledged_at, now())
        from public.quiz_questions mapping
        join public.questions question on question.id = mapping.question_id
        where mapping.quiz_id = new.quiz_id
        on conflict (question_id, quiz_id, event_type)
            where quiz_id is not null and event_type = 'posted'
            do nothing;
    end if;
    return new;
end;
$$;

drop trigger if exists record_content_usage_on_quiz_post on public.quiz_runs;
create trigger record_content_usage_on_quiz_post
after update of status on public.quiz_runs
for each row execute function public.record_content_usage_on_quiz_post();

create table if not exists public.content_replenishment_jobs (
    id uuid primary key default extensions.gen_random_uuid(),
    logical_date date not null,
    subject_key text not null
        references public.quiz_subjects(subject_key) on delete restrict,
    micro_topic_id uuid
        references public.quiz_micro_topics(id) on delete restrict,
    due_at timestamptz not null,
    status text not null default 'due'
        check (status in ('due','claimed','running','retry_wait','complete','quarantined','dead_letter')),
    target_candidate_count smallint not null default 15
        check (target_candidate_count between 12 and 15),
    generation_batch_size smallint not null default 5
        check (generation_batch_size between 3 and 5),
    accepted_count integer not null default 0 check (accepted_count >= 0),
    rejected_count integer not null default 0 check (rejected_count >= 0),
    retry_count integer not null default 0 check (retry_count >= 0),
    next_retry_at timestamptz,
    worker_id text,
    claimed_at timestamptz,
    lease_expires_at timestamptz,
    last_error_code text,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique nulls not distinct (logical_date, subject_key, micro_topic_id),
    check (
        (status in ('claimed','running') and worker_id is not null and lease_expires_at is not null)
        or status not in ('claimed','running')
    )
);

create index if not exists idx_content_replenishment_dispatch
    on public.content_replenishment_jobs (status, due_at, next_retry_at, lease_expires_at);
create index if not exists idx_content_replenishment_micro_topic
    on public.content_replenishment_jobs (micro_topic_id)
    where micro_topic_id is not null;

create table if not exists public.content_replenishment_job_events (
    id bigint generated always as identity primary key,
    job_id uuid not null
        references public.content_replenishment_jobs(id) on delete restrict,
    event_type text not null,
    from_status text,
    to_status text,
    worker_id text,
    accepted_count integer not null default 0 check (accepted_count >= 0),
    rejected_count integer not null default 0 check (rejected_count >= 0),
    rejection_codes text[] not null default '{}',
    error_code text,
    created_at timestamptz not null default now()
);

create index if not exists idx_content_replenishment_events_job
    on public.content_replenishment_job_events (job_id, created_at, id);

drop trigger if exists protect_content_replenishment_job_events_append_only
    on public.content_replenishment_job_events;
create trigger protect_content_replenishment_job_events_append_only
before update or delete on public.content_replenishment_job_events
for each row execute function public.reject_append_only_content_mutation();

create or replace function public.ensure_content_replenishment_job(
    p_logical_date date,
    p_subject_key text,
    p_micro_topic_id uuid,
    p_due_at timestamptz,
    p_target_candidate_count integer default 15,
    p_generation_batch_size integer default 5
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.content_replenishment_jobs%rowtype;
begin
    if p_logical_date is null or p_due_at is null
       or nullif(btrim(p_subject_key), '') is null
       or p_target_candidate_count not between 12 and 15
       or p_generation_batch_size not between 3 and 5 then
        raise exception 'valid replenishment job specification is required';
    end if;
    insert into public.content_replenishment_jobs (
        logical_date, subject_key, micro_topic_id, due_at,
        target_candidate_count, generation_batch_size
    ) values (
        p_logical_date, p_subject_key, p_micro_topic_id, p_due_at,
        p_target_candidate_count, p_generation_batch_size
    )
    on conflict (logical_date, subject_key, micro_topic_id) do update set
        due_at = least(public.content_replenishment_jobs.due_at, excluded.due_at),
        updated_at = now()
    returning * into v_job;
    if v_job.created_at = v_job.updated_at then
        insert into public.content_replenishment_job_events (
            job_id, event_type, to_status
        ) values (v_job.id, 'ensured', v_job.status);
    end if;
    return to_jsonb(v_job);
end;
$$;

create or replace function public.claim_content_replenishment_jobs(
    p_worker_id text,
    p_now timestamptz default now(),
    p_lease_minutes integer default 20,
    p_limit integer default 5
)
returns setof public.content_replenishment_jobs
language plpgsql
security invoker
set search_path = ''
as $$
begin
    if nullif(btrim(p_worker_id), '') is null or p_now is null then
        raise exception 'worker and current timestamp are required';
    end if;
    return query
    with candidates as (
        select job.id, job.status as prior_status
        from public.content_replenishment_jobs job
        where job.due_at <= p_now
          and (
              job.status = 'due'
              or (job.status = 'retry_wait' and coalesce(job.next_retry_at, job.due_at) <= p_now)
              or (job.status in ('claimed','running') and job.lease_expires_at <= p_now)
          )
        order by job.due_at, job.subject_key
        for update skip locked
        limit greatest(1, least(coalesce(p_limit, 5), 25))
    ), claimed as (
        update public.content_replenishment_jobs job
        set status = 'claimed', worker_id = p_worker_id, claimed_at = p_now,
            lease_expires_at = p_now + make_interval(
                mins => greatest(5, least(coalesce(p_lease_minutes, 20), 120))
            ),
            next_retry_at = null, updated_at = now()
        from candidates
        where job.id = candidates.id
        returning job.*, candidates.prior_status
    ), events as (
        insert into public.content_replenishment_job_events (
            job_id, event_type, from_status, to_status, worker_id
        )
        select id, 'claimed', prior_status, status, worker_id from claimed
        returning 1
    )
    select
        id, logical_date, subject_key, micro_topic_id, due_at, status,
        target_candidate_count, generation_batch_size, accepted_count,
        rejected_count, retry_count, next_retry_at, worker_id, claimed_at,
        lease_expires_at, last_error_code, created_at, updated_at
    from claimed order by due_at, subject_key;
end;
$$;

create or replace function public.complete_content_replenishment_batch(
    p_job_id uuid,
    p_worker_id text,
    p_accepted_count integer,
    p_rejected_count integer,
    p_rejection_codes text[] default '{}',
    p_error_code text default null,
    p_retry_at timestamptz default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_job public.content_replenishment_jobs%rowtype;
    v_prior text;
begin
    select * into v_job from public.content_replenishment_jobs
    where id = p_job_id for update;
    if not found or v_job.worker_id is distinct from p_worker_id
       or v_job.status not in ('claimed','running') then
        raise exception 'replenishment job is not owned by this worker';
    end if;
    if coalesce(p_accepted_count, -1) < 0 or coalesce(p_rejected_count, -1) < 0 then
        raise exception 'batch counts must be non-negative';
    end if;
    v_prior := v_job.status;
    update public.content_replenishment_jobs job set
        accepted_count = job.accepted_count + p_accepted_count,
        rejected_count = job.rejected_count + p_rejected_count,
        retry_count = job.retry_count + case when p_error_code is null then 0 else 1 end,
        status = case
            when p_error_code is not null then 'retry_wait'
            when job.accepted_count + p_accepted_count >= job.target_candidate_count then 'complete'
            else 'due'
        end,
        due_at = case when p_error_code is null then now() else job.due_at end,
        next_retry_at = case when p_error_code is not null
            then coalesce(p_retry_at, now() + interval '15 minutes') else null end,
        last_error_code = p_error_code,
        worker_id = null, claimed_at = null, lease_expires_at = null, updated_at = now()
    where job.id = p_job_id
    returning * into v_job;
    insert into public.content_replenishment_job_events (
        job_id, event_type, from_status, to_status, worker_id,
        accepted_count, rejected_count, rejection_codes, error_code
    ) values (
        v_job.id,
        case when p_error_code is null then 'batch_completed' else 'batch_failed' end,
        v_prior, v_job.status, p_worker_id, p_accepted_count, p_rejected_count,
        coalesce(p_rejection_codes, '{}'), p_error_code
    );
    return to_jsonb(v_job);
end;
$$;

create or replace function public.get_verified_question_inventory(
    p_subject_key text,
    p_now timestamptz default now(),
    p_limit integer default 300
)
returns setof jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select to_jsonb(question) || jsonb_build_object(
        'chapter', question.topic,
        'topic_key', question.micro_topic_key,
        'source_verification_status', source.verification_status,
        'source_review_required', source.review_required
    )
    from public.questions question
    join public.source_documents source on source.id = question.source_document_id
    where question.subject = p_subject_key
      and question.status = 'active'
      and question.verification_status = 'verified'
      and question.inventory_status in ('verified','used')
      and not question.review_required
      and question.knowledge_point_id is not null
      and question.variant_fingerprint is not null
      and (question.expires_at is null or question.expires_at >= p_now)
      and source.verification_status = 'verified'
      and not source.review_required
      and (source.expires_at is null or source.expires_at >= p_now)
      and exists (
          select 1
          from public.knowledge_point_evidence evidence
          join public.source_facts fact on fact.id = evidence.source_fact_id
          where evidence.knowledge_point_id = question.knowledge_point_id
            and evidence.support_type = 'supports'
            and fact.verification_status = 'verified'
            and not fact.review_required
            and (fact.expires_at is null or fact.expires_at >= p_now)
            and (fact.effective_until is null or fact.effective_until >= p_now)
      )
    order by question.eligible_at asc nulls first,
             question.usage_count, question.last_used_at asc nulls first,
             question.created_at, question.id
    limit greatest(10, least(coalesce(p_limit, 300), 1000));
$$;

create or replace function public.get_recent_content_usage(
    p_subject_key text,
    p_since timestamptz
)
returns setof jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select to_jsonb(event) || event.metadata || jsonb_build_object(
        'subject', question.subject,
        'knowledge_point_id', event.knowledge_point_id,
        'variant_fingerprint', question.variant_fingerprint
    )
    from public.content_usage_events event
    join public.questions question on question.id = event.question_id
    where question.subject = p_subject_key
      and event.event_type = 'posted'
      and event.occurred_at >= p_since
    order by event.occurred_at desc, event.id desc;
$$;

alter table public.content_replenishment_jobs enable row level security;
alter table public.content_replenishment_job_events enable row level security;
revoke all on table public.content_replenishment_jobs from public, anon, authenticated;
revoke all on table public.content_replenishment_job_events from public, anon, authenticated;
revoke all on sequence public.content_replenishment_job_events_id_seq from public, anon, authenticated;
grant select, insert, update on table public.content_replenishment_jobs to service_role;
grant select, insert on table public.content_replenishment_job_events to service_role;
grant usage, select on sequence public.content_replenishment_job_events_id_seq to service_role;

revoke all on function public.record_content_usage_on_quiz_post() from public, anon, authenticated;
revoke all on function public.ensure_content_replenishment_job(date,text,uuid,timestamptz,integer,integer) from public, anon, authenticated;
revoke all on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer) from public, anon, authenticated;
revoke all on function public.complete_content_replenishment_batch(uuid,text,integer,integer,text[],text,timestamptz) from public, anon, authenticated;
revoke all on function public.get_verified_question_inventory(text,timestamptz,integer) from public, anon, authenticated;
revoke all on function public.get_recent_content_usage(text,timestamptz) from public, anon, authenticated;
grant execute on function public.ensure_content_replenishment_job(date,text,uuid,timestamptz,integer,integer) to service_role;
grant execute on function public.claim_content_replenishment_jobs(text,timestamptz,integer,integer) to service_role;
grant execute on function public.complete_content_replenishment_batch(uuid,text,integer,integer,text[],text,timestamptz) to service_role;
grant execute on function public.get_verified_question_inventory(text,timestamptz,integer) to service_role;
grant execute on function public.get_recent_content_usage(text,timestamptz) to service_role;

create or replace function public.get_phase_c_inventory_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_functions(signature) as (values
        ('ensure_content_replenishment_job(date,text,uuid,timestamp with time zone,integer,integer)'),
        ('claim_content_replenishment_jobs(text,timestamp with time zone,integer,integer)'),
        ('complete_content_replenishment_batch(uuid,text,integer,integer,text[],text,timestamp with time zone)'),
        ('get_verified_question_inventory(text,timestamp with time zone,integer)'),
        ('get_recent_content_usage(text,timestamp with time zone)')
    ), permission_failures as (
        select role_name || ':' || signature as failure
        from required_functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
        union all
        select 'service_role:' || signature from required_functions
        where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
    )
    select jsonb_build_object(
        'ready',
            to_regclass('public.content_replenishment_jobs') is not null
            and to_regclass('public.content_replenishment_job_events') is not null
            and to_regclass('public.content_usage_events') is not null
            and not exists (select 1 from permission_failures),
        'inventory_jobs', to_regclass('public.content_replenishment_jobs') is not null,
        'usage_history', to_regclass('public.content_usage_events') is not null,
        'function_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from permission_failures),
            '[]'::jsonb
        ),
        'phase_c_inventory_migration_version', '20260808093621'
    );
$$;

revoke all on function public.get_phase_c_inventory_contract() from public, anon, authenticated;
grant execute on function public.get_phase_c_inventory_contract() to service_role;
