-- Keep extension-owned functions and operators out of the API-exposed public
-- schema. Replace the one dependent RPC in the same migration, then remove the
-- historical duplicate GIN index found in restored staging data.

create schema if not exists extensions;
alter extension pg_trgm set schema extensions;

create or replace function public.find_similar_questions(
    query_normalized text,
    query_bot_type text default 'daily_mcq',
    sim_threshold double precision default 0.35,
    match_count integer default 5
)
returns table (id uuid, question_text text, similarity real)
language sql
stable
security invoker
set search_path = ''
as $$
    select q.id, q.question_text,
           extensions.similarity(q.normalized_text, query_normalized) as similarity
    from public.questions q
    where q.bot_type = query_bot_type
      and q.status = 'active'
      and q.verification_status = 'verified'
      and not q.review_required
      and (q.expires_at is null or q.expires_at >= now())
      and extensions.similarity(q.normalized_text, query_normalized) >= sim_threshold
    order by extensions.similarity(q.normalized_text, query_normalized) desc
    limit greatest(1, least(match_count, 20));
$$;

revoke all on function public.find_similar_questions(text,text,double precision,integer)
    from public, anon, authenticated;
grant execute on function public.find_similar_questions(text,text,double precision,integer)
    to service_role;

drop index if exists public.idx_questions_normalized_text;
