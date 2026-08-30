-- A data-modifying CTE cannot read its own newly inserted rows back through the
-- base table in the same statement snapshot. Preserve the audited queue writer
-- as a private base and retry its read once only when that first call returned
-- no rows. The second statement sees committed-in-transaction inserts and
-- returns the exact ensured jobs to the caller.

alter function public.ensure_due_content_replenishment_jobs(timestamptz)
    rename to ensure_due_content_replenishment_jobs_source_optional_base;

create function public.ensure_due_content_replenishment_jobs(
    p_now timestamptz default now()
)
returns setof public.content_replenishment_jobs
language plpgsql
security invoker
set search_path = ''
as $$
begin
    return query
    select *
    from public.ensure_due_content_replenishment_jobs_source_optional_base(p_now);

    if not found then
        return query
        select *
        from public.ensure_due_content_replenishment_jobs_source_optional_base(p_now);
    end if;
end;
$$;

comment on function public.ensure_due_content_replenishment_jobs(timestamptz)
is 'Ensures and returns bounded jobs for verified stable topics and rotation-approved current-affairs topics.';
comment on function public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)
is 'Private source-backed replenishment queue writer; call the public service-role wrapper.';

revoke all on function
    public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)
    from public, anon, authenticated;
revoke all on function public.ensure_due_content_replenishment_jobs(timestamptz)
    from public, anon, authenticated;
grant execute on function
    public.ensure_due_content_replenishment_jobs_source_optional_base(timestamptz)
    to service_role;
grant execute on function public.ensure_due_content_replenishment_jobs(timestamptz)
    to service_role;
