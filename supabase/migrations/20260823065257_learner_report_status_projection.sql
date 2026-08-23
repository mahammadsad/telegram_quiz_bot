-- Reporter-visible, answer-free moderation status. This is callable only by
-- the trusted application service role; Telegram identity is verified in app.py.
create or replace function public.get_my_question_report_statuses(
    p_user_id uuid,
    p_limit integer default 50,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security definer
set search_path = ''
as $$
with mine as (
    select report.id, report.question_id, report.quiz_id, report.reason,
           report.status as report_status, report.created_at,
           moderation.status as case_status, moderation.resolution,
           moderation.updated_at as case_updated_at
    from public.question_reports report
    left join public.question_moderation_cases moderation
      on moderation.question_id = report.question_id
    where report.user_id = p_user_id
), page as (
    select * from mine
    order by created_at desc, id desc
    limit greatest(1, least(coalesce(p_limit, 50), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'items', coalesce(jsonb_agg(jsonb_build_object(
        'reportId', id, 'questionId', question_id, 'quizId', quiz_id,
        'reason', reason, 'reportStatus', report_status,
        'caseStatus', coalesce(case_status, 'received'),
        'resolution', case when case_status in ('resolved','dismissed','superseded','reinstated')
                           then resolution else null end,
        'createdAt', created_at, 'updatedAt', coalesce(case_updated_at, created_at)
    ) order by created_at desc, id desc), '[]'::jsonb),
    'total', (select count(*) from mine),
    'limit', greatest(1, least(coalesce(p_limit, 50), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0)
)
from page;
$$;

revoke execute on function public.get_my_question_report_statuses(uuid,integer,integer)
    from public, anon, authenticated;
grant execute on function public.get_my_question_report_statuses(uuid,integer,integer)
    to service_role;
