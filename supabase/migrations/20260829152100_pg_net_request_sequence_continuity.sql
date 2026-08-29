-- Reinstalling non-relocatable pg_net recreates its request ID sequence. Keep
-- future request IDs above the durable scheduler audit history so the first
-- post-reinstall dispatch cannot collide with an older request.

do $$
declare
    v_audit_max bigint;
    v_sequence_last bigint;
    v_sequence_called boolean;
begin
    if to_regclass('net.http_request_queue_id_seq') is null
       or to_regclass('private.scheduler_dispatch_requests') is null then
        return;
    end if;

    select max(request_id) into v_audit_max
    from private.scheduler_dispatch_requests;
    if v_audit_max is null then
        return;
    end if;

    select last_value, is_called
    into v_sequence_last, v_sequence_called
    from net.http_request_queue_id_seq;

    if v_sequence_last < v_audit_max
       or (v_sequence_last = v_audit_max and not v_sequence_called) then
        perform setval('net.http_request_queue_id_seq'::regclass, v_audit_max, true);
    end if;
end;
$$;
