-- Atomic, idempotent post acknowledgement and usage finalization.
-- Additive and safe to rerun after 20260801045552_leaderboard_privacy_hotfix.sql.

alter table public.quiz_runs
    add column if not exists posting_intent_fingerprint text;
alter table public.quiz_runs
    add column if not exists posting_intended_at timestamptz;
alter table public.quiz_runs
    add column if not exists telegram_acknowledged_at timestamptz;

alter table public.quiz_runs drop constraint if exists quiz_runs_posting_intent_fingerprint_check;
alter table public.quiz_runs add constraint quiz_runs_posting_intent_fingerprint_check
    check (
        posting_intent_fingerprint is null
        or posting_intent_fingerprint ~ '^[0-9a-f]{64}$'
    );

alter table public.quiz_micro_topics
    add column if not exists usage_count integer not null default 0
    check (usage_count >= 0);
alter table public.quiz_chapters
    add column if not exists usage_count integer not null default 0
    check (usage_count >= 0);
alter table public.quiz_chapters
    add column if not exists last_used_at timestamptz;
alter table public.source_documents
    add column if not exists usage_count integer not null default 0
    check (usage_count >= 0);
alter table public.source_documents
    add column if not exists last_used_at timestamptz;

create or replace function public.record_quiz_post_intent(
    p_quiz_id text,
    p_worker_id text,
    p_fingerprint text,
    p_intended_at timestamptz
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_run public.quiz_runs%rowtype;
begin
    if nullif(btrim(p_quiz_id), '') is null
       or nullif(btrim(p_worker_id), '') is null
       or p_fingerprint !~ '^[0-9a-f]{64}$'
       or p_intended_at is null then
        raise exception 'valid quiz, worker, fingerprint, and intended timestamp are required';
    end if;

    select * into v_run
    from public.quiz_runs
    where quiz_id = p_quiz_id
    for update;
    if not found then
        raise exception 'quiz run does not exist';
    end if;
    if v_run.status <> 'posting' or v_run.worker_id is distinct from p_worker_id then
        raise exception 'quiz run is not owned in posting state';
    end if;
    if not v_run.integrity_verified
       or v_run.checksum_contract_version <> 2
       or v_run.generated_checksum is null
       or v_run.generated_checksum is distinct from v_run.persisted_checksum
       or (select count(*) from public.quiz_questions where quiz_id = p_quiz_id) <> 10 then
        raise exception 'quiz pack is not checksum-certified';
    end if;
    if v_run.posting_intent_fingerprint is not null
       and v_run.posting_intent_fingerprint <> p_fingerprint then
        raise exception 'posting intent conflicts with the persisted fingerprint';
    end if;

    update public.quiz_runs
    set posting_intent_fingerprint = p_fingerprint,
        posting_intended_at = coalesce(posting_intended_at, p_intended_at),
        updated_at = now()
    where quiz_id = p_quiz_id;

    return jsonb_build_object(
        'quiz_id', p_quiz_id,
        'status', 'posting',
        'posting_intent_fingerprint', p_fingerprint
    );
end;
$$;

create or replace function public.finalize_quiz_post(
    p_quiz_id text,
    p_worker_id text,
    p_telegram_message_id bigint,
    p_acknowledged_at timestamptz,
    p_telegram_chat_id bigint,
    p_telegram_thread_id bigint,
    p_min_gap_days integer default 21,
    p_max_gap_days integer default 180
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_run public.quiz_runs%rowtype;
    v_question_count integer;
begin
    if nullif(btrim(p_quiz_id), '') is null
       or nullif(btrim(p_worker_id), '') is null
       or p_telegram_message_id is null
       or p_telegram_message_id <= 0
       or p_acknowledged_at is null then
        raise exception 'valid quiz, worker, message, and acknowledgement are required';
    end if;

    select * into v_run
    from public.quiz_runs
    where quiz_id = p_quiz_id
    for update;
    if not found then
        raise exception 'quiz run does not exist';
    end if;

    if v_run.status = 'posted' then
        if v_run.telegram_message_id = p_telegram_message_id then
            return jsonb_build_object(
                'quiz_id', p_quiz_id,
                'status', 'posted',
                'telegram_message_id', p_telegram_message_id,
                'idempotent_replay', true
            );
        end if;
        raise exception 'quiz was already finalized with a different Telegram message';
    end if;
    if v_run.telegram_message_id is not null
       and v_run.telegram_message_id <> p_telegram_message_id then
        raise exception 'Telegram message acknowledgement conflicts with existing state';
    end if;
    if v_run.status <> 'posting' or v_run.worker_id is distinct from p_worker_id then
        raise exception 'quiz run is not owned in posting state';
    end if;
    if v_run.posting_intent_fingerprint is null or v_run.posting_intended_at is null then
        raise exception 'posting intent was not persisted before delivery';
    end if;
    if not v_run.integrity_verified
       or v_run.checksum_contract_version <> 2
       or v_run.generated_checksum is null
       or v_run.generated_checksum is distinct from v_run.persisted_checksum then
        raise exception 'quiz pack is not checksum-certified';
    end if;

    select count(*) into v_question_count
    from public.quiz_questions
    where quiz_id = p_quiz_id;
    if v_question_count <> 10 then
        raise exception 'quiz pack must contain exactly 10 questions';
    end if;

    update public.questions question
    set usage_count = question.usage_count + 1,
        last_used_at = p_acknowledged_at,
        next_global_review = v_run.quiz_date + least(
            greatest(coalesce(p_max_gap_days, 180), 1),
            greatest(coalesce(p_min_gap_days, 21), 1) * (question.usage_count + 1)
        )
    from public.quiz_questions mapping
    where mapping.quiz_id = p_quiz_id
      and mapping.question_id = question.id;

    with topic_usage as (
        select question.micro_topic_id, count(*)::integer as exposure_count
        from public.quiz_questions mapping
        join public.questions question on question.id = mapping.question_id
        where mapping.quiz_id = p_quiz_id
          and question.micro_topic_id is not null
        group by question.micro_topic_id
    )
    update public.quiz_micro_topics topic
    set usage_count = topic.usage_count + topic_usage.exposure_count,
        last_used_at = p_acknowledged_at,
        updated_at = now()
    from topic_usage
    where topic.id = topic_usage.micro_topic_id;

    with source_usage as (
        select question.source_document_id, count(*)::integer as exposure_count
        from public.quiz_questions mapping
        join public.questions question on question.id = mapping.question_id
        where mapping.quiz_id = p_quiz_id
          and question.source_document_id is not null
        group by question.source_document_id
    )
    update public.source_documents source
    set usage_count = source.usage_count + source_usage.exposure_count,
        last_used_at = p_acknowledged_at,
        updated_at = now()
    from source_usage
    where source.id = source_usage.source_document_id;

    update public.quiz_chapters chapter
    set usage_count = chapter.usage_count + 1,
        last_used_at = p_acknowledged_at,
        updated_at = now()
    where chapter.subject_key = v_run.subject_key
      and chapter.name = v_run.chapter;

    insert into public.chapter_history (
        subject_key, chapter, selected_for, quiz_id
    ) values (
        v_run.subject_key, v_run.chapter, v_run.quiz_date, v_run.quiz_id
    )
    on conflict (subject_key, selected_for) do update set
        chapter = excluded.chapter,
        quiz_id = excluded.quiz_id;

    update public.quiz_runs
    set status = 'posted',
        posted_at = p_acknowledged_at,
        telegram_acknowledged_at = p_acknowledged_at,
        telegram_chat_id = p_telegram_chat_id,
        telegram_thread_id = p_telegram_thread_id,
        telegram_message_id = p_telegram_message_id,
        last_error_category = null,
        last_error_at = null,
        retryable = false,
        worker_id = null,
        claimed_at = null,
        claim_expires_at = null,
        updated_at = now()
    where quiz_id = p_quiz_id;

    return jsonb_build_object(
        'quiz_id', p_quiz_id,
        'status', 'posted',
        'telegram_message_id', p_telegram_message_id,
        'question_count', v_question_count,
        'idempotent_replay', false
    );
end;
$$;

create or replace function public.record_quiz_post_unknown(
    p_quiz_id text,
    p_worker_id text,
    p_telegram_message_id bigint,
    p_acknowledged_at timestamptz,
    p_telegram_chat_id bigint,
    p_telegram_thread_id bigint,
    p_error_category text
)
returns jsonb
language plpgsql
security definer
set search_path = ''
as $$
declare
    v_run public.quiz_runs%rowtype;
begin
    select * into v_run
    from public.quiz_runs
    where quiz_id = p_quiz_id
    for update;
    if not found then
        raise exception 'quiz run does not exist';
    end if;
    if v_run.status = 'posted' then
        if v_run.telegram_message_id = p_telegram_message_id then
            return jsonb_build_object(
                'quiz_id', p_quiz_id, 'status', 'posted', 'idempotent_replay', true
            );
        end if;
        raise exception 'posted quiz cannot be changed to unknown';
    end if;
    if v_run.worker_id is distinct from p_worker_id or v_run.status <> 'posting' then
        raise exception 'quiz run is not owned in posting state';
    end if;
    if v_run.telegram_message_id is not null
       and v_run.telegram_message_id <> p_telegram_message_id then
        raise exception 'Telegram message acknowledgement conflicts with existing state';
    end if;

    update public.quiz_runs
    set status = 'posting_unknown',
        telegram_message_id = coalesce(telegram_message_id, p_telegram_message_id),
        telegram_acknowledged_at = coalesce(telegram_acknowledged_at, p_acknowledged_at),
        telegram_chat_id = coalesce(telegram_chat_id, p_telegram_chat_id),
        telegram_thread_id = coalesce(telegram_thread_id, p_telegram_thread_id),
        last_error_category = coalesce(nullif(btrim(p_error_category), ''), 'post_finalization_failed'),
        last_error_at = now(),
        retryable = false,
        worker_id = null,
        claimed_at = null,
        claim_expires_at = null,
        updated_at = now()
    where quiz_id = p_quiz_id;

    return jsonb_build_object(
        'quiz_id', p_quiz_id,
        'status', 'posting_unknown',
        'telegram_message_id', p_telegram_message_id
    );
end;
$$;

create or replace function public.get_post_finalization_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_columns(table_name, column_name) as (
        values
            ('quiz_runs', 'posting_intent_fingerprint'),
            ('quiz_runs', 'posting_intended_at'),
            ('quiz_runs', 'telegram_acknowledged_at'),
            ('quiz_micro_topics', 'usage_count'),
            ('quiz_chapters', 'usage_count'),
            ('quiz_chapters', 'last_used_at'),
            ('source_documents', 'usage_count'),
            ('source_documents', 'last_used_at')
    ), missing_columns as (
        select format('%s.%s', required.table_name, required.column_name) as name
        from required_columns required
        where not exists (
            select 1
            from information_schema.columns column_info
            where column_info.table_schema = 'public'
              and column_info.table_name = required.table_name
              and column_info.column_name = required.column_name
        )
    ), function_permissions as (
        select * from (values
            ('record_quiz_post_intent(text,text,text,timestamp with time zone)'),
            ('finalize_quiz_post(text,text,bigint,timestamp with time zone,bigint,bigint,integer,integer)'),
            ('record_quiz_post_unknown(text,text,bigint,timestamp with time zone,bigint,bigint,text)')
        ) functions(signature)
    ), permission_failures as (
        select role_name || ':' || functions.signature as failure
        from function_permissions functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(
            roles.role_name,
            'public.' || functions.signature,
            'EXECUTE'
        )
        union all
        select 'service_role:' || functions.signature
        from function_permissions functions
        where not has_function_privilege(
            'service_role',
            'public.' || functions.signature,
            'EXECUTE'
        )
    ), facts as (
        select
            coalesce((select jsonb_agg(name order by name) from missing_columns), '[]'::jsonb)
                as missing_columns,
            coalesce((select jsonb_agg(failure order by failure) from permission_failures), '[]'::jsonb)
                as function_permission_failures,
            to_regprocedure('public.record_quiz_post_intent(text,text,text,timestamp with time zone)') is not null
                and to_regprocedure('public.finalize_quiz_post(text,text,bigint,timestamp with time zone,bigint,bigint,integer,integer)') is not null
                and to_regprocedure('public.record_quiz_post_unknown(text,text,bigint,timestamp with time zone,bigint,bigint,text)') is not null
                as functions_ready
    )
    select jsonb_build_object(
        'post_finalization_migration_version', '20260808063007',
        'post_finalization_migration_applied',
            jsonb_array_length(facts.missing_columns) = 0 and facts.functions_ready,
        'ready',
            jsonb_array_length(facts.missing_columns) = 0
            and jsonb_array_length(facts.function_permission_failures) = 0
            and facts.functions_ready,
        'missing_columns', facts.missing_columns,
        'function_permission_failures', facts.function_permission_failures
    )
    from facts;
$$;

revoke all on function public.record_quiz_post_intent(text, text, text, timestamptz)
    from public, anon, authenticated;
revoke all on function public.finalize_quiz_post(
    text, text, bigint, timestamptz, bigint, bigint, integer, integer
) from public, anon, authenticated;
revoke all on function public.record_quiz_post_unknown(
    text, text, bigint, timestamptz, bigint, bigint, text
) from public, anon, authenticated;
revoke all on function public.get_post_finalization_contract()
    from public, anon, authenticated;

grant execute on function public.record_quiz_post_intent(text, text, text, timestamptz)
    to service_role;
grant execute on function public.finalize_quiz_post(
    text, text, bigint, timestamptz, bigint, bigint, integer, integer
) to service_role;
grant execute on function public.record_quiz_post_unknown(
    text, text, bigint, timestamptz, bigint, bigint, text
) to service_role;
grant execute on function public.get_post_finalization_contract()
    to service_role;
