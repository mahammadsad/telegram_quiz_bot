-- Activate only the reviewed source-backed chapter set for the 13 daily quizzes.
-- Forward-only: no historical quiz or learning rows change.

with approved_chapter(key) as (
    values
        ('computer:fundamentals'),
        ('computer:hardware-software'),
        ('computer:operating-systems'),
        ('computer:internet-networking'),
        ('computer:ms-office'),
        ('computer:databases'),
        ('computer:cyber-security'),
        ('bengali:phonetics'),
        ('bengali:word-sentence'),
        ('reasoning:syllogism'),
        ('reasoning:venn'),
        ('mathematics:simplification'),
        ('mathematics:geometry'),
        ('english:parts-tense'),
        ('english:error-correction'),
        ('miscellaneous:national-symbols'),
        ('miscellaneous:indian-culture'),
        ('polity:making-preamble-citizenship'),
        ('polity:pm-council'),
        ('geography:india-location'),
        ('geography:rivers-water'),
        ('science:measurement-motion'),
        ('science:heat-optics-sound'),
        ('economics:banking-rbi'),
        ('economics:inflation'),
        ('history:ancient-india'),
        ('history:national-movement'),
        ('environment:ecosystem'),
        ('environment:biodiversity'),
        ('current-affairs:national'),
        ('current-affairs:science-technology')
),
canonical_subject(subject_key) as (
    values
        ('computer'), ('bengali'), ('reasoning'), ('mathematics'), ('english'),
        ('miscellaneous'), ('polity'), ('geography'), ('science'), ('economics'),
        ('history'), ('environment'), ('current-affairs')
)
update public.quiz_chapters chapter
set rotation_enabled = exists (
        select 1
        from approved_chapter approved
        where approved.key = chapter.key
    ),
    updated_at = now()
where chapter.subject_key in (
        select subject_key from canonical_subject
    )
  and chapter.rotation_enabled is distinct from exists (
        select 1
        from approved_chapter approved
        where approved.key = chapter.key
    );

do $rotation_contract$
declare
    v_missing_keys text[];
    v_invalid_subjects text[];
    v_unapproved_enabled text[];
begin
    with approved_chapter(key) as (
        values
            ('computer:fundamentals'),
            ('computer:hardware-software'),
            ('computer:operating-systems'),
            ('computer:internet-networking'),
            ('computer:ms-office'),
            ('computer:databases'),
            ('computer:cyber-security'),
            ('bengali:phonetics'),
            ('bengali:word-sentence'),
            ('reasoning:syllogism'),
            ('reasoning:venn'),
            ('mathematics:simplification'),
            ('mathematics:geometry'),
            ('english:parts-tense'),
            ('english:error-correction'),
            ('miscellaneous:national-symbols'),
            ('miscellaneous:indian-culture'),
            ('polity:making-preamble-citizenship'),
            ('polity:pm-council'),
            ('geography:india-location'),
            ('geography:rivers-water'),
            ('science:measurement-motion'),
            ('science:heat-optics-sound'),
            ('economics:banking-rbi'),
            ('economics:inflation'),
            ('history:ancient-india'),
            ('history:national-movement'),
            ('environment:ecosystem'),
            ('environment:biodiversity'),
            ('current-affairs:national'),
            ('current-affairs:science-technology')
    )
    select array_agg(approved.key order by approved.key)
    into v_missing_keys
    from approved_chapter approved
    left join public.quiz_chapters chapter on chapter.key = approved.key
    where chapter.id is null;

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
            ('current-affairs', 2)
    ),
    actual as (
        select subject_key, count(*)::integer as actual_count
        from public.quiz_chapters
        where active and rotation_enabled
        group by subject_key
    )
    select array_agg(expected.subject_key order by expected.subject_key)
    into v_invalid_subjects
    from expected
    left join actual using (subject_key)
    where coalesce(actual.actual_count, 0) <> expected.expected_count;

    with approved_chapter(key) as (
        values
            ('computer:fundamentals'),
            ('computer:hardware-software'),
            ('computer:operating-systems'),
            ('computer:internet-networking'),
            ('computer:ms-office'),
            ('computer:databases'),
            ('computer:cyber-security'),
            ('bengali:phonetics'),
            ('bengali:word-sentence'),
            ('reasoning:syllogism'),
            ('reasoning:venn'),
            ('mathematics:simplification'),
            ('mathematics:geometry'),
            ('english:parts-tense'),
            ('english:error-correction'),
            ('miscellaneous:national-symbols'),
            ('miscellaneous:indian-culture'),
            ('polity:making-preamble-citizenship'),
            ('polity:pm-council'),
            ('geography:india-location'),
            ('geography:rivers-water'),
            ('science:measurement-motion'),
            ('science:heat-optics-sound'),
            ('economics:banking-rbi'),
            ('economics:inflation'),
            ('history:ancient-india'),
            ('history:national-movement'),
            ('environment:ecosystem'),
            ('environment:biodiversity'),
            ('current-affairs:national'),
            ('current-affairs:science-technology')
    )
    select array_agg(chapter.key order by chapter.key)
    into v_unapproved_enabled
    from public.quiz_chapters chapter
    where chapter.active
      and chapter.rotation_enabled
      and chapter.subject_key in (
          'computer', 'bengali', 'reasoning', 'mathematics', 'english',
          'miscellaneous', 'polity', 'geography', 'science', 'economics',
          'history', 'environment', 'current-affairs'
      )
      and not exists (
          select 1
          from approved_chapter approved
          where approved.key = chapter.key
      );

    if v_missing_keys is not null then
        raise exception 'Source-backed rotation is missing chapter keys: %', v_missing_keys;
    end if;
    if v_invalid_subjects is not null then
        raise exception 'Source-backed rotation has invalid subject counts: %', v_invalid_subjects;
    end if;
    if v_unapproved_enabled is not null then
        raise exception 'Unapproved chapters remain enabled: %', v_unapproved_enabled;
    end if;
