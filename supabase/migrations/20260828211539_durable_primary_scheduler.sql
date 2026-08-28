-- Make Supabase Cron the primary, observable heartbeat for the durable quiz
-- ledger. GitHub's own scheduled events remain a lower-frequency recovery
-- path; Cron only asks GitHub Actions to run the existing fail-closed
-- dispatcher and never handles quiz content or Telegram credentials.

do $$
begin
    if exists (select 1 from pg_available_extensions where name = 'pg_net') then
        execute 'create extension if not exists pg_net';
    end if;
    if exists (select 1 from pg_available_extensions where name = 'pg_cron') then
        execute 'create extension if not exists pg_cron with schema pg_catalog';
    end if;
end;
$$;

create schema if not exists private;
revoke all on schema private from public, anon, authenticated, service_role;

create table if not exists private.scheduler_dispatch_requests (
    id bigint generated always as identity primary key,
    mode text not null check (mode in ('dispatch-due-jobs', 'daily-completeness')),
    request_id bigint not null unique,
    requested_at timestamptz not null default now(),
    response_status integer,
    response_received_at timestamptz,
    outcome text not null default 'queued'
        check (outcome in ('queued', 'accepted', 'rejected', 'expired')),
    error_category text
);

alter table private.scheduler_dispatch_requests enable row level security;
revoke all on private.scheduler_dispatch_requests from public, anon, authenticated, service_role;
revoke all on sequence private.scheduler_dispatch_requests_id_seq
    from public, anon, authenticated, service_role;

create index if not exists idx_scheduler_dispatch_requests_pending
    on private.scheduler_dispatch_requests (requested_at, request_id)
    where outcome = 'queued';

create or replace function private.dispatch_github_workflow(p_mode text)
returns bigint
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_token text;
    v_expiry timestamptz;
    v_request_id bigint;
begin
    if p_mode not in ('dispatch-due-jobs', 'daily-completeness') then
        raise exception 'unsupported scheduler mode';
    end if;
    if not exists (select 1 from pg_extension where extname = 'pg_net') then
        raise exception 'pg_net is not installed';
    end if;

    select decrypted_secret into v_token
    from vault.decrypted_secrets
    where name = 'github_scheduler_token';

    select decrypted_secret::timestamptz into v_expiry
    from vault.decrypted_secrets
    where name = 'github_scheduler_token_expires_at';

    if nullif(v_token, '') is null or v_expiry is null then
        raise exception 'scheduler credentials are not configured';
    end if;
    if v_expiry <= now() + interval '48 hours' then
        raise exception 'scheduler credential is expired or inside renewal window';
    end if;

    select net.http_post(
        url => 'https://api.github.com/repos/mahammadsad/telegram_quiz_bot/actions/workflows/main.yml/dispatches',
        headers => pg_catalog.jsonb_build_object(
            'Accept', 'application/vnd.github+json',
            'Authorization', 'Bearer ' || v_token,
            'Content-Type', 'application/json',
            'User-Agent', 'citizen-affairs-supabase-scheduler',
            'X-GitHub-Api-Version', '2022-11-28'
        ),
        body => pg_catalog.jsonb_build_object(
            'ref', 'main',
            'inputs', pg_catalog.jsonb_build_object('mode', p_mode)
        ),
        timeout_milliseconds => 10000
    ) into v_request_id;

    insert into private.scheduler_dispatch_requests (mode, request_id)
    values (p_mode, v_request_id);
    return v_request_id;
end;
$$;

create or replace function private.reconcile_scheduler_requests()
returns integer
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_updated integer := 0;
    v_expired integer := 0;
begin
    if not exists (select 1 from pg_extension where extname = 'pg_net') then
        return 0;
    end if;

    update private.scheduler_dispatch_requests request
    set response_status = response.status_code,
        response_received_at = response.created,
        outcome = case when response.status_code = 204 then 'accepted' else 'rejected' end,
        error_category = case
            when response.timed_out then 'timeout'
            when response.error_msg is not null then 'transport'
            when response.status_code <> 204 then 'github_rejected'
            else null
        end
    from net._http_response response
    where request.outcome = 'queued'
      and response.id = request.request_id;
    get diagnostics v_updated = row_count;

    update private.scheduler_dispatch_requests
    set outcome = 'expired', error_category = 'response_missing'
    where outcome = 'queued'
      and requested_at < now() - interval '10 minutes';
    get diagnostics v_expired = row_count;

    delete from private.scheduler_dispatch_requests
    where requested_at < now() - interval '30 days';
    return v_updated + v_expired;
