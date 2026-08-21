-- Public, answer-free discovery for published mock, sectional, and PYQ tests.

create or replace function public.get_learning_test_catalog(
    p_exam_key text default null,
    p_test_type text default null,
    p_subject_key text default null,
    p_limit integer default 50,
    p_offset integer default 0
)
returns jsonb
language sql
stable
security invoker
set search_path = ''
as $$
with filtered as (
    select
        instance.id,
        instance.title,
        instance.lifecycle_status,
        instance.question_count,
        instance.total_marks,
        instance.time_limit_seconds,
        instance.scheduled_start_at,
        instance.scheduled_end_at,
        definition.test_type,
        definition.subject_key,
        definition.rank_cohort,
        exam.exam_key,
        exam.display_name as exam_name,
        coalesce(max(section.negative_marks_per_wrong), 0) as negative_marks_per_wrong,
        count(section.id) as section_count
    from public.test_instances instance
    join public.test_definitions definition on definition.id = instance.test_definition_id
    left join public.exams exam on exam.id = definition.exam_id
    left join public.test_section_instances section on section.test_instance_id = instance.id
    where instance.lifecycle_status in ('published', 'open')
      and instance.question_count > 0
      and (p_exam_key is null or exam.exam_key = upper(p_exam_key))
      and (p_test_type is null or definition.test_type = p_test_type)
      and (p_subject_key is null or definition.subject_key = p_subject_key)
    group by instance.id, definition.id, exam.id
), page as (
    select * from filtered
    order by
        case when lifecycle_status = 'open' then 0 else 1 end,
        scheduled_start_at desc nulls last,
        title,
        id
    limit greatest(1, least(coalesce(p_limit, 50), 100))
    offset greatest(coalesce(p_offset, 0), 0)
)
select jsonb_build_object(
    'total', (select count(*) from filtered),
    'limit', greatest(1, least(coalesce(p_limit, 50), 100)),
    'offset', greatest(coalesce(p_offset, 0), 0),
    'rows', coalesce((select jsonb_agg(jsonb_build_object(
        'testInstanceId', row.id,
        'title', row.title,
        'testType', row.test_type,
        'examKey', row.exam_key,
        'examName', row.exam_name,
        'subjectKey', row.subject_key,
        'questionCount', row.question_count,
        'sectionCount', row.section_count,
        'totalMarks', row.total_marks,
        'timeLimitSeconds', row.time_limit_seconds,
        'negativeMarksPerWrong', row.negative_marks_per_wrong,
        'availability', row.lifecycle_status,
        'scheduledStartAt', row.scheduled_start_at,
        'scheduledEndAt', row.scheduled_end_at,
        'rankCohort', row.rank_cohort
    ) order by row.scheduled_start_at desc nulls last, row.title, row.id) from page row), '[]'::jsonb)
);
$$;

revoke all on function public.get_learning_test_catalog(text,text,text,integer,integer)
    from public, anon, authenticated;
grant execute on function public.get_learning_test_catalog(text,text,text,integer,integer)
    to service_role;
