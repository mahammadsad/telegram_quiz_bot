-- Keep learner-facing APIs on canonical subject keys (for example `computer`)
-- while the legacy questions table continues to store internal names (for
-- example `Computer Education`).  Wrappers preserve the already-tested query
-- bodies and normalize both filters and response projections.

create or replace function public.canonical_subject_key(p_value text)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
select coalesce(
    (
        select s.subject_key
        from public.quiz_subjects s
        where s.subject_key = p_value or s.internal_name = p_value
        order by (s.subject_key = p_value) desc, s.subject_key
        limit 1
    ),
    p_value
);
$$;

create or replace function public.canonical_subject_internal_name(p_value text)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
select coalesce(
    (
        select s.internal_name
        from public.quiz_subjects s
        where s.subject_key = p_value
        limit 1
    ),
    p_value
);
$$;

create or replace function public.canonicalize_subject_rows(p_rows jsonb)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
select coalesce(
    jsonb_agg(
        item || jsonb_build_object(
            'subjectKey', public.canonical_subject_key(item->>'subjectKey')
        )
        order by position
    ),
    '[]'::jsonb
)
from jsonb_array_elements(coalesce(p_rows, '[]'::jsonb))
    with ordinality as rows(item, position);
$$;

alter function public.get_user_learning_dashboard(uuid)
    rename to get_user_learning_dashboard_internal;
alter function public.get_user_due_reviews(uuid, integer, integer)
    rename to get_user_due_reviews_internal;
alter function public.get_user_wrong_questions(uuid, text, integer, integer)
    rename to get_user_wrong_questions_internal;
alter function public.get_user_bookmarks(uuid)
    rename to get_user_bookmarks_internal;
alter function public.get_leaderboard_page(text, text, integer, integer)
    rename to get_leaderboard_page_internal;

create or replace function public.get_user_learning_dashboard(p_user_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    v_result := public.get_user_learning_dashboard_internal(p_user_id);
    v_result := jsonb_set(
        v_result,
        '{weakSubjects}',
        public.canonicalize_subject_rows(v_result->'weakSubjects'),
        true
    );
    v_result := jsonb_set(
        v_result,
        '{subjectPerformance}',
        public.canonicalize_subject_rows(v_result->'subjectPerformance'),
        true
    );
    return v_result;
end;
$$;

create or replace function public.get_user_due_reviews(
    p_user_id uuid,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    v_result := public.get_user_due_reviews_internal(p_user_id, p_limit, p_offset);
    return jsonb_set(
        v_result,
        '{rows}',
        public.canonicalize_subject_rows(v_result->'rows'),
        true
    );
end;
$$;

create or replace function public.get_user_wrong_questions(
    p_user_id uuid,
    p_subject_key text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    v_result := public.get_user_wrong_questions_internal(
        p_user_id,
        public.canonical_subject_internal_name(p_subject_key),
        p_limit,
        p_offset
    );
    return jsonb_set(
        v_result,
        '{rows}',
        public.canonicalize_subject_rows(v_result->'rows'),
        true
    );
end;
$$;

create or replace function public.get_user_bookmarks(p_user_id uuid)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    v_result := public.get_user_bookmarks_internal(p_user_id);
    return jsonb_set(
        v_result,
        '{questions}',
        public.canonicalize_subject_rows(v_result->'questions'),
        true
    );
end;
$$;

create or replace function public.get_leaderboard_page(
    p_type text default 'weekly_accuracy',
    p_subject_key text default null,
    p_limit integer default 20,
    p_offset integer default 0
)
returns jsonb
language plpgsql
stable
security invoker
set search_path = ''
as $$
declare
    v_result jsonb;
begin
    v_result := public.get_leaderboard_page_internal(
        p_type,
        public.canonical_subject_internal_name(p_subject_key),
        p_limit,
        p_offset
    );
    if lower(coalesce(p_type, '')) = 'subject_accuracy' then
        v_result := jsonb_set(
            v_result,
            '{subjectKey}',
            to_jsonb(public.canonical_subject_key(p_subject_key)),
            true
        );
    end if;
    return v_result;
end;
$$;

revoke execute on function public.canonical_subject_key(text)
    from public, anon, authenticated;
revoke execute on function public.canonical_subject_internal_name(text)
    from public, anon, authenticated;
revoke execute on function public.canonicalize_subject_rows(jsonb)
    from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard_internal(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_user_due_reviews_internal(uuid, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_wrong_questions_internal(uuid, text, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_bookmarks_internal(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_leaderboard_page_internal(text, text, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_learning_dashboard(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_user_due_reviews(uuid, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    from public, anon, authenticated;
revoke execute on function public.get_user_bookmarks(uuid)
    from public, anon, authenticated;
revoke execute on function public.get_leaderboard_page(text, text, integer, integer)
    from public, anon, authenticated;

grant execute on function public.canonical_subject_key(text) to service_role;
grant execute on function public.canonical_subject_internal_name(text) to service_role;
grant execute on function public.canonicalize_subject_rows(jsonb) to service_role;
grant execute on function public.get_user_learning_dashboard_internal(uuid) to service_role;
grant execute on function public.get_user_due_reviews_internal(uuid, integer, integer)
    to service_role;
grant execute on function public.get_user_wrong_questions_internal(uuid, text, integer, integer)
    to service_role;
grant execute on function public.get_user_bookmarks_internal(uuid) to service_role;
grant execute on function public.get_leaderboard_page_internal(text, text, integer, integer)
    to service_role;
grant execute on function public.get_user_learning_dashboard(uuid) to service_role;
grant execute on function public.get_user_due_reviews(uuid, integer, integer)
    to service_role;
grant execute on function public.get_user_wrong_questions(uuid, text, integer, integer)
    to service_role;
grant execute on function public.get_user_bookmarks(uuid) to service_role;
grant execute on function public.get_leaderboard_page(text, text, integer, integer)
    to service_role;
