-- Keep the exact verified atomic claim in the generation prompt while hashing
-- the immutable source-document summary that save_quiz_pack_atomic verifies.

drop function if exists public.get_current_affairs_grounding_bundle(text,date,integer);

create function public.get_current_affairs_grounding_bundle(
    p_chapter text,
    p_target_date date,
    p_limit integer default 8
)
returns table (
    source_document_id uuid,
    micro_topic_id uuid,
    micro_topic_key text,
    micro_topic_name text,
    source_url text,
    source_title text,
    source_domain text,
    source_kind text,
    source_published_at timestamptz,
    source_accessed_at timestamptz,
    fact_summary text,
    fact_version text,
    expires_at timestamptz,
    current_affairs_event_date date,
    current_affairs_practice_pool text,
    current_affairs_verification_policy text,
    current_affairs_canonical_claim text
)
language sql
stable
security invoker
set search_path = ''
as $$
    with pool as (
        select *
        from public.get_current_affairs_practice_pool(
            p_target_date, 'daily_quick', least(coalesce(p_limit, 8) * 6, 200)
        )
    ), evidence as (
        select
            pool.*,
            source.id as source_document_id,
            source.micro_topic_id,
            topic.key as micro_topic_key,
            topic.name as micro_topic_name,
            source.source_url,
            source.source_title,
            source.source_domain,
            source.source_kind,
            source.source_published_at,
            source.source_accessed_at,
            source.fact_summary as source_fact_summary,
            source.fact_version,
            least(source.expires_at, pool.expires_at) as effective_expiry,
            row_number() over (
                partition by pool.claim_id
                order by link.is_primary desc, source.source_published_at desc, source.id
            ) as evidence_rank
        from pool
        join public.current_affairs_claim_evidence link
          on link.claim_id = pool.claim_id
        join public.source_facts fact on fact.id = link.source_fact_id
        join public.source_documents source on source.id = fact.source_document_id
        join public.quiz_micro_topics topic on topic.id = source.micro_topic_id
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        where chapter.subject_key = 'current-affairs'
          and chapter.name = p_chapter
          and source.verification_status = 'verified'
          and not source.review_required
          and fact.verification_status = 'verified'
          and not fact.review_required
          and (source.expires_at is null or source.expires_at::date >= p_target_date)
    )
    select
        evidence.source_document_id,
        evidence.micro_topic_id,
        evidence.micro_topic_key,
        evidence.micro_topic_name,
        evidence.source_url,
        evidence.source_title,
        evidence.source_domain,
        evidence.source_kind,
        evidence.source_published_at,
        evidence.source_accessed_at,
        evidence.source_fact_summary as fact_summary,
        evidence.fact_version,
        evidence.effective_expiry as expires_at,
        evidence.event_date as current_affairs_event_date,
        evidence.practice_pool as current_affairs_practice_pool,
        evidence.verification_policy as current_affairs_verification_policy,
        evidence.canonical_claim as current_affairs_canonical_claim
    from evidence
    where evidence.evidence_rank = 1
    order by
        evidence.importance * evidence.category_weight desc,
        evidence.corroborating_sources desc,
        evidence.event_date desc,
        evidence.cluster_key,
        evidence.claim_id
    limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

revoke all on function public.get_current_affairs_grounding_bundle(text,date,integer)
    from public, anon, authenticated;
grant execute on function public.get_current_affairs_grounding_bundle(text,date,integer)
    to service_role;

create or replace function public.get_phase_d_current_affairs_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_functions(signature) as (values
        ('upsert_current_affairs_event_bundle(uuid,jsonb)'),
        ('get_current_affairs_practice_pool(date,text,integer)'),
        ('get_current_affairs_grounding_bundle(text,date,integer)')
    ), function_permission_failures as (
        select role_name || ':' || signature as failure
        from required_functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
        union all
        select 'service_role:' || signature from required_functions
        where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
    ), required_tables(name) as (values
        ('current_affairs_events'), ('current_affairs_event_sources'),
        ('current_affairs_event_claims'), ('current_affairs_claim_evidence'),
        ('current_affairs_category_weights'), ('current_affairs_review_events')
    ), table_permission_failures as (
        select role_name || ':' || name as failure
        from required_tables
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_table_privilege(role_name, 'public.' || name, 'SELECT')
           or has_table_privilege(role_name, 'public.' || name, 'INSERT')
           or has_table_privilege(role_name, 'public.' || name, 'UPDATE')
           or has_table_privilege(role_name, 'public.' || name, 'DELETE')
    )
    select jsonb_build_object(
        'ready',
            to_regclass('public.current_affairs_events') is not null
            and to_regclass('public.current_affairs_event_claims') is not null
            and to_regclass('public.current_affairs_claim_evidence') is not null
            and to_regprocedure('public.upsert_current_affairs_event_bundle(uuid,jsonb)') is not null
            and to_regprocedure('public.get_current_affairs_practice_pool(date,text,integer)') is not null
            and to_regprocedure('public.get_current_affairs_grounding_bundle(text,date,integer)') is not null
            and not exists (select 1 from function_permission_failures)
            and not exists (select 1 from table_permission_failures),
        'event_dates', true,
        'multi_source_clusters', true,
        'atomic_claims', true,
        'correction_and_expiry', true,
        'weighted_revision_pools', true,
        'claim_projection_parity', true,
        'function_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from function_permission_failures),
            '[]'::jsonb
        ),
        'table_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from table_permission_failures),
            '[]'::jsonb
        ),
        'phase_d_current_affairs_migration_version', '20260809010000'
    );
$$;

revoke all on function public.get_phase_d_current_affairs_contract()
    from public, anon, authenticated;
grant execute on function public.get_phase_d_current_affairs_contract()
    to service_role;