end;
$rotation_contract$;

-- Current-affairs dates are audience-local dates. Avoid UTC date truncation
-- dropping a release published shortly after midnight in Asia/Kolkata.
create or replace function public.get_grounding_bundle(
    p_subject_key text,
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
    expires_at timestamptz
)
language sql
stable
security invoker
set search_path = ''
as $$
with selected_topic as (
    select mt.id
    from public.quiz_micro_topics mt
    join public.quiz_chapters c on c.id = mt.chapter_id
    where c.subject_key = p_subject_key
      and c.name = p_chapter
      and c.active and mt.active
      and exists (
          select 1
          from public.source_documents candidate
          where candidate.micro_topic_id = mt.id
            and candidate.verification_status = 'verified'
            and not candidate.review_required
            and (
                candidate.expires_at is null
                or (candidate.expires_at at time zone 'Asia/Kolkata')::date
                    >= p_target_date
            )
            and (
                p_subject_key <> 'current-affairs'
                or (
                    candidate.source_kind in ('official', 'primary')
                    and (
                        candidate.source_published_at
                        at time zone 'Asia/Kolkata'
                    )::date between p_target_date - 45 and p_target_date
                )
            )
      )
    order by mt.last_used_at asc nulls first, mt.target_coverage desc, mt.key
    limit 1
)
select
    source.id,
    mt.id,
    mt.key,
    mt.name,
    source.source_url,
    source.source_title,
    source.source_domain,
    source.source_kind,
    source.source_published_at,
    source.source_accessed_at,
    source.fact_summary,
    source.fact_version,
    source.expires_at
from selected_topic chosen
join public.quiz_micro_topics mt on mt.id = chosen.id
join public.source_documents source on source.micro_topic_id = mt.id
where source.verification_status = 'verified'
  and not source.review_required
  and (
      source.expires_at is null
      or (source.expires_at at time zone 'Asia/Kolkata')::date >= p_target_date
  )
  and (
      p_subject_key <> 'current-affairs'
      or (
          source.source_kind in ('official', 'primary')
          and (
              source.source_published_at at time zone 'Asia/Kolkata'
          )::date between p_target_date - 45 and p_target_date
      )
  )
order by source.source_published_at desc nulls last, source.verified_at desc, source.id
limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

-- Preserve the complete 2.2.0 security verifier and add the data rollout gate.
alter function public.get_application_schema_contract()
    rename to get_application_schema_contract_v220_rate_limits_base;

