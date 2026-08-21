-- Authenticated data export and recoverable account-deletion requests.

create table if not exists public.account_deletion_requests (
    id uuid primary key default gen_random_uuid(),
    user_id uuid not null references public.users(id) on delete cascade,
    status text not null default 'pending'
        check (status in ('pending', 'cancelled', 'processing', 'completed', 'failed')),
    requested_at timestamptz not null default clock_timestamp(),
    eligible_at timestamptz not null default clock_timestamp() + interval '7 days',
    cancelled_at timestamptz,
    processed_at timestamptz,
    failure_code text
);

create unique index if not exists idx_account_deletion_one_active
    on public.account_deletion_requests(user_id)
    where status in ('pending', 'processing');

create table if not exists public.account_deletion_audit (
    id bigint generated always as identity primary key,
    request_id uuid not null unique,
    user_reference_hash text not null check (user_reference_hash ~ '^[0-9a-f]{64}$'),
    processed_at timestamptz not null,
    outcome text not null check (outcome in ('completed', 'failed')),
    failure_code text
);

alter table public.account_deletion_requests enable row level security;
alter table public.account_deletion_requests force row level security;
alter table public.account_deletion_audit enable row level security;
alter table public.account_deletion_audit force row level security;
revoke all on table public.account_deletion_requests, public.account_deletion_audit
    from public, anon, authenticated;
grant select, insert, update, delete on table public.account_deletion_requests to service_role;
grant select, insert on table public.account_deletion_audit to service_role;

create or replace function public.export_learner_data(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select jsonb_build_object(
    'exportedAt', clock_timestamp(),
    'profile', (select to_jsonb(row) from public.users row where row.id = p_user_id),
    'preferences', (select to_jsonb(row) from public.user_preferences row where row.user_id = p_user_id),
    'quizAttempts', coalesce((select jsonb_agg(to_jsonb(row) order by row.completed_at desc)
        from public.quiz_attempts row where row.user_id = p_user_id), '[]'::jsonb),
    'practiceAnswers', coalesce((select jsonb_agg(to_jsonb(row) order by row.answered_at desc)
        from public.personal_practice_answers row where row.user_id = p_user_id), '[]'::jsonb),
    'questionReports', coalesce((select jsonb_agg(to_jsonb(row) order by row.created_at desc)
        from public.question_reports row where row.user_id = p_user_id), '[]'::jsonb),
    'questionBookmarks', coalesce((select jsonb_agg(to_jsonb(row) order by row.created_at desc)
        from public.user_question_bookmarks row where row.user_id = p_user_id), '[]'::jsonb),
    'resourceBookmarks', coalesce((select jsonb_agg(to_jsonb(row) order by row.created_at desc)
        from public.user_resource_bookmarks row where row.user_id = p_user_id), '[]'::jsonb),
    'mastery', coalesce((select jsonb_agg(to_jsonb(row))
        from public.personal_knowledge_mastery row where row.user_id = p_user_id), '[]'::jsonb),
    'deletionRequests', coalesce((select jsonb_agg(to_jsonb(row) order by row.requested_at desc)
        from public.account_deletion_requests row where row.user_id = p_user_id), '[]'::jsonb)
)
where exists (select 1 from public.users where id = p_user_id);
$$;

create or replace function public.request_account_deletion(p_user_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare v_request public.account_deletion_requests%rowtype;
begin
    update public.account_deletion_requests
    set status = 'cancelled', cancelled_at = clock_timestamp()
    where user_id = p_user_id and status = 'pending';
    insert into public.account_deletion_requests(user_id)
    values (p_user_id)
    returning * into v_request;
    return jsonb_build_object(
        'requestId', v_request.id,
        'status', v_request.status,
        'requestedAt', v_request.requested_at,
        'eligibleAt', v_request.eligible_at,
        'gracePeriodDays', 7
    );
end;
$$;

create or replace function public.cancel_account_deletion(p_user_id uuid)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare v_count integer;
begin
    update public.account_deletion_requests
    set status = 'cancelled', cancelled_at = clock_timestamp()
    where user_id = p_user_id and status = 'pending';
    get diagnostics v_count = row_count;
    return jsonb_build_object('cancelled', v_count > 0);
end;
$$;

create or replace function public.process_due_account_deletions(p_limit integer default 25)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_request public.account_deletion_requests%rowtype;
    v_processed integer := 0;
begin
    for v_request in
        select * from public.account_deletion_requests
        where status = 'pending' and eligible_at <= clock_timestamp()
        order by eligible_at, id
        for update skip locked
        limit greatest(1, least(coalesce(p_limit, 25), 100))
    loop
        update public.account_deletion_requests
        set status = 'processing'
        where id = v_request.id;
        insert into public.account_deletion_audit(
            request_id, user_reference_hash, processed_at, outcome
        ) values (
            v_request.id,
            encode(extensions.digest(v_request.user_id::text, 'sha256'), 'hex'),
            clock_timestamp(),
            'completed'
        );
        delete from public.users where id = v_request.user_id;
        v_processed := v_processed + 1;
    end loop;
    return jsonb_build_object('processed', v_processed);
end;
$$;

revoke all on function public.export_learner_data(uuid) from public, anon, authenticated;
revoke all on function public.request_account_deletion(uuid) from public, anon, authenticated;
revoke all on function public.cancel_account_deletion(uuid) from public, anon, authenticated;
revoke all on function public.process_due_account_deletions(integer) from public, anon, authenticated;
grant execute on function public.export_learner_data(uuid) to service_role;
grant execute on function public.request_account_deletion(uuid) to service_role;
grant execute on function public.cancel_account_deletion(uuid) to service_role;
grant execute on function public.process_due_account_deletions(integer) to service_role;
