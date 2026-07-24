from __future__ import annotations

import pytest


@pytest.fixture
def valid_questions():
    return [
        {
            "question": f"বাংলা পরীক্ষামূলক প্রশ্ন নম্বর {index} কী?",
            "options": [f"বিকল্প {index}-{option}" for option in range(4)],
            "correct_index": index % 4,
            "explanation": "এটি সংক্ষিপ্ত বাংলা ব্যাখ্যা।",
            "detailed_explanation": "এটি সঠিক উত্তরের বিস্তারিত বাংলা ব্যাখ্যা। পরীক্ষার জন্য তথ্যটি গুরুত্বপূর্ণ।",
            "subject_key": "history",
            "chapter": "আধুনিক ভারত",
            "difficulty": "easy" if index < 3 else "medium" if index < 8 else "hard",
            "micro_topic_id": "11111111-1111-4111-8111-111111111111",
            "micro_topic_key": "history:modern-india:core",
            "source_document_id": "22222222-2222-4222-8222-222222222222",
            "source_url": "https://ncert.nic.in/history/example",
            "source_title": "NCERT ইতিহাসের যাচাইকৃত উৎস",
            "source_domain": "ncert.nic.in",
            "source_kind": "official",
            "source_published_at": None,
            "source_accessed_at": "2026-07-18T09:00:00+00:00",
            "evidence_summary": "যাচাইকৃত উৎসে প্রশ্নটির তথ্য সরাসরি সমর্থিত।",
            "fact_version": "2026-07-18",
            "language": "bn",
            "verification_status": "verified",
            "verification_score": 0.95,
            "verification_notes": "All source-grounded checks passed.",
            "verification_checks": {
                "correct_answer_supported": True,
                "options_distinct": True,
                "explanation_supported": True,
                "unambiguous": True,
                "fact_current": True,
                "micro_topic_match": True,
                "difficulty_match": True,
            },
            "verified_at": "2026-07-18T10:00:00+00:00",
            "verification_model": "test-verifier",
        }
        for index in range(10)
    ]
