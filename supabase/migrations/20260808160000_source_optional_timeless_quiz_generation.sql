-- Allow independently model-verified, timeless syllabus questions without an
-- external source. Current affairs and every source-backed path remain strict.

alter table public.question_verifications
    alter column source_document_id drop not null;

alter table public.question_verifications
    add column if not exists verification_basis text not null default 'source';

do $$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'question_verifications_basis_check'
          and conrelid = 'public.question_verifications'::regclass
    ) then
        alter table public.question_verifications
            add constraint question_verifications_basis_check check (
                (verification_basis = 'source' and source_document_id is not null)
                or
                (verification_basis = 'independent_model' and source_document_id is null)
            );
    end if;
end;
$$;

create or replace function public.save_model_validated_quiz_pack_atomic(
    p_quiz_id text,
    p_worker_id text,
    p_questions jsonb,
    p_content_checksum text,
    p_replace boolean default false
)
returns jsonb
language plpgsql
security invoker
set search_path = ''
as $$
declare
    v_item jsonb;
    v_identity_item jsonb;
    v_effective_item jsonb;
    v_order integer;
    v_question_id uuid;
    v_existing public.questions%rowtype;
    v_previous public.questions%rowtype;
    v_micro_topic public.quiz_micro_topics%rowtype;
    v_knowledge public.knowledge_points%rowtype;
    v_knowledge_key text;
    v_entity text;
    v_answer_value text;
    v_relation text;
    v_mapping_count integer;
    v_stem_hash text;
    v_content_hash text;
    v_content_version integer;
    v_persisted_checksum text;
    v_ready boolean;
