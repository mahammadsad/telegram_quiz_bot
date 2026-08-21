-- Allow a service-role operator to reconcile a Telegram acknowledgement that
-- was durably recorded after database finalization failed.  Recovery is only
-- accepted when every supplied Telegram identifier matches the stored receipt;
-- it never sends another message.

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
    v_effective_acknowledged_at timestamptz;
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

    if v_run.status = 'posting_unknown' then
        if v_run.worker_id is not null
           or v_run.telegram_message_id is distinct from p_telegram_message_id
           or v_run.telegram_acknowledged_at is null
           or v_run.telegram_chat_id is distinct from p_telegram_chat_id
           or v_run.telegram_thread_id is distinct from p_telegram_thread_id then
            raise exception 'stored Telegram acknowledgement does not match recovery request';
        end if;
        v_effective_acknowledged_at := v_run.telegram_acknowledged_at;
    elsif v_run.status = 'posting' and v_run.worker_id is not distinct from p_worker_id then
        v_effective_acknowledged_at := p_acknowledged_at;
    else
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
        last_used_at = v_effective_acknowledged_at,
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
        last_used_at = v_effective_acknowledged_at,
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
        last_used_at = v_effective_acknowledged_at,
        updated_at = now()
    from source_usage
    where source.id = source_usage.source_document_id;

    update public.quiz_chapters chapter
    set usage_count = chapter.usage_count + 1,
        last_used_at = v_effective_acknowledged_at,
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
        posted_at = v_effective_acknowledged_at,
        telegram_acknowledged_at = v_effective_acknowledged_at,
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
        'reconciled_unknown', v_run.status = 'posting_unknown',
        'idempotent_replay', false
    );
end;
$$;

revoke all on function public.finalize_quiz_post(
    text, text, bigint, timestamptz, bigint, bigint, integer, integer
) from public, anon, authenticated;
grant execute on function public.finalize_quiz_post(
    text, text, bigint, timestamptz, bigint, bigint, integer, integer
) to service_role;
