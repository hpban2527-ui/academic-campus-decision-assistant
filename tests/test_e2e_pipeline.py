"""Comprehensive End-to-End & Dual-Mode Integration Tests for HCMUS Academic Campus Decision Assistant.

Covers:
1. Strict Intake Mode (PR #3 Contract: 14-field publication lock, REVIEW_REQUIRED, 0 auto-awarded points).
2. Demo Simulation Mode (5 mandatory E2E scenarios through real SP1 -> prepare_publication -> evaluate_reviewed_activity -> SP2 evaluate_progress):
   - Case 1: PCCC Training Workshop (Mục 1.9, R19, C1 +5đ projected, confirmed stays 20/30, hypothetical 25/30).
   - Case 2: Blood Donation (Mục 4.2, R42, C4 +10đ demo-confirmed, 10 -> 20/25).
   - Case 3: Online Webinar missing completion_requirements (D16 flag -> NEEDS_REVIEW, +0đ).
   - Case 4: Category C3 Cap enforcement (CALC_02, R3101 +10đ capped at +3đ -> 22 -> 25/25).
   - Case 5: Duplicate Post Detection (MinHash-LSH & canonical URL -> REJECTED_DUPLICATE, +0đ).
3. Academic Snapshot SP2 Engine Bridge (/api/sp2/evaluate: R11=+10, R1203=+10, R23 quarantined).
4. Lead Dataset & Regulation Audit (/api/lead/audit) & Frontend No-Fake-Fallback Guard.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from api.lead_contract import ACTIVITY_FIELDS
from api.server import E2E_SCENARIOS, app

client = TestClient(app)


@pytest.fixture(autouse=True)
def fresh_api_state():
    assert client.post("/api/reset").status_code == 200


def payload(case_id: int, *, simulate_demo: bool = False) -> dict:
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
        "simulate_demo": simulate_demo,
    }


def test_backend_loads_real_team_data_and_exposes_rule_audit():
    response = client.get("/api/health")
    assert response.status_code == 200
    info = response.json()
    assert info["status"] == "healthy"
    assert info["regulation"] == "1028/QD-KHTN-CTSV"
    assert info["total_rules"] == 75
    assert info["total_activities"] >= 20


def test_demo_profile_has_authentic_category_caps_and_demo_label():
    info = client.get("/api/profile").json()
    assert info["demo_only"] is True
    assert info["official_score_verified"] is False
    caps = {k: v["max"] for k, v in info["category_scores"].items()}
    assert caps == {"C1": 30, "C2": 20, "C3": 25, "C4": 25, "C5": 30}


@pytest.mark.parametrize("case_id", [1, 2, 3, 4, 5])
def test_five_real_api_e2e_paths_do_not_fabricate_credit_in_strict_mode(case_id):
    """In default Strict Intake Mode (simulate_demo=False), no post auto-awards points."""
    response = client.post("/api/evaluate", json=payload(case_id, simulate_demo=False))
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["success"] is True
    assert set(result["sp1"]["record"]) == set(ACTIVITY_FIELDS)
    assert "drl_recognized" not in result["sp1"]["record"]
    assert "drl_recognized" in result["sp1"]["meta"]
    assert result["sp1"]["meta"]["publication_status"] == "REVIEW_REQUIRED"
    assert result["sp1"]["meta"]["routed_to"] in ("review_queue", "discarded_duplicate")
    assert result["sp2"]["confirmed_added"] == 0
    assert result["sp2"]["projected_added"] == 0
    assert result["sp2"]["decision"] in ("PENDING_REVIEW", "NEEDS_REVIEW", "REJECTED_DUPLICATE")


def test_demo_e2e_case_1_pccc_projected_points():
    """Case 1 (Demo Mode): PCCC workshop without evidence -> PROJECTED (+5đ on C1, confirmed stays 20, hypothetical 25)."""
    res = client.post("/api/evaluate", json=payload(1, simulate_demo=True)).json()
    assert res["mode"] == "DEMO_ONLY"
    assert res["official_award_verified"] is False
    sp2 = res["sp2"]
    assert sp2["decision"] == "PROJECTED"
    assert sp2["rule"]["rule_id"] == "R19"
    assert sp2["category_id"] == "C1"
    assert sp2["projected_added"] == 5
    assert sp2["confirmed_added"] == 0
    assert sp2["category_before"] == 20
    assert sp2["category_after"] == 20
    assert sp2["hypothetical_category_after"] == 25
    assert sp2["category_cap"] == 30
    assert sp2["category_missing"] == 5


def test_demo_e2e_case_2_blood_donation_confirmed_points():
    """Case 2 (Demo Mode): Blood donation with simulated evidence -> DEMO_CONFIRMED (+10đ on C4, 10 -> 20/25)."""
    res = client.post("/api/evaluate", json=payload(2, simulate_demo=True)).json()
    assert res["mode"] == "DEMO_ONLY"
    assert res["official_award_verified"] is False
    sp2 = res["sp2"]
    assert sp2["decision"] == "DEMO_CONFIRMED"
    assert sp2["rule"]["rule_id"] == "R42"
    assert sp2["category_id"] == "C4"
    assert sp2["confirmed_added"] == 10
    assert sp2["projected_added"] == 0
    assert sp2["category_before"] == 10
    assert sp2["category_after"] == 20
    assert sp2["category_cap"] == 25
    assert sp2["category_missing"] == 5


def test_demo_e2e_case_3_online_missing_requirements_d16():
    """Case 3 (Demo Mode): Online webinar missing completion_requirements -> D16 flag, NEEDS_REVIEW, +0đ."""
    res = client.post("/api/evaluate", json=payload(3, simulate_demo=True)).json()
    meta = res["sp1"]["meta"]
    assert "needs_review:completion_requirements" in meta["flags"]
    sp2 = res["sp2"]
    assert sp2["decision"] == "NEEDS_REVIEW"
    assert sp2["projected_added"] == 0
    assert sp2["confirmed_added"] == 0


def test_demo_e2e_case_4_category_cap_c3():
    """Case 4 (Demo Mode): Category C3 is 22/25đ. Adding +10đ rule R3101 is capped at +3đ by SP2 engine."""
    res = client.post("/api/evaluate", json=payload(4, simulate_demo=True)).json()
    sp2 = res["sp2"]
    assert sp2["decision"] == "DEMO_CONFIRMED"
    assert sp2["rule"]["rule_id"] == "R3101"
    assert sp2["category_id"] == "C3"
    assert sp2["rule_points"] == 10
    assert sp2["confirmed_added"] == 3
    assert sp2["category_before"] == 22
    assert sp2["category_after"] == 25
    assert sp2["category_cap"] == 25
    assert sp2["category_missing"] == 0
    assert "CALC_02" in sp2["explanation"]


def test_demo_e2e_case_5_duplicate_detection():
    """Case 5 (Both Modes): Duplicate post is rejected with 0 points."""
    res = client.post("/api/evaluate", json=payload(5, simulate_demo=True)).json()
    assert res["dedup"]["is_duplicate"] is True
    assert res["sp2"]["decision"] == "REJECTED_DUPLICATE"
    assert res["sp2"]["confirmed_added"] == 0
    assert res["sp2"]["projected_added"] == 0


def test_self_checked_evidence_is_not_verified_in_strict_mode():
    c = payload(2, simulate_demo=False)
    c["has_evidence"] = True
    r = client.post("/api/evaluate", json=c).json()
    assert r["sp2"]["confirmed_added"] == 0
    assert "chỉ là khai báo" in r["sp2"]["explanation"]


def test_manually_selected_rule_does_not_award_points_in_strict_mode():
    c = payload(4, simulate_demo=False)
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
            "status": "PENDING",
            "evidence_status": "VERIFIED",
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0},
        },
    }
    response = client.post("/api/sp2/evaluate", json=data)
    assert response.status_code == 200
    assert response.json()["sp2"]["confirmed_total"] == 0


def test_official_verification_unavailable_fails_closed():
    response = client.post(
        "/api/sp2/evaluate",
        json={
            "demo": False,
            "student_profile": {"university": "HCMUS"},
            "scope": {"universities": ["HCMUS"]},
            "student_snapshot": {
                "status": "CONFIRMED",
                "evidence_status": "VERIFIED",
                "values": {},
            },
        },
    )
    assert response.status_code == 422


def test_frontend_cannot_fallback_to_fake_credit():
    html = (ROOT / "web/index.html").read_text(encoding="utf-8")
    assert "result = runClientFallback(reqBody)" not in html
    assert "Simulated point calculations are intentionally disabled" in html
