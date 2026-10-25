"""End-to-End Integration Tests for HCMUS Academic Campus Decision Assistant.

Covers the 5 mandatory E2E scenarios:
1. PCCC Training Workshop (Mục 1.9, C1 +5đ, no evidence -> Projected points).
2. Blood Donation (Mục 4.2, C4 +10đ, with verified evidence -> Confirmed points).
3. Online Webinar missing completion requirements (D16 rule -> needs_review:completion_requirements -> review_queue).
4. Category C3 Cap enforcement (CALC_02 -> Capped at max_score 25đ, +3đ added instead of +10đ).
5. Duplicate Post Detection (MinHash LSH & exact match -> Rejection, 0 points added).
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add src to python path
src_dir = Path(__file__).resolve().parents[1] / "src"
if str(src_dir) not in sys.path:
    sys.path.insert(0, str(src_dir))

import pytest
from fastapi.testclient import TestClient
from api.server import app, E2E_SCENARIOS

client = TestClient(app)


def test_api_health_endpoint():
    """Verify backend health and dataset initialization."""
    response = client.get("/api/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["regulation"] == "1028/QD-KHTN-CTSV"
    assert data["total_rules"] >= 70
    assert data["total_activities"] >= 20


def test_student_profile_endpoint():
    """Verify student profile and category caps."""
    response = client.get("/api/profile")
    assert response.status_code == 200
    profile = response.json()
    assert profile["student_id"] == "25127242"
    assert profile["full_name"] == "Lưu Minh Tiến"
    assert "C1" in profile["category_scores"]
    assert profile["category_scores"]["C1"]["max"] == 30
    assert profile["category_scores"]["C3"]["max"] == 25


def test_e2e_case_1_pccc_projected_points():
    """Case 1: PCCC training workshop without evidence -> Points are PROJECTED (Mục 1.9, C1 +5đ)."""
    c = E2E_SCENARIOS[1]
    response = client.post("/api/evaluate", json={
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": False,
        "rule_override": c["rule_override"],
    })
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True

    # SP1 checks
    rec = res["sp1"]["record"]
    meta = res["sp1"]["meta"]
    assert meta["status"] == "valid"
    assert rec["mode"] == "offline"
    assert rec["points"] == 5.0
    assert "CHÁY" in rec["title"].upper()

    # SP2 checks
    sp2 = res["sp2"]
    assert sp2["decision"] == "PROJECTED"
    assert sp2["rule"]["rule_id"] == "R19"
    assert sp2["category_id"] == "C1"
    assert sp2["projected_added"] == 5
    assert sp2["confirmed_added"] == 0
    assert sp2["category_before"] == 20
    assert sp2["category_after"] == 25
    assert sp2["category_missing"] == 5
    assert "1028/QD-KHTN-CTSV" in sp2["citation"]


def test_e2e_case_2_blood_donation_confirmed_points():
    """Case 2: Blood donation with verified certificate -> Points are CONFIRMED (Mục 4.2, C4 +10đ)."""
    c = E2E_SCENARIOS[2]
    response = client.post("/api/evaluate", json={
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": True,
        "rule_override": c["rule_override"],
    })
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True

    # SP1 checks
    rec = res["sp1"]["record"]
    meta = res["sp1"]["meta"]
    assert meta["status"] == "valid"
    assert rec["points"] == 10.0
    assert "HIẾN MÁU" in rec["title"].upper()

    # SP2 checks
    sp2 = res["sp2"]
    assert sp2["decision"] == "CONFIRMED"
    assert sp2["rule"]["rule_id"] == "R42"
    assert sp2["category_id"] == "C4"
    assert sp2["confirmed_added"] == 10
    assert sp2["projected_added"] == 0
    assert sp2["category_before"] == 10
    assert sp2["category_after"] == 20
    assert sp2["category_missing"] == 5


def test_e2e_case_3_online_missing_requirements_d16():
    """Case 3: Online recognized activity missing completion requirements -> partial status, routed to review_queue."""
    c = E2E_SCENARIOS[3]
    response = client.post("/api/evaluate", json={
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": False,
        "rule_override": c["rule_override"],
    })
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True

    # SP1 checks: D16 flag trigger
    rec = res["sp1"]["record"]
    meta = res["sp1"]["meta"]
    assert meta["status"] == "partial"
    assert "needs_review:completion_requirements" in meta["flags"]
    assert rec["mode"] == "online"

    # SP2 checks: CALC_05 holds points, no score increase
    sp2 = res["sp2"]
    assert sp2["decision"] == "NEEDS_REVIEW_CALC_05"
    assert sp2["projected_added"] == 0
    assert sp2["confirmed_added"] == 0


def test_e2e_case_4_category_cap_c3():
    """Case 4: Category C3 is currently 22/25đ. Adding 10đ competition must be CAPPED at +3đ."""
    c = E2E_SCENARIOS[4]
    response = client.post("/api/evaluate", json={
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": True,
        "rule_override": "R3101",
    })
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True

    # SP2 checks
    sp2 = res["sp2"]
    assert sp2["decision"] == "CONFIRMED"
    assert sp2["rule"]["rule_id"] == "R3101"
    assert sp2["category_id"] == "C3"
    assert sp2["rule_points"] == 10
    # Room in C3 is 25 - 22 = 3
    assert sp2["confirmed_added"] == 3
    assert sp2["category_before"] == 22
    assert sp2["category_after"] == 25
    assert sp2["category_missing"] == 0
    assert "Áp trần CALC_02" in sp2["explanation"]


def test_e2e_case_5_duplicate_detection():
    """Case 5: Submitting a duplicate post that already exists -> REJECTED_DUPLICATE, 0 points added."""
    c = E2E_SCENARIOS[5]
    response = client.post("/api/evaluate", json={
        "post_id": c["post_id"],
        "publisher": c["publisher"],
        "platform": c["platform"],
        "date_posted": c["date_posted"],
        "url": c["url"],
        "raw_content": c["raw_content"],
        "has_evidence": True,
        "rule_override": c["rule_override"],
    })
    assert response.status_code == 200
    res = response.json()
    assert res["success"] is True

    # Dedup and SP2 checks
    assert res["dedup"]["is_duplicate"] is True
    sp2 = res["sp2"]
    assert sp2["decision"] == "REJECTED_DUPLICATE"
    assert sp2["confirmed_added"] == 0
    assert sp2["projected_added"] == 0
    assert "trùng lặp" in sp2["explanation"].lower()
