"""Evaluation helpers for Vietnamese preference extraction.

The benchmark measures extraction only.  It never asks the model to score an
activity or create a schedule, keeping the AI boundary from days 1-4 intact.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from personalization.models import StudentPreference


PREFERENCE_DIMENSIONS = {
    "topic": ("topic_preferences", "topic_id"),
    "category": ("category_priorities", "category_id"),
    "campus": ("campus_preferences", "campus_id"),
    "mode": ("mode_preferences", "mode"),
    "time": ("time_preferences", "time_slot"),
}
EXCLUSION_DIMENSIONS = {
    "campus": "campus_ids",
    "mode": "modes",
    "time": "time_slots",
}


def _prediction_preferences(preference: StudentPreference) -> dict[tuple[str, str], int]:
    result: dict[tuple[str, str], int] = {}
    for dimension, (field, key) in PREFERENCE_DIMENSIONS.items():
        for item in getattr(preference, field):
            value = getattr(item, key).value
            result[(dimension, value)] = item.weight
    return result


def _prediction_exclusions(preference: StudentPreference) -> set[tuple[str, str]]:
    result: set[tuple[str, str]] = set()
    for dimension, field in EXCLUSION_DIMENSIONS.items():
        result.update((dimension, item.value) for item in getattr(preference.hard_exclusions, field))
    return result


def evaluate_prediction(expected: Mapping[str, Any], preference: StudentPreference) -> dict[str, Any]:
    """Compare one validated model output with one reviewed expectation."""

    expected_rows = expected.get("preferences", [])
    expected_weights = {
        (row["dimension"], row["value"]): int(row.get("min_weight", 1))
        for row in expected_rows
    }
    predicted_weights = _prediction_preferences(preference)
    expected_keys = set(expected_weights)
    predicted_keys = set(predicted_weights)
    true_positive = expected_keys & predicted_keys
    missing = expected_keys - predicted_keys
    unexpected = predicted_keys - expected_keys
    weight_passes = {
        key for key in true_positive
        if predicted_weights[key] >= expected_weights[key]
    }

    expected_exclusions = {
        (row["dimension"], row["value"])
        for row in expected.get("hard_exclusions", [])
    }
    predicted_exclusions = _prediction_exclusions(preference)
    exclusion_correct = expected_exclusions == predicted_exclusions

    limit_checks = []
    expected_limits = expected.get("limits", {})
    for field in ("max_activities", "max_duration_minutes", "max_fee"):
        value = expected_limits.get(field)
        actual = getattr(preference.limits, field)
        # Skip fields that are absent on both sides, but count an invented
        # model limit as an explicit constraint failure.
        if value is not None or actual is not None:
            limit_checks.append({"field": field, "expected": value, "actual": actual, "correct": actual == value})
    expected_strategy = expected.get("strategy")
    strategy_correct = expected_strategy is None or preference.strategy.value == expected_strategy

    tp = len(true_positive)
    predicted_count = len(predicted_keys)
    expected_count = len(expected_keys)
    return {
        "preference_counts": {
            "expected": expected_count,
            "predicted": predicted_count,
            "true_positive": tp,
        },
        "precision": 1.0 if predicted_count == 0 and expected_count == 0 else (tp / predicted_count if predicted_count else 0.0),
        "recall": 1.0 if expected_count == 0 else tp / expected_count,
        "weight_accuracy": 1.0 if not true_positive else len(weight_passes) / len(true_positive),
        "missing": [{"dimension": key[0], "value": key[1]} for key in sorted(missing)],
        "unexpected": [{"dimension": key[0], "value": key[1]} for key in sorted(unexpected)],
        "weight_failures": [
            {
                "dimension": key[0],
                "value": key[1],
                "minimum": expected_weights[key],
                "actual": predicted_weights[key],
            }
            for key in sorted(true_positive - weight_passes)
        ],
        "hard_exclusions": {
            "correct": exclusion_correct,
            "expected": [{"dimension": key[0], "value": key[1]} for key in sorted(expected_exclusions)],
            "actual": [{"dimension": key[0], "value": key[1]} for key in sorted(predicted_exclusions)],
        },
        "limit_checks": limit_checks,
        "strategy": {
            "expected": expected_strategy,
            "actual": preference.strategy.value,
            "correct": strategy_correct,
        },
    }


def aggregate_evaluations(case_results: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Return micro preference metrics and exact constraint metrics."""

    successful = [row for row in case_results if row.get("status") == "OK"]
    counts = [row["metrics"]["preference_counts"] for row in successful]
    expected = sum(row["expected"] for row in counts)
    predicted = sum(row["predicted"] for row in counts)
    true_positive = sum(row["true_positive"] for row in counts)
    matched = sum(row["metrics"]["preference_counts"]["true_positive"] for row in successful)
    weight_score = sum(
        row["metrics"]["weight_accuracy"] * row["metrics"]["preference_counts"]["true_positive"]
        for row in successful
    )
    constraint_checks: list[bool] = []
    strategy_checks: list[bool] = []
    for row in successful:
        metrics = row["metrics"]
        constraint_checks.append(metrics["hard_exclusions"]["correct"])
        constraint_checks.extend(item["correct"] for item in metrics["limit_checks"])
        if metrics["strategy"]["expected"] is not None:
            strategy_checks.append(metrics["strategy"]["correct"])

    precision = 1.0 if predicted == 0 and expected == 0 else (true_positive / predicted if predicted else 0.0)
    recall = 1.0 if expected == 0 else true_positive / expected
    weight_accuracy = 1.0 if matched == 0 else weight_score / matched
    constraint_accuracy = 1.0 if not constraint_checks else sum(constraint_checks) / len(constraint_checks)
    strategy_accuracy = 1.0 if not strategy_checks else sum(strategy_checks) / len(strategy_checks)
    metrics_for_overall = [precision, recall, weight_accuracy, constraint_accuracy, strategy_accuracy]
    return {
        "case_count": len(case_results),
        "successful_cases": len(successful),
        "failed_cases": len(case_results) - len(successful),
        "preference_precision": round(precision, 4),
        "preference_recall": round(recall, 4),
        "weight_accuracy": round(weight_accuracy, 4),
        "constraint_accuracy": round(constraint_accuracy, 4),
        "strategy_accuracy": round(strategy_accuracy, 4),
        "overall_score": round(sum(metrics_for_overall) / len(metrics_for_overall), 4),
    }
