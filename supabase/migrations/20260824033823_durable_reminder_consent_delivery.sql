-- Durable, answer-free reminder consent and delivery controls. Real delivery
-- remains disabled at the application/configuration layer until a reliable
-- scheduler and a synthetic Telegram canary are approved.

create table if not exists public.learner_reminder_consents (
    user_id uuid primary key references public.users(id) on delete cascade,
    enabled boolean not null default false,
    policy_version text,
    consent_source text,
    consented_at timestamptz,
    unsubscribed_at timestamptz,
    timezone_name text not null default 'Asia/Kolkata',
    preferred_local_time time not null default '19:00',
    quiet_hours_start time not null default '21:00',
    quiet_hours_end time not null default '08:00',
    synthetic_only boolean not null default false,
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    check (consent_source is null or consent_source in ('settings', 'synthetic_canary')),
    check (quiet_hours_start <> quiet_hours_end),
    check (
        not enabled
        or (
            policy_version = 'reminder-consent-v1'
            and consented_at is not null
            and unsubscribed_at is null
            and consent_source is not null
        )
    ),
    check (not synthetic_only or consent_source = 'synthetic_canary')
);

create table if not exists public.learner_reminder_deliveries (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    logical_date date not null,
    reminder_kind text not null check (reminder_kind in ('daily_study', 'synthetic_canary')),
    consent_version text not null,
    state text not null default 'queued'
        check (state in ('queued', 'claimed', 'retry_wait', 'sent', 'failed', 'cancelled')),
    not_before timestamptz not null,
    next_attempt_at timestamptz not null,
    lease_owner text,
    lease_expires_at timestamptz,
    attempt_count integer not null default 0 check (attempt_count between 0 and 5),
    max_attempts integer not null default 5 check (max_attempts between 1 and 5),
    telegram_message_id bigint,
    sent_at timestamptz,
    failure_code text,
    created_at timestamptz not null default clock_timestamp(),
    updated_at timestamptz not null default clock_timestamp(),
    unique (user_id, logical_date, reminder_kind, consent_version),
    check (next_attempt_at >= not_before),
    check (
        (state = 'claimed' and lease_owner is not null and lease_expires_at is not null)
        or (state <> 'claimed' and lease_owner is null and lease_expires_at is null)
    ),
    check (
        state <> 'sent'
        or (telegram_message_id is not null and telegram_message_id > 0 and sent_at is not null)
    )
);

create index if not exists idx_learner_reminder_deliveries_due
    on public.learner_reminder_deliveries (next_attempt_at, created_at, id)
    where state in ('queued', 'retry_wait');
create index if not exists idx_learner_reminder_deliveries_user_date
    on public.learner_reminder_deliveries (user_id, logical_date desc);

alter table public.learner_reminder_consents enable row level security;
alter table public.learner_reminder_consents force row level security;
alter table public.learner_reminder_deliveries enable row level security;
alter table public.learner_reminder_deliveries force row level security;

revoke all on table public.learner_reminder_consents,
    public.learner_reminder_deliveries from public, anon, authenticated;
grant select, insert, update, delete on table public.learner_reminder_consents,
    public.learner_reminder_deliveries to service_role;

create or replace function public.get_learner_reminder_consent(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'enabled', coalesce(consent.enabled, false),
    'policyVersion', consent.policy_version,
    'consentSource', consent.consent_source,
    'consentedAt', consent.consented_at,
    'unsubscribedAt', consent.unsubscribed_at,
    'timezone', coalesce(consent.timezone_name, 'Asia/Kolkata'),
    'preferredLocalTime', coalesce(consent.preferred_local_time, '19:00'::time),
    'quietHoursStart', coalesce(consent.quiet_hours_start, '21:00'::time),
    'quietHoursEnd', coalesce(consent.quiet_hours_end, '08:00'::time),
    'syntheticOnly', coalesce(consent.synthetic_only, false),
    'deliveryAvailable', false
)
from (select p_user_id as user_id) requested
left join public.learner_reminder_consents consent using (user_id);
$$;

