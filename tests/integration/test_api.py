"""Integration guardrail tests for the Lead-owned API, not Frontend UI tests."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from api.server import E2E_SCENARIOS, app

client = TestClient(app)


def _announcement(case_number: int = 1, *, has_evidence: bool = True):
    c = E2E_SCENARIOS[case_number]
    return {
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": has_evidence,
        "rule_override": "R19",
    }


def test_health_reports_actual_rule_inventory():
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["total_rules"] == 75


def test_user_checkbox_cannot_confirm_an_official_score():
    """POST input is not a validated school award, regardless of the checkbox."""
    response = client.post("/api/evaluate", json=_announcement())
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["sp1"]["record"]["mandatory"] in (True, False)
    assert payload["sp1"]["record"]["fee"] >= 0
    assert len(payload["sp1"]["record"]) == 14
    assert payload["sp1"]["meta"]["publication_status"] == "REVIEW_REQUIRED"
    assert payload["sp2"]["decision"] != "CONFIRMED"
    assert payload["sp2"]["confirmed_added"] == 0
    assert payload["sp2"]["projected_added"] == 0
    assert payload["sp2"]["total_score_after"] is None


def test_imaginary_rule_override_does_not_fabricate_points():
    body = _announcement()
    body["rule_override"] = "NOT_A_RULE"
    response = client.post("/api/evaluate", json=body)
    assert response.status_code == 200, response.text
    assert response.json()["sp2"]["rule"] is None
    assert response.json()["sp2"]["confirmed_added"] == 0


def test_sp2_disallows_client_asserted_official_mode():
    payload = {
        "demo": False,
        "student_profile": {"university": "HCMUS"},
        "student_snapshot": {
            "status": "CONFIRMED", "evidence_status": "VERIFIED",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0}
        },
        "scope": {"universities": ["HCMUS"]},
    }
    response = client.post("/api/sp2/evaluate", json=payload)
    assert response.status_code == 422


def test_sp2_verified_fixture_stays_demo_only():
    payload = {
        "demo": True,
        "student_profile": {"university": "HCMUS"},
        "student_snapshot": {
            "status": "CONFIRMED",
            "evidence_status": "VERIFIED",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0},
        },
        "scope": {"universities": ["HCMUS"]},
        "personal_targets": {"C1": 30},
    }
    response = client.post("/api/sp2/evaluate", json=payload)
    assert response.status_code == 200, response.text
    out = response.json()
    assert out["mode"] == "DEMO_ONLY"
    assert out["official_award_verified"] is False
    assert out["sp2"]["rule_evaluation"]["matched_rules"][0]["rule_id"] == "R11"
    assert out["sp2"]["confirmed_total"] == 25


def test_missing_evidence_cannot_raise_confirmed_total():
    payload = {
        "student_profile": {"university": "HCMUS"},
        "student_snapshot": {
            "status": "PENDING",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0}
        },
        "scope": {"universities": ["HCMUS"]},
    }
    response = client.post("/api/sp2/evaluate", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["sp2"]["confirmed_total"] == 0
