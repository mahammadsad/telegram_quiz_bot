-- Build each current-affairs grounding bundle inside its requested chapter.
-- The previous implementation limited the global weighted pool first, which
-- allowed high-volume categories to starve an otherwise healthy chapter.

create or replace function public.get_current_affairs_grounding_bundle(
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
    with claim_counts as (
        select evidence.claim_id,
            count(distinct evidence.source_fact_id) as corroborating_sources
        from public.current_affairs_claim_evidence evidence
        group by evidence.claim_id
    ), eligible as (
        select
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
            source.fact_summary,
            source.fact_version,
            least(source.expires_at, claim.expires_at) as effective_expiry,
            event.event_date,
            case
                when p_target_date - event.event_date between 0 and 7 then 'daily'
                when p_target_date - event.event_date between 8 and 30 then 'weekly'
                when p_target_date - event.event_date between 31 and 90 then 'monthly'
                when p_target_date - event.event_date between 91 and 180
                     and event.importance >= 4 then 'six_month'
            end as practice_pool,
            event.verification_policy,
            claim.canonical_claim,
            event.importance,
            coalesce(weight.weight, 1.0) as category_weight,
            counts.corroborating_sources,
            event.cluster_key,
            claim.id as claim_id,
            row_number() over (
                partition by claim.id
                order by evidence.is_primary desc,
                    source.source_published_at desc,
                    source.id
            ) as evidence_rank
        from public.current_affairs_events event
        join public.current_affairs_event_claims claim on claim.event_id = event.id
        join claim_counts counts on counts.claim_id = claim.id
        join public.current_affairs_claim_evidence evidence on evidence.claim_id = claim.id
        join public.source_facts fact on fact.id = evidence.source_fact_id
        join public.source_documents source on source.id = fact.source_document_id
        join public.quiz_micro_topics topic on topic.id = source.micro_topic_id
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        left join lateral (
            select configured.weight
            from public.current_affairs_category_weights configured
            where configured.test_definition_key = 'daily_quick'
              and configured.category = event.category
              and configured.effective_from <= p_target_date
              and (
                  configured.effective_until is null
                  or configured.effective_until >= p_target_date
              )
            order by configured.effective_from desc
            limit 1
        ) weight on true
        where chapter.subject_key = 'current-affairs'
          and chapter.name = p_chapter
          and chapter.active
          and chapter.rotation_enabled
          and topic.active
          and event.verification_status = 'verified'
          and not event.review_required
          and claim.verification_status = 'verified'
          and not claim.review_required
          and event.event_date between p_target_date - 180 and p_target_date
          and claim.valid_from::date <= p_target_date
          and claim.expires_at::date >= p_target_date
          and source.verification_status = 'verified'
          and not source.review_required
          and source.source_kind in ('official', 'primary')
          and (source.expires_at is null or source.expires_at::date >= p_target_date)
          and fact.verification_status = 'verified'
          and not fact.review_required
          and (fact.expires_at is null or fact.expires_at::date >= p_target_date)
          and (
              fact.effective_until is null
              or fact.effective_until::date >= p_target_date
          )
    )
    select
        eligible.source_document_id,
        eligible.micro_topic_id,
        eligible.micro_topic_key,
        eligible.micro_topic_name,
        eligible.source_url,
        eligible.source_title,
        eligible.source_domain,
        eligible.source_kind,
        eligible.source_published_at,
        eligible.source_accessed_at,
        eligible.fact_summary,
        eligible.fact_version,
        eligible.effective_expiry as expires_at,
        eligible.event_date as current_affairs_event_date,
        eligible.practice_pool as current_affairs_practice_pool,
        eligible.verification_policy as current_affairs_verification_policy,
        eligible.canonical_claim as current_affairs_canonical_claim
    from eligible
    where eligible.evidence_rank = 1
      and eligible.practice_pool is not null
    order by
        eligible.importance * eligible.category_weight desc,
        eligible.corroborating_sources desc,
        eligible.event_date desc,
        eligible.cluster_key,
        eligible.claim_id
    limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

revoke all on function public.get_current_affairs_grounding_bundle(text,date,integer)
    from public, anon, authenticated;
grant execute on function public.get_current_affairs_grounding_bundle(text,date,integer)
    to service_role;

alter function public.get_application_schema_contract_v220_source_rollout_base()
    rename to get_application_schema_contract_v220_source_rollout_before_chapter_grounding;

revoke all on function
    public.get_application_schema_contract_v220_source_rollout_before_chapter_grounding()
    from public, anon, authenticated;

create function public.get_application_schema_contract_v220_source_rollout_base()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_migration_applied boolean := false;
    v_generation_coverage_ready boolean := false;
begin
    v_base := public.get_application_schema_contract_v220_source_rollout_before_chapter_grounding();
    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = '20260905043800'
                   or name = 'current_affairs_chapter_grounding'
            )
        $migration_check$ into v_migration_applied;
    end if;

    with required_chapter(name) as (
        values
            ('জাতীয় সাম্প্রতিক ঘটনা'),
            ('বিজ্ঞান ও প্রযুক্তি'),
            ('অর্থনীতি, প্রতিবেদন ও সূচক')
    )
    select not exists (
        select 1 from required_chapter
        where not exists (
            select 1
            from public.get_current_affairs_grounding_bundle(
                required_chapter.name,
                (now() at time zone 'Asia/Kolkata')::date,
                1
            )
        )
    ) into v_generation_coverage_ready;

    return v_base || jsonb_build_object(
        'current_affairs_chapter_grounding_migration_version', '20260905043800',
        'current_affairs_chapter_grounding_migration_applied', v_migration_applied,
        'current_affairs_generation_coverage_ready', v_generation_coverage_ready,
        'source_coverage_ready',
            coalesce((v_base->>'source_coverage_ready')::boolean, false)
            and v_generation_coverage_ready,
        'ready', coalesce((v_base->>'ready')::boolean, false) and v_migration_applied
    );
end;
$$;

revoke all on function public.get_application_schema_contract_v220_source_rollout_base()
    from public, anon, authenticated;
grant execute on function
    public.get_application_schema_contract_v220_source_rollout_before_chapter_grounding()
    to service_role;
grant execute on function public.get_application_schema_contract_v220_source_rollout_base()
    to service_role;

alter function public.get_platform_contract_v1()
    rename to get_platform_contract_v1_before_current_affairs_chapter_grounding;

revoke all on function public.get_platform_contract_v1_before_current_affairs_chapter_grounding()
    from public, anon, authenticated;

create function public.get_platform_contract_v1()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_checks jsonb;
    v_missing jsonb;
    v_migration_applied boolean := false;
begin
    v_base := public.get_platform_contract_v1_before_current_affairs_chapter_grounding();
    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = '20260905043800'
                   or name = 'current_affairs_chapter_grounding'
            )
        $migration_check$ into v_migration_applied;
    end if;

    v_checks := coalesce(v_base->'checks', '{}'::jsonb)
        || jsonb_build_object('currentAffairsChapterGrounding', v_migration_applied);
    select coalesce(jsonb_agg(key order by key), '[]'::jsonb)
    into v_missing
    from jsonb_each(v_checks)
    where value is distinct from 'true'::jsonb;

    return v_base || jsonb_build_object(
        'ready', jsonb_array_length(v_missing) = 0,
        'contract_version', '1.5.0',
        'required_migration_version', '20260905043800',
        'migration_applied', v_migration_applied,
        'checks', v_checks,
        'missing_checks', v_missing
    );
end;
$$;

revoke all on function public.get_platform_contract_v1()
    from public, anon, authenticated;
grant execute on function public.get_platform_contract_v1() to service_role;
