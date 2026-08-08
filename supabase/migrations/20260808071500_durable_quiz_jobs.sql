-- Durable, lease-based quiz delivery jobs. quiz_runs remains the compatible
-- generated-pack/read model; quiz_jobs is authoritative for due/retry/delivery.

create table if not exists public.quiz_jobs (
    id uuid primary key default extensions.gen_random_uuid(),
    quiz_id text not null unique,
    logical_date date not null,
    subject_key text not null references public.quiz_subjects(subject_key) on delete restrict,
    due_at timestamptz not null,
    status text not null default 'due' check (status in (
        'due', 'claimed', 'generating', 'ready', 'posting', 'posted',
        'retry_wait', 'blocked', 'posting_unknown', 'dead_letter'
    )),
    retry_count integer not null default 0 check (retry_count >= 0),
    next_retry_at timestamptz,
    claimed_at timestamptz,
    lease_expires_at timestamptz,
    worker_id text,
    pack_checksum text,
    telegram_message_id bigint,
    telegram_acknowledged_at timestamptz,
    last_error_category text,
    last_error_code text,
    last_error_at timestamptz,
    blocking_reason text,
    source_bundle_hash text,
    configuration_hash text not null,
    code_sha text not null,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    posted_at timestamptz,
    unique (logical_date, subject_key),
    check (source_bundle_hash is null or source_bundle_hash ~ '^[0-9a-f]{64}$'),
    check (configuration_hash ~ '^[0-9a-f]{64}$'),
    check (nullif(btrim(code_sha), '') is not null),
    check (
        (status in ('claimed', 'generating', 'ready', 'posting')
            and worker_id is not null and lease_expires_at is not null)
        or status not in ('claimed', 'generating', 'ready', 'posting')
    )
);

create index if not exists idx_quiz_jobs_dispatch
    on public.quiz_jobs (status, due_at, next_retry_at, lease_expires_at);
create index if not exists idx_quiz_jobs_daily_health
    on public.quiz_jobs (logical_date, subject_key, status);

create table if not exists public.quiz_job_events (
    id bigint generated always as identity primary key,
    job_id uuid not null references public.quiz_jobs(id) on delete restrict,
    quiz_id text not null,
    event_type text not null,
    from_status text,
    to_status text,
    worker_id text,
    attempt_number integer not null default 0 check (attempt_number >= 0),
    category text,
    code text,
    detail jsonb not null default '{}'::jsonb,
    provider text,
    model text,
    latency_ms integer check (latency_ms is null or latency_ms >= 0),
    created_at timestamptz not null default now()
);

create index if not exists idx_quiz_job_events_job_time
    on public.quiz_job_events (job_id, created_at, id);

create or replace function public.prevent_quiz_job_event_mutation()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
begin
    raise exception 'quiz_job_events is append-only';
end;
$$;

drop trigger if exists quiz_job_events_append_only on public.quiz_job_events;
create trigger quiz_job_events_append_only
before update or delete on public.quiz_job_events
for each row execute function public.prevent_quiz_job_event_mutation();

