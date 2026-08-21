-- Authoritative daily-quiz timing. Client clocks remain telemetry only.

create table if not exists public.daily_quiz_attempt_starts (
    id uuid primary key default gen_random_uuid(),
    quiz_id text not null references public.quiz_runs(quiz_id) on delete cascade,
    user_id uuid not null references public.users(id) on delete cascade,
    client_attempt_id uuid not null,
    started_at timestamptz not null default clock_timestamp(),
    deadline_at timestamptz not null default clock_timestamp() + interval '24 hours',
    submitted_at timestamptz,
    server_duration_seconds integer,
    client_duration_seconds integer,
    client_response_times jsonb,
    timing_trusted boolean not null default true,
    anomaly_codes text[] not null default '{}',
    created_at timestamptz not null default clock_timestamp(),
    unique (quiz_id, user_id, client_attempt_id),
    check (deadline_at > started_at),
    check (server_duration_seconds is null or server_duration_seconds between 0 and 86400),
    check (client_duration_seconds is null or client_duration_seconds between 0 and 86400),
    check (client_response_times is null or jsonb_typeof(client_response_times) = 'array')
);

create index if not exists idx_daily_quiz_attempt_starts_active
    on public.daily_quiz_attempt_starts (user_id, quiz_id, started_at desc)
    where submitted_at is null;

alter table public.daily_quiz_attempt_starts enable row level security;
alter table public.daily_quiz_attempt_starts force row level security;
revoke all on table public.daily_quiz_attempt_starts from public, anon, authenticated;
grant select, insert, update on table public.daily_quiz_attempt_starts to service_role;

