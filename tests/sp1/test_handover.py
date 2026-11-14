from copy import deepcopy

from sp1.handover import ACTIVITY_FIELDS, NOT_STATED, auto_evidence, contract_problems, eligibility, project

BASE = {"duplicate_of": None, "possible_duplicates": [], "activity": {
    "activity_id": "TMP-1", "post_type": "activity", "title": "Workshop", "domain": "skills", "mode": "offline",
    "source": {"post_id": "p1", "publisher": "Unit", "platform": "Facebook", "date_posted": "2026-10-01T09:00:00",
               "URL_post": "https://example.invalid/p1"},
    "window": {"open": "2026-10-18T08:00:00+07:00", "close": None}, "duration_minutes": 120,
    "duration_source": "default_offline_2h", "registration_deadline": None, "location": "Room A", "campus": ["CS1"],
    "audience": {"text": "Sinh viên\nextra line", "cohorts": [], "programs": [], "all_students": True},
    "mandatory": False, "points_announced": None, "fee": 0, "registration_url": "forms.gle/abc", "join_url": None,
    "completion_requirements": [], "multi_session": False, "recognition_stated": None, "drl_recognized": True,
    "semester_by_program": {"standard": "HK1_2026_2027", "high_quality": "HK1_2026_2027"},
    "meta": {"status": "valid", "flags": [], "time_defaults": {}, "derived": {"fee": "team_default:fee_not_stated_free"}}}}


def rec(**changes):
    record = deepcopy(BASE)
    for key, value in changes.items():
        target = record if key in ("duplicate_of",) else record["activity"]
        target[key] = value
    return record


def test_projection_has_exact_contract_and_applies_conventions():
    out = project(rec())
    a = out["activity"]
    assert tuple(a) == ACTIVITY_FIELDS and contract_problems(a) == []
    assert a["end"] == "2026-10-18T10:00:00+07:00" and out["derived"]["end"] == "start_plus_duration:default_offline_2h"
    assert a["registration_deadline"] == a["start"]
    assert out["derived"]["registration_deadline"] == "team_convention:deadline_at_start"
    assert a["completion_requirements"] == NOT_STATED
    assert a["source"]["URL_registration"] == "https://forms.gle/abc"
    assert a["audience"] == ["Sinh viên"] and out["sidecar"]["post_id"] == "p1"


def test_stated_values_are_never_replaced():
    out = project(rec(window={"open": "2026-10-18T08:00:00+07:00", "close": "2026-10-18T11:30:00+07:00"},
                      registration_deadline="2026-10-15T23:59:00+07:00",
                      completion_requirements=[{"type": "quiz", "threshold": 70, "unit": "percent", "deadline": None}]))
    a = out["activity"]
    assert a["end"] == "2026-10-18T11:30:00+07:00" and a["registration_deadline"] == "2026-10-15T23:59:00+07:00"
    assert '"quiz"' in a["completion_requirements"] and "end" not in out["derived"]


def test_date_only_start_gets_no_invented_end():
    record = rec()
    record["activity"]["meta"]["time_defaults"] = {"window_open": "date_only_0000"}
    out = project(record)
    assert out["activity"]["end"] is None and "start_time_not_stated" in out["warnings"]


def test_blocking_gates():
    assert project(rec(duplicate_of="p0"))["blocked"] == ["duplicate"]
    assert project(rec(post_type="info_only"))["blocked"] == ["not_an_activity"]
    assert project(rec(mode=None))["blocked"] == ["missing_mode"]
    assert project(rec(fee={"amount_vnd": 100000, "per": "team", "deposit": False}))["blocked"] == ["fee_not_per_person"]
    assert project(rec(mode=None))["activity"] is None


def test_online_window_gets_flexible_schedule_evidence():
    out = project(rec(mode="online", location=None, duration_minutes=30, duration_source="default_quiz_30m",
                      window={"open": "2026-10-18T08:00:00+07:00", "close": "2026-10-25T20:00:00+07:00"}))
    assert out["schedule"] == {"type": "FLEXIBLE_WINDOW", "duration_minutes": 30}
    assert out["activity"]["location"] is None


def test_eligibility_and_auto_evidence_are_rule_based_and_labelled():
    profile = {"cohort": "K24", "program": "standard"}
    assert eligibility({"cohorts": ["K25"], "programs": [], "all_students": False}, profile) == "INELIGIBLE"
    assert eligibility({"cohorts": ["K24"], "programs": [], "all_students": False}, profile) == "ELIGIBLE"
    assert eligibility({"cohorts": [], "programs": [], "all_students": False}, profile) == "NEEDS_REVIEW"
    partial = rec(activity_id="TMP-2")
    partial["activity"]["meta"]["status"] = "partial"
    evidence = auto_evidence([project(rec()), project(partial), project(rec(mode=None))], profile, "HK1_2026_2027")
    assert evidence["label"] == "auto_checked_not_human_reviewed"
    assert evidence["source_review_by_activity"] == {"TMP-1": True, "TMP-2": None}
    assert evidence["term_scope_by_activity"]["TMP-1"] == "IN_SCOPE"
    assert auto_evidence([project(rec())], profile, "HK3_2025_2026")["term_scope_by_activity"]["TMP-1"] == "OUT_OF_SCOPE"
