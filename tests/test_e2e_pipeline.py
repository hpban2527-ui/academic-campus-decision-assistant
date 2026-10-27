"""Integrated API acceptance tests.

All 5 browser demonstrations are synthetic. Successful HTTP responses must
never be interpreted as official DRL points or proof of eligibility.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from api.server import E2E_SCENARIOS, app
from api.lead_contract import ACTIVITY_FIELDS

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_api_state():
    assert client.post("/api/reset").status_code == 200


def payload(case_id: int) -> dict:
    c = E2E_SCENARIOS[case_id]
    return {
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": c["evidence"],
        "rule_override": c["rule_override"],
    }


def test_backend_loads_real_team_data_and_exposes_rule_audit():
    response = client.get("/api/health")
    assert response.status_code == 200
    info = response.json()
    assert info["total_rules"] == 75
    assert info["total_activities"] >= 20


def test_demo_profile_never_claims_official_verification():
    info = client.get("/api/profile").json()
    assert info["demo_only"] is True
    assert info["official_score_verified"] is False


@pytest.mark.parametrize("case_id", [1, 2, 3, 4, 5])
def test_five_real_api_e2e_paths_do_not_fabricate_credit(case_id):
    response = client.post("/api/evaluate", json=payload(case_id))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] is True
    assert set(result["sp1"]["record"]) == set(ACTIVITY_FIELDS)
    assert result["sp1"]["meta"]["publication_status"] == "REVIEW_REQUIRED"
    assert result["sp1"]["meta"]["routed_to"] in ("review_queue", "discarded_duplicate")
    assert result["sp2"]["confirmed_added"] == 0
    assert result["sp2"]["projected_added"] == 0
    assert result["sp2"]["decision"] in ("PENDING_REVIEW", "NEEDS_REVIEW", "REJECTED_DUPLICATE")


def test_repeated_post_is_rejected_without_credit():
    r = client.post("/api/evaluate", json=payload(5)).json()
    assert r["dedup"]["is_duplicate"] is True
    assert r["sp2"]["decision"] == "REJECTED_DUPLICATE"
    assert r["sp2"]["confirmed_added"] == 0


def test_self_checked_evidence_is_not_verified():
    c = payload(2)
    c["has_evidence"] = True
    r = client.post("/api/evaluate", json=c).json()
    assert r["sp2"]["confirmed_added"] == 0
    assert "chỉ là khai báo" in r["sp2"]["explanation"]


def test_manually_selected_rule_does_not_award_points():
    c = payload(4)
    c["rule_override"] = "R3101"
    r = client.post("/api/evaluate", json=c).json()
    assert r["sp2"]["rule"]["rule_id"] == "R3101"
    assert r["sp2"]["rule_points"] is None
    assert r["sp2"]["confirmed_added"] == 0


def test_real_sp2_engine_with_team_rules_and_numeric_progress():
    data = {
        "demo": True,
        "student_profile": {"university": "HCMUS"},
        "scope": {"universities": ["HCMUS"]},
        "student_snapshot": {
            "record_id": "demo-only-01",
            "status": "CONFIRMED",
            "evidence_status": "VERIFIED",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0},
        },
        "personal_targets": {"C1": 30},
    }
    response = client.post("/api/sp2/evaluate", json=data)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "DEMO_ONLY"
    assert result["official_award_verified"] is False
    assert result["sp2"]["confirmed_total"] == 20
    category = next(x for x in result["sp2"]["confirmed_by_criterion"] if x["code"] == "C1")
    assert category["score"] == 20 and category["remaining"] == 10
    rules = result["sp2"]["rule_evaluation"]["matched_rules"]
    assert [r["rule_id"] for r in rules] == ["R11", "R1203"]


def test_unverified_snapshot_does_not_gain_any_points():
    data = {
        "demo": True,
        "student_profile": {"university": "HCMUS"},
        "scope": {"universities": ["HCMUS"]},
        "student_snapshot": {
            "status": "PENDING", "evidence_status": "VERIFIED",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0},
        },
    }
    response = client.post("/api/sp2/evaluate", json=data)
    assert response.status_code == 200
    assert response.json()["sp2"]["confirmed_total"] == 0


def test_official_verification_unavailable_fails_closed():
    response = client.post("/api/sp2/evaluate", json={
        "demo": False,
        "student_profile": {"university": "HCMUS"},
        "scope": {"universities": ["HCMUS"]},
        "student_snapshot": {
            "status": "CONFIRMED", "evidence_status": "VERIFIED", "values": {},
        },
    })
    assert response.status_code == 422


def test_frontend_cannot_fallback_to_fake_credit():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "result = runClientFallback(reqBody)" not in html
    assert "Simulated point calculations are intentionally disabled" in html
