-- Phase D: first-class current-affairs events, exact-span atomic claims,
-- correction/expiry state, multi-source corroboration, and revision pools.

create table if not exists public.current_affairs_events (
    id uuid primary key default extensions.gen_random_uuid(),
    cluster_key text not null unique check (cluster_key ~ '^[0-9a-f]{64}$'),
    cluster_version smallint not null default 1 check (cluster_version > 0),
    event_title text not null check (length(btrim(event_title)) >= 8),
    event_date date not null,
    event_end_date date,
    event_date_precision text not null
        check (event_date_precision in ('explicit','publication_fallback','date_range')),
    geography text not null
        check (geography in ('india','west_bengal','international')),
    category text not null check (category in (
        'west_bengal','economy_banking','science_technology','schemes',
        'appointments_awards','international','sports','reports_indices',
        'polity_governance'
    )),
    organizations text[] not null default '{}',
    importance smallint not null check (importance between 1 and 5),
    confidence numeric not null check (confidence between 0 and 1),
    valid_from timestamptz not null,
    review_after timestamptz not null,
    expires_at timestamptz not null,
    correction_state text not null default 'none'
        check (correction_state in ('none','suspected','confirmed','superseded')),
    supersedes_event_id uuid
        references public.current_affairs_events(id) on delete restrict,
    verification_policy text not null,
    verification_status text not null default 'review_required' check (
        verification_status in (
            'draft','review_required','verified','corrected','superseded',
            'expired','quarantined'
        )
    ),
    review_required boolean not null default true,
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    check (event_end_date is null or event_end_date >= event_date),
    check (review_after >= valid_from and expires_at >= review_after),
    check (verification_status <> 'verified' or (not review_required and verified_at is not null))
);

create index if not exists idx_current_affairs_events_supersedes
    on public.current_affairs_events (supersedes_event_id)
    where supersedes_event_id is not null;
create index if not exists idx_current_affairs_events_pool
    on public.current_affairs_events (
        verification_status, event_date desc, category, geography, importance desc
    ) where not review_required;
create index if not exists idx_current_affairs_events_review
    on public.current_affairs_events (review_required, correction_state, review_after);

create table if not exists public.current_affairs_event_sources (
    event_id uuid not null
        references public.current_affairs_events(id) on delete restrict,
    source_document_id uuid not null
        references public.source_documents(id) on delete restrict,
    publication_date date not null,
    update_date date,
    source_domain text not null,
    is_authoritative boolean not null default true,
    created_at timestamptz not null default now(),
    primary key (event_id, source_document_id)
);

create index if not exists idx_current_affairs_event_sources_document
    on public.current_affairs_event_sources (source_document_id);

create table if not exists public.current_affairs_event_claims (
    id uuid primary key default extensions.gen_random_uuid(),
    event_id uuid not null
        references public.current_affairs_events(id) on delete restrict,
    claim_key text not null check (claim_key ~ '^[0-9a-f]{64}$'),
    canonical_claim text not null check (length(btrim(canonical_claim)) >= 40),
    valid_from timestamptz not null,
    review_after timestamptz not null,
    expires_at timestamptz not null,
    supersedes_claim_id uuid
        references public.current_affairs_event_claims(id) on delete restrict,
    verification_policy text not null,
    verification_status text not null default 'review_required' check (
        verification_status in (
            'draft','review_required','verified','corrected','superseded',
            'expired','quarantined'
        )
    ),
    review_required boolean not null default true,
    verified_at timestamptz,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now(),
    unique (event_id, claim_key),
    check (review_after >= valid_from and expires_at >= review_after),
    check (verification_status <> 'verified' or (not review_required and verified_at is not null))
);

create index if not exists idx_current_affairs_claims_event
    on public.current_affairs_event_claims (event_id);
create index if not exists idx_current_affairs_claims_supersedes
    on public.current_affairs_event_claims (supersedes_claim_id)
    where supersedes_claim_id is not null;