create or replace function public.ensure_daily_quiz_jobs(
    p_jobs jsonb,
    p_configuration_hash text,
    p_code_sha text,
    p_source_bundle_hash text default null
)
returns setof public.quiz_jobs
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_count integer;
begin
    if jsonb_typeof(p_jobs) <> 'array'
       or p_configuration_hash !~ '^[0-9a-f]{64}$'
       or nullif(btrim(p_code_sha), '') is null
       or (p_source_bundle_hash is not null and p_source_bundle_hash !~ '^[0-9a-f]{64}$') then
        raise exception 'valid job specs and build identities are required';
    end if;

    select count(*) into v_count from jsonb_array_elements(p_jobs);
    if v_count <> 13 then
        raise exception 'exactly 13 daily jobs are required';
    end if;

    return query
    with specs as (
        select
            nullif(btrim(item->>'quiz_id'), '') as quiz_id,
            (item->>'logical_date')::date as logical_date,
            nullif(btrim(item->>'subject_key'), '') as subject_key,
            (item->>'due_at')::timestamptz as due_at
        from jsonb_array_elements(p_jobs) item
    ), validated as (
        select * from specs
        where quiz_id is not null and subject_key is not null and due_at is not null
    ), inserted as (
        insert into public.quiz_jobs (
            quiz_id, logical_date, subject_key, due_at,
            configuration_hash, code_sha, source_bundle_hash
        )
        select
            quiz_id, logical_date, subject_key, due_at,
            p_configuration_hash, p_code_sha, p_source_bundle_hash
        from validated
        on conflict (logical_date, subject_key) do update set
            configuration_hash = case
                when public.quiz_jobs.status in ('due', 'retry_wait')
                    then excluded.configuration_hash
                else public.quiz_jobs.configuration_hash
            end,
            code_sha = case
                when public.quiz_jobs.status in ('due', 'retry_wait')
                    then excluded.code_sha
                else public.quiz_jobs.code_sha
            end,
            source_bundle_hash = case
                when public.quiz_jobs.status in ('due', 'retry_wait')
                    then excluded.source_bundle_hash
                else public.quiz_jobs.source_bundle_hash
            end,
            updated_at = now()
        returning public.quiz_jobs.*
    ), events as (
        insert into public.quiz_job_events (
            job_id, quiz_id, event_type, to_status, detail
        )
        select id, quiz_id, 'job_ensured', status,
            jsonb_build_object('due_at', due_at)
        from inserted
        where created_at = updated_at
        returning 1
    )
    select * from inserted order by due_at;

    if (select count(distinct subject_key) from public.quiz_jobs
        where logical_date = (select min((item->>'logical_date')::date)
                              from jsonb_array_elements(p_jobs) item)) <> 13 then
        raise exception 'daily job set is incomplete or duplicated';
    end if;
end;
$$;

create or replace function public.claim_due_quiz_jobs(
    p_worker_id text,
    p_now timestamptz default now(),
    p_lease_minutes integer default 20,
    p_limit integer default 13
)
returns setof public.quiz_jobs
language plpgsql
security definer
set search_path = ''
as $$
begin
    if nullif(btrim(p_worker_id), '') is null or p_now is null then
        raise exception 'worker and current timestamp are required';
    end if;

    return query
    with expired_posting as (
        update public.quiz_jobs job
        set status = 'posting_unknown',
            blocking_reason = 'posting lease expired; delivery requires reconciliation',
            last_error_category = 'telegram_delivery_unknown',
            last_error_code = 'posting_lease_expired',
            last_error_at = p_now,
            worker_id = null,
            claimed_at = null,
            lease_expires_at = null,
            updated_at = now()
        where job.status = 'posting'
          and job.lease_expires_at <= p_now
        returning job.*, 'posting'::text as prior_status
    ), expired_events as (
        insert into public.quiz_job_events (
            job_id, quiz_id, event_type, from_status, to_status,
            attempt_number, category, code
        )
        select id, quiz_id, 'lease_expired_unknown', prior_status, status,
            retry_count, last_error_category, last_error_code
        from expired_posting
        returning 1
    ), candidates as (
        select job.id
        from public.quiz_jobs job
        where job.due_at <= p_now
          and (
              job.status = 'due'
              or (job.status = 'retry_wait' and coalesce(job.next_retry_at, job.due_at) <= p_now)
              or (job.status in ('claimed', 'generating', 'ready')
                  and job.lease_expires_at <= p_now)
          )
        order by job.due_at, job.subject_key
        for update skip locked
        limit greatest(1, least(coalesce(p_limit, 13), 52))
    ), claimed as (
        update public.quiz_jobs job
        set status = 'claimed',
            worker_id = p_worker_id,
            claimed_at = p_now,
            lease_expires_at = p_now + make_interval(
                mins => greatest(5, least(coalesce(p_lease_minutes, 20), 120))
            ),
            next_retry_at = null,
            updated_at = now()
        from candidates
        where job.id = candidates.id
        returning job.*
    ), claimed_events as (
        insert into public.quiz_job_events (
            job_id, quiz_id, event_type, to_status, worker_id, attempt_number
        )
        select id, quiz_id, 'claimed', status, worker_id, retry_count from claimed
        returning 1
    )
    select * from claimed order by due_at, subject_key;
end;
$$;

