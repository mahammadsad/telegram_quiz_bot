-- Practice clients address questions with `questionId` everywhere else.  The
-- legacy bookmark projection exposed the same UUID as `id`, which made a real
-- bookmarked-question queue render but fail when it tried to submit or remove
-- that question.  Preserve the resource projection and ordering while making
-- the question identity contract consistent.

create or replace function public.get_user_bookmarks(p_user_id uuid)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with canonical as (
    select public.canonicalize_subject_rows(
        public.get_user_bookmarks_internal(p_user_id)
    ) as payload
), projected as (
    select
        payload,
        coalesce((
            select jsonb_agg(
                (entry.value - 'id')
                || jsonb_build_object('questionId', entry.value->'id')
                order by entry.ordinality
            )
            from jsonb_array_elements(coalesce(payload->'questions', '[]'::jsonb))
                with ordinality as entry(value, ordinality)
        ), '[]'::jsonb) as questions
    from canonical
)
select payload || jsonb_build_object(
    'questions', questions,
    'mode', 'practice',
    'sourceType', 'bookmark'
)
from projected;
$$;

revoke all on function public.get_user_bookmarks(uuid)
    from public, anon, authenticated;
grant execute on function public.get_user_bookmarks(uuid) to service_role;
