-- Official publishers sometimes expose page titles longer than the public
-- learning-resource projection permits. Keep the immutable source document
-- intact and bound only the cached display metadata.

create or replace function public.cache_verified_source_resources(p_subject_key text)
returns bigint
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_count bigint;
begin
    if p_subject_key is null or btrim(p_subject_key) = '' then
        raise exception 'subject key is required';
    end if;

    with current_sources as (
        select distinct on (sd.micro_topic_id, sd.source_url)
            sd.*,
            c.subject_key,
            c.key as chapter_key,
            mt.key as micro_topic_key
        from public.source_documents sd
        join public.quiz_micro_topics mt on mt.id = sd.micro_topic_id
        join public.quiz_chapters c on c.id = mt.chapter_id
        where c.subject_key = p_subject_key
          and c.key is not null
          and sd.verification_status = 'verified'
          and not sd.review_required
          and (sd.expires_at is null or sd.expires_at >= now())
        order by
            sd.micro_topic_id,
            sd.source_url,
            sd.source_accessed_at desc,
            sd.verified_at desc,
            sd.created_at desc,
            sd.id desc
    )
    insert into public.learning_resources (
        subject_key, chapter_key, micro_topic_id, micro_topic_key,
        source_document_id, language, resource_type, title, url,
        source_name, source_domain, description, quality_score,
        relevance_score, verified, verification_status, is_active,
        last_checked_at, published_at, approved_by, verified_at
    )
    select
        source.subject_key,
        source.chapter_key,
        source.micro_topic_id,
        source.micro_topic_key,
        source.id,
        'en',
        case
            when lower(source.source_url) ~ '\.pdf($|[?#])' then 'pdf'
            else 'official_webpage'
        end,
        left(btrim(source.source_title), 300),
        source.source_url,
        case
            when source.source_domain = 'nios.ac.in' then 'NIOS'
            when source.source_domain = 'support.microsoft.com' then 'Microsoft Support'
            when source.source_domain = 'cybercrime.gov.in' then 'Ministry of Home Affairs'
            else source.source_domain
        end,
        source.source_domain,
        'Operator-approved reference used to ground this quiz topic.',
        case source.source_kind when 'official' then 1.0 when 'primary' then 0.95 else 0.80 end,
        0.90,
        true,
        'verified',
        true,
        source.source_accessed_at,
        source.source_published_at,
        'approved-source-bundle',
        source.verified_at
    from current_sources source
    on conflict (micro_topic_id, language, url) do update set
        is_active = true,
        last_checked_at = excluded.last_checked_at,
        failure_count = 0,
        updated_at = now();

    get diagnostics v_count = row_count;
    return v_count;
end;
$$;

create or replace function public.get_source_optional_generation_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'migration_version', '20260809003000',
        'ready',
            to_regprocedure('public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)') is not null
            and to_regprocedure('public.cache_verified_source_resources(text)') is not null
            and exists (
                select 1 from information_schema.columns
                where table_schema = 'public'
                  and table_name = 'question_verifications'
                  and column_name = 'verification_basis'
            )
            and not has_function_privilege(
                'anon',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            )
            and not has_function_privilege(
                'authenticated',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            )
            and has_function_privilege(
                'service_role',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            )
            and not has_function_privilege(
                'anon', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            )
            and not has_function_privilege(
                'authenticated', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            )
            and has_function_privilege(
                'service_role', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            ),
        'current_affairs_source_required', true,
        'knowledge_cooldown_days', 30,
        'function_permission_failures', to_jsonb(array_remove(array[
            case when has_function_privilege(
                'anon',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            ) then 'anon:save_model_validated_quiz_pack_atomic' end,
            case when has_function_privilege(
                'authenticated',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            ) then 'authenticated:save_model_validated_quiz_pack_atomic' end,
            case when not has_function_privilege(
                'service_role',
                'public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)',
                'EXECUTE'
            ) then 'service_role:save_model_validated_quiz_pack_atomic' end,
            case when has_function_privilege(
                'anon', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            ) then 'anon:cache_verified_source_resources' end,
            case when has_function_privilege(
                'authenticated', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            ) then 'authenticated:cache_verified_source_resources' end,
            case when not has_function_privilege(
                'service_role', 'public.cache_verified_source_resources(text)', 'EXECUTE'
            ) then 'service_role:cache_verified_source_resources' end
        ], null))
    );
$$;

revoke all on function public.cache_verified_source_resources(text)
    from public, anon, authenticated;
revoke all on function public.get_source_optional_generation_contract()
    from public, anon, authenticated;
grant execute on function public.cache_verified_source_resources(text)
    to service_role;
grant execute on function public.get_source_optional_generation_contract()
    to service_role;
