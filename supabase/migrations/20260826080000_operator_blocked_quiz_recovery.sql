-- Audited operator recovery for generation jobs that were blocked by a
-- non-retryable provider response which has subsequently been corrected.

create or replace function public.requeue_blocked_quiz_job(
    p_job_id uuid,
    p_actor text,
    p_reason text,
    p_expected_error_code text
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
    if nullif(btrim(p_actor), '') is null
       or nullif(btrim(p_reason), '') is null
       or nullif(btrim(p_expected_error_code), '') is null then
        raise exception 'actor, reason, and expected error code are required';
    end if;

    select * into v_job
    from public.quiz_jobs
    where id = p_job_id
    for update;
    if not found then
        raise exception 'quiz job does not exist';
    end if;
    if v_job.status <> 'blocked' then
        raise exception 'only a blocked quiz job can be requeued';
    end if;
    if v_job.last_error_code is distinct from btrim(p_expected_error_code) then
        raise exception 'quiz job error code changed before recovery';
    end if;
    if v_job.telegram_message_id is not null
       or v_job.telegram_acknowledged_at is not null then
        raise exception 'a job with Telegram acknowledgement cannot be requeued';
    end if;

    select * into v_run
    from public.quiz_runs
    where quiz_id = v_job.quiz_id
    for update;
    if found and (
        v_run.status in ('posted', 'posting', 'posting_unknown')
        or v_run.telegram_message_id is not null
        or v_run.telegram_acknowledged_at is not null
    ) then
        raise exception 'quiz run delivery state does not permit generation recovery';
    end if;

    update public.quiz_jobs
    set status = 'retry_wait',
        next_retry_at = now(),
        blocking_reason = null,
        worker_id = null,
        claimed_at = null,
        lease_expires_at = null,
        updated_at = now()
    where id = v_job.id;

    insert into public.quiz_job_events (
        job_id, quiz_id, event_type, from_status, to_status,
        worker_id, attempt_number, category, code, detail
    ) values (
        v_job.id, v_job.quiz_id, 'operator_requeued', v_job.status, 'retry_wait',
        btrim(p_actor), v_job.retry_count, v_job.last_error_category,
        v_job.last_error_code,
        jsonb_build_object('actor', btrim(p_actor), 'reason', btrim(p_reason))
    );

    return jsonb_build_object(
        'job_id', v_job.id,
        'quiz_id', v_job.quiz_id,
        'status', 'retry_wait',
        'retry_count', v_job.retry_count
    );
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
        ('reconcile_quiz_job_unknown(uuid,text,text,text,bigint)'),
        ('requeue_blocked_quiz_job(uuid,text,text,text)')
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
        'operator_recovery', true,
        'ready', jobs_ready and events_ready
            and jsonb_array_length(function_permission_failures) = 0,
        'function_permission_failures', function_permission_failures
    ) from facts;
$$;

revoke all on function public.requeue_blocked_quiz_job(uuid,text,text,text)
    from public, anon, authenticated;
revoke all on function public.get_quiz_job_contract()
    from public, anon, authenticated;
grant execute on function public.requeue_blocked_quiz_job(uuid,text,text,text)
    to service_role;
grant execute on function public.get_quiz_job_contract()
    to service_role;