create or replace function public.transition_quiz_job(
    p_job_id uuid,
    p_worker_id text,
    p_target_status text,
    p_event_type text,
    p_detail jsonb default '{}'::jsonb,
    p_pack_checksum text default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job public.quiz_jobs%rowtype;
    v_allowed boolean := false;
begin
    select * into v_job from public.quiz_jobs where id = p_job_id for update;
    if not found then raise exception 'quiz job does not exist'; end if;
    if v_job.worker_id is distinct from p_worker_id
       or v_job.lease_expires_at is null
       or v_job.lease_expires_at <= now() then
        raise exception 'quiz job lease is not owned or has expired';
    end if;

    v_allowed := case
        when v_job.status = 'claimed' and p_target_status = 'generating' then true
        when v_job.status = 'generating' and p_target_status = 'ready' then true
        when v_job.status = 'ready' and p_target_status = 'posting' then true
        else false
    end;
    if not v_allowed then
        raise exception 'invalid quiz job transition: % -> %', v_job.status, p_target_status;
    end if;

    update public.quiz_jobs
    set status = p_target_status,
        pack_checksum = coalesce(p_pack_checksum, pack_checksum),
        updated_at = now()
    where id = p_job_id;
    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status,
        worker_id, attempt_number, detail
    ) values (
        v_job.id, v_job.quiz_id, coalesce(nullif(btrim(p_event_type), ''), 'transition'),
        v_job.status, p_target_status, p_worker_id, v_job.retry_count,
        coalesce(p_detail, '{}'::jsonb)
    );
    return jsonb_build_object('job_id', p_job_id, 'status', p_target_status);
end;
$$;

create or replace function public.fail_quiz_job(
    p_job_id uuid,
    p_worker_id text,
    p_retryable boolean,
    p_category text,
    p_code text,
    p_reason text,
    p_max_retries integer default 5,
    p_base_delay_seconds integer default 60,
    p_max_delay_seconds integer default 1800
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job public.quiz_jobs%rowtype;
    v_retry integer;
    v_target text;
    v_delay integer;
    v_next timestamptz;
begin
    select * into v_job from public.quiz_jobs where id = p_job_id for update;
    if not found then raise exception 'quiz job does not exist'; end if;
    if v_job.status in ('posted', 'posting_unknown') then
        raise exception 'posted or unknown-delivery jobs cannot enter normal failure handling';
    end if;
    if v_job.worker_id is distinct from p_worker_id then
        raise exception 'quiz job lease is not owned';
    end if;

    v_retry := v_job.retry_count + 1;
    if not coalesce(p_retryable, false) then
        v_target := 'blocked';
    elsif v_retry >= greatest(1, coalesce(p_max_retries, 5)) then
        v_target := 'dead_letter';
    else
        v_target := 'retry_wait';
    end if;
    if v_target = 'retry_wait' then
        v_delay := least(
            greatest(coalesce(p_max_delay_seconds, 1800), 60),
            greatest(coalesce(p_base_delay_seconds, 60), 10)
                * (2 ^ least(v_retry - 1, 10))::integer
                + (abs(hashtext(v_job.id::text || ':' || v_retry::text)) % 31)
        );
        v_next := now() + make_interval(secs => v_delay);
    end if;

    update public.quiz_jobs
    set status = v_target,
        retry_count = v_retry,
        next_retry_at = v_next,
        last_error_category = nullif(btrim(p_category), ''),
        last_error_code = nullif(btrim(p_code), ''),
        last_error_at = now(),
        blocking_reason = case when v_target in ('blocked', 'dead_letter')
            then coalesce(nullif(btrim(p_reason), ''), nullif(btrim(p_category), ''))
            else null end,
        worker_id = null,
        claimed_at = null,
        lease_expires_at = null,
        updated_at = now()
    where id = p_job_id;
    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status, worker_id,
        attempt_number, category, code, detail
    ) values (
        v_job.id, v_job.quiz_id, 'attempt_failed', v_job.status, v_target,
        p_worker_id, v_retry, nullif(btrim(p_category), ''), nullif(btrim(p_code), ''),
        jsonb_build_object('reason', p_reason, 'next_retry_at', v_next)
    );
    return jsonb_build_object(
        'job_id', p_job_id, 'status', v_target,
        'retry_count', v_retry, 'next_retry_at', v_next
    );