create or replace function public.start_daily_quiz_attempt_atomic(
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_row public.daily_quiz_attempt_starts%rowtype;
    v_overlap boolean;
begin
    if p_client_attempt_id is null then
        raise exception 'a client-generated UUID attempt identifier is required';
    end if;
    if not exists (select 1 from public.users where id = p_user_id) then
        raise exception 'authenticated user does not exist';
    end if;
    if not exists (
        select 1 from public.quiz_runs
        where quiz_id = p_quiz_id and (integrity_verified or status = 'posted')
    ) then
        raise exception 'quiz is not ready to start';
    end if;

    perform pg_advisory_xact_lock(hashtextextended(
        p_quiz_id || ':' || p_user_id::text || ':' || p_client_attempt_id::text, 0
    ));
    select exists (
        select 1 from public.daily_quiz_attempt_starts
        where quiz_id = p_quiz_id
          and user_id = p_user_id
          and client_attempt_id <> p_client_attempt_id
          and submitted_at is null
          and deadline_at > clock_timestamp()
    ) into v_overlap;

    insert into public.daily_quiz_attempt_starts (
        quiz_id, user_id, client_attempt_id, anomaly_codes
    ) values (
        p_quiz_id, p_user_id, p_client_attempt_id,
        case when v_overlap then array['multi_device_or_parallel_start']::text[] else '{}'::text[] end
    )
    on conflict (quiz_id, user_id, client_attempt_id) do nothing;

    select * into strict v_row
    from public.daily_quiz_attempt_starts
    where quiz_id = p_quiz_id
      and user_id = p_user_id
      and client_attempt_id = p_client_attempt_id;

    return jsonb_build_object(
        'attemptId', v_row.client_attempt_id,
        'startedAt', v_row.started_at,
        'deadlineAt', v_row.deadline_at,
        'timingTrusted', v_row.timing_trusted,
        'anomalyCodes', v_row.anomaly_codes,
        'idempotentReplay', v_row.created_at < clock_timestamp() - interval '10 milliseconds'
    );
end;
$$;

create or replace function public.submit_server_timed_quiz_attempt_atomic(
    p_quiz_id text,
    p_user_id uuid,
    p_client_attempt_id uuid,
    p_answers jsonb,
    p_client_duration_seconds integer default null,
    p_response_times jsonb default null,
    p_marked_for_review jsonb default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_start public.daily_quiz_attempt_starts%rowtype;
    v_duration integer;
    v_trusted boolean := false;
    v_anomalies text[] := '{}';
    v_result jsonb;
begin
    if p_client_duration_seconds is not null
       and p_client_duration_seconds not between 0 and 86400 then
        raise exception 'client duration must be between 0 and 86400 seconds';
    end if;

    select * into v_start
    from public.daily_quiz_attempt_starts
    where quiz_id = p_quiz_id
      and user_id = p_user_id
      and client_attempt_id = p_client_attempt_id
    for update;

    if found then
        v_anomalies := v_start.anomaly_codes;
        if v_start.submitted_at is not null then
            v_duration := v_start.server_duration_seconds;
            v_trusted := v_start.timing_trusted;
        else
            v_duration := floor(extract(epoch from (clock_timestamp() - v_start.started_at)))::integer;
            if v_duration < 0 then
                v_anomalies := array_append(v_anomalies, 'server_clock_negative');
                v_duration := null;
            elsif clock_timestamp() > v_start.deadline_at or v_duration > 86400 then
                v_anomalies := array_append(v_anomalies, 'attempt_deadline_exceeded');
                v_duration := null;
            else
                v_trusted := true;
            end if;
            if p_client_duration_seconds is not null
               and v_duration is not null
               and abs(p_client_duration_seconds - v_duration) > greatest(30, ceil(v_duration * 0.20)::integer) then
                v_anomalies := array_append(v_anomalies, 'client_clock_mismatch');
            end if;
        end if;
    else
        -- Backward compatibility: legacy clients may submit, but their timing
        -- is NULL and therefore cannot win an official duration tie-break.
        v_duration := null;
        v_trusted := false;
        v_anomalies := array['legacy_without_server_start']::text[];
    end if;

    v_result := public.submit_quiz_attempt_atomic(
        p_quiz_id,
        p_user_id,
        p_client_attempt_id,
        p_answers,
        v_duration,
        null,
        p_marked_for_review
    );

    if v_start.id is not null and v_start.submitted_at is null then
        update public.daily_quiz_attempt_starts
        set submitted_at = clock_timestamp(),
            server_duration_seconds = v_duration,
            client_duration_seconds = p_client_duration_seconds,
            client_response_times = p_response_times,
            timing_trusted = v_trusted,
            anomaly_codes = array(select distinct unnest(v_anomalies))
        where id = v_start.id;
    end if;

    return v_result || jsonb_build_object(
        'durationSeconds', v_duration,
        'timingTrusted', v_trusted,
        'timingSource', case when v_trusted then 'server' else 'legacy_untrusted' end,
        'timingAnomalyCodes', v_anomalies
    );
end;
$$;

create or replace function public.get_daily_attempt_timing_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'ready',
            to_regclass('public.daily_quiz_attempt_starts') is not null
            and to_regprocedure('public.start_daily_quiz_attempt_atomic(text,uuid,uuid)') is not null
            and to_regprocedure('public.submit_server_timed_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)') is not null,
        'migration_version', '20260820090000',
        'server_timed_rank', true,
        'legacy_timing_untrusted', true,
        'client_response_times_untrusted', true
    );
$$;

revoke all on function public.start_daily_quiz_attempt_atomic(text,uuid,uuid)
    from public, anon, authenticated;
revoke all on function public.submit_server_timed_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb)
    from public, anon, authenticated;
revoke all on function public.get_daily_attempt_timing_contract()
    from public, anon, authenticated;
grant execute on function public.start_daily_quiz_attempt_atomic(text,uuid,uuid) to service_role;
grant execute on function public.submit_server_timed_quiz_attempt_atomic(text,uuid,uuid,jsonb,integer,jsonb,jsonb) to service_role;
grant execute on function public.get_daily_attempt_timing_contract() to service_role;

comment on table public.daily_quiz_attempt_starts is
    'Server-authoritative daily attempt clocks and untrusted client timing telemetry.';
