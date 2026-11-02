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
    assert out["sp2"]["confirmed_total"] == 20


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


def _availability_payload(apply_scope="WEEK_ONLY"):
    semester = apply_scope == "SEMESTER_WEEKLY"
    return {
        "availability": {
            "availability_version": "sp3-availability/0.2",
            "timezone": "Asia/Ho_Chi_Minh",
            "week_start": "2026-11-02",
            "apply_scope": apply_scope,
            "weekly_blocks": [
                {
                    "day_of_week": "MONDAY",
                    "start_time": "08:00",
                    "end_time": "11:30",
                }
            ],
            "effective_from": "2026-11-01" if semester else None,
            "effective_until": "2026-11-30" if semester else None,
            "exceptions": [],
            "busy_intervals": [],
        },
        "window_start": "2026-11-01T00:00:00+07:00",
        "window_end": "2026-11-17T00:00:00+07:00",
    }


def test_sp3_availability_endpoint_resolves_ui_week_without_persisting_it():
    response = client.post(
        "/api/sp3/availability/resolve",
        json=_availability_payload(),
    )

    assert response.status_code == 200, response.text
    result = response.json()
    assert result["mode"] == "DEMO_ONLY"
    assert result["persistent"] is False
    assert result["apply_scope"] == "WEEK_ONLY"
    assert result["available_intervals"] == [
        {
            "start": "2026-11-02T08:00:00+07:00",
            "end": "2026-11-02T11:30:00+07:00",
        }
    ]


def test_sp3_availability_endpoint_subtracts_ad_hoc_busy_intervals():
    payload = _availability_payload()
    payload["availability"]["busy_intervals"] = [
        {
            "start": "2026-11-02T09:00:00+07:00",
            "end": "2026-11-02T10:00:00+07:00",
        }
    ]

    response = client.post("/api/sp3/availability/resolve", json=payload)

    assert response.status_code == 200, response.text
    assert response.json()["available_intervals"] == [
        {
            "start": "2026-11-02T08:00:00+07:00",
            "end": "2026-11-02T09:00:00+07:00",
        },
        {
            "start": "2026-11-02T10:00:00+07:00",
            "end": "2026-11-02T11:30:00+07:00",
        },
    ]


def test_sp3_availability_endpoint_rejects_an_ambiguous_semester_repeat():
    payload = _availability_payload("SEMESTER_WEEKLY")
    payload["availability"]["effective_until"] = None

    response = client.post("/api/sp3/availability/resolve", json=payload)

    assert response.status_code == 422
    assert "are required" in response.json()["detail"]