end;
$$;

create or replace function public.sync_quiz_job_from_posted_run(
    p_quiz_id text,
    p_worker_id text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job public.quiz_jobs%rowtype;
    v_run public.quiz_runs%rowtype;
begin
    select * into v_job from public.quiz_jobs where quiz_id = p_quiz_id for update;
    select * into v_run from public.quiz_runs where quiz_id = p_quiz_id;
    if v_job.id is null or v_run.quiz_id is null or v_run.status <> 'posted' then
        raise exception 'a posted compatible quiz run is required';
    end if;
    if v_job.status = 'posted' then
        return jsonb_build_object('job_id', v_job.id, 'status', 'posted', 'idempotent_replay', true);
    end if;
    if v_job.worker_id is distinct from p_worker_id then
        raise exception 'quiz job lease is not owned';
    end if;
    update public.quiz_jobs set
        status = 'posted',
        telegram_message_id = v_run.telegram_message_id,
        telegram_acknowledged_at = coalesce(v_run.telegram_acknowledged_at, v_run.posted_at),
        posted_at = v_run.posted_at,
        pack_checksum = v_run.persisted_checksum,
        worker_id = null, claimed_at = null, lease_expires_at = null,
        last_error_category = null, last_error_code = null,
        blocking_reason = null, updated_at = now()
    where id = v_job.id;
    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status, worker_id,
        attempt_number, detail
    ) values (
        v_job.id, v_job.quiz_id, 'synced_posted_run', v_job.status, 'posted',
        p_worker_id, v_job.retry_count,
        jsonb_build_object('telegram_message_id', v_run.telegram_message_id)
    );
    return jsonb_build_object('job_id', v_job.id, 'status', 'posted', 'idempotent_replay', false);
end;
$$;

create or replace function public.mark_quiz_job_posting_unknown(
    p_job_id uuid,
    p_worker_id text,
    p_category text,
    p_code text,
    p_reason text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job public.quiz_jobs%rowtype;
begin
    select * into v_job from public.quiz_jobs where id = p_job_id for update;
    if not found then raise exception 'quiz job does not exist'; end if;
    if v_job.status = 'posting_unknown' then
        return jsonb_build_object('job_id', p_job_id, 'status', 'posting_unknown', 'idempotent_replay', true);
    end if;
    if v_job.status = 'posted' or v_job.worker_id is distinct from p_worker_id then
        raise exception 'quiz job cannot enter unknown delivery state';
    end if;
    update public.quiz_jobs set
        status = 'posting_unknown',
        last_error_category = coalesce(nullif(btrim(p_category), ''), 'telegram_delivery_unknown'),
        last_error_code = coalesce(nullif(btrim(p_code), ''), 'delivery_reconciliation_required'),
        last_error_at = now(),
        blocking_reason = coalesce(nullif(btrim(p_reason), ''), 'Telegram delivery requires reconciliation'),
        worker_id = null, claimed_at = null, lease_expires_at = null,
        updated_at = now()
    where id = p_job_id;
    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status,
        worker_id, attempt_number, category, code, detail
    ) values (
        v_job.id, v_job.quiz_id, 'delivery_unknown', v_job.status,
        'posting_unknown', p_worker_id, v_job.retry_count,
        nullif(btrim(p_category), ''), nullif(btrim(p_code), ''),
        jsonb_build_object('reason', p_reason)
    );
    return jsonb_build_object('job_id', p_job_id, 'status', 'posting_unknown', 'idempotent_replay', false);
end;
$$;

create or replace function public.reflect_quiz_run_delivery_on_job()
returns trigger
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_prior text;
    v_job_id uuid;
    v_retry integer;
