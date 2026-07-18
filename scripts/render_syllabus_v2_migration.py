"""Render the immutable syllabus-v2 seed migration from the Python catalogue."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from config.syllabus import SYLLABUS


def catalogue_payload() -> list[dict]:
    return [
        {
            "subject_key": subject_key,
            "exam_relevance": list(chapters[0].exam_relevance),
            "chapters": [
                {
                    "key": chapter.key,
                    "name": chapter.name,
                    "display_order": chapter.display_order,
                    "priority": chapter.priority,
                    "rotation_enabled": chapter.rotation_enabled,
                    "micro_topics": [
                        {
                            "key": topic.key,
                            "name": topic.name,
                        }
                        for topic in chapter.micro_topics
                    ],
                }
                for chapter in chapters
            ],
        }
        for subject_key, chapters in SYLLABUS.items()
    ]


def render_sql() -> str:
    payload = json.dumps(catalogue_payload(), ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    chapter_count = sum(len(chapters) for chapters in SYLLABUS.values())
    topic_count = sum(len(chapter.micro_topics) for chapters in SYLLABUS.values() for chapter in chapters)
    return f"""-- Syllabus-v2 normalized catalogue generated from config/syllabus_catalog.py.
-- Catalogue SHA-256: {digest}
-- Seed size: 13 subjects, {chapter_count} chapters, {topic_count} new micro-topics.
-- Existing hashed :core micro-topics remain intact for source and quiz history compatibility.

alter table public.quiz_chapters
    add column if not exists key text,
    add column if not exists exam_relevance text[] not null default '{{}}',
    add column if not exists priority smallint not null default 2,
    add column if not exists rotation_enabled boolean not null default false,
    add column if not exists syllabus_version integer not null default 1;

alter table public.quiz_micro_topics
    add column if not exists priority smallint not null default 2,
    add column if not exists syllabus_version integer not null default 1;

do $constraints$
begin
    if not exists (
        select 1 from pg_constraint
        where conname = 'quiz_chapters_key_format'
          and conrelid = 'public.quiz_chapters'::regclass
    ) then
        alter table public.quiz_chapters add constraint quiz_chapters_key_format
            check (key is null or (key = lower(key) and key !~ '[[:space:]]'));
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'quiz_chapters_priority_range'
          and conrelid = 'public.quiz_chapters'::regclass
    ) then
        alter table public.quiz_chapters add constraint quiz_chapters_priority_range
            check (priority between 1 and 3);
    end if;
    if not exists (
        select 1 from pg_constraint
        where conname = 'quiz_micro_topics_priority_range'
          and conrelid = 'public.quiz_micro_topics'::regclass
    ) then
        alter table public.quiz_micro_topics add constraint quiz_micro_topics_priority_range
            check (priority between 1 and 3);
    end if;
end;
$constraints$;

create unique index if not exists idx_quiz_chapters_key
    on public.quiz_chapters (key)
    where key is not null;
create index if not exists idx_quiz_chapters_rotation
    on public.quiz_chapters (subject_key, rotation_enabled, display_order);
create index if not exists idx_quiz_micro_topics_priority
    on public.quiz_micro_topics (chapter_id, active, priority desc, last_used_at);

do $seed$
declare
    subject_entry jsonb;
    chapter_entry jsonb;
    topic_entry jsonb;
    chapter_id uuid;
begin
    for subject_entry in
        select value from jsonb_array_elements($catalogue${payload}$catalogue$::jsonb)
    loop
        update public.quiz_subjects
        set exam_relevance = array(
                select jsonb_array_elements_text(subject_entry->'exam_relevance')
            ),
            updated_at = now()
        where subject_key = subject_entry->>'subject_key';

        if not found then
            raise exception 'Unknown canonical syllabus subject: %', subject_entry->>'subject_key';
        end if;

        for chapter_entry in
            select value from jsonb_array_elements(subject_entry->'chapters')
        loop
            insert into public.quiz_chapters (
                subject_key, key, name, normalized_name, display_order,
                exam_relevance, priority, rotation_enabled, syllabus_version, active
            ) values (
                subject_entry->>'subject_key',
                chapter_entry->>'key',
                chapter_entry->>'name',
                lower(btrim(chapter_entry->>'name')),
                (chapter_entry->>'display_order')::integer,
                array(select jsonb_array_elements_text(subject_entry->'exam_relevance')),
                (chapter_entry->>'priority')::smallint,
                (chapter_entry->>'rotation_enabled')::boolean,
                2,
                true
            )
            on conflict (subject_key, name) do update set
                key = excluded.key,
                normalized_name = excluded.normalized_name,
                display_order = excluded.display_order,
                exam_relevance = excluded.exam_relevance,
                priority = excluded.priority,
                rotation_enabled = excluded.rotation_enabled,
                syllabus_version = excluded.syllabus_version,
                active = true,
                updated_at = now()
            returning id into chapter_id;

            for topic_entry in
                select value from jsonb_array_elements(chapter_entry->'micro_topics')
            loop
                insert into public.quiz_micro_topics (
                    chapter_id, key, name, normalized_name, exam_relevance,
                    difficulty_targets, target_coverage, mastery_relevance,
                    priority, syllabus_version, active
                ) values (
                    chapter_id,
                    topic_entry->>'key',
                    topic_entry->>'name',
                    lower(btrim(topic_entry->>'name')),
                    array(select jsonb_array_elements_text(subject_entry->'exam_relevance')),
                    case (chapter_entry->>'priority')::smallint
                        when 3 then '{{"easy":2,"medium":5,"hard":3}}'::jsonb
                        when 2 then '{{"easy":3,"medium":5,"hard":2}}'::jsonb
                        else '{{"easy":4,"medium":5,"hard":1}}'::jsonb
                    end,
                    case (chapter_entry->>'priority')::smallint
                        when 3 then 20 when 2 then 12 else 8
                    end,
                    case (chapter_entry->>'priority')::smallint
                        when 3 then 2.0 when 2 then 1.5 else 1.0
                    end,
                    (chapter_entry->>'priority')::smallint,
                    2,
                    true
                )
                on conflict (key) do update set
                    chapter_id = excluded.chapter_id,
                    name = excluded.name,
                    normalized_name = excluded.normalized_name,
                    exam_relevance = excluded.exam_relevance,
                    difficulty_targets = excluded.difficulty_targets,
                    target_coverage = excluded.target_coverage,
                    mastery_relevance = excluded.mastery_relevance,
                    priority = excluded.priority,
                    syllabus_version = excluded.syllabus_version,
                    active = true,
                    updated_at = now();
            end loop;
        end loop;
    end loop;
end;
$seed$;

alter table public.quiz_subjects enable row level security;
alter table public.quiz_chapters enable row level security;
alter table public.quiz_micro_topics enable row level security;

revoke all on table public.quiz_subjects, public.quiz_chapters,
    public.quiz_micro_topics from public, anon, authenticated;
grant select, insert, update, delete on table public.quiz_subjects,
    public.quiz_chapters, public.quiz_micro_topics to service_role;
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    args.output.write_text(render_sql(), encoding="utf-8")


if __name__ == "__main__":
    main()
