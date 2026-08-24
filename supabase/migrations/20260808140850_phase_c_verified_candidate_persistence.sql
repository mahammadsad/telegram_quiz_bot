-- Phase C: deterministic identity parity and atomic persistence for accepted
-- asynchronous candidates. Rejected candidates never enter the question bank.

create or replace function public.normalized_identity_text(p_value text)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    select btrim(regexp_replace(
        regexp_replace(
            lower(btrim(coalesce(p_value, ''))),
            $punct$[।,.!?"'‘’“”:;()\[\]{}—–-]+$punct$,
            ' ', 'g'
        ),
        '[[:space:]]+', ' ', 'g'
    ));
$$;

create or replace function public.knowledge_identity_hash(p_candidate jsonb)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    select encode(extensions.digest(convert_to(
        public.content_hash_part('subject', public.normalized_identity_text(p_candidate ->> 'subject'))
        || public.content_hash_part('entity', public.normalized_identity_text(p_candidate ->> 'entity_key'))
        || public.content_hash_part('relation', public.normalized_identity_text(p_candidate ->> 'relation_key'))
        || public.content_hash_part('answer_value', public.normalized_identity_text(p_candidate ->> 'answer_value'))
        || public.content_hash_part('time_scope', public.normalized_identity_text(p_candidate ->> 'time_scope')),
        'UTF8'
    ), 'sha256'), 'hex');
$$;

create or replace function public.question_variant_fingerprint(p_candidate jsonb)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    with values as (
        select
            public.normalized_identity_text(p_candidate ->> 'question_text') as stem,
            public.normalized_identity_text(p_candidate ->> 'option_a') as option_1,
            public.normalized_identity_text(p_candidate ->> 'option_b') as option_2,
            public.normalized_identity_text(p_candidate ->> 'option_c') as option_3,
            public.normalized_identity_text(p_candidate ->> 'option_d') as option_4,
            case p_candidate ->> 'correct_option'
                when 'A' then public.normalized_identity_text(p_candidate ->> 'option_a')
                when 'B' then public.normalized_identity_text(p_candidate ->> 'option_b')
                when 'C' then public.normalized_identity_text(p_candidate ->> 'option_c')
                when 'D' then public.normalized_identity_text(p_candidate ->> 'option_d')
                else ''
            end as answer,
            public.normalized_identity_text(p_candidate ->> 'language') as language
    )
    select encode(extensions.digest(convert_to(
        public.content_hash_part('stem', stem)
        || public.content_hash_part('option_1', option_1)
        || public.content_hash_part('option_2', option_2)
        || public.content_hash_part('option_3', option_3)
        || public.content_hash_part('option_4', option_4)
        || public.content_hash_part('answer', answer)
        || public.content_hash_part('language', language),
        'UTF8'
    ), 'sha256'), 'hex') from values;
$$;

create or replace function public.source_fact_identity_hash(p_candidate jsonb)
returns text
language sql
immutable
security invoker
set search_path = ''
as $$
    select encode(extensions.digest(convert_to(
        public.content_hash_part('source_document_id', public.normalized_identity_text(p_candidate ->> 'source_document_id'))
        || public.content_hash_part('canonical_fact', public.normalized_identity_text(p_candidate ->> 'canonical_claim'))
        || public.content_hash_part('evidence_span', public.normalized_identity_text(p_candidate ->> 'evidence_summary'))
        || public.content_hash_part('document_version', public.normalized_identity_text(p_candidate ->> 'fact_version')),
        'UTF8'
    ), 'sha256'), 'hex');
$$;

create or replace function public.save_verified_content_candidates(
    p_candidates jsonb,
    p_generation_context jsonb
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_effective jsonb;
    v_source public.source_documents%rowtype;
    v_knowledge public.knowledge_points%rowtype;
    v_fact public.source_facts%rowtype;
    v_existing public.questions%rowtype;
    v_previous public.questions%rowtype;
    v_question_id uuid;
    v_context_id uuid;
    v_content_version integer;
    v_ids uuid[] := '{}';
    v_source_ids uuid[];
begin
    if jsonb_typeof(p_candidates) <> 'array'
       or jsonb_array_length(p_candidates) not between 1 and 5
       or jsonb_typeof(p_generation_context) <> 'object'
       or coalesce(p_generation_context ->> 'prompt_hash', '') !~ '^[0-9a-f]{64}$' then
        raise exception 'one to five candidates and a valid generation context are required';
    end if;

    select coalesce(array_agg(value::uuid), '{}') into v_source_ids
    from jsonb_array_elements_text(
        coalesce(p_generation_context -> 'source_document_ids', '[]'::jsonb)
    );
    insert into public.question_generation_contexts (
        subject_key, micro_topic_id, prompt_hash, provider, model, latency_ms,
        input_tokens, output_tokens, source_document_ids, candidate_count,
        accepted_count, rejection_codes, novelty_metrics
    ) values (
        p_generation_context ->> 'subject_key',
        nullif(p_generation_context ->> 'micro_topic_id', '')::uuid,
        p_generation_context ->> 'prompt_hash',
        p_generation_context ->> 'provider', p_generation_context ->> 'model',
        nullif(p_generation_context ->> 'latency_ms', '')::integer,
        nullif(p_generation_context ->> 'input_tokens', '')::integer,
        nullif(p_generation_context ->> 'output_tokens', '')::integer,
        v_source_ids,
        coalesce((p_generation_context ->> 'candidate_count')::integer, jsonb_array_length(p_candidates)),
        jsonb_array_length(p_candidates),
        coalesce(array(select jsonb_array_elements_text(
            coalesce(p_generation_context -> 'rejection_codes', '[]'::jsonb)
        )), '{}'),
        coalesce(p_generation_context -> 'novelty_metrics', '{}'::jsonb)
    ) returning id into v_context_id;

    for v_item in select value from jsonb_array_elements(p_candidates)
    loop
        if v_item ->> 'verification_status' <> 'verified'
           or coalesce((v_item ->> 'verification_score')::numeric, 0) < 0.85
           or coalesce(v_item ->> 'knowledge_key', '') !~ '^[0-9a-f]{64}$'
           or coalesce(v_item ->> 'variant_fingerprint', '') !~ '^[0-9a-f]{64}$'
           or coalesce(v_item ->> 'source_fact_checksum', '') !~ '^[0-9a-f]{64}$'
           or public.knowledge_identity_hash(v_item) <> v_item ->> 'knowledge_key'
           or public.question_variant_fingerprint(v_item) <> v_item ->> 'variant_fingerprint'
           or public.source_fact_identity_hash(v_item) <> v_item ->> 'source_fact_checksum' then
            raise exception 'candidate identity or verification contract failed';
        end if;

        select * into v_source from public.source_documents source
        where source.id = (v_item ->> 'source_document_id')::uuid
          and source.micro_topic_id = (v_item ->> 'micro_topic_id')::uuid
          and source.verification_status = 'verified'
          and not source.review_required
          and (source.expires_at is null or source.expires_at >= now());
        if not found then
            raise exception 'candidate source is not current and verified';
        end if;

        insert into public.knowledge_points (
            knowledge_key, subject_key, micro_topic_id, canonical_claim,
            entity_key, relation_key, answer_value, time_scope,
            syllabus_location, syllabus_status, status
        ) values (
            v_item ->> 'knowledge_key', v_item ->> 'subject',
            (v_item ->> 'micro_topic_id')::uuid, v_item ->> 'canonical_claim',
            v_item ->> 'entity_key', v_item ->> 'relation_key',
            v_item ->> 'answer_value', v_item ->> 'time_scope',
            v_item ->> 'topic', 'mapped', 'active'
        )
        on conflict (knowledge_key) do update set updated_at = now()
        where public.knowledge_points.subject_key = excluded.subject_key
          and public.knowledge_points.entity_key = excluded.entity_key
          and public.knowledge_points.relation_key = excluded.relation_key
          and public.knowledge_points.answer_value = excluded.answer_value
          and public.knowledge_points.time_scope = excluded.time_scope
        returning * into v_knowledge;
        if v_knowledge.id is null then
            raise exception 'knowledge identity collision';
        end if;

        insert into public.source_facts (
            source_document_id, fact_checksum, canonical_fact, evidence_span,
            document_version, expires_at, review_required,
            verification_status, verified_at
        ) values (
            v_source.id, v_item ->> 'source_fact_checksum',
            v_item ->> 'canonical_claim', v_source.fact_summary,
            v_source.fact_version, v_source.expires_at, false,
            'verified', coalesce(v_source.verified_at, now())
        )
        on conflict (source_document_id, fact_checksum) do update set
            canonical_fact = public.source_facts.canonical_fact
        returning * into v_fact;

        insert into public.knowledge_point_evidence (
            knowledge_point_id, source_fact_id, support_type, confidence, is_primary
        ) values (
            v_knowledge.id, v_fact.id, 'supports',
            (v_item ->> 'verification_score')::numeric,
            v_source.source_kind in ('official','primary')
        ) on conflict (knowledge_point_id, source_fact_id, support_type) do nothing;

        v_effective := v_item || jsonb_build_object(
            'source_url', v_source.source_url,
            'source_title', v_source.source_title,
            'source_domain', v_source.source_domain,
            'source_kind', v_source.source_kind,
            'source_published_at', v_source.source_published_at,
            'source_accessed_at', v_source.source_accessed_at,
            'evidence_summary', v_source.fact_summary,
            'fact_version', v_source.fact_version
        );
        if public.question_stem_hash(v_item ->> 'question_text') <> v_item ->> 'stem_hash'
           or public.question_content_hash(v_effective) <> v_item ->> 'content_hash' then
            raise exception 'candidate content hash contract failed';
        end if;

        select * into v_existing from public.questions question
        where question.variant_fingerprint = v_item ->> 'variant_fingerprint'
           or question.content_hash = v_item ->> 'content_hash'
        order by (question.variant_fingerprint is not null) desc
        limit 1 for update;
        if found then
            if v_existing.status in ('reported','under_review','rejected','archived')
               or v_existing.review_required
               or v_existing.verification_status <> 'verified' then
                raise exception 'unsafe historical question cannot enter inventory';
            end if;
            update public.questions set
                knowledge_point_id = v_knowledge.id,
                variant_fingerprint = v_item ->> 'variant_fingerprint',
                inventory_status = 'verified', eligible_at = coalesce(eligible_at, now())
            where id = v_existing.id
            returning id into v_question_id;
        else
            perform pg_advisory_xact_lock(hashtextextended(
                'question-stem:' || (v_item ->> 'stem_hash'), 0
            ));
            select * into v_previous from public.questions question
            where question.stem_hash = v_item ->> 'stem_hash'
            order by question.content_version desc limit 1;
            v_content_version := coalesce(v_previous.content_version, 0) + 1;
            insert into public.questions (
                question_text, option_a, option_b, option_c, option_d,
                correct_option, explanation, detailed_explanation, subject,
                topic, difficulty, gemini_model, source, week_number, bot_type,
                question_hash, normalized_text, status, micro_topic_id,
                micro_topic_key, source_document_id, source_url, source_title,
                source_domain, source_kind, source_published_at,
                source_accessed_at, evidence_summary, verified_at,
                verification_status, verification_notes, verification_score,
                verification_model, fact_version, expires_at, review_required,
                stem_hash, content_hash, content_version,
                supersedes_question_id, language, knowledge_point_id,
                variant_fingerprint, question_form, inventory_status, eligible_at
            ) values (
                v_item ->> 'question_text', v_item ->> 'option_a',
                v_item ->> 'option_b', v_item ->> 'option_c',
                v_item ->> 'option_d', v_item ->> 'correct_option',
                v_item ->> 'explanation', v_item ->> 'detailed_explanation',
                v_item ->> 'subject', v_item ->> 'topic', v_item ->> 'difficulty',
                nullif(v_item ->> 'gemini_model', ''), 'verified_inventory',
                nullif(v_item ->> 'week_number', '')::integer,
                coalesce(nullif(v_item ->> 'bot_type', ''), 'daily_mcq'),
                v_item ->> 'question_hash', v_item ->> 'normalized_text', 'active',
                (v_item ->> 'micro_topic_id')::uuid, v_item ->> 'micro_topic_key',
                v_source.id, v_source.source_url, v_source.source_title,
                v_source.source_domain, v_source.source_kind,
                v_source.source_published_at, v_source.source_accessed_at,
                v_source.fact_summary, (v_item ->> 'verified_at')::timestamptz,
                'verified', v_item ->> 'verification_notes',
                (v_item ->> 'verification_score')::numeric,
                nullif(v_item ->> 'verification_model', ''), v_source.fact_version,
                v_source.expires_at, false, v_item ->> 'stem_hash',
                v_item ->> 'content_hash', v_content_version, v_previous.id,
                v_item ->> 'language', v_knowledge.id,
                v_item ->> 'variant_fingerprint',
                coalesce(nullif(v_item ->> 'question_form', ''), 'mcq'),
                'verified', now()
            ) returning id into v_question_id;
            if v_previous.id is not null
               and v_previous.status in ('draft','generated','verified','active') then
                update public.questions set status = 'archived', inventory_status = 'superseded'
                where id = v_previous.id;
            end if;
        end if;

        insert into public.question_verifications (
            question_id, source_document_id, verifier_model, verdict,
            confidence, checks, notes, checked_at
        ) values (
            v_question_id, v_source.id, v_item ->> 'verification_model', 'verified',
            (v_item ->> 'verification_score')::numeric,
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes', (v_item ->> 'verified_at')::timestamptz
        );
        insert into public.content_verification_artifacts (
            knowledge_point_id, question_id, source_fact_id, verdict,
            confidence, verifier_type, verifier_ref, checks, notes, checked_at
        ) values (
            v_knowledge.id, v_question_id, v_fact.id, 'verified',
            (v_item ->> 'verification_score')::numeric, 'model',
            v_item ->> 'verification_model',
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes', (v_item ->> 'verified_at')::timestamptz
        );
        v_ids := array_append(v_ids, v_question_id);
    end loop;

    return jsonb_build_object(
        'accepted_count', cardinality(v_ids),
        'question_ids', to_jsonb(v_ids),
        'generation_context_id', v_context_id
    );
end;
$$;

create or replace function public.ensure_due_content_replenishment_jobs(
    p_now timestamptz default now()
)
returns setof public.content_replenishment_jobs
language sql
security invoker
set search_path = ''
as $$
    with candidates as (
        select
            (p_now at time zone 'Asia/Kolkata')::date as logical_date,
            chapter.subject_key,
            topic.id as micro_topic_id,
            p_now as due_at
        from public.quiz_micro_topics topic
        join public.quiz_chapters chapter on chapter.id = topic.chapter_id
        where topic.active and chapter.active and chapter.rotation_enabled
          and exists (
              select 1 from public.source_documents source
              where source.micro_topic_id = topic.id
                and source.verification_status = 'verified'
                and not source.review_required
                and (source.expires_at is null or source.expires_at >= p_now)
          )
          and (
              select count(*) from public.questions question
              where question.micro_topic_id = topic.id
                and question.status = 'active'
                and question.verification_status = 'verified'
                and question.inventory_status in ('verified','used')
                and not question.review_required
                and question.knowledge_point_id is not null
                and question.variant_fingerprint is not null
                and (question.expires_at is null or question.expires_at >= p_now)
          ) < 12
    ), inserted as (
        insert into public.content_replenishment_jobs (
            logical_date, subject_key, micro_topic_id, due_at,
            target_candidate_count, generation_batch_size
        )
        select logical_date, subject_key, micro_topic_id, due_at, 15, 5
        from candidates
        on conflict (logical_date, subject_key, micro_topic_id) do update set
            due_at = least(public.content_replenishment_jobs.due_at, excluded.due_at),
            updated_at = now()
        returning public.content_replenishment_jobs.*
    ), events as (
        insert into public.content_replenishment_job_events (
            job_id, event_type, to_status
        )
        select id, 'auto_ensured', status from inserted
        where created_at = updated_at
        returning 1
    )
    select * from inserted order by due_at, subject_key, micro_topic_id;
$$;

create or replace function public.get_content_replenishment_bundle(
    p_job_id uuid,
    p_now timestamptz default now(),
    p_limit integer default 8
)
returns setof jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    select jsonb_build_object(
        'job_id', job.id,
        'subject_key', job.subject_key,
        'chapter', chapter.name,
        'micro_topic_id', topic.id,
        'micro_topic_key', topic.key,
        'micro_topic_name', topic.name,
        'source_document_id', source.id,
        'source_url', source.source_url,
        'source_title', source.source_title,
        'source_domain', source.source_domain,
        'source_kind', source.source_kind,
        'source_published_at', source.source_published_at,
        'source_accessed_at', source.source_accessed_at,
        'fact_summary', source.fact_summary,
        'fact_version', source.fact_version,
        'expires_at', source.expires_at
    )
    from public.content_replenishment_jobs job
    join public.quiz_micro_topics topic on topic.id = job.micro_topic_id
    join public.quiz_chapters chapter on chapter.id = topic.chapter_id
    join public.source_documents source on source.micro_topic_id = topic.id
    where job.id = p_job_id
      and source.verification_status = 'verified'
      and not source.review_required
      and (source.expires_at is null or source.expires_at >= p_now)
    order by source.source_published_at desc nulls last, source.verified_at desc, source.id
    limit greatest(1, least(coalesce(p_limit, 8), 20));
$$;

revoke all on function public.normalized_identity_text(text) from public, anon, authenticated;
revoke all on function public.knowledge_identity_hash(jsonb) from public, anon, authenticated;
revoke all on function public.question_variant_fingerprint(jsonb) from public, anon, authenticated;
revoke all on function public.source_fact_identity_hash(jsonb) from public, anon, authenticated;
revoke all on function public.save_verified_content_candidates(jsonb,jsonb) from public, anon, authenticated;
revoke all on function public.ensure_due_content_replenishment_jobs(timestamptz) from public, anon, authenticated;
revoke all on function public.get_content_replenishment_bundle(uuid,timestamptz,integer) from public, anon, authenticated;
grant execute on function public.save_verified_content_candidates(jsonb,jsonb) to service_role;
grant execute on function public.ensure_due_content_replenishment_jobs(timestamptz) to service_role;
grant execute on function public.get_content_replenishment_bundle(uuid,timestamptz,integer) to service_role;

create or replace function public.get_phase_c_candidate_contract()
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
    with required_functions(signature) as (values
        ('save_verified_content_candidates(jsonb,jsonb)'),
        ('ensure_due_content_replenishment_jobs(timestamp with time zone)'),
        ('get_content_replenishment_bundle(uuid,timestamp with time zone,integer)')
    ), permission_failures as (
        select role_name || ':' || signature as failure
        from required_functions
        cross join (values ('anon'), ('authenticated')) roles(role_name)
        where has_function_privilege(role_name, 'public.' || signature, 'EXECUTE')
        union all
        select 'service_role:' || signature from required_functions
        where not has_function_privilege('service_role', 'public.' || signature, 'EXECUTE')
    )
    select jsonb_build_object(
        'ready',
            to_regprocedure('public.save_verified_content_candidates(jsonb,jsonb)') is not null
            and to_regprocedure('public.question_variant_fingerprint(jsonb)') is not null
            and not exists (select 1 from permission_failures),
        'stable_identity_parity',
            to_regprocedure('public.knowledge_identity_hash(jsonb)') is not null
            and to_regprocedure('public.question_variant_fingerprint(jsonb)') is not null
            and to_regprocedure('public.source_fact_identity_hash(jsonb)') is not null,
        'function_permission_failures', coalesce(
            (select jsonb_agg(failure order by failure) from permission_failures),
            '[]'::jsonb
        ),
        'phase_c_candidate_migration_version', '20260808094602'
    );
$$;

revoke all on function public.get_phase_c_candidate_contract() from public, anon, authenticated;
grant execute on function public.get_phase_c_candidate_contract() to service_role;