begin
    if new.status not in ('posted', 'posting_unknown') or new.status = old.status then
        return new;
    end if;
    select id, status, retry_count into v_job_id, v_prior, v_retry
    from public.quiz_jobs where quiz_id = new.quiz_id for update;
    if v_job_id is null or v_prior = new.status then return new; end if;
    update public.quiz_jobs set
        status = new.status,
        pack_checksum = coalesce(new.persisted_checksum, pack_checksum),
        telegram_message_id = coalesce(new.telegram_message_id, telegram_message_id),
        telegram_acknowledged_at = coalesce(new.telegram_acknowledged_at, telegram_acknowledged_at),
        posted_at = case when new.status = 'posted' then new.posted_at else posted_at end,
        last_error_category = case when new.status = 'posted' then null else new.last_error_category end,
        last_error_code = case when new.status = 'posted' then null else 'delivery_reconciliation_required' end,
        blocking_reason = case when new.status = 'posted' then null else 'Telegram delivery requires operator reconciliation' end,
        worker_id = null, claimed_at = null, lease_expires_at = null,
        updated_at = now()
    where id = v_job_id;
    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status,
        attempt_number, category, detail
    ) values (
        v_job_id, new.quiz_id,
        case when new.status = 'posted' then 'telegram_acknowledged' else 'delivery_unknown' end,
        v_prior, new.status, v_retry, new.last_error_category,
        jsonb_build_object('telegram_message_id', new.telegram_message_id)
    );
    return new;
end;
$$;

drop trigger if exists reflect_quiz_run_delivery_on_job on public.quiz_runs;
create trigger reflect_quiz_run_delivery_on_job
after update of status on public.quiz_runs
for each row execute function public.reflect_quiz_run_delivery_on_job();

