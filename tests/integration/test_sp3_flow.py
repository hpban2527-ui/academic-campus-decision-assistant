"""Lead-owned tests for the read-only SP3 handoff API."""

from __future__ import annotations

import sys
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from api.server import app

client = TestClient(app)


def test_sp1_catalog_preserves_review_status():
    response = client.get("/api/sp3/catalog")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["activity_count"] == 20
    assert body["unstructured_new_posts"] == 18
    assert body["term"]["id"] == "HK3_2025_2026"
    assert all(item["publication_status"] == "REVIEW_REQUIRED" for item in body["activities"])
    assert all(item["score_binding_verified"] is False for item in body["activities"])
    assert all(item["data_qa"]["activity_id"] == item["activity"]["activity_id"] for item in body["activities"])


def test_demo_planning_calls_real_sp2_and_sp3():
    response = client.post("/api/sp3/demo/plan", json={"scenario": "first_plan"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["mode"], body["official_award_verified"]) == ("DEMO_ONLY", False)
    assert body["data_source"] == "SYNTHETIC-DEMO"
    assert body["plan"]["status"] == "TARGET_MET"
    assert body["plan"]["score_summary"]["projected_total"] == 80
    assert len(body["plan"]["selected_activities"]) == 3
    assert body["feasibility"]["context"]["calendar_version"] == body["availability"]["calendar_version"]


def test_demo_replan_and_skip_are_read_only():
    replan = client.post("/api/sp3/demo/plan", json={"scenario": "replan"})
    assert replan.status_code == 200, replan.text
    assert replan.json()["plan"]["status"] == "TARGET_MET"
    assert replan.json()["plan"]["score_comparison"]["new_projected_total"] == 80
    skipped = client.post("/api/sp3/demo/plan", json={"scenario": "what_if_skip"})
    assert skipped.status_code == 200, skipped.text
    assert skipped.json()["plan"]["status"] == "PARTIAL"
    assert "QUIZ-L" not in {
        item["activity_id"] for item in skipped.json()["plan"]["selected_activities"]
    }
    assert skipped.json()["official_award_verified"] is False


def test_demo_scenario_is_explicit():
    response = client.post("/api/sp3/demo/plan", json={"scenario": "official"})
    assert response.status_code == 422
