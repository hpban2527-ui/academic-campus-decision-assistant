from __future__ import annotations

from copy import deepcopy

from fastapi.testclient import TestClient

from api import server


client = TestClient(server.app)


def _request(preference: dict) -> dict:
    return {
        "confirmed": True,
        "preference": preference,
        "total_target": 80,
        "busy_intervals": [],
    }


def test_personalized_plan_requires_explicit_confirmation(valid_preference_payload):
    payload = _request(valid_preference_payload)
    payload["confirmed"] = False

    response = client.post("/api/sp3/personalized/plan", json=payload)

    assert response.status_code == 422


def test_personalized_plan_returns_auditable_breakdown(valid_preference_payload):
    response = client.post(
        "/api/sp3/personalized/plan",
        json=_request(valid_preference_payload),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["preference_confirmed"] is True
    assert result["personalization"]["algorithm"] == "weighted-deterministic-v1"
    assert result["integration"] == {
        "adapter": "personalization-planner-adapter/1.0",
        "planner_contract": "sp3-planner/0.2",
        "candidate_source": "upstream_planner_input",
        "ready_for_external_planner_input": True,
        "fixture_used_for_demo": True,
    }
    selected = {item["activity_id"] for item in result["plan"]["selected_activities"]}
    explained = {item["activity_id"] for item in result["personalization"]["selected_breakdown"]}
    assert selected == explained
    assert result["personalization"]["total_utility"] > 0


def test_weighted_campus_preference_changes_tie_break(valid_preference_payload):
    preference = deepcopy(valid_preference_payload)
    preference["campus_preferences"] = [{"campus_id": "DONG_HOA", "weight": 5}]
    preference["time_preferences"] = []

    response = client.post("/api/sp3/personalized/plan", json=_request(preference))

    assert response.status_code == 200, response.text
    selected = {item["activity_id"] for item in response.json()["plan"]["selected_activities"]}
    assert "SEM-B" in selected
    assert "SEM-A" not in selected


def test_confirmed_hard_exclusion_removes_matching_candidates(valid_preference_payload):
    preference = deepcopy(valid_preference_payload)
    preference["mode_preferences"] = []
    preference["hard_exclusions"]["modes"] = ["online"]

    response = client.post("/api/sp3/personalized/plan", json=_request(preference))

    assert response.status_code == 200, response.text
    hard_excluded = response.json()["personalization"]["hard_excluded"]
    excluded_ids = {item["activity_id"] for item in hard_excluded}
    assert {"QUIZ-M", "QUIZ-L"} <= excluded_ids
    selected_ids = {item["activity_id"] for item in response.json()["plan"]["selected_activities"]}
    assert not ({"QUIZ-M", "QUIZ-L"} & selected_ids)


def test_personalization_is_preserved_for_replan_and_what_if(valid_preference_payload):
    for scenario in ("replan", "what_if_skip"):
        payload = _request(deepcopy(valid_preference_payload))
        payload["scenario"] = scenario

        response = client.post("/api/sp3/personalized/plan", json=payload)

        assert response.status_code == 200, response.text
        result = response.json()
        assert result["scenario"] == "personalized_" + scenario
        assert result["personalization"]["strategy"] == "BALANCED"
        assert result["preference_confirmed"] is True


def test_preference_first_can_fill_the_confirmed_activity_ceiling(valid_preference_payload):
    preference = deepcopy(valid_preference_payload)
    preference["strategy"] = "PREFERENCE_FIRST"
    preference["time_preferences"] = []

    response = client.post("/api/sp3/personalized/plan", json=_request(preference))

    assert response.status_code == 200, response.text
    result = response.json()
    assert len(result["plan"]["selected_activities"]) == preference["limits"]["max_activities"]
    assert result["plan"]["search"]["complete"] is True
    assert result["plan"]["search"]["optimality_proven"] is True