create index if not exists idx_current_affairs_claims_eligible
    on public.current_affairs_event_claims (expires_at, review_after)
    where verification_status = 'verified' and not review_required;

create table if not exists public.current_affairs_claim_evidence (
    claim_id uuid not null
        references public.current_affairs_event_claims(id) on delete restrict,
    source_fact_id uuid not null
        references public.source_facts(id) on delete restrict,
    is_primary boolean not null default true,
    created_at timestamptz not null default now(),
    primary key (claim_id, source_fact_id)
);

create index if not exists idx_current_affairs_claim_evidence_fact
    on public.current_affairs_claim_evidence (source_fact_id);

create table if not exists public.current_affairs_category_weights (
    test_definition_key text not null,
    category text not null check (category in (
        'west_bengal','economy_banking','science_technology','schemes',
        'appointments_awards','international','sports','reports_indices',
        'polity_governance'
    )),
    weight numeric not null check (weight > 0 and weight <= 10),
    effective_from date not null,
    effective_until date,
    created_at timestamptz not null default now(),
    primary key (test_definition_key, category, effective_from),
    check (effective_until is null or effective_until >= effective_from)
);

insert into public.current_affairs_category_weights (
    test_definition_key, category, weight, effective_from
) values
    ('daily_quick','west_bengal',1.35,'2026-08-08'),
    ('daily_quick','economy_banking',1.20,'2026-08-08'),
    ('daily_quick','science_technology',1.15,'2026-08-08'),
    ('daily_quick','schemes',1.10,'2026-08-08'),
    ('daily_quick','appointments_awards',1.00,'2026-08-08'),
    ('daily_quick','international',0.95,'2026-08-08'),
    ('daily_quick','sports',0.90,'2026-08-08'),
    ('daily_quick','reports_indices',1.00,'2026-08-08'),
    ('daily_quick','polity_governance',1.10,'2026-08-08')
on conflict (test_definition_key, category, effective_from) do update set
    weight = excluded.weight;

create table if not exists public.current_affairs_review_events (
    id bigint generated always as identity primary key,
    event_id uuid references public.current_affairs_events(id) on delete restrict,
    claim_id uuid references public.current_affairs_event_claims(id) on delete restrict,
    decision text not null check (decision in (
        'submitted','verified','rejected','corrected','superseded',
        'expired','quarantined','reinstated'
    )),
    reviewer_ref text,
    notes text,
    metadata jsonb not null default '{}'::jsonb
        check (jsonb_typeof(metadata) = 'object'),
    created_at timestamptz not null default now(),
    check (num_nonnulls(event_id, claim_id) >= 1)
);

create index if not exists idx_current_affairs_reviews_event
    on public.current_affairs_review_events (event_id, created_at desc)
    where event_id is not null;
create index if not exists idx_current_affairs_reviews_claim
    on public.current_affairs_review_events (claim_id, created_at desc)
    where claim_id is not null;

drop trigger if exists protect_current_affairs_review_events_append_only
    on public.current_affairs_review_events;
create trigger protect_current_affairs_review_events_append_only
before update or delete on public.current_affairs_review_events
for each row execute function public.reject_append_only_content_mutation();

