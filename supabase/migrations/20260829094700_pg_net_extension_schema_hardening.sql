-- Supabase's security advisor flags extensions whose ownership namespace is
-- public. pg_net is non-relocatable after installation, so move it only while
-- both the application audit ledger and pg_net request queue are empty.

do $$
declare
    v_extension_schema text;
    v_extension_version text;
begin
    select namespace.nspname, extension.extversion
    into v_extension_schema, v_extension_version
    from pg_extension extension
    join pg_namespace namespace on namespace.oid = extension.extnamespace
    where extension.extname = 'pg_net';

    if not found or v_extension_schema <> 'public' then
        return;
    end if;

    if exists (
        select 1 from private.scheduler_dispatch_requests
        where outcome = 'queued'
    ) then
        raise exception 'cannot move pg_net while scheduler requests are awaiting reconciliation';
    end if;
    if to_regclass('net.http_request_queue') is not null
       and exists (select 1 from net.http_request_queue) then
        raise exception 'cannot move pg_net while HTTP requests are queued';
    end if;

    create schema if not exists extensions;
    drop extension pg_net;
    execute format(
        'create extension pg_net with schema extensions version %L',
        v_extension_version
    );

    if not exists (
        select 1
        from pg_extension extension
        join pg_namespace namespace on namespace.oid = extension.extnamespace
        where extension.extname = 'pg_net'
          and namespace.nspname = 'extensions'
    ) then
        raise exception 'pg_net was not recreated in the extensions schema';
    end if;
end;
$$;