create or replace function public.reconcile_quiz_job_unknown(
    p_job_id uuid,
    p_action text,
    p_actor text,
    p_reason text,
    p_telegram_message_id bigint default null
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job public.quiz_jobs%rowtype;
    v_run public.quiz_runs%rowtype;
begin
    if nullif(btrim(p_actor), '') is null or nullif(btrim(p_reason), '') is null then
        raise exception 'actor and reconciliation reason are required';
    end if;
    select * into v_job from public.quiz_jobs where id = p_job_id for update;
    select * into v_run from public.quiz_runs where quiz_id = v_job.quiz_id for update;
    if v_job.status <> 'posting_unknown' or v_run.status <> 'posting_unknown' then
        raise exception 'job and run must both require posting reconciliation';
    end if;

    if p_action = 'confirm_no_message' then
        if coalesce(v_job.telegram_message_id, v_run.telegram_message_id) is not null then
            raise exception 'a known Telegram message ID cannot be confirmed absent';
        end if;
        update public.quiz_runs set status = 'posting_failed', retryable = true,
            last_error_category = 'operator_confirmed_no_delivery', last_error_at = now(),
            updated_at = now()
        where quiz_id = v_job.quiz_id;
        update public.quiz_jobs set status = 'retry_wait', next_retry_at = now(),
            blocking_reason = null, last_error_category = 'operator_confirmed_no_delivery',
            last_error_code = 'reconciled_retry', last_error_at = now(), updated_at = now()
        where id = p_job_id;
        insert into public.quiz_job_events (
            job_id, quiz_id, event_type, from_status, to_status,
            attempt_number, category, code, detail
        ) values (
            v_job.id, v_job.quiz_id, 'operator_reconciled_retry', v_job.status,
            'retry_wait', v_job.retry_count, 'operator_confirmed_no_delivery',
            'reconciled_retry', jsonb_build_object('actor', p_actor, 'reason', p_reason)
        );
        return jsonb_build_object('job_id', p_job_id, 'status', 'retry_wait');
    end if;

    if p_action = 'attach_message' then
        if p_telegram_message_id is null or p_telegram_message_id <= 0 then
            raise exception 'a positive Telegram message ID is required';
        end if;
        if coalesce(v_run.telegram_message_id, p_telegram_message_id) <> p_telegram_message_id then
            raise exception 'Telegram message ID conflicts with preserved acknowledgement';
        end if;
        update public.quiz_runs set status = 'posting', worker_id = p_actor,
            claimed_at = now(), claim_expires_at = now() + interval '20 minutes',
            telegram_message_id = p_telegram_message_id, updated_at = now()
        where quiz_id = v_job.quiz_id;
        perform public.finalize_quiz_post(
            v_job.quiz_id, p_actor, p_telegram_message_id,
            coalesce(v_run.telegram_acknowledged_at, now()),
            v_run.telegram_chat_id, v_run.telegram_thread_id, 21, 180
        );
        insert into public.quiz_job_events (
            job_id, quiz_id, event_type, from_status, to_status,
            attempt_number, detail
        ) values (
            v_job.id, v_job.quiz_id, 'operator_reconciled_posted', v_job.status,
            'posted', v_job.retry_count,
            jsonb_build_object('actor', p_actor, 'reason', p_reason,
                               'telegram_message_id', p_telegram_message_id)
        );
        return jsonb_build_object('job_id', p_job_id, 'status', 'posted');
    end if;
    raise exception 'reconciliation action must be attach_message or confirm_no_message';
end;
$$;

create or replace function public.get_quiz_job_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_functions(signature) as (values
        ('ensure_daily_quiz_jobs(jsonb,text,text,text)'),
        ('claim_due_quiz_jobs(text,timestamp with time zone,integer,integer)'),
        ('transition_quiz_job(uuid,text,text,text,jsonb,text)'),
        ('fail_quiz_job(uuid,text,boolean,text,text,text,integer,integer,integer)'),
        ('sync_quiz_job_from_posted_run(text,text)'),
        ('mark_quiz_job_posting_unknown(uuid,text,text,text,text)'),
        ('reconcile_quiz_job_unknown(uuid,text,text,text,bigint)')
    ), permission_failures as (
        select role_name || ':' || signature as failure
        from required_functions cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
        union all
        select 'service_role:' || signature from required_functions
        where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
    ), facts as (
        select
            to_regclass('public.quiz_jobs') is not null as jobs_ready,
            to_regclass('public.quiz_job_events') is not null as events_ready,
            coalesce((select jsonb_agg(failure order by failure) from permission_failures), '[]'::jsonb)
                as function_permission_failures
    )
    select jsonb_build_object(
        'quiz_job_migration_version', '20260808071500',
        'quiz_job_migration_applied', jobs_ready and events_ready,
        'ready', jobs_ready and events_ready
            and jsonb_array_length(function_permission_failures) = 0,
        'function_permission_failures', function_permission_failures
    ) from facts;
$$;

alter table public.quiz_jobs enable row level security;
alter table public.quiz_job_events enable row level security;

revoke all on table public.quiz_jobs from public, anon, authenticated;
revoke all on table public.quiz_job_events from public, anon, authenticated;
grant select, insert, update on table public.quiz_jobs to service_role;
grant select, insert on table public.quiz_job_events to service_role;
grant usage, select on sequence public.quiz_job_events_id_seq to service_role;

revoke all on function public.prevent_quiz_job_event_mutation() from public, anon, authenticated;
revoke all on function public.reflect_quiz_run_delivery_on_job() from public, anon, authenticated;
revoke all on function public.ensure_daily_quiz_jobs(jsonb,text,text,text) from public, anon, authenticated;
revoke all on function public.claim_due_quiz_jobs(text,timestamptz,integer,integer) from public, anon, authenticated;
revoke all on function public.transition_quiz_job(uuid,text,text,text,jsonb,text) from public, anon, authenticated;
revoke all on function public.fail_quiz_job(uuid,text,boolean,text,text,text,integer,integer,integer) from public, anon, authenticated;
revoke all on function public.sync_quiz_job_from_posted_run(text,text) from public, anon, authenticated;
revoke all on function public.mark_quiz_job_posting_unknown(uuid,text,text,text,text) from public, anon, authenticated;
revoke all on function public.reconcile_quiz_job_unknown(uuid,text,text,text,bigint) from public, anon, authenticated;
revoke all on function public.get_quiz_job_contract() from public, anon, authenticated;

grant execute on function public.ensure_daily_quiz_jobs(jsonb,text,text,text) to service_role;
grant execute on function public.claim_due_quiz_jobs(text,timestamptz,integer,integer) to service_role;
grant execute on function public.transition_quiz_job(uuid,text,text,text,jsonb,text) to service_role;
grant execute on function public.fail_quiz_job(uuid,text,boolean,text,text,text,integer,integer,integer) to service_role;
grant execute on function public.sync_quiz_job_from_posted_run(text,text) to service_role;
grant execute on function public.mark_quiz_job_posting_unknown(uuid,text,text,text,text) to service_role;
grant execute on function public.reconcile_quiz_job_unknown(uuid,text,text,text,bigint) to service_role;
grant execute on function public.get_quiz_job_contract() to service_role;