create function public.get_application_schema_contract()
returns jsonb
language plpgsql
stable
security definer
set search_path = ''
as $$
declare
    v_base jsonb;
    v_source_rollout_migration_applied boolean := false;
    v_rotation_ready boolean := false;
    v_source_coverage_ready boolean := false;
begin
    v_base := public.get_application_schema_contract_v220_rate_limits_base();

    if to_regclass('supabase_migrations.schema_migrations') is not null then
        execute
            'select exists (
                select 1 from supabase_migrations.schema_migrations
                where version = $1 or name = ''source_backed_rotation_v1''
            )'
        into v_source_rollout_migration_applied
        using '20260728040209';
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
            ('current-affairs', 2)
    ),
    actual as (
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
          and (
            key is null
            or key not in (
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
              'current-affairs:science-technology'
            )
          )
    )
    into v_rotation_ready;

    with approved_chapter(key) as (
        values
            ('computer:fundamentals'),
            ('computer:hardware-software'),
            ('computer:operating-systems'),
            ('computer:internet-networking'),
            ('computer:ms-office'),
            ('computer:databases'),
            ('computer:cyber-security'),
            ('bengali:phonetics'),
            ('bengali:word-sentence'),
            ('reasoning:syllogism'),
            ('reasoning:venn'),
            ('mathematics:simplification'),
            ('mathematics:geometry'),
            ('english:parts-tense'),
            ('english:error-correction'),
            ('miscellaneous:national-symbols'),
            ('miscellaneous:indian-culture'),
            ('polity:making-preamble-citizenship'),
            ('polity:pm-council'),
            ('geography:india-location'),
            ('geography:rivers-water'),
            ('science:measurement-motion'),
            ('science:heat-optics-sound'),
            ('economics:banking-rbi'),
            ('economics:inflation'),
            ('history:ancient-india'),
            ('history:national-movement'),
            ('environment:ecosystem'),
            ('environment:biodiversity'),
            ('current-affairs:national'),
            ('current-affairs:science-technology')
    ),
    local_clock(today) as (
        values ((now() at time zone 'Asia/Kolkata')::date)
    )
    select not exists (
        select 1
        from approved_chapter approved
        left join public.quiz_chapters chapter on chapter.key = approved.key
        cross join local_clock
        where chapter.id is null
           or not exists (
                select 1
                from public.quiz_micro_topics topic
                join public.source_documents source
                  on source.micro_topic_id = topic.id
                where topic.chapter_id = chapter.id
                  and topic.active
                  and source.verification_status = 'verified'
                  and not source.review_required
                  and (
                      source.expires_at is null
                      or (
                          source.expires_at at time zone 'Asia/Kolkata'
                      )::date >= local_clock.today
                  )
                  and (
                      chapter.subject_key <> 'current-affairs'
                      or (
                          source.source_kind in ('official', 'primary')
                          and (
                              source.source_published_at
                              at time zone 'Asia/Kolkata'
                          )::date between local_clock.today - 45
                              and local_clock.today
                      )
                  )
           )
    )
    into v_source_coverage_ready;

    return v_base || jsonb_build_object(
        'source_rollout_migration_version', '20260728040209',
        'source_rollout_migration_applied',
            v_source_rollout_migration_applied,
        'source_backed_rotation_ready', v_rotation_ready,
        'source_coverage_ready', v_source_coverage_ready,
        'ready',
            (v_base->>'ready')::boolean
            and v_base->>'contract_key' = 'telegram_quiz_api'
            and v_base->>'contract_version' = '2.2.0'
            and v_source_rollout_migration_applied
            and v_rotation_ready
    );
end;
$$;

revoke execute on function public.get_application_schema_contract_v220_rate_limits_base()
    from public, anon, authenticated;
revoke execute on function public.get_application_schema_contract()
    from public, anon, authenticated;
revoke execute on function public.get_grounding_bundle(text, text, date, integer)
    from public, anon, authenticated;

grant execute on function public.get_application_schema_contract_v220_rate_limits_base()
    to service_role;
grant execute on function public.get_application_schema_contract()
    to service_role;
grant execute on function public.get_grounding_bundle(text, text, date, integer)
    to service_role;
