from __future__ import annotations

import json
from pathlib import Path

from personalization.evaluation import aggregate_evaluations, evaluate_prediction
from personalization.models import CampusId, CategoryId, ModeId, StudentPreference, TimeSlotId, TopicId


ROOT = Path(__file__).resolve().parents[2]


def test_exact_prediction_scores_one(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    expected = {
        "preferences": [
            {"dimension": "topic", "value": "mathematics", "min_weight": 5},
            {"dimension": "topic", "value": "artificial_intelligence", "min_weight": 4},
            {"dimension": "category", "value": "C4", "min_weight": 5},
            {"dimension": "campus", "value": "NVC", "min_weight": 5},
            {"dimension": "mode", "value": "online", "min_weight": 5},
            {"dimension": "time", "value": "weekday_evening", "min_weight": 4},
        ],
        "limits": {
            "max_activities": 4,
            "max_duration_minutes": 600,
            "max_fee": 200000,
        },
        "hard_exclusions": [],
        "strategy": "BALANCED",
    }

    metrics = evaluate_prediction(expected, preference)

    assert metrics["precision"] == 1.0
    assert metrics["recall"] == 1.0
    assert metrics["weight_accuracy"] == 1.0
    assert all(item["correct"] for item in metrics["limit_checks"])
    assert metrics["hard_exclusions"]["correct"] is True
    assert metrics["strategy"]["correct"] is True


def test_aggregate_keeps_provider_errors_visible(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)
    metrics = evaluate_prediction(
        {
            "preferences": [{"dimension": "topic", "value": "mathematics", "min_weight": 5}],
            "limits": {},
            "hard_exclusions": [],
            "strategy": "BALANCED",
        },
        preference,
    )

    summary = aggregate_evaluations([
        {"status": "OK", "metrics": metrics},
        {"status": "ERROR", "error": {"code": "AI_TIMEOUT"}},
    ])

    assert summary["case_count"] == 2
    assert summary["successful_cases"] == 1
    assert summary["failed_cases"] == 1
    assert summary["preference_recall"] == 1.0
    assert summary["preference_precision"] < 1.0


def test_invented_optional_limit_counts_as_constraint_failure(valid_preference_payload):
    preference = StudentPreference.model_validate(valid_preference_payload)

    metrics = evaluate_prediction(
        {
            "preferences": [],
            "limits": {},
            "hard_exclusions": [],
            "strategy": "BALANCED",
        },
        preference,
    )

    assert len(metrics["limit_checks"]) == 3
    assert all(item["expected"] is None for item in metrics["limit_checks"])
    assert not any(item["correct"] for item in metrics["limit_checks"])


def test_reviewed_vietnamese_fixture_uses_supported_contract_values():
    payload = json.loads((ROOT / "data" / "personalization_eval_cases.json").read_text(encoding="utf-8"))
    allowed = {
        "topic": {item.value for item in TopicId},
        "category": {item.value for item in CategoryId},
        "campus": {item.value for item in CampusId},
        "mode": {item.value for item in ModeId},
        "time": {item.value for item in TimeSlotId},
    }

    assert payload["schema_version"] == "personalization-eval/0.1"
    assert len(payload["cases"]) >= 8
    assert len({case["case_id"] for case in payload["cases"]}) == len(payload["cases"])
    for case in payload["cases"]:
        assert case["text"].strip()
        rows = case["expected"]["preferences"] + case["expected"]["hard_exclusions"]
        for row in rows:
            assert row["dimension"] in allowed
            assert row["value"] in allowed[row["dimension"]]
