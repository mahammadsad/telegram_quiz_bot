-- Some legacy deployments store questions.subject as quiz_subjects.internal_name,
-- while current imports store quiz_subjects.subject_key. Resolve the value that
-- is actually present without rewriting historical question rows.

create or replace function public.canonical_subject_internal_name(p_value text)
returns text
language sql
stable
security invoker
set search_path = ''
as $$
with subject_match as (
    select s.subject_key, s.internal_name
    from public.quiz_subjects s
    where s.subject_key = p_value or s.internal_name = p_value
    order by (s.subject_key = p_value) desc, s.subject_key
    limit 1
), stored_value as (
    select q.subject, m.subject_key
    from public.questions q
    cross join subject_match m
    where q.subject in (m.subject_key, m.internal_name)
    group by q.subject, m.subject_key
    order by (q.subject = m.subject_key) desc, count(*) desc
    limit 1
)
select coalesce(
    (select subject from stored_value),
    (select subject_key from subject_match),
    p_value
);
$$;

revoke execute on function public.canonical_subject_internal_name(text)
    from public, anon, authenticated;
grant execute on function public.canonical_subject_internal_name(text)
    to service_role;
