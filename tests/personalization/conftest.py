from __future__ import annotations

import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture
def valid_preference_payload() -> dict:
    return {
        "topic_preferences": [
            {"topic_id": "mathematics", "weight": 5},
            {"topic_id": "artificial_intelligence", "weight": 4},
        ],
        "category_priorities": [{"category_id": "C4", "weight": 5}],
        "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
        "mode_preferences": [{"mode": "online", "weight": 5}],
        "time_preferences": [{"time_slot": "weekday_evening", "weight": 4}],
        "limits": {
            "max_activities": 4,
            "max_duration_minutes": 600,
            "max_fee": 200000,
        },
        "hard_exclusions": {
            "campus_ids": [],
            "modes": [],
            "time_slots": [],
        },
        "strategy": "BALANCED",
    }
