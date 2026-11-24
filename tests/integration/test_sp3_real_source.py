"""The ?source=real switch plans over the SP1 v2 store; the default stays the synthetic MVP fixture."""
import pytest
from fastapi.testclient import TestClient

from api.server import app

client = TestClient(app)


def test_default_catalog_is_unchanged():
    data = client.get("/api/sp3/catalog").json()
    assert data.get("data_source") != "OPERATIONAL-DATASET"
    assert data["term"]["id"] == "SYNTHETIC-DEMO"


def test_real_catalog_lists_handed_over_activities():
    data = client.get("/api/sp3/catalog?source=real&term_id=HK1_2026_2027").json()
    assert data["data_source"] == "OPERATIONAL-DATASET"
    assert data["term"]["id"] == "HK1_2026_2027"
    assert data["activity_count"] == len(data["activities"]) > 0
    assert data["source_dataset"]["bound"] <= data["activity_count"]
    assert all(row["score_binding_verified"] is False for row in data["activities"])


def test_unknown_source_is_rejected():
    assert client.get("/api/sp3/catalog?source=prod").status_code == 422


def test_default_plan_is_still_synthetic():
    data = client.post("/api/sp3/demo/plan", json={"scenario": "first_plan"}).json()
    assert data["data_source"] == "SYNTHETIC-DEMO"


@pytest.mark.parametrize("scenario", ["first_plan", "replan", "what_if_skip"])
def test_real_plan_runs_and_passes_the_checker(scenario):
    response = client.post("/api/sp3/demo/plan?source=real&term_id=HK1_2026_2027", json={"scenario": scenario, "total_target": 80})
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["data_source"] == "OPERATIONAL-DATASET"
    assert data["official_award_verified"] is False
    plan = data["plan"]
    assert plan["status"] in {"TARGET_MET", "PARTIAL", "NO_FEASIBLE_PLAN", "NEEDS_REVIEW"}
    catalog_ids = {a["activity"]["activity_id"] for a in data["feasibility"]["candidates"]}
    assert {a["activity_id"] for a in plan["selected_activities"]} <= catalog_ids
    if scenario == "what_if_skip":
        skipped = data["what_if_skip_activity_id"]
        assert skipped and skipped not in {a["activity_id"] for a in plan["selected_activities"]}


def test_real_plan_respects_busy_slots():
    url = "/api/sp3/demo/plan?source=real&term_id=HK1_2026_2027"
    free = client.post(url, json={"scenario": "first_plan"}).json()["plan"]
    day = min(block["start"][:10] for item in free["selected_activities"] for block in item["scheduled_blocks"])
    busy = [{"start": f"{day}T00:00:00+07:00", "end": f"{day}T23:59:00+07:00"}]
    plan = client.post(url, json={"scenario": "first_plan", "busy_intervals": busy}).json()["plan"]
    for item in plan["selected_activities"]:
        for block in item["scheduled_blocks"]:
            assert not block["start"].startswith(day)
