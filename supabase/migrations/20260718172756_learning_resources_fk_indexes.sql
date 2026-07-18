-- Cover the two denormalized taxonomy foreign keys used by imports and
-- integrity checks. The primary quiz lookup remains micro_topic_id-first.

create index if not exists idx_learning_resources_subject_key
    on public.learning_resources (subject_key);

create index if not exists idx_learning_resources_micro_topic_key
    on public.learning_resources (micro_topic_key);
