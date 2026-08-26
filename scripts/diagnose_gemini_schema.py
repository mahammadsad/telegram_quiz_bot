"""Staging-only probe for Gemini request-context compatibility.

The probe performs no database or Telegram writes and never prints model output
or the recent-question exclusions it reads.
"""

from __future__ import annotations

from datetime import date

from bot import (
    _mcq_response_schema,
    _recent_generation_exclusions,
    build_mcq_prompt,
)
from services.gemini_provider_pool import GeminiGenerationError, GeminiProviderPool
from services.source_grounding import load_generation_bundle


def main() -> int:
    subject = "computer"
    chapter = "অপারেটিং সিস্টেম"
    bundle = load_generation_bundle(subject, chapter, date.today())
    schema = _mcq_response_schema(bundle)
    exclusions = _recent_generation_exclusions(subject)
    variants = (
        ("no_exclusions", []),
        ("twenty_exclusions", exclusions[:20]),
        ("all_exclusions", exclusions),
    )
    pool = GeminiProviderPool()
    failed = False
    for label, selected_exclusions in variants:
        prompt = build_mcq_prompt(
            subject,
            chapter,
            bundle,
            selected_exclusions,
        )
        try:
            text, _metadata = pool.generate_subject_quiz(
                prompt=prompt,
                response_schema=schema,
            )
        except GeminiGenerationError as exc:
            failed = True
            print(
                f"CONTEXT_PROBE variant={label} exclusions={len(selected_exclusions)} "
                f"prompt_chars={len(prompt)} result=failed category={exc.category}"
            )
        else:
            print(
                f"CONTEXT_PROBE variant={label} exclusions={len(selected_exclusions)} "
                f"prompt_chars={len(prompt)} result=accepted response_chars={len(text)}"
            )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
