-- Legacy projects created personal_review_schedule without cascade actions.
-- Align those foreign keys with the canonical schema so user/question cleanup
-- cannot leave an undeletable private review schedule.

alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_user_id_fkey;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_user_id_fkey
    foreign key (user_id) references public.users(id) on delete cascade;

alter table public.personal_review_schedule
    drop constraint if exists personal_review_schedule_question_id_fkey;
alter table public.personal_review_schedule
    add constraint personal_review_schedule_question_id_fkey
    foreign key (question_id) references public.questions(id) on delete cascade;
