"""Real SP2 engine bridging a locally reviewed SP1 activity (demo-only)."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from api.reviewed_pipeline import evaluate_reviewed_activity, fingerprint
from api.server import app

CONFIG = json.loads((ROOT / "data/drl_rules.json").read_text(encoding="utf-8"))
SCHEMA = json.loads((ROOT / "schemas/activity.schema.json").read_text(encoding="utf-8"))
CLIENT = TestClient(app)


def setup():
    record = {
        "activity_id": "ACT-CHECKED-01",
        "source": {"publisher": "Synthetic Student Club", "platform": "facebook",
                   "URL_post": "https://example.org/demo/workshop", "URL_registration": None},
        "title": "Synthetic workshop", "domain": "skills",
        "start": "2026-10-28T14:00:00+07:00", "end": "2026-10-28T16:00:00+07:00",
        "registration_deadline": None, "mode": "offline", "location": "Demo classroom",
        "points": 5, "mandatory": False, "audience": ["Students"], "fee": 0,
        "completion_requirements": "Attendance sheet",
    }
    meta = {"status": "valid", "flags": [], "is_duplicate": False}
    approval = {
        "decision": "APPROVED", "activity_id": record["activity_id"],
        "fingerprint": fingerprint(record), "source_url": record["source"]["URL_post"],
        "reviewer_id": "DEMO_REVIEWER", "reviewed_at": "2026-10-27T14:00:00+07:00",
        "regulation_id": CONFIG["regulation"]["regulation_id"], "rule_id": "R19",
    }
    profile = {"student_id": "demo-student", "university": "HCMUS"}
    baseline = {
        "student_id": "demo-student", "regulation_id": CONFIG["regulation"]["regulation_id"],
        "category_scores": {"C1": 20, "C2": 0, "C3": 0, "C4": 0, "C5": 0},
        "included_activity_ids": [],
    }
    proof = {
        "activity_id": record["activity_id"], "student_id": "demo-student",
        "status": "CONFIRMED", "evidence_status": "VERIFIED",
        "verifier_id": "SYNTHETIC_REVIEWER", "verified_at": "2026-10-27T14:00:00+07:00",
        "evidence_ref": "synthetic://attendance",
    }
    return {"record": record, "metadata": meta, "approval": approval,
            "participation": proof, "baseline": baseline,
            "student_profile": profile, "rules_config": CONFIG, "schema": SCHEMA}


def test_reviewed_activity_is_projected_not_credited():
    a = setup()
    a["participation"] = None
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "PROJECTED"
    assert result["projected_added"] == 5
    assert result["confirmed_added"] == 0
    assert result["confirmed_total_after"] == 20
    assert result["hypothetical_category_after"] == 25
    assert result["official_award_verified"] is False


def test_internal_demo_verification_counts_with_sp2_engine():
    result = evaluate_reviewed_activity(**setup())
    assert result["status"] == "DEMO_CONFIRMED"
    assert result["confirmed_added"] == 5
    assert result["confirmed_total_before"] == 20
    assert result["confirmed_total_after"] == 25
    assert result["remaining_after_hypothetical"] == 5
    assert result["official_award_verified"] is False


def test_no_reviewer_no_award():
    a = setup()
    a["approval"]["decision"] = "PENDING"
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "NEEDS_REVIEW"


def test_tampered_record_is_not_approved():
    a = setup()
    a["record"]["title"] += " tampered"
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "NEEDS_REVIEW"


def test_announced_point_conflict_must_be_reviewed():
    a = setup()
    a["record"]["points"] = 10
    a["approval"]["fingerprint"] = fingerprint(a["record"])
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "NEEDS_REVIEW"


def test_absent_baseline_ledger_fails_closed():
    a = setup()
    del a["baseline"]["included_activity_ids"]
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "NEEDS_BASELINE"


def test_duplicate_activity_from_baseline_not_counted():
    a = setup()
    a["baseline"]["included_activity_ids"] = [a["record"]["activity_id"]]
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "ALREADY_COUNTED"
    assert result["confirmed_added"] == 0


def test_unverified_rule_not_credited():
    a = setup()
    a["record"]["points"] = 5
    a["approval"]["rule_id"] = "R23"
    a["approval"]["fingerprint"] = fingerprint(a["record"])
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "NEEDS_REVIEW"


def test_missing_participation_verifier_stays_projected():
    a = setup()
    a["participation"]["verifier_id"] = None
    result = evaluate_reviewed_activity(**a)
    assert result["status"] == "PROJECTED"


def test_category_cap_uses_engine_not_unbounded_rule_sum():
    a = setup()
    a["baseline"]["category_scores"]["C1"] = 29
    result = evaluate_reviewed_activity(**a)
    assert result["confirmed_added"] == 1
    assert result["category_after"] == 30


def test_api_reviewer_fixture_is_explicitly_demo_only():
    r = CLIENT.post("/api/pipeline/demo", json={"case_id": 1})
    assert r.status_code == 200, r.text
    assert r.json()["mode"] == "DEMO_ONLY"
    assert r.json()["official_award_verified"] is False
    assert r.json()["sp2"]["confirmed_added"] == 0


def test_audit_includes_quarantined_rule_and_data_quality():
    r = CLIENT.get("/api/lead/audit")
    assert r.status_code == 200, r.text
    assert "R23" in r.json()["rules_needing_review"]
    assert r.json()["dataset"]["total"] >= 20
