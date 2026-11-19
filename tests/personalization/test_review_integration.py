"""Read-only integration checks for the joined review contracts (no HTTP sockets or model calls)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from api import server
from api.sp3_real import DATA_SOURCE, real_plan, real_plan_options
from api.sp3_service import (
    list_swap_alternatives, personalized_plan_options, preview_personalized_swap,
    preview_personalized_removal, remove_planned_activity, what_if_skip_planned_activity,
    preview_personalized_addition,
)
from personalization.models import StudentPreference


@pytest.fixture
def review_case(valid_preference_payload):
    payload = deepcopy(valid_preference_payload)
    payload["limits"]["max_duration_minutes"] = None
    preference = StudentPreference.model_validate(payload)
    options = personalized_plan_options(preference, target_total=80)["options"]
    return payload, preference, options, options[1]["result"]


def test_remove_contracts_are_identical_and_do_not_replace_or_move(review_case):
    _, preference, _, base = review_case
    expected = remove_planned_activity(preference, base, "SEM-A")
    assert preview_personalized_removal(preference, base, "SEM-A") == expected
    assert preview_personalized_swap(preference, base, "SEM-A", None) == expected
    before = {row["activity_id"]: row["scheduled_blocks"] for row in base["plan"]["selected_activities"]}
    after = {row["activity_id"]: row["scheduled_blocks"] for row in expected["result"]["plan"]["selected_activities"]}
    assert after == {key: value for key, value in before.items() if key != "SEM-A"}
    assert expected["warnings"] == ["BELOW_TARGET"]


def test_preview_refreshes_explanations_to_match_the_selected_plan(review_case):
    _, preference, _, base = review_case
    result = preview_personalized_swap(preference, base, "SEM-A", "SEM-C")["result"]
    assert {row["activity_id"] for row in result["personalization"]["selected_breakdown"]} == {
        row["activity_id"] for row in result["plan"]["selected_activities"]
    }
    assert result["checker_violations"] == 0


def test_real_review_routes_and_both_remove_routes_use_one_contract(review_case):
    payload, _, _, _ = review_case
    payload["limits"]["max_fee"] = None
    preference = StudentPreference.model_validate(payload)
    base = real_plan("first_plan", target_total=80, preference=preference)
    removed = base["plan"]["selected_activities"][0]["activity_id"]
    common = dict(confirmed_profile=True, preference=payload, base_result=base)
    swap = server.preview_sp3_smart_swap(server.SmartSwapRequest(**common, remove_activity_id=removed, add_activity_id=None), source="real")
    direct = server.preview_sp3_removal(server.CalendarActivityChangeRequest(**common, activity_id=removed), source="real")
    assert swap == direct
    assert swap["result"]["data_source"] == DATA_SOURCE
    assert swap["added_activity_ids"] == []
    alternatives = list_swap_alternatives(preference, base, removed, source="real")
    assert alternatives["status"] == "ALTERNATIVES"
    assert all(item["preview"]["result"]["checker_violations"] == 0 for item in alternatives["items"])
    what_if = what_if_skip_planned_activity(preference, base, removed, source="real")
    assert what_if["result"]["data_source"] == DATA_SOURCE


def test_current_availability_overrides_a_stale_plan_in_every_route(review_case):
    payload, _, _, base = review_case
    availability = {
        "availability_version": "sp3-availability/0.2", "timezone": "Asia/Ho_Chi_Minh",
        "week_start": "2026-11-09", "apply_scope": "SEMESTER_WEEKLY",
        "effective_from": "2026-11-09", "effective_until": "2027-03-31",
        "weekly_blocks": [{"day_of_week": day, "start_time": "07:00", "end_time": "21:00"}
                          for day in ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")],
        "exceptions": [],
        "busy_intervals": [{"start": "2026-11-12T14:00:00+07:00", "end": "2026-11-12T15:00:00+07:00"}],
    }
    request = dict(confirmed_profile=True, preference=payload, base_result=base,
                   remove_activity_id="SEM-A", availability=availability)
    response = server.list_sp3_swap_alternatives(server.SwapAlternativesRequest(**request))
    assert "SEM-C" not in {item["activity_id"] for item in response["items"]}
    with pytest.raises(server.HTTPException) as error:
        server.preview_sp3_smart_swap(server.SmartSwapRequest(**request, add_activity_id="SEM-C"))
    assert error.value.status_code == 422


def test_each_sp3_endpoint_is_registered_once():
    routes = [(tuple(sorted(route.methods)), route.path) for route in server.app.routes if hasattr(route, "methods")]
    assert len(routes) == len(set(routes))


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for controller integration")
@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("scenario", ["flow", "alternatives_failure", "impact_failure", "suggestion_one", "focus", "above_target", "empty"])
def test_real_page_controllers_review_confirm_and_persist_without_network(review_case, mobile, scenario):
    payload, preference, options, base = review_case
    activity_id = "SEM-A"
    if scenario == "above_target":
        base = preview_personalized_addition(preference, base, "SEM-C")["result"]
        options[1]["result"] = base
        activity_id = "SEM-C"
    data = _panel_payload(preference, base, activity_id)
    data.update(preference=payload, options=options, mobile=mobile, scenario=scenario, activityId=activity_id)
    if scenario.endswith("_failure"):
        data["failure"] = scenario.removesuffix("_failure")
    if scenario == "empty":
        # Transport-level empty response: keep all scoring in untouched engine previews.
        data["alternatives"] = {**data["alternatives"], "items": []}
    if scenario == "flow":
        edited = data["alternatives"]["items"][0]
        data["dashboard"] = _panel_payload(preference, edited["preview"]["result"], edited["activity_id"])
        data["dashboard"].update(baseVersion=edited["preview"]["result"]["plan"]["plan_version"], activityId=edited["activity_id"])
    if scenario == "suggestion_one":
        assert len(data["suggestion"]["added_activity_ids"]) == 1
    if scenario == "above_target":
        assert data["impact"]["target_met"] is True
    _run_panel_controllers(data)


def _panel_payload(preference, base, activity_id):
    return {"alternatives": list_swap_alternatives(preference, base, activity_id, limit=10),
            "impact": remove_planned_activity(preference, base, activity_id),
            "suggestion": what_if_skip_planned_activity(preference, base, activity_id)}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for controller integration")
@pytest.mark.parametrize("mobile", [False, True])
def test_multi_activity_suggestion_uses_a_real_engine_preview(valid_preference_payload, mobile):
    payload = deepcopy(valid_preference_payload)
    payload["limits"]["max_duration_minutes"] = None
    payload["limits"]["max_activities"] = None
    preference = StudentPreference.model_validate(payload)
    options = personalized_plan_options(preference, target_total=80)["options"]
    options[1] = deepcopy(options[0])
    data = _panel_payload(preference, options[1]["result"], "QUIZ-L")
    assert len(data["suggestion"]["added_activity_ids"]) >= 2
    data.update(preference=payload, options=options, mobile=mobile, scenario="suggestion_two", activityId="QUIZ-L")
    _run_panel_controllers(data)


def _run_panel_controllers(data):
    root = Path(__file__).resolve().parents[2]
    output = subprocess.run(["node", "tests/review_dashboard_runtime.cjs"], cwd=root,
                            input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, timeout=25)
    assert output.returncode == 0, output.stdout + output.stderr
    assert json.loads(output.stdout.splitlines()[-1])["passed"] is True


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for controller integration")
@pytest.mark.parametrize("mobile", [False, True])
@pytest.mark.parametrize("scenario", ["onboarding", "onboarding_error", "onboarding_delayed", "onboarding_switch"])
def test_onboarding_plans_once_then_reviews_before_confirmation(review_case, mobile, scenario):
    payload, preference, _, _ = review_case
    data = {"preference": payload, "mobile": mobile, "scenario": scenario,
            "options": personalized_plan_options(preference, target_total=85)["options"]}
    if scenario == "onboarding_error":
        data["failure"] = "options"
    _run_panel_controllers(data)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for controller integration")
@pytest.mark.parametrize("mobile", [False, True])
def test_operational_source_uses_real_review_routes_even_if_global_selector_changed(review_case, mobile):
    payload, _, _, _ = review_case
    payload["limits"]["max_fee"] = None
    preference = StudentPreference.model_validate(payload)
    options = real_plan_options(preference, target_total=80)["options"]
    base = options[1]["result"]
    activity_id = base["plan"]["selected_activities"][0]["activity_id"]
    data = {"preference": payload, "options": options, "mobile": mobile,
            "scenario": "real_source", "activityId": activity_id,
            "alternatives": list_swap_alternatives(preference, base, activity_id, source="real", limit=10),
            "impact": remove_planned_activity(preference, base, activity_id, source="real"),
            "suggestion": what_if_skip_planned_activity(preference, base, activity_id, source="real")}
    _run_panel_controllers(data)
