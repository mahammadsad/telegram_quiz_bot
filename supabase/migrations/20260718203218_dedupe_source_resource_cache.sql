-- A micro-topic URL may accumulate multiple immutable fact versions. Select
-- one current verified version before mirroring metadata so a single cache
-- batch never proposes the same (micro_topic_id, language, url) twice.

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
        source.source_title,
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

revoke execute on function public.cache_verified_source_resources(text)
    from public, anon, authenticated;
grant execute on function public.cache_verified_source_resources(text)
    to service_role;
