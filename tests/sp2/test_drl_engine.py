from __future__ import annotations

import pytest

from sp2.drl_engine import (
    DRLEngineError,
    audit_rules_config,
    evaluate_progress,
    evaluate_rule_conditions,
)


@pytest.fixture
def demo_rule_set():
    return {
        "rule_set_id": "drl_demo_2026_sem1",
        "version": "demo-1",
        "scope": {
            "universities": ["HCMUS"],
            "faculties": ["FIT"],
            "cohorts": [2025],
            "programs": None,
        },
        "verified": False,
        "max_total_score": 100,
        "criteria": [
            {"code": "COMMUNITY_DEMO", "max_score": 20, "default_target": 20},
            {"code": "ACADEMIC_DEMO", "max_score": 30, "default_target": 15},
        ],
        "topic_requirements": [
            {
                "topic_code": "TOPIC_B_DEMO",
                "required_confirmed_activities": 2,
                "extra_conditions": [],
            }
        ],
    }


@pytest.fixture
def profile():
    return {"university": "HCMUS", "faculty": "FIT", "cohort": 2025}


def confirmed(record_id, **values):
    return {
        "record_id": record_id,
        "status": "CONFIRMED",
        "evidence_status": "VERIFIED",
        **values,
    }


def test_t12_pending_points_are_not_added(demo_rule_set, profile):
    records = [
        confirmed("ok", criterion_code="COMMUNITY_DEMO", points=12),
        {
            "record_id": "wait",
            "status": "PENDING",
            "criterion_code": "COMMUNITY_DEMO",
            "points": 8,
        },
    ]
    result = evaluate_progress(demo_rule_set, profile, records)
    assert result["confirmed_total"] == 12
    assert result["pending_items"][0]["record_id"] == "wait"


def test_t13_remaining_to_target_is_numeric(demo_rule_set, profile):
    result = evaluate_progress(
        demo_rule_set,
        profile,
        [confirmed("r1", criterion_code="COMMUNITY_DEMO", points=12)],
    )
    community = result["confirmed_by_criterion"][0]
    assert community == {
        "code": "COMMUNITY_DEMO",
        "raw_score": 12,
        "score": 12,
        "max_score": 20,
        "target": 20,
        "remaining": 8,
        "record_ids": ["r1"],
    }


def test_t14_one_of_two_topics_leaves_one(demo_rule_set, profile):
    result = evaluate_progress(
        demo_rule_set,
        profile,
        [confirmed("topic-1", activity_id="a1", topic_code="TOPIC_B_DEMO")],
    )
    assert result["topic_progress"][0]["confirmed_count"] == 1
    assert result["topic_progress"][0]["remaining"] == 1


def test_t15_pending_topic_is_not_counted(demo_rule_set, profile):
    records = [
        confirmed("topic-1", activity_id="a1", topic_code="TOPIC_B_DEMO"),
        {
            "record_id": "topic-2",
            "activity_id": "a2",
            "topic_code": "TOPIC_B_DEMO",
            "status": "PENDING",
        },
    ]
    result = evaluate_progress(demo_rule_set, profile, records)
    assert result["topic_progress"][0]["confirmed_count"] == 1
    assert result["pending_items"][0]["record_id"] == "topic-2"


def test_t16_criterion_cap_is_applied(demo_rule_set, profile):
    records = [
        confirmed("a", activity_id="a", criterion_code="COMMUNITY_DEMO", points=12),
        confirmed("b", activity_id="b", criterion_code="COMMUNITY_DEMO", points=15),
    ]
    result = evaluate_progress(demo_rule_set, profile, records)
    criterion = result["confirmed_by_criterion"][0]
    assert criterion["raw_score"] == 27
    assert criterion["score"] == 20
    assert result["confirmed_total"] == 20


def test_t17_wrong_cohort_does_not_calculate(demo_rule_set, profile):
    wrong_profile = {**profile, "cohort": 2024}
    result = evaluate_progress(
        demo_rule_set,
        wrong_profile,
        [confirmed("r1", criterion_code="COMMUNITY_DEMO", points=20)],
    )
    assert result["rule_resolution"] == "NEEDS_VERIFICATION"
    assert result["confirmed_total"] == 0
    assert result["applied_records"] == []


def test_t18_missing_scope_data_returns_needs_info(demo_rule_set):
    result = evaluate_progress(
        demo_rule_set,
        {"university": "HCMUS", "faculty": "FIT"},
        [],
    )
    assert result["rule_resolution"] == "NEEDS_INFO"
    assert any("cohorts" in reason for reason in result["verification_flags"])


def test_confirmed_without_verified_evidence_is_not_scored(demo_rule_set, profile):
    record = {
        "record_id": "unsafe",
        "status": "CONFIRMED",
        "criterion_code": "COMMUNITY_DEMO",
        "points": 20,
    }
    result = evaluate_progress(demo_rule_set, profile, [record])
    assert result["confirmed_total"] == 0
    assert result["pending_items"][0]["status"] == "NEEDS_VERIFICATION"


def test_duplicate_activity_is_not_counted_twice(demo_rule_set, profile):
    records = [
        confirmed("r1", activity_id="same", topic_code="TOPIC_B_DEMO"),
        confirmed("r2", activity_id="same", topic_code="TOPIC_B_DEMO"),
    ]
    result = evaluate_progress(demo_rule_set, profile, records)
    assert result["topic_progress"][0]["confirmed_count"] == 1
    assert any("duplicate topic" in flag for flag in result["verification_flags"])


