-- The legacy schema already has a generated UNIQUE (user_id, question_id)
-- constraint. Early personalized-learning rollouts checked only a fixed
-- constraint name and could therefore add an identical second index. Keep the
-- canonical legacy constraint when both exist, while preserving the named
-- foundation constraint on databases where it is the only one.

do $$
begin
    if exists (
        select 1
        from pg_constraint candidate
        where candidate.conrelid = 'public.personal_review_schedule'::regclass
          and candidate.contype = 'u'
          and candidate.conname <> 'personal_review_schedule_user_question_key'
          and array(
              select a.attname
              from unnest(candidate.conkey) with ordinality as key(attnum, position)
              join pg_attribute a
                on a.attrelid = candidate.conrelid
               and a.attnum = key.attnum
              order by key.position
          ) = array['user_id', 'question_id']::name[]
    ) then
        alter table public.personal_review_schedule
            drop constraint if exists personal_review_schedule_user_question_key;
    end if;
end;
$$;
