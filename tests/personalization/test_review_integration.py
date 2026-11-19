"""Read-only integration checks for the joined review contracts (no HTTP sockets or model calls)."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from api import server
from api.sp3_real import real_plan
from api.sp3_service import (
    list_swap_alternatives, personalized_plan_options, preview_personalized_swap,
    preview_personalized_removal, remove_planned_activity, what_if_skip_planned_activity,
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
    payload, preference, _, _ = review_case
    base = real_plan("first_plan", target_total=80, preference=preference)
    removed = base["plan"]["selected_activities"][0]["activity_id"]
    common = dict(confirmed_profile=True, preference=payload, base_result=base)
    swap = server.preview_sp3_smart_swap(server.SmartSwapRequest(**common, remove_activity_id=removed, add_activity_id=None), source="real")
    direct = server.preview_sp3_removal(server.CalendarActivityChangeRequest(**common, activity_id=removed), source="real")
    assert swap == direct
    assert swap["result"]["data_source"] == "SP1-STORE-V2"
    assert swap["added_activity_ids"] == []
    alternatives = list_swap_alternatives(preference, base, removed, source="real")
    assert alternatives["status"] == "ALTERNATIVES"
    assert all(item["preview"]["result"]["checker_violations"] == 0 for item in alternatives["items"])
    what_if = what_if_skip_planned_activity(preference, base, removed, source="real")
    assert what_if["result"]["data_source"] == "SP1-STORE-V2"


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
def test_real_page_controllers_review_confirm_and_persist_without_network(review_case):
    payload, preference, options, base = review_case
    data = {"preference": payload, "options": options,
            "alternatives": list_swap_alternatives(preference, base, "SEM-A")}
    root = Path(__file__).resolve().parents[2]
    output = subprocess.run(["node", "tests/review_dashboard_runtime.cjs"], cwd=root,
                            input=json.dumps(data), text=True, encoding="utf-8", capture_output=True, timeout=25)
    assert output.returncode == 0, output.stdout + output.stderr
    assert json.loads(output.stdout.splitlines()[-1])["passed"] is True