begin
    if nullif(btrim(coalesce(p_quiz_id, '')), '') is null
       or nullif(btrim(coalesce(p_worker_id, '')), '') is null then
        raise exception 'quiz_id and worker_id are required';
    end if;
    if jsonb_typeof(p_questions) <> 'array'
       or jsonb_array_length(p_questions) <> 10 then
        raise exception 'quiz pack must contain exactly 10 questions';
    end if;
    if coalesce(p_content_checksum, '') !~ '^[0-9a-f]{64}$' then
        raise exception 'a valid content checksum is required';
    end if;
    if not exists (
        select 1 from public.quiz_runs r
        where r.quiz_id = p_quiz_id
          and r.worker_id = p_worker_id
          and r.claim_expires_at > now()
          and r.subject_key <> 'current-affairs'
    ) then
        raise exception 'quiz run is not owned, current, and eligible for source-optional generation';
    end if;

    select count(*) into v_mapping_count
    from public.quiz_questions qq where qq.quiz_id = p_quiz_id;
    if v_mapping_count = 10 and not p_replace then
        v_persisted_checksum := public.quiz_pack_checksum(p_quiz_id);
        v_ready := v_persisted_checksum = p_content_checksum;
        update public.quiz_runs
        set status = case when v_ready then 'ready' else 'integrity_failed' end,
            question_count = 10,
            content_checksum = case when v_ready then p_content_checksum else content_checksum end,
            generated_checksum = p_content_checksum,
            persisted_checksum = v_persisted_checksum,
            checksum_contract_version = 2,
            integrity_verified = v_ready,
            integrity_diagnostic_code = case when v_ready then null else 'existing_pack_checksum_mismatch' end,
            last_error_category = case when v_ready then null else 'database_integrity_error' end,
            generated_at = case when v_ready then coalesce(generated_at, now()) else generated_at end,
            ready_at = case when v_ready then coalesce(ready_at, now()) else ready_at end,
            worker_id = case when v_ready then worker_id else null end,
            claimed_at = case when v_ready then claimed_at else null end,
            claim_expires_at = case when v_ready then claim_expires_at else null end,
            updated_at = now()
        where quiz_id = p_quiz_id and worker_id = p_worker_id;
        if not v_ready then
            insert into public.quiz_pack_integrity_failures (
                quiz_id, worker_id, generated_checksum, persisted_checksum,
                question_ids, question_count, diagnostic_code
            )
            select p_quiz_id, p_worker_id, p_content_checksum, v_persisted_checksum,
                   coalesce(array_agg(qq.question_id order by qq.question_order), '{}'),
                   count(*)::integer, 'existing_pack_checksum_mismatch'
            from public.quiz_questions qq where qq.quiz_id = p_quiz_id;
        end if;
        return jsonb_build_object(
            'quiz_id', p_quiz_id, 'question_count', 10, 'reused', true,
            'ready', v_ready, 'generated_checksum', p_content_checksum,
            'persisted_checksum', v_persisted_checksum
        );
    end if;
    if v_mapping_count > 0 and not p_replace then
        raise exception 'existing quiz pack is incomplete; explicit replacement is required';
    end if;
    if p_replace then
        delete from public.quiz_questions where quiz_id = p_quiz_id;
    end if;

    v_order := 0;
    for v_item in select value from jsonb_array_elements(p_questions)
    loop
        v_order := v_order + 1;
        if nullif(btrim(v_item ->> 'question_text'), '') is null
           or nullif(btrim(v_item ->> 'option_a'), '') is null
           or nullif(btrim(v_item ->> 'option_b'), '') is null
           or nullif(btrim(v_item ->> 'option_c'), '') is null
           or nullif(btrim(v_item ->> 'option_d'), '') is null
           or nullif(btrim(v_item ->> 'subject'), '') is null
           or v_item ->> 'subject' = 'current-affairs'
           or nullif(btrim(v_item ->> 'topic'), '') is null
           or v_item ->> 'correct_option' not in ('A','B','C','D')
           or nullif(btrim(v_item ->> 'source_document_id'), '') is not null
           or v_item ->> 'verification_status' <> 'verified'
           or coalesce((v_item ->> 'verification_score')::numeric, 0) < 0.85
           or nullif(btrim(v_item ->> 'verification_notes'), '') is null
           or nullif(btrim(v_item ->> 'verified_at'), '') is null
           or coalesce((v_item -> 'verification_checks' ->> 'independent_model')::boolean, false) is not true
           or coalesce((v_item -> 'verification_checks' ->> 'source_grounded')::boolean, true) is not false
           or nullif(btrim(v_item ->> 'canonical_claim'), '') is null
           or nullif(btrim(v_item ->> 'knowledge_entity'), '') is null
           or nullif(btrim(v_item ->> 'knowledge_relation'), '') is null
           or nullif(btrim(v_item ->> 'knowledge_answer_value'), '') is null
           or v_item ->> 'knowledge_time_scope' <> 'timeless'
           or coalesce(v_item ->> 'stem_hash', '') !~ '^[0-9a-f]{64}$'
           or coalesce(v_item ->> 'content_hash', '') !~ '^[0-9a-f]{64}$'
           or coalesce(v_item ->> 'variant_fingerprint', '') !~ '^[0-9a-f]{64}$' then
            raise exception 'question % failed the independently verified timeless contract', v_order;
        end if;

        select * into v_micro_topic
        from public.quiz_micro_topics mt
        where mt.id = (v_item ->> 'micro_topic_id')::uuid
          and mt.key = v_item ->> 'micro_topic_key'
          and mt.active;
        if not found or not exists (
            select 1 from public.quiz_chapters c
            where c.id = v_micro_topic.chapter_id
              and c.subject_key = v_item ->> 'subject'
              and c.name = v_item ->> 'topic'
              and c.active
        ) then
            raise exception 'question % is outside its active curated chapter', v_order;
        end if;

        if coalesce(v_item ->> 'knowledge_key', '') !~ '^[0-9a-f]{64}$'
           or nullif(btrim(v_item ->> 'entity_key'), '') is null
           or nullif(btrim(v_item ->> 'relation_key'), '') is null
           or nullif(btrim(v_item ->> 'answer_value'), '') is null
           or v_item ->> 'time_scope' <> 'timeless' then
            raise exception 'question % is missing canonical knowledge identity', v_order;
        end if;
        v_entity := v_item ->> 'entity_key';
        v_answer_value := v_item ->> 'answer_value';
        v_relation := public.normalized_identity_text(v_item ->> 'relation_key');
        v_identity_item := jsonb_build_object(
            'subject', v_item ->> 'subject',
            'entity_key', v_entity,
            'relation_key', v_relation,
            'answer_value', v_answer_value,
            'time_scope', 'timeless'
        );
        v_knowledge_key := public.knowledge_identity_hash(v_identity_item);
        if v_knowledge_key <> v_item ->> 'knowledge_key' then
            raise exception 'question % failed canonical knowledge identity parity', v_order;
        end if;
        perform pg_advisory_xact_lock(hashtextextended('knowledge:' || v_knowledge_key, 0));

        insert into public.knowledge_points (
            knowledge_key, subject_key, micro_topic_id, canonical_claim,
            entity_key, relation_key, answer_value, time_scope,
            syllabus_location, syllabus_status, status
        ) values (
            v_knowledge_key, v_item ->> 'subject', v_micro_topic.id,
            v_item ->> 'canonical_claim', public.normalized_identity_text(v_entity),
            v_relation, v_answer_value, 'timeless', v_item ->> 'topic',
            'mapped', 'active'
        )
        on conflict (knowledge_key) do update set updated_at = now()
        returning * into v_knowledge;

        if v_knowledge.subject_key <> v_item ->> 'subject'
           or v_knowledge.entity_key <> public.normalized_identity_text(v_entity)
           or v_knowledge.relation_key <> v_relation
           or public.normalized_identity_text(v_knowledge.answer_value)
              <> public.normalized_identity_text(v_answer_value)
           or v_knowledge.time_scope <> 'timeless' then
            raise exception 'question % has a knowledge identity collision', v_order;
        end if;
        if exists (
            select 1 from public.questions q
            where q.knowledge_point_id = v_knowledge.id
              and q.status not in ('rejected','quarantined')
              and greatest(q.created_at, coalesce(q.last_used_at::timestamptz, q.created_at))
                  >= now() - interval '30 days'
        ) then
            raise exception 'question % repeats a knowledge point inside the 30-day cooldown', v_order;
        end if;

        v_effective_item := v_item || jsonb_build_object(
            'source_document_id', null, 'source_url', null, 'source_title', null,
            'source_domain', null, 'source_kind', null, 'source_published_at', null,
            'source_accessed_at', null, 'evidence_summary', null,
            'fact_version', null,
            'language', coalesce(nullif(v_item ->> 'language', ''), 'bn')
        );
        v_stem_hash := public.question_stem_hash(v_item ->> 'question_text');
        v_content_hash := public.question_content_hash(v_effective_item);
        if v_stem_hash <> v_item ->> 'stem_hash'
           or v_stem_hash <> v_item ->> 'question_hash'
           or v_content_hash <> v_item ->> 'content_hash'
           or public.question_variant_fingerprint(v_item)
              <> v_item ->> 'variant_fingerprint' then
            raise exception 'question % failed immutable content identity checks', v_order;
        end if;

        perform pg_advisory_xact_lock(hashtextextended('question-stem:' || v_stem_hash, 0));
        select * into v_existing from public.questions q
        where q.content_hash = v_content_hash limit 1;
        if found then
            if v_existing.stem_hash <> v_stem_hash
               or v_existing.subject <> v_item ->> 'subject'
               or v_existing.topic <> v_item ->> 'topic'
               or v_existing.knowledge_point_id <> v_knowledge.id
               or v_existing.status in ('reported','under_review','quarantined','rejected','archived')
               or v_existing.review_required then
                raise exception 'question content cannot be reused at position %', v_order;
            end if;
            v_question_id := v_existing.id;
        else
            select * into v_previous from public.questions q
            where q.stem_hash = v_stem_hash
            order by q.content_version desc, q.created_at desc, q.id desc limit 1;
            if found then
                v_content_version := v_previous.content_version + 1;
            else
                v_content_version := 1;
                v_previous.id := null;
            end if;
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
                v_item ->> 'subject', v_item ->> 'topic',
                lower(coalesce(nullif(v_item ->> 'difficulty', ''), 'medium')),
                nullif(v_item ->> 'gemini_model', ''), 'gemini_model_validated',
                nullif(v_item ->> 'week_number', '')::integer,
                coalesce(nullif(v_item ->> 'bot_type', ''), 'daily_mcq'),
                v_stem_hash, v_item ->> 'normalized_text', 'active',
                v_micro_topic.id, v_micro_topic.key, null, null, null, null,
                null, null, null, null, (v_item ->> 'verified_at')::timestamptz,
                'verified', v_item ->> 'verification_notes',
                (v_item ->> 'verification_score')::numeric,
                nullif(v_item ->> 'verification_model', ''), null, null, false,
                v_stem_hash, v_content_hash, v_content_version, v_previous.id,
                coalesce(nullif(v_item ->> 'language', ''), 'bn'), v_knowledge.id,
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
            confidence, checks, notes, checked_at, verification_basis
        ) values (
            v_question_id, null, nullif(v_item ->> 'verification_model', ''),
            'verified', (v_item ->> 'verification_score')::numeric,
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes',
            (v_item ->> 'verified_at')::timestamptz, 'independent_model'
        );
        insert into public.content_verification_artifacts (
            knowledge_point_id, question_id, verdict, confidence,
            verifier_type, verifier_ref, checks, notes, checked_at
        ) values (
            v_knowledge.id, v_question_id, 'verified',
            (v_item ->> 'verification_score')::numeric, 'independent_model',
            v_item ->> 'verification_model',
            coalesce(v_item -> 'verification_checks', '{}'::jsonb),
            v_item ->> 'verification_notes', (v_item ->> 'verified_at')::timestamptz
        );
        insert into public.quiz_questions (quiz_id, question_id, question_order)
        values (p_quiz_id, v_question_id, v_order);
    end loop;

    select count(*) into v_mapping_count from public.quiz_questions
    where quiz_id = p_quiz_id;
    if v_mapping_count <> 10 then
        raise exception 'atomic quiz save did not produce exactly 10 mappings';
    end if;
    v_persisted_checksum := public.quiz_pack_checksum(p_quiz_id);
    v_ready := v_persisted_checksum = p_content_checksum;
    if not v_ready then
        insert into public.quiz_pack_integrity_failures (
            quiz_id, worker_id, generated_checksum, persisted_checksum,
            question_ids, question_count, diagnostic_code
        )
        select p_quiz_id, p_worker_id, p_content_checksum, v_persisted_checksum,
               coalesce(array_agg(qq.question_id order by qq.question_order), '{}'),
               count(*)::integer, 'saved_pack_checksum_mismatch'
        from public.quiz_questions qq where qq.quiz_id = p_quiz_id;
        update public.quiz_runs set
            status = 'integrity_failed', question_count = v_mapping_count,
            generated_checksum = p_content_checksum,
            persisted_checksum = v_persisted_checksum,
            checksum_contract_version = 2, integrity_verified = false,
            integrity_diagnostic_code = 'saved_pack_checksum_mismatch',
            last_error_category = 'database_integrity_error', last_error_at = now(),
            worker_id = null, claimed_at = null, claim_expires_at = null,
            updated_at = now()
        where quiz_id = p_quiz_id and worker_id = p_worker_id;
    else
        update public.quiz_runs set
            status = 'ready', question_count = 10,
            content_checksum = p_content_checksum,
            generated_checksum = p_content_checksum,
            persisted_checksum = v_persisted_checksum,
            checksum_contract_version = 2, integrity_verified = true,
            integrity_diagnostic_code = null, last_error_category = null,
            generated_at = coalesce(generated_at, now()), ready_at = now(),
            updated_at = now()
        where quiz_id = p_quiz_id and worker_id = p_worker_id;
    end if;
    return jsonb_build_object(
        'quiz_id', p_quiz_id, 'question_count', v_mapping_count, 'reused', false,
        'ready', v_ready, 'generated_checksum', p_content_checksum,
        'persisted_checksum', v_persisted_checksum
    );
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
        'migration_version', '20260808160000',
        'ready',
            to_regprocedure('public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)') is not null
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
            ) then 'service_role:save_model_validated_quiz_pack_atomic' end
        ], null))
    );
$$;

revoke all on function public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)
    from public, anon, authenticated;
revoke all on function public.get_source_optional_generation_contract()
    from public, anon, authenticated;
grant execute on function public.save_model_validated_quiz_pack_atomic(text,text,jsonb,text,boolean)
    to service_role;
grant execute on function public.get_source_optional_generation_contract()
    to service_role;