def test_verified_activity_claim_can_supply_points(demo_rule_set, profile):
    activities = [
        {
            "activity_id": "act-1",
            "benefit_claims": [
                {
                    "claim_id": "claim-1",
                    "type": "DRL_POINTS",
                    "drl_criterion": "COMMUNITY_DEMO",
                    "points": 7,
                    "verification_status": "VERIFIED_BY_REVIEWER",
                }
            ],
        }
    ]
    result = evaluate_progress(
        demo_rule_set,
        profile,
        [confirmed("r1", activity_id="act-1")],
        activities=activities,
    )
    assert result["confirmed_total"] == 7
    assert result["applied_records"][0]["claim_ids"] == ["claim-1"]


def test_unverified_activity_claim_never_supplies_points(demo_rule_set, profile):
    activities = [
        {
            "activity_id": "act-1",
            "benefit_claims": [
                {
                    "type": "DRL_POINTS",
                    "drl_criterion": "COMMUNITY_DEMO",
                    "points": 20,
                    "verification_status": "UNVERIFIED",
                }
            ],
        }
    ]
    result = evaluate_progress(
        demo_rule_set,
        profile,
        [confirmed("r1", activity_id="act-1")],
        activities=activities,
    )
    assert result["confirmed_total"] == 0
    assert any("no recognised" in flag for flag in result["verification_flags"])


def test_personal_target_overrides_default_without_changing_cap(demo_rule_set, profile):
    result = evaluate_progress(
        demo_rule_set,
        profile,
        [confirmed("r1", criterion_code="COMMUNITY_DEMO", points=12)],
        personal_targets={"COMMUNITY_DEMO": 18},
    )
    criterion = result["confirmed_by_criterion"][0]
    assert criterion["target"] == 18
    assert criterion["remaining"] == 6
    assert criterion["max_score"] == 20


def test_production_mode_rejects_demo_rules(demo_rule_set, profile):
    result = evaluate_progress(
        demo_rule_set, profile, [], require_verified_rules=True
    )
    assert result["rule_resolution"] == "NEEDS_VERIFICATION"
    assert "Rule set is not reviewer-verified" in result["verification_flags"]


def test_low_level_rule_conditions_support_numeric_outputs():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "max_total_score": 100,
            "category_caps": [{"category_id": "C1", "max_score": 20}],
        },
        "rules": [
            {
                "rule_id": "GPA",
                "criterion_id": "1.2",
                "category_id": "C1",
                "condition": {
                    "field": "semester_gpa",
                    "operator": "range",
                    "min_inclusive": 8.0,
                    "max_exclusive": 9.0,
                },
                "points": 10,
                "unit": "per_semester",
            },
            {
                "rule_id": "NO_VIOLATION",
                "criterion_id": "1.1",
                "category_id": "C1",
                "condition": {
                    "field": "academic_exam_violations",
                    "operator": "equals",
                    "value": 0,
                },
                "points": 15,
                "unit": "per_semester",
            },
        ],
    }
    result = evaluate_rule_conditions(
        config, {"semester_gpa": 8.5, "academic_exam_violations": 0}
    )
    assert result["rule_points_total"] == 20
    assert result["raw_total_before_cap"] == 20
    assert result["final_score"] == 20


def test_low_level_total_cap_and_missing_field_reason():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "max_total_score": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": "R",
                "criterion_id": "1",
                "category_id": "C1",
                "condition": {"field": "x", "operator": "greater_than", "value": 0},
                "points": 10,
                "unit": "per_semester",
            }
        ],
    }
    result = evaluate_rule_conditions(
        config,
        {"x": 1, "current_confirmed_score": 96, "eligible_extra_points": 15},
        required_fields={"academic_exam_violations"},
    )
    assert result["raw_total_before_cap"] == 121
    assert result["final_score"] == 100
    assert result["missing_fields"] == ["academic_exam_violations"]
    assert result["needs_review"] is True


def test_audit_rejects_mixed_type_range_bound():
    config = {
        "scoring_model": {
            "category_caps": [{"category_id": "C4", "max_score": 25}]
        },
        "rules": [
            {
                "rule_id": "R4302",
                "criterion_id": "4.3",
                "category_id": "C4",
                "condition": {
                    "field": "volunteer_hours_per_activity",
                    "operator": "range",
                    "min_inclusive": 24,
                    "max_exclusive": "one_week",
                },
                "points": 10,
            }
        ],
    }
    issues = audit_rules_config(config)
    assert any(issue["code"] == "RANGE_BOUND_NOT_NUMERIC" for issue in issues)
    result = evaluate_rule_conditions(config, {"volunteer_hours_per_activity": 30})
    assert result["matched_rules"] == []
    assert result["needs_review"] is True
    assert result["configuration_issues"] == issues


def test_fatal_duplicate_rule_id_stops_ambiguous_evaluation():
    duplicated = {
        "scoring_model": {
            "semester_score_min": 0,
            "max_total_score": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": "SAME",
                "criterion_id": "1",
                "category_id": "C1",
                "condition": {"field": "x", "operator": "equals", "value": 1},
                "points": 5,
            },
            {
                "rule_id": "SAME",
                "criterion_id": "2",
                "category_id": "C1",
                "condition": {"field": "y", "operator": "equals", "value": 1},
                "points": 5,
            },
        ],
    }
    with pytest.raises(DRLEngineError):
        evaluate_rule_conditions(duplicated, {"x": 1, "y": 1})


def test_null_is_not_treated_as_zero_or_false():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "max_total_score": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": "ZERO",
                "criterion_id": "1",
                "category_id": "C1",
                "condition": {"field": "violations", "operator": "equals", "value": 0},
                "points": 10,
            }
        ],
    }
    result = evaluate_rule_conditions(config, {"violations": None})
    assert result["matched_rules"] == []
    assert result["final_score"] == 0
