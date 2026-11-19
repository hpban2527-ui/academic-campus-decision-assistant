from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

from api.server import app
from api.sp3_service import (
    personalized_plan_options,
    preview_personalized_addition,
    preview_personalized_removal,
    preview_personalized_swap,
)
from personalization.models import StudentPreference


def _preference(valid_preference_payload, strategy: str = "BALANCED") -> StudentPreference:
    payload = deepcopy(valid_preference_payload)
    payload["strategy"] = strategy
    return StudentPreference.model_validate(payload)


def test_three_strategies_are_computed_and_identical_plans_are_deduplicated(valid_preference_payload) -> None:
    result = personalized_plan_options(_preference(valid_preference_payload), target_total=80)

    assert len(result["options"]) == 3
    assert {item["strategy"] for item in result["attempted"]} == {
        "MINIMUM_EFFORT",
        "BALANCED",
        "PREFERENCE_FIRST",
    }
    signatures = [item["signature"] for item in result["options"]]
    assert len(signatures) == len(set(signatures))
    assert all(item["plan"]["selected_activities"] is not None for item in result["options"])
    assert all("target_shortfall" in item for item in result["options"])


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


def test_calendar_add_and_remove_previews_are_whole_plan_validated(valid_preference_payload) -> None:
    preference = _preference(valid_preference_payload)
    base = next(
        option["result"] for option in personalized_plan_options(preference, target_total=80)["options"]
        if option["strategy"] == "BALANCED"
    )

    added = preview_personalized_addition(preference, base, "SEM-C")
    assert added["status"] == "PREVIEW"
    assert "SEM-C" in added["added_activity_ids"]
    assert added["after"]["projected_total"] is not None
    assert "target_shortfall" in added["after"]

    removed = preview_personalized_removal(preference, base, "SEM-A")
    assert removed["status"] == "PREVIEW"
    assert "SEM-A" in removed["dropped_activity_ids"]
    assert removed["after"]["projected_total"] is not None


def test_real_source_options_use_real_planner_and_canonical_weekly_availability(valid_preference_payload) -> None:
    availability = {
        "availability_version": "sp3-availability/0.2",
        "timezone": "Asia/Ho_Chi_Minh",
        "week_start": "2026-10-05",
        "apply_scope": "SEMESTER_WEEKLY",
        "weekly_blocks": [
            {"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
            for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        ],
        "effective_from": "2026-10-01",
        "effective_until": "2026-11-15",
        "exceptions": [{"date": "2026-10-12", "blocks": []}],
        "busy_intervals": [],
    }
    response = TestClient(app).post(
        "/api/sp3/personalized/options?source=real",
        json={
            "confirmed": True,
            "preference": valid_preference_payload,
            "scenario": "first_plan",
            "total_target": 80,
            "busy_intervals": [],
            "availability": availability,
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["source"] == "real"
    assert len(payload["attempted"]) == 3
    assert len(payload["options"]) == 3
    assert all(option["result"]["data_source"] == "SP1-STORE-V2" for option in payload["options"])
    assert all(option["result"]["availability"]["apply_scope"] == "SEMESTER_WEEKLY" for option in payload["options"])


def test_real_source_smart_swap_is_explicitly_unsupported(valid_preference_payload) -> None:
    response = TestClient(app).post(
        "/api/sp3/personalized/swap-preview?source=real",
        json={
            "confirmed_profile": True,
            "preference": valid_preference_payload,
            "base_result": {},
            "remove_activity_id": "A",
            "add_activity_id": "B",
        },
    )

    assert response.status_code == 422
    assert "not yet available for source=real" in response.json()["detail"]

    for endpoint in ("add-preview", "remove-preview"):
        unsupported = TestClient(app).post(
            f"/api/sp3/personalized/{endpoint}?source=real",
            json={
                "confirmed_profile": True,
                "preference": valid_preference_payload,
                "base_result": {},
                "activity_id": "A",
            },
        )
        assert unsupported.status_code == 422
        assert "source=real" in unsupported.json()["detail"]

