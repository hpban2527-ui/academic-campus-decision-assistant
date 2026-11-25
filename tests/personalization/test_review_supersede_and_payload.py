"""Alternatives requests: an older request stops when a newer one starts, and the shared
feasibility block is sent once without changing what the page receives."""
from __future__ import annotations

from copy import deepcopy

import pytest
from fastapi import HTTPException

from api import server, sp3_service
from api.sp3_real import real_plan_options
from api.sp3_service import (
    ReviewSuperseded, list_swap_alternatives, personalized_plan_options, share_alternative_feasibility,
)
from personalization.models import StudentPreference


def _synthetic_case(payload):
    preference = StudentPreference.model_validate(deepcopy(payload))
    base = next(o for o in personalized_plan_options(preference, target_total=80)["options"]
                if o["strategy"] == "BALANCED")["result"]
    return preference, base


def test_a_superseded_request_stops_between_candidates(valid_preference_payload):
    preference, base = _synthetic_case(valid_preference_payload)
    calls = []

    def superseded():
        calls.append(1)
        return len(calls) > 1  # a newer request starts after the first candidate

    with pytest.raises(ReviewSuperseded):
        list_swap_alternatives(preference, base, "SEM-A", 10, is_superseded=superseded)
    # A check that never fires changes nothing.
    assert list_swap_alternatives(preference, base, "SEM-A", 10, is_superseded=lambda: False) == \
        list_swap_alternatives(preference, base, "SEM-A", 10)


def test_only_a_newer_request_of_the_same_student_term_and_source_supersedes():
    first = server._review_superseded_check("SUP-1", "HK1_2026_2027", "real")
    other_student = server._review_superseded_check("SUP-2", "HK1_2026_2027", "real")
    other_term = server._review_superseded_check("SUP-1", "HK3_2025_2026", "real")
    assert not first() and not other_student() and not other_term()
    second = server._review_superseded_check("SUP-1", "HK1_2026_2027", "real")
    assert first() and not second() and not other_student() and not other_term()
    assert server._review_superseded_check(None, "HK1_2026_2027", "real") is None


def test_the_endpoint_answers_409_when_superseded(monkeypatch, valid_preference_payload):
    preference, base = _synthetic_case(valid_preference_payload)

    def replaced(*args, **kwargs):
        raise ReviewSuperseded("newer request")

    monkeypatch.setattr(server, "_sp3_list_alternatives", replaced)
    request = server.SwapAlternativesRequest(
        confirmed_profile=True, preference=preference, base_result=base, remove_activity_id="SEM-A", limit=10)
    with pytest.raises(HTTPException) as error:
        server.list_sp3_swap_alternatives(request, source="synthetic", student_id=None, term_id="SYNTHETIC-DEMO")
    assert error.value.status_code == 409 and error.value.detail["code"] == "REVIEW_SUPERSEDED"


def _restore(shared: dict) -> dict:
    """What reviewDashShareAlternativeFeasibility does in the page."""
    restored = deepcopy(shared)
    block = restored.pop("shared")["feasibility"]
    for item in restored["items"]:
        item["preview"]["result"]["feasibility"] = block
    return restored


def test_shared_feasibility_round_trips_on_the_synthetic_source(valid_preference_payload):
    preference, base = _synthetic_case(valid_preference_payload)
    response = list_swap_alternatives(preference, base, "SEM-A", 10)
    shared = share_alternative_feasibility(response)
    if len(response["items"]) > 0:
        assert "shared" in shared and all("feasibility" not in i["preview"]["result"] for i in shared["items"])
    assert _restore(shared) == response if "shared" in shared else shared == response


def test_shared_feasibility_round_trips_and_shrinks_the_real_response():
    import json
    preference = StudentPreference.model_validate({
        "topic_preferences": [{"topic_id": "mathematics", "weight": 4}], "category_priorities": [],
        "campus_preferences": [], "mode_preferences": [], "time_preferences": [],
        "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
        "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None}, "strategy": "BALANCED",
    })
    option = next(o for o in real_plan_options(preference, term_id="HK1_2026_2027", target_total=80)["options"]
                  if o.get("status") == "READY")
    base = option["result"]
    remove_id = base["plan"]["selected_activities"][0]["activity_id"]
    response = list_swap_alternatives(preference, base, remove_id, 10, source="real", term_id="HK1_2026_2027")
    assert len(response["items"]) > 1
    shared = share_alternative_feasibility(response)
    assert _restore(shared) == response
    assert len(json.dumps(shared)) < len(json.dumps(response)) / 2


def test_differing_feasibility_blocks_are_left_alone():
    response = {"items": [
        {"preview": {"result": {"feasibility": {"a": 1}, "plan": {}}}},
        {"preview": {"result": {"feasibility": {"a": 2}, "plan": {}}}},
    ]}
    assert share_alternative_feasibility(response) is response
    assert share_alternative_feasibility({"items": []}) == {"items": []}
