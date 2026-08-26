"""Staging-only probe for Gemini structured-output compatibility.

The probe performs no database or Telegram writes and never prints model output.
"""

from __future__ import annotations

from copy import deepcopy

from bot import _mcq_response_schema
from services.gemini_provider_pool import GeminiGenerationError, GeminiProviderPool
from services.source_grounding import GroundingBundle, MicroTopicReference


def _bundle() -> GroundingBundle:
    topics = tuple(
        MicroTopicReference(
            id=f"00000000-0000-4000-8000-{index:012d}",
            key=f"computer:operating-systems:t{index:02d}",
            name=f"Diagnostic topic {index}",
        )
        for index in range(1, 5)
    )
    return GroundingBundle(
        subject_key="computer",
        chapter="অপারেটিং সিস্টেম",
        micro_topic_id=topics[0].id,
        micro_topic_key=topics[0].key,
        micro_topic_name=topics[0].name,
        documents=(),
        topics=topics,
    )


def main() -> int:
    strict = _mcq_response_schema(_bundle())
    without_bounds = deepcopy(strict)
    without_bounds.pop("minItems")
    without_bounds.pop("maxItems")
    without_enums = deepcopy(without_bounds)
    for field in ("subject_key", "chapter", "micro_topic_key", "difficulty"):
        without_enums["items"]["properties"][field].pop("enum", None)
    minimal = {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
        },
    }
    variants = (
        ("minimal", minimal),
        ("without_enums_or_bounds", without_enums),
        ("without_outer_bounds", without_bounds),
        ("strict", strict),
    )
    pool = GeminiProviderPool()
    prompt = "Return a JSON array that satisfies the supplied schema. Use harmless placeholder text."
    failed = False
    for label, schema in variants:
        try:
            text, _metadata = pool.generate_subject_quiz(
                prompt=prompt,
                response_schema=schema,
            )
        except GeminiGenerationError as exc:
            failed = True
            print(f"SCHEMA_PROBE variant={label} result=failed category={exc.category}")
        else:
            print(f"SCHEMA_PROBE variant={label} result=accepted response_chars={len(text)}")
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