create or replace function public.set_learner_reminder_consent(
    p_user_id uuid,
    p_enabled boolean,
    p_policy_version text,
    p_consent_source text,
    p_timezone_name text default 'Asia/Kolkata',
    p_preferred_local_time time default '19:00',
    p_quiet_hours_start time default '21:00',
    p_quiet_hours_end time default '08:00',
    p_synthetic_only boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_in_quiet_hours boolean;
begin
    if not exists (select 1 from public.users where id = p_user_id) then
        raise exception 'learner does not exist';
    end if;
    if p_enabled is null or p_preferred_local_time is null or p_synthetic_only is null then
        raise exception 'complete reminder consent values are required';
    end if;
    if p_quiet_hours_start is null or p_quiet_hours_end is null
       or p_quiet_hours_start = p_quiet_hours_end then
        raise exception 'quiet hours must define a non-empty bounded interval';
    end if;
    if not exists (select 1 from pg_timezone_names where name = p_timezone_name) then
        raise exception 'invalid learner timezone';
    end if;

    if p_quiet_hours_start < p_quiet_hours_end then
        v_in_quiet_hours := p_preferred_local_time >= p_quiet_hours_start
            and p_preferred_local_time < p_quiet_hours_end;
    else
        v_in_quiet_hours := p_preferred_local_time >= p_quiet_hours_start
            or p_preferred_local_time < p_quiet_hours_end;
    end if;

    if p_enabled then
        if p_policy_version is distinct from 'reminder-consent-v1' then
            raise exception 'current reminder consent policy is required';
        end if;
        if p_consent_source not in ('settings', 'synthetic_canary') then
            raise exception 'invalid reminder consent source';
        end if;
        if p_synthetic_only and p_consent_source <> 'synthetic_canary' then
            raise exception 'synthetic consent must use the synthetic canary source';
        end if;
        if v_in_quiet_hours then
            raise exception 'preferred reminder time falls within quiet hours';
        end if;
    end if;

    insert into public.learner_reminder_consents (
        user_id, enabled, policy_version, consent_source, consented_at,
        unsubscribed_at, timezone_name, preferred_local_time,
        quiet_hours_start, quiet_hours_end, synthetic_only, updated_at
    ) values (
        p_user_id,
        p_enabled,
        case when p_enabled then p_policy_version else null end,
        case when p_enabled then p_consent_source else null end,
        case when p_enabled then clock_timestamp() else null end,
        case when p_enabled then null else clock_timestamp() end,
        p_timezone_name,
        p_preferred_local_time,
        p_quiet_hours_start,
        p_quiet_hours_end,
        case when p_enabled then p_synthetic_only else false end,
        clock_timestamp()
    )
    on conflict (user_id) do update set
        enabled = excluded.enabled,
        policy_version = excluded.policy_version,
        consent_source = excluded.consent_source,
        consented_at = case
            when excluded.enabled and public.learner_reminder_consents.enabled
                and public.learner_reminder_consents.policy_version = excluded.policy_version
                then public.learner_reminder_consents.consented_at
            else excluded.consented_at
        end,
        unsubscribed_at = excluded.unsubscribed_at,
        timezone_name = excluded.timezone_name,
        preferred_local_time = excluded.preferred_local_time,
        quiet_hours_start = excluded.quiet_hours_start,
        quiet_hours_end = excluded.quiet_hours_end,
        synthetic_only = excluded.synthetic_only,
        updated_at = clock_timestamp();

    if not p_enabled then
        update public.learner_reminder_deliveries
        set state = 'cancelled',
            lease_owner = null,
            lease_expires_at = null,
            failure_code = 'consent_withdrawn',
            updated_at = clock_timestamp()
        where user_id = p_user_id
          and state in ('queued', 'claimed', 'retry_wait');
    end if;

    return public.get_learner_reminder_consent(p_user_id);
end;
$$;

create or replace function public.queue_learner_reminder(
    p_user_id uuid,
    p_logical_date date,
    p_reminder_kind text,
    p_not_before timestamptz
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_consent public.learner_reminder_consents%rowtype;
    v_delivery public.learner_reminder_deliveries%rowtype;
begin
    if p_logical_date is null or p_not_before is null then
        raise exception 'logical date and not-before time are required';
    end if;
    if p_reminder_kind not in ('daily_study', 'synthetic_canary') then
        raise exception 'invalid reminder kind';
    end if;

    select * into v_consent
    from public.learner_reminder_consents
    where user_id = p_user_id and enabled
    for update;
    if not found or v_consent.policy_version <> 'reminder-consent-v1' then
        raise exception 'active current reminder consent is required';
    end if;
    if v_consent.synthetic_only <> (p_reminder_kind = 'synthetic_canary') then
        raise exception 'reminder kind does not match consent scope';
    end if;

    insert into public.learner_reminder_deliveries (
        user_id, logical_date, reminder_kind, consent_version,
        not_before, next_attempt_at
    ) values (
        p_user_id, p_logical_date, p_reminder_kind, v_consent.policy_version,
        p_not_before, p_not_before
    )
    on conflict (user_id, logical_date, reminder_kind, consent_version)
    do update set updated_at = public.learner_reminder_deliveries.updated_at
    returning * into v_delivery;

    return jsonb_build_object(
        'deliveryId', v_delivery.id,
        'state', v_delivery.state,
        'idempotencyKey', concat_ws(':', p_user_id, p_logical_date, p_reminder_kind, v_consent.policy_version),
        'idempotentReplay', v_delivery.created_at < clock_timestamp() - interval '10 milliseconds'
    );
end;
$$;

create or replace function public.claim_due_learner_reminders(
    p_worker_id text,
    p_limit integer default 25
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_rows jsonb;
begin
    if nullif(btrim(p_worker_id), '') is null then
        raise exception 'worker id is required';
    end if;

    update public.learner_reminder_deliveries
    set state = case when attempt_count >= max_attempts then 'failed' else 'retry_wait' end,
        next_attempt_at = case
            when attempt_count >= max_attempts then next_attempt_at
            else clock_timestamp() + interval '30 seconds'
        end,
        lease_owner = null,
        lease_expires_at = null,
        failure_code = case
            when attempt_count >= max_attempts then 'retry_exhausted'
            else 'lease_expired'
        end,
        updated_at = clock_timestamp()
    where state = 'claimed' and lease_expires_at <= clock_timestamp();

    with candidates as (
        select delivery.id
        from public.learner_reminder_deliveries delivery
        join public.learner_reminder_consents consent
          on consent.user_id = delivery.user_id
         and consent.enabled
         and consent.policy_version = delivery.consent_version
        where delivery.state in ('queued', 'retry_wait')
          and delivery.next_attempt_at <= clock_timestamp()
          and delivery.attempt_count < delivery.max_attempts
        order by delivery.next_attempt_at, delivery.created_at, delivery.id
        for update of delivery skip locked
        limit greatest(1, least(coalesce(p_limit, 25), 100))
    ), claimed as (
        update public.learner_reminder_deliveries delivery
        set state = 'claimed',
            lease_owner = p_worker_id,
            lease_expires_at = clock_timestamp() + interval '2 minutes',
            attempt_count = delivery.attempt_count + 1,
            updated_at = clock_timestamp()
        from candidates
        where delivery.id = candidates.id
        returning delivery.*
    )
    select coalesce(jsonb_agg(jsonb_build_object(
        'deliveryId', claimed.id,
        'userId', claimed.user_id,
        'logicalDate', claimed.logical_date,
        'reminderKind', claimed.reminder_kind,
        'consentVersion', claimed.consent_version,
        'attempt', claimed.attempt_count,
        'leaseExpiresAt', claimed.lease_expires_at
    ) order by claimed.next_attempt_at, claimed.created_at, claimed.id), '[]'::jsonb)
    into v_rows
    from claimed;

    return jsonb_build_object('items', v_rows, 'count', jsonb_array_length(v_rows));
end;
$$;

create or replace function public.complete_learner_reminder_delivery(
    p_delivery_id uuid,
    p_worker_id text,
    p_outcome text,
    p_telegram_message_id bigint default null,
    p_failure_code text default null,
    p_retry_after_seconds integer default null
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_delivery public.learner_reminder_deliveries%rowtype;
    v_consent_active boolean;
    v_terminal_failure boolean;
begin
    if p_outcome not in ('sent', 'retry_wait', 'failed', 'cancelled') then
        raise exception 'invalid reminder outcome';
    end if;
    if p_failure_code is not null and p_failure_code !~ '^[a-z0-9_]{1,64}$' then
        raise exception 'invalid reminder failure code';
    end if;
    if p_outcome = 'sent' and (p_telegram_message_id is null or p_telegram_message_id <= 0) then
        raise exception 'a valid Telegram receipt is required';
    end if;
    if p_outcome = 'retry_wait'
       and (p_retry_after_seconds is null or p_retry_after_seconds not between 30 and 86400) then
        raise exception 'safe retry delay must be between 30 and 86400 seconds';
    end if;

    select * into v_delivery
    from public.learner_reminder_deliveries
    where id = p_delivery_id
    for update;
    if not found or v_delivery.state <> 'claimed'
       or v_delivery.lease_owner is distinct from p_worker_id
       or v_delivery.lease_expires_at <= clock_timestamp() then
        raise exception 'delivery lease is unavailable';
    end if;

    select exists (
        select 1 from public.learner_reminder_consents consent
        where consent.user_id = v_delivery.user_id
          and consent.enabled
          and consent.policy_version = v_delivery.consent_version
    ) into v_consent_active;
    if not v_consent_active then
        p_outcome := 'cancelled';
        p_failure_code := 'consent_withdrawn';
        p_telegram_message_id := null;
    end if;

    v_terminal_failure := p_failure_code in (
        'telegram_blocked', 'chat_not_found', 'user_deactivated'
    );
    if v_terminal_failure then
        p_outcome := 'failed';
        update public.learner_reminder_consents
        set enabled = false,
            policy_version = null,
            consent_source = null,
            consented_at = null,
            unsubscribed_at = clock_timestamp(),
            synthetic_only = false,
            updated_at = clock_timestamp()
        where user_id = v_delivery.user_id;
        update public.learner_reminder_deliveries
        set state = 'cancelled',
            lease_owner = null,
            lease_expires_at = null,
            failure_code = 'permanent_chat_error',
            updated_at = clock_timestamp()
        where user_id = v_delivery.user_id
          and id <> p_delivery_id
          and state in ('queued', 'claimed', 'retry_wait');
    end if;

    if p_outcome = 'retry_wait' and v_delivery.attempt_count >= v_delivery.max_attempts then
        p_outcome := 'failed';
        p_failure_code := 'retry_exhausted';
    end if;

    update public.learner_reminder_deliveries
    set state = p_outcome,
        next_attempt_at = case
            when p_outcome = 'retry_wait'
                then clock_timestamp() + make_interval(secs => p_retry_after_seconds)
            else next_attempt_at
        end,
        lease_owner = null,
        lease_expires_at = null,
        telegram_message_id = case when p_outcome = 'sent' then p_telegram_message_id else null end,
        sent_at = case when p_outcome = 'sent' then clock_timestamp() else null end,
        failure_code = case when p_outcome = 'sent' then null else p_failure_code end,
        updated_at = clock_timestamp()
    where id = p_delivery_id
    returning * into v_delivery;

    return jsonb_build_object(
        'deliveryId', v_delivery.id,
        'state', v_delivery.state,
        'attemptCount', v_delivery.attempt_count,
        'failureCode', v_delivery.failure_code,
        'sentAt', v_delivery.sent_at
    );
end;
$$;

create or replace function public.get_learner_reminder_delivery_metrics(
    p_date_from date default current_date - 6,
    p_date_to date default current_date
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_rows jsonb;
begin
    if p_date_from is null or p_date_to is null or p_date_to < p_date_from
       or p_date_to - p_date_from > 31 then
        raise exception 'metrics window must be between 1 and 32 days';
    end if;
    select coalesce(jsonb_agg(jsonb_build_object(
        'date', daily.logical_date,
        'kind', daily.reminder_kind,
        'state', daily.state,
        'count', daily.delivery_count
    ) order by daily.logical_date, daily.reminder_kind, daily.state), '[]'::jsonb)
    into v_rows
    from (
        select logical_date, reminder_kind, state, count(*)::integer as delivery_count
        from public.learner_reminder_deliveries
        where logical_date between p_date_from and p_date_to
        group by logical_date, reminder_kind, state
    ) daily;
    return jsonb_build_object('from', p_date_from, 'to', p_date_to, 'rows', v_rows);
end;
$$;

create or replace function public.get_reminder_delivery_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'ready',
        to_regclass('public.learner_reminder_consents') is not null
        and to_regclass('public.learner_reminder_deliveries') is not null
        and to_regprocedure('public.set_learner_reminder_consent(uuid,boolean,text,text,text,time without time zone,time without time zone,time without time zone,boolean)') is not null
        and to_regprocedure('public.queue_learner_reminder(uuid,date,text,timestamp with time zone)') is not null
        and to_regprocedure('public.claim_due_learner_reminders(text,integer)') is not null
        and to_regprocedure('public.complete_learner_reminder_delivery(uuid,text,text,bigint,text,integer)') is not null,
    'migrationVersion', '20260824033823',
    'consentPolicyVersion', 'reminder-consent-v1',
    'deliveryEnabled', false,
    'answerFreePayload', true,
    'maxAttempts', 5,
    'maxClaimBatch', 100
);
$$;

revoke all on function public.get_learner_reminder_consent(uuid)
    from public, anon, authenticated;
revoke all on function public.set_learner_reminder_consent(
    uuid, boolean, text, text, text, time, time, time, boolean
) from public, anon, authenticated;
revoke all on function public.queue_learner_reminder(uuid, date, text, timestamptz)
    from public, anon, authenticated;
revoke all on function public.claim_due_learner_reminders(text, integer)
    from public, anon, authenticated;
revoke all on function public.complete_learner_reminder_delivery(
    uuid, text, text, bigint, text, integer
) from public, anon, authenticated;
revoke all on function public.get_learner_reminder_delivery_metrics(date, date)
    from public, anon, authenticated;
revoke all on function public.get_reminder_delivery_contract()
    from public, anon, authenticated;

grant execute on function public.get_learner_reminder_consent(uuid) to service_role;
grant execute on function public.set_learner_reminder_consent(
    uuid, boolean, text, text, text, time, time, time, boolean
) to service_role;
grant execute on function public.queue_learner_reminder(uuid, date, text, timestamptz)
    to service_role;
grant execute on function public.claim_due_learner_reminders(text, integer)
    to service_role;
grant execute on function public.complete_learner_reminder_delivery(
    uuid, text, text, bigint, text, integer
) to service_role;
grant execute on function public.get_learner_reminder_delivery_metrics(date, date)
    to service_role;
grant execute on function public.get_reminder_delivery_contract() to service_role;
