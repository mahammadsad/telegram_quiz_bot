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
        }
        for index in range(10)
    ]
