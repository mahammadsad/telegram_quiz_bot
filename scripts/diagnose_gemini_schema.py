"""Staging-only probe for Gemini request-context compatibility.

The probe performs no database or Telegram writes and never prints model output
or the recent-question exclusions it reads.
"""

from __future__ import annotations

from datetime import date

from bot import (
    _mcq_response_schema,
    build_mcq_prompt,
)
from services.gemini_provider_pool import GeminiGenerationError, GeminiProviderPool
from services.source_grounding import load_generation_bundle


def main() -> int:
    subject = "computer"
    chapter = "অপারেটিং সিস্টেম"
    bundle = load_generation_bundle(subject, chapter, date.today())
    schema = _mcq_response_schema(bundle)
    full_prompt = build_mcq_prompt(subject, chapter, bundle, [])
    variants = (
        ("first_1000_chars", full_prompt[:1000]),
        ("first_2500_chars", full_prompt[:2500]),
        ("first_4000_chars", full_prompt[:4000]),
        ("full_no_exclusions", full_prompt),
    )
    pool = GeminiProviderPool()
    failed = False
    for label, prompt in variants:
        try:
            text, _metadata = pool.generate_subject_quiz(
                prompt=prompt,
                response_schema=schema,
            )
        except GeminiGenerationError as exc:
            failed = True
            print(
                f"CONTEXT_PROBE variant={label} prompt_chars={len(prompt)} "
                f"result=failed category={exc.category}"
            )
        else:
            print(
                f"CONTEXT_PROBE variant={label} prompt_chars={len(prompt)} "
                f"result=accepted response_chars={len(text)}"
            )
    return int(failed)


if __name__ == "__main__":
    raise SystemExit(main())
