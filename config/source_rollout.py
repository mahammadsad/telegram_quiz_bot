"""Explicit source-approved chapter rotation for the 13-subject rollout.

This is intentionally narrower than the full syllabus catalogue. A chapter may
enter generation only after its source bundle is reviewed, imported, and
covered by the rollout tests.
"""

from __future__ import annotations

ROTATION_CHAPTER_KEYS: dict[str, tuple[str, ...]] = {
    "computer": (
        "computer:fundamentals",
        "computer:hardware-software",
        "computer:operating-systems",
        "computer:internet-networking",
        "computer:ms-office",
        "computer:databases",
        "computer:cyber-security",
    ),
    "bengali": (
        "bengali:phonetics",
        "bengali:word-sentence",
    ),
    "reasoning": (
        "reasoning:syllogism",
        "reasoning:venn",
    ),
    "mathematics": (
        "mathematics:simplification",
        "mathematics:geometry",
    ),
    "english": (
        "english:parts-tense",
        "english:error-correction",
    ),
    "miscellaneous": (
        "miscellaneous:national-symbols",
        "miscellaneous:indian-culture",
    ),
    "polity": (
        "polity:making-preamble-citizenship",
        "polity:pm-council",
    ),
    "geography": (
        "geography:india-location",
        "geography:rivers-water",
    ),
    "science": (
        "science:measurement-motion",
        "science:heat-optics-sound",
    ),
    "economics": (
        "economics:banking-rbi",
        "economics:inflation",
    ),
    "history": (
        "history:ancient-india",
        "history:national-movement",
    ),
    "environment": (
        "environment:ecosystem",
        "environment:biodiversity",
    ),
    "current-affairs": (
        "current-affairs:national",
        "current-affairs:science-technology",
        "current-affairs:economy-reports",
    ),
}

STATIC_SOURCE_BUNDLES: tuple[str, ...] = (
    "sources/computer_education_pilot.json",
    "sources/bengali_reasoning_gk_expansion_v1.json",
    "sources/mathematics_expansion_v2.json",
    "sources/english_expansion_v2.json",
    "sources/polity_expansion_v2.json",
    "sources/geography_economics_history_environment_expansion_v1.json",
    "sources/science_expansion_v2.json",
)

DYNAMIC_SOURCE_SUBJECTS: frozenset[str] = frozenset({"current-affairs"})