create or replace function public.upsert_current_affairs_event_bundle(
    p_source_document_id uuid,
    p_event jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_source public.source_documents%rowtype;
    v_event public.current_affairs_events%rowtype;
    v_claim public.current_affairs_event_claims%rowtype;
    v_fact public.source_facts%rowtype;
    v_item jsonb;
    v_claim_count integer := 0;
    v_verified boolean;
begin
    if p_source_document_id is null or jsonb_typeof(p_event) <> 'object' then
        raise exception 'source document and event object are required';
    end if;
    select source.* into v_source
    from public.source_documents source
    join public.quiz_micro_topics topic on topic.id = source.micro_topic_id
    join public.quiz_chapters chapter on chapter.id = topic.chapter_id
    where source.id = p_source_document_id
      and chapter.subject_key = 'current-affairs'
    for update of source;
    if not found then
        raise exception 'current-affairs source document does not exist';
    end if;
    if p_event ->> 'cluster_key' !~ '^[0-9a-f]{64}$'
       or (p_event ->> 'cluster_version')::integer <> 1
       or nullif(btrim(p_event ->> 'event_title'), '') is null
       or p_event ->> 'verification_policy' <> 'official_exact_span_v1'
       or jsonb_typeof(p_event -> 'claims') <> 'array'
       or jsonb_array_length(p_event -> 'claims') not between 1 and 8 then
        raise exception 'current-affairs event contract failed';
    end if;
    v_verified := coalesce((p_event ->> 'verification_status') = 'verified', false)
        and not coalesce((p_event ->> 'review_required')::boolean, true)
        and coalesce(p_event ->> 'correction_state', 'none') = 'none';

    insert into public.current_affairs_events (
        cluster_key, cluster_version, event_title, event_date, event_end_date,
        event_date_precision, geography, category, organizations, importance,
        confidence, valid_from, review_after, expires_at, correction_state,
        verification_policy, verification_status, review_required, verified_at
    ) values (
        p_event ->> 'cluster_key', (p_event ->> 'cluster_version')::smallint,
        p_event ->> 'event_title', (p_event ->> 'event_date')::date,
        nullif(p_event ->> 'event_end_date', '')::date,
        p_event ->> 'event_date_precision', p_event ->> 'geography',
        p_event ->> 'category',
        array(select jsonb_array_elements_text(coalesce(p_event -> 'organizations', '[]'::jsonb))),
        (p_event ->> 'importance')::smallint,
        (p_event ->> 'confidence')::numeric,
        (p_event ->> 'valid_from')::timestamptz,
        (p_event ->> 'review_after')::timestamptz,
        (p_event ->> 'expires_at')::timestamptz,
        coalesce(p_event ->> 'correction_state', 'none'),
        p_event ->> 'verification_policy',
        case when v_verified then 'verified' else 'review_required' end,
        not v_verified, case when v_verified then now() else null end
    ) on conflict (cluster_key) do update set
        importance = greatest(public.current_affairs_events.importance, excluded.importance),
        confidence = greatest(public.current_affairs_events.confidence, excluded.confidence),
        correction_state = case
            when excluded.correction_state <> 'none' then excluded.correction_state
            else public.current_affairs_events.correction_state
        end,
        review_required = public.current_affairs_events.review_required or excluded.review_required,
        verification_status = case
            when public.current_affairs_events.review_required or excluded.review_required
                then 'review_required'
            else 'verified'
        end,
        updated_at = now()
    returning * into v_event;

    insert into public.current_affairs_event_sources (
        event_id, source_document_id, publication_date, update_date,
        source_domain, is_authoritative
    ) values (
        v_event.id, v_source.id,
        coalesce((p_event ->> 'publication_date')::date, v_source.source_published_at::date),
        v_source.updated_at::date, v_source.source_domain,
        v_source.source_kind in ('official','primary')
    ) on conflict (event_id, source_document_id) do nothing;

    for v_item in select value from jsonb_array_elements(p_event -> 'claims')
    loop
        if v_item ->> 'claim_key' !~ '^[0-9a-f]{64}$'
           or length(btrim(v_item ->> 'canonical_claim')) < 40
           or v_item ->> 'canonical_claim' is distinct from v_item ->> 'evidence_span'
           or v_item ->> 'verification_policy' <> 'official_exact_span_v1' then
            raise exception 'current-affairs atomic claim contract failed';
        end if;
        insert into public.current_affairs_event_claims (
            event_id, claim_key, canonical_claim, valid_from, review_after,
            expires_at, verification_policy, verification_status,
            review_required, verified_at
        ) values (
            v_event.id, v_item ->> 'claim_key', v_item ->> 'canonical_claim',
            (v_item ->> 'valid_from')::timestamptz,
            (v_item ->> 'review_after')::timestamptz,
            (v_item ->> 'expires_at')::timestamptz,
            v_item ->> 'verification_policy',
            case when v_verified then 'verified' else 'review_required' end,
            not v_verified, case when v_verified then now() else null end
        ) on conflict (event_id, claim_key) do update set
            updated_at = now()
        returning * into v_claim;

        insert into public.source_facts (
            source_document_id, fact_checksum, canonical_fact, evidence_span,
            document_version, source_event_at, effective_from, effective_until,
            expires_at, review_required, verification_status, verified_at
        ) values (
            v_source.id, v_item ->> 'claim_key', v_item ->> 'canonical_claim',
            v_item ->> 'evidence_span', v_source.fact_version,
            v_event.event_date::timestamptz, (v_item ->> 'valid_from')::timestamptz,
            (v_item ->> 'expires_at')::timestamptz,
            (v_item ->> 'expires_at')::timestamptz, not v_verified,
            case when v_verified then 'verified' else 'draft' end,
            case when v_verified then now() else null end
        ) on conflict (source_document_id, fact_checksum) do update set
            canonical_fact = public.source_facts.canonical_fact
        returning * into v_fact;

        insert into public.current_affairs_claim_evidence (
            claim_id, source_fact_id, is_primary
        ) values (
            v_claim.id, v_fact.id, v_source.source_kind in ('official','primary')
        ) on conflict (claim_id, source_fact_id) do nothing;
        v_claim_count := v_claim_count + 1;
    end loop;

    insert into public.current_affairs_review_events (
        event_id, decision, notes, metadata
    ) values (
        v_event.id, case when v_verified then 'verified' else 'submitted' end,
        'Imported by the versioned exact-span current-affairs pipeline.',
        jsonb_build_object(
            'verification_policy', p_event ->> 'verification_policy',
            'source_document_id', p_source_document_id,
            'claim_count', v_claim_count
        )
    );
    return jsonb_build_object(
        'event_id', v_event.id,
        'cluster_key', v_event.cluster_key,
        'claim_count', v_claim_count,
        'verification_status', v_event.verification_status,
        'review_required', v_event.review_required
    );
end;
$$;

create or replace function public.get_current_affairs_practice_pool(
    p_target_date date,
    p_test_definition_key text default 'daily_quick',
    p_limit integer default 40
)
returns table (
    event_id uuid,
    claim_id uuid,
    cluster_key text,
    event_title text,
    event_date date,
    practice_pool text,
    category text,
    geography text,
    importance smallint,
    category_weight numeric,
    verification_policy text,
    canonical_claim text,
    corroborating_sources bigint,
    expires_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
    with eligible as (
        select
            event.id as event_id,
            claim.id as claim_id,
            event.cluster_key,
            event.event_title,
            event.event_date,
            event.category,
            event.geography,
            event.importance,
            event.verification_policy,
            claim.canonical_claim,
            claim.expires_at,
            count(distinct link.source_fact_id) as corroborating_sources,
            case
                when p_target_date - event.event_date between 0 and 7 then 'daily'
                when p_target_date - event.event_date between 8 and 30 then 'weekly'
                when p_target_date - event.event_date between 31 and 90 then 'monthly'
                when p_target_date - event.event_date between 91 and 180
                     and event.importance >= 4 then 'six_month'
            end as practice_pool
        from public.current_affairs_events event
        join public.current_affairs_event_claims claim on claim.event_id = event.id
        join public.current_affairs_claim_evidence link on link.claim_id = claim.id
        where event.verification_status = 'verified' and not event.review_required
          and claim.verification_status = 'verified' and not claim.review_required
          and event.event_date between p_target_date - 180 and p_target_date
          and claim.valid_from::date <= p_target_date
          and claim.expires_at::date >= p_target_date
        group by event.id, claim.id
    ), weighted as (
        select eligible.*, coalesce(weight.weight, 1.0) as category_weight
        from eligible
        left join lateral (
            select configured.weight
            from public.current_affairs_category_weights configured
            where configured.test_definition_key = p_test_definition_key
              and configured.category = eligible.category
              and configured.effective_from <= p_target_date
              and (
                  configured.effective_until is null
                  or configured.effective_until >= p_target_date
              )
            order by configured.effective_from desc
            limit 1
        ) weight on true
        where eligible.practice_pool is not null
    )
    select
        weighted.event_id, weighted.claim_id, weighted.cluster_key,
        weighted.event_title, weighted.event_date, weighted.practice_pool,
        weighted.category, weighted.geography, weighted.importance,
        weighted.category_weight, weighted.verification_policy,
        weighted.canonical_claim,
        weighted.corroborating_sources, weighted.expires_at
    from weighted
    order by
        weighted.importance * weighted.category_weight desc,
        weighted.corroborating_sources desc,
        weighted.event_date desc,
        weighted.cluster_key,
        weighted.claim_id
    limit greatest(1, least(coalesce(p_limit, 40), 200));
$$;

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
    current_affairs_verification_policy text
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
        evidence.canonical_claim as fact_summary,
        evidence.fact_version,
        evidence.effective_expiry as expires_at,
        evidence.event_date as current_affairs_event_date,
        evidence.practice_pool as current_affairs_practice_pool,
        evidence.verification_policy as current_affairs_verification_policy
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

alter table public.current_affairs_events enable row level security;
alter table public.current_affairs_event_sources enable row level security;
alter table public.current_affairs_event_claims enable row level security;
alter table public.current_affairs_claim_evidence enable row level security;
alter table public.current_affairs_category_weights enable row level security;
alter table public.current_affairs_review_events enable row level security;

revoke all on table public.current_affairs_events from public, anon, authenticated;
revoke all on table public.current_affairs_event_sources from public, anon, authenticated;
revoke all on table public.current_affairs_event_claims from public, anon, authenticated;
revoke all on table public.current_affairs_claim_evidence from public, anon, authenticated;
revoke all on table public.current_affairs_category_weights from public, anon, authenticated;
revoke all on table public.current_affairs_review_events from public, anon, authenticated;
revoke all on sequence public.current_affairs_review_events_id_seq from public, anon, authenticated;

grant select, insert, update on table public.current_affairs_events to service_role;
grant select, insert on table public.current_affairs_event_sources to service_role;
grant select, insert, update on table public.current_affairs_event_claims to service_role;
grant select, insert on table public.current_affairs_claim_evidence to service_role;
grant select, insert, update on table public.current_affairs_category_weights to service_role;
grant select, insert on table public.current_affairs_review_events to service_role;
grant usage, select on sequence public.current_affairs_review_events_id_seq to service_role;

revoke all on function public.upsert_current_affairs_event_bundle(uuid,jsonb)
    from public, anon, authenticated;
revoke all on function public.get_current_affairs_practice_pool(date,text,integer)
    from public, anon, authenticated;
revoke all on function public.get_current_affairs_grounding_bundle(text,date,integer)
    from public, anon, authenticated;
grant execute on function public.upsert_current_affairs_event_bundle(uuid,jsonb)
    to service_role;
grant execute on function public.get_current_affairs_practice_pool(date,text,integer)
    to service_role;
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
        'function_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from function_permission_failures),
            '[]'::jsonb
        ),
        'table_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from table_permission_failures),
            '[]'::jsonb
        ),
        'phase_d_current_affairs_migration_version', '20260808103500'
    );
$$;

revoke all on function public.get_phase_d_current_affairs_contract()
    from public, anon, authenticated;
grant execute on function public.get_phase_d_current_affairs_contract()
    to service_role;

comment on table public.current_affairs_events is
    'Stable event clusters; publication dates live on source links, never in event_date.';
comment on table public.current_affairs_event_claims is
    'Atomic claims with claim-specific validity, correction, expiry, and review state.';