end;
$$;

create or replace function private.configure_primary_scheduler()
returns void
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_job_id bigint;
begin
    if not exists (select 1 from pg_extension where extname = 'pg_cron')
       or not exists (select 1 from pg_extension where extname = 'pg_net') then
        raise exception 'pg_cron and pg_net must both be installed';
    end if;

    -- Validate the secret and its renewal window before changing any jobs.
    perform 1
    from vault.decrypted_secrets token
    join vault.decrypted_secrets expiry
      on expiry.name = 'github_scheduler_token_expires_at'
    where token.name = 'github_scheduler_token'
      and nullif(token.decrypted_secret, '') is not null
      and expiry.decrypted_secret::timestamptz > now() + interval '48 hours';
    if not found then
        raise exception 'valid scheduler credentials are required';
    end if;

    for v_job_id in
        select jobid from cron.job
        where jobname in (
            'citizen-affairs-primary-dispatch',
            'citizen-affairs-daily-completeness',
            'citizen-affairs-scheduler-reconcile'
        )
    loop
        perform cron.unschedule(v_job_id);
    end loop;

    perform cron.schedule(
        'citizen-affairs-primary-dispatch',
        '4,19,34,49 * * * *',
        $command$select private.dispatch_github_workflow('dispatch-due-jobs');$command$
    );
    perform cron.schedule(
        'citizen-affairs-daily-completeness',
        '11 15 * * *',
        $command$select private.dispatch_github_workflow('daily-completeness');$command$
    );
    perform cron.schedule(
        'citizen-affairs-scheduler-reconcile',
        '9,24,39,54 * * * *',
        $command$select private.reconcile_scheduler_requests();$command$
    );
end;
$$;

create or replace function public.get_primary_scheduler_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_token_present boolean := false;
    v_token_valid boolean := false;
    v_dispatch_ready boolean := false;
    v_completeness_ready boolean := false;
    v_reconcile_ready boolean := false;
begin
    select nullif(decrypted_secret, '') is not null
    into v_token_present
    from vault.decrypted_secrets
    where name = 'github_scheduler_token';

    select decrypted_secret::timestamptz > now() + interval '48 hours'
    into v_token_valid
    from vault.decrypted_secrets
    where name = 'github_scheduler_token_expires_at';

    if exists (select 1 from pg_extension where extname = 'pg_cron') then
        select
            bool_or(jobname = 'citizen-affairs-primary-dispatch' and active
                and schedule = '4,19,34,49 * * * *'),
            bool_or(jobname = 'citizen-affairs-daily-completeness' and active
                and schedule = '11 15 * * *'),
            bool_or(jobname = 'citizen-affairs-scheduler-reconcile' and active
                and schedule = '9,24,39,54 * * * *')
        into v_dispatch_ready, v_completeness_ready, v_reconcile_ready
        from cron.job;
    end if;

    return pg_catalog.jsonb_build_object(
        'ready', coalesce(v_token_present, false)
            and coalesce(v_token_valid, false)
            and coalesce(v_dispatch_ready, false)
            and coalesce(v_completeness_ready, false)
            and coalesce(v_reconcile_ready, false),
        'migration_version', '20260828211539',
        'pg_cron_ready', exists (select 1 from pg_extension where extname = 'pg_cron'),
        'pg_net_ready', exists (select 1 from pg_extension where extname = 'pg_net'),
        'credential_present', coalesce(v_token_present, false),
        'credential_outside_renewal_window', coalesce(v_token_valid, false),
        'dispatch_job_ready', coalesce(v_dispatch_ready, false),
        'completeness_job_ready', coalesce(v_completeness_ready, false),
        'reconcile_job_ready', coalesce(v_reconcile_ready, false),
        'recent_rejected_requests', (
            select count(*) from private.scheduler_dispatch_requests
            where requested_at >= now() - interval '24 hours'
              and outcome in ('rejected', 'expired')
        )
    );
end;
$$;

revoke all on function private.dispatch_github_workflow(text)
    from public, anon, authenticated, service_role;
revoke all on function private.reconcile_scheduler_requests()
    from public, anon, authenticated, service_role;
revoke all on function private.configure_primary_scheduler()
    from public, anon, authenticated, service_role;
revoke all on function public.get_primary_scheduler_contract()
    from public, anon, authenticated;
grant execute on function public.get_primary_scheduler_contract() to service_role;
