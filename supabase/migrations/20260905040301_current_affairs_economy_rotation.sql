-- Add RBI-backed economy and reports coverage to the reviewed current-affairs
-- rotation without weakening any existing application or platform contract.

do $$
begin
    if not exists (
        select 1
        from public.quiz_chapters
        where key = 'current-affairs:economy-reports'
          and subject_key = 'current-affairs'
          and active
    ) then
        raise exception 'current-affairs economy chapter is missing or inactive';
    end if;
end;
$$;

update public.quiz_chapters
set rotation_enabled = true
where key = 'current-affairs:economy-reports'
  and subject_key = 'current-affairs'
  and active
  and not rotation_enabled;

-- Replace only the internal source-rollout layer. Later quiz-quality and
-- personal-learning wrappers continue to call this stable function name.
alter function public.get_application_schema_contract_v220_source_rollout_base()
    rename to get_application_schema_contract_v220_source_rollout_before_economy;

revoke all on function
    public.get_application_schema_contract_v220_source_rollout_before_economy()
    from public, anon, authenticated;

create function public.get_application_schema_contract_v220_source_rollout_base()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_prior jsonb;
    v_contract_base jsonb;
    v_migration_applied boolean := false;
    v_rotation_ready boolean := false;
    v_economy_coverage_ready boolean := false;
begin
    v_prior := public.get_application_schema_contract_v220_source_rollout_before_economy();
    v_contract_base := public.get_application_schema_contract_v220_rate_limits_base();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = '20260905040301'
                   or name = 'current_affairs_economy_rotation'
            )
        $migration_check$ into v_migration_applied;
    end if;

    with expected(subject_key, expected_count) as (
        values
            ('computer', 7),
            ('bengali', 2),
            ('reasoning', 2),
            ('mathematics', 2),
            ('english', 2),
            ('miscellaneous', 2),
            ('polity', 2),
            ('geography', 2),
            ('science', 2),
            ('economics', 2),
            ('history', 2),
            ('environment', 2),
            ('current-affairs', 3)
    ), actual as (
        select subject_key, count(*)::integer as actual_count
        from public.quiz_chapters
        where active and rotation_enabled
        group by subject_key
    )
    select not exists (
        select 1
        from expected
        left join actual using (subject_key)
        where coalesce(actual.actual_count, 0) <> expected.expected_count
    )
    and not exists (
        select 1
        from public.quiz_chapters
        where active and rotation_enabled
          and key not in (
              'computer:fundamentals',
              'computer:hardware-software',
              'computer:operating-systems',
              'computer:internet-networking',
              'computer:ms-office',
              'computer:databases',
              'computer:cyber-security',
              'bengali:phonetics',
              'bengali:word-sentence',
              'reasoning:syllogism',
              'reasoning:venn',
              'mathematics:simplification',
              'mathematics:geometry',
              'english:parts-tense',
              'english:error-correction',
              'miscellaneous:national-symbols',
              'miscellaneous:indian-culture',
              'polity:making-preamble-citizenship',
              'polity:pm-council',
              'geography:india-location',
              'geography:rivers-water',
              'science:measurement-motion',
              'science:heat-optics-sound',
              'economics:banking-rbi',
              'economics:inflation',
              'history:ancient-india',
              'history:national-movement',
              'environment:ecosystem',
              'environment:biodiversity',
              'current-affairs:national',
              'current-affairs:science-technology',
              'current-affairs:economy-reports'
          )
    )
    into v_rotation_ready;

    select
        count(distinct source.id) >= 4
        and count(distinct topic.id) >= 2
    into v_economy_coverage_ready
    from public.quiz_chapters chapter
    join public.quiz_micro_topics topic
      on topic.chapter_id = chapter.id
     and topic.active
    join public.source_documents source
      on source.micro_topic_id = topic.id
    where chapter.key = 'current-affairs:economy-reports'
      and chapter.active
      and source.verification_status = 'verified'
      and not source.review_required
      and source.source_kind in ('official', 'primary')
      and (source.expires_at is null or source.expires_at >= now())
      and source.source_published_at >= now() - interval '45 days'
      and source.source_published_at <= now();

    return v_prior || jsonb_build_object(
        'current_affairs_economy_rotation_migration_version', '20260905040301',
        'current_affairs_economy_rotation_migration_applied', v_migration_applied,
        'source_backed_rotation_ready', v_rotation_ready,
        'source_coverage_ready',
            coalesce((v_prior->>'source_coverage_ready')::boolean, false)
            and v_economy_coverage_ready,
        'current_affairs_economy_coverage_ready', v_economy_coverage_ready,
        'ready',
            coalesce((v_contract_base->>'ready')::boolean, false)
            and v_contract_base->>'contract_key' = 'telegram_quiz_api'
            and v_contract_base->>'contract_version' = '2.2.0'
            and coalesce(
                (v_prior->>'source_rollout_migration_applied')::boolean,
                false
            )
            and v_migration_applied
            and v_rotation_ready
    );
end;
$$;

revoke all on function public.get_application_schema_contract_v220_source_rollout_base()
    from public, anon, authenticated;
grant execute on function
    public.get_application_schema_contract_v220_source_rollout_before_economy()
    to service_role;
grant execute on function public.get_application_schema_contract_v220_source_rollout_base()
    to service_role;

-- Advance the platform gate while retaining every check accumulated by the
-- previous wrappers.
alter function public.get_platform_contract_v1()
    rename to get_platform_contract_v1_before_current_affairs_economy;

revoke all on function public.get_platform_contract_v1_before_current_affairs_economy()
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
    v_application jsonb;
    v_checks jsonb;
    v_missing jsonb;
    v_migration_applied boolean := false;
begin
    v_base := public.get_platform_contract_v1_before_current_affairs_economy();
    v_application := public.get_application_schema_contract();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute $migration_check$
            select exists (
                select 1
                from supabase_migrations.schema_migrations
                where version = '20260905040301'
                   or name = 'current_affairs_economy_rotation'
            )
        $migration_check$ into v_migration_applied;
    end if;

    v_checks := coalesce(v_base->'checks', '{}'::jsonb)
        || jsonb_build_object(
            'currentAffairsEconomyRotation',
                v_migration_applied
                and coalesce(
                    (
                        v_application
                        ->> 'current_affairs_economy_rotation_migration_applied'
                    )::boolean,
                    false
                )
                and coalesce(
                    (v_application->>'source_backed_rotation_ready')::boolean,
                    false
                )
        );

    select coalesce(jsonb_agg(key order by key), '[]'::jsonb)
    into v_missing
    from jsonb_each(v_checks)
    where value is distinct from 'true'::jsonb;

    return v_base || jsonb_build_object(
        'ready', jsonb_array_length(v_missing) = 0,
        'contract_version', '1.4.0',
        'required_migration_version', '20260905040301',
        'migration_applied', v_migration_applied,
        'checks', v_checks,
        'missing_checks', v_missing
    );
end;
$$;

revoke all on function public.get_platform_contract_v1()
    from public, anon, authenticated;
grant execute on function public.get_platform_contract_v1() to service_role;
