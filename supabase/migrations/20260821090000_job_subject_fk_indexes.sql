-- Cover the subject foreign keys used by the durable delivery and content
-- replenishment queues. These indexes keep parent-key updates/deletes and
-- subject-scoped operational queries from scanning the complete job tables.

create index if not exists idx_quiz_jobs_subject_key
    on public.quiz_jobs (subject_key);

create index if not exists idx_content_replenishment_jobs_subject_key
    on public.content_replenishment_jobs (subject_key);
