from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi.testclient import TestClient

import api.sp3_service as sp3_service
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


def test_three_strategies_are_computed_independently(valid_preference_payload) -> None:
    result = personalized_plan_options(_preference(valid_preference_payload), target_total=80)

    assert len(result["options"]) == 3
    assert {item["strategy"] for item in result["attempted"]} == {
        "MINIMUM_EFFORT",
        "BALANCED",
        "PREFERENCE_FIRST",
    }
    assert [item["strategy"] for item in result["options"]] == [
        "MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST",
    ]
    assert all(item["plan"]["selected_activities"] is not None for item in result["options"])
    assert all("target_shortfall" in item for item in result["options"])


def test_identical_strategy_results_still_return_three_cards(valid_preference_payload, monkeypatch) -> None:
    preference = _preference(valid_preference_payload)
    identical = personalized_plan_options(preference, target_total=80)["options"][0]["result"]
    monkeypatch.setattr(sp3_service, "personalized_demo_plan", lambda *args, **kwargs: deepcopy(identical))

    result = personalized_plan_options(preference, target_total=80)

    assert len(result["options"]) == 3
    assert [item["status"] for item in result["options"]] == ["READY", "READY", "READY"]
    assert result["options"][1]["duplicate_of"] == "MINIMUM_EFFORT"
    assert result["options"][2]["duplicate_of"] == "MINIMUM_EFFORT"
    assert result["deduplicated"] == 0
    assert result["message"] is None


def test_one_strategy_failure_does_not_abort_other_cards(valid_preference_payload, monkeypatch) -> None:
    original = sp3_service.personalized_demo_plan

    def fail_balanced(preference, **kwargs):
        if preference.strategy.value == "BALANCED":
            raise RuntimeError("SP3 independent personalized-plan check failed.")
        return original(preference, **kwargs)

    monkeypatch.setattr(sp3_service, "personalized_demo_plan", fail_balanced)
    result = personalized_plan_options(_preference(valid_preference_payload), target_total=80)

    assert len(result["options"]) == 3
    assert [item["status"] for item in result["options"]] == ["READY", "FAILED", "READY"]
    assert result["options"][1]["error"] == "SP3 independent personalized-plan check failed."


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
        "/api/sp3/personalized/options?source=real&term_id=HK1_2026_2027",
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
    assert all(option["result"]["data_source"] == "OPERATIONAL-DATASET" for option in payload["options"])
    assert all(option["result"]["availability"]["apply_scope"] == "SEMESTER_WEEKLY" for option in payload["options"])


def test_real_source_smart_swap_and_null_addition_removal_are_supported(valid_preference_payload) -> None:
    # The real catalog has activities with unstated fees. This test covers removal, not the fee cap.
    without_fee_cap = deepcopy(valid_preference_payload)
    without_fee_cap["limits"]["max_fee"] = None
    preference = _preference(without_fee_cap)
    from api.sp3_real import real_plan_options

    real_base = real_plan_options(preference, term_id="HK1_2026_2027", target_total=80)["options"][0]["result"]
    selected = [item["activity_id"] for item in real_base["plan"]["selected_activities"]]
    assert selected

    removed = preview_personalized_swap(
        preference,
        real_base,
        selected[0],
        None,
        source="real",
        term_id="HK1_2026_2027",
    )
    assert removed["status"] == "PREVIEW"
    assert selected[0] in removed["dropped_activity_ids"]
    assert removed["result"]["data_source"] == "OPERATIONAL-DATASET"

    invalid = TestClient(app).post(
        "/api/sp3/personalized/swap-preview?source=real&term_id=HK1_2026_2027",
        json={
            "confirmed_profile": True,
            "preference": valid_preference_payload,
            "base_result": {},
            "remove_activity_id": "A",
            "add_activity_id": None,
        },
    )
    assert invalid.status_code == 422
    assert "plan and feasibility" in invalid.json()["detail"]
