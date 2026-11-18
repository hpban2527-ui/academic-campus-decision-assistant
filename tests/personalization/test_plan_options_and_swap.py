from __future__ import annotations

from copy import deepcopy

import pytest

from api.sp3_service import personalized_plan_options, preview_personalized_swap
from personalization.models import StudentPreference


def _preference(valid_preference_payload, strategy: str = "BALANCED") -> StudentPreference:
    payload = deepcopy(valid_preference_payload)
    payload["strategy"] = strategy
    return StudentPreference.model_validate(payload)


def test_three_strategies_are_computed_and_identical_plans_are_deduplicated(valid_preference_payload) -> None:
    result = personalized_plan_options(_preference(valid_preference_payload), target_total=80)

    assert 1 <= len(result["options"]) <= 3
    assert {item["strategy"] for item in result["attempted"]} == {
        "MINIMUM_EFFORT",
        "BALANCED",
        "PREFERENCE_FIRST",
    }
    signatures = [item["signature"] for item in result["options"]]
    assert len(signatures) == len(set(signatures))
    assert all(item["plan"]["selected_activities"] is not None for item in result["options"])


def test_swap_preview_rejects_unselected_or_same_activity(valid_preference_payload) -> None:
    preference = _preference(valid_preference_payload)
    base = personalized_plan_options(preference, target_total=80)["options"][0]["result"]
    selected = [item["activity_id"] for item in base["plan"]["selected_activities"]]
    assert selected

    with pytest.raises(ValueError, match="different"):
        preview_personalized_swap(preference, base, selected[0], selected[0])
    with pytest.raises(ValueError, match="selected"):
        preview_personalized_swap(preference, base, "NOT-IN-PLAN", selected[0])


def test_confirmed_canonical_availability_reaches_every_strategy(valid_preference_payload) -> None:
    availability = {
        "availability_version": "sp3-availability/0.2",
        "timezone": "Asia/Ho_Chi_Minh",
        "week_start": "2026-11-09",
        "apply_scope": "SEMESTER_WEEKLY",
        "weekly_blocks": [
            {"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        ],
        "effective_from": "2026-11-09",
        "effective_until": "2027-03-31",
        "exceptions": [{"date": "2026-11-17", "blocks": []}],
        "busy_intervals": [],
    }

    result = personalized_plan_options(
        _preference(valid_preference_payload),
        target_total=80,
        availability_request=availability,
    )

    assert result["options"]
    assert all(
        option["result"]["availability"]["effective_until"] == "2027-03-31"
        for option in result["options"]
    )


def test_swap_preview_rescores_whole_plan_and_preserves_unaffected(valid_preference_payload) -> None:
    preference = _preference(valid_preference_payload)
    options = personalized_plan_options(preference, target_total=80)["options"]
    base = next(option["result"] for option in options if option["strategy"] == "BALANCED")

    preview = preview_personalized_swap(preference, base, "SEM-A", "SEM-C")

    assert preview["status"] == "PREVIEW"
    assert preview["requires_confirmation"] is True
    assert preview["dropped_activity_ids"] == ["SEM-A"]
    assert "SEM-C" in preview["added_activity_ids"]
    assert preview["before"]["projected_total"] is not None
    assert preview["after"]["projected_total"] is not None
    assert preview["result"]["plan"]["selected_activities"]

