from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from sp2 import (
    DRLEngineError,
    audit_rules_config,
    evaluate_rule_conditions,
    evaluate_rules_progress,
)


ROOT = Path(__file__).resolve().parents[2]


def load_shared_json(path: str):
    local_path = ROOT / path
    if local_path.exists():
        return json.loads(local_path.read_text(encoding="utf-8"))
    try:
        content = subprocess.check_output(
            ["git", "show", f"origin/Ngoc_Tuyen:{path}"],
            cwd=ROOT,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError):
        pytest.skip(f"shared file is not available: {path}")
    return json.loads(content)


@pytest.fixture(scope="module")
def actual_rules():
    return load_shared_json("data/drl_rules.json")


def test_actual_rules_file_can_be_checked(actual_rules):
    issues = audit_rules_config(actual_rules)
    assert len(actual_rules["rules"]) == 75
    assert issues == []


def test_actual_rules_match_gpa_and_violation_rules(actual_rules):
    result = evaluate_rule_conditions(
        actual_rules,
        {"semester_gpa": 8.5, "academic_exam_violations": 0},
    )
    assert [item["rule_id"] for item in result["matched_rules"]] == ["R11", "R1203"]
    assert [item["points"] for item in result["matched_rules"]] == [10, 10]
    assert result["category_scores"] == [
        {"category_id": "C1", "raw_score": 20, "cap": 30, "score": 20}
    ]
    assert result["needs_review"] is False


def test_rule_result_is_converted_to_progress(actual_rules):
    sample = json.loads(
        (ROOT / "tests/sp2/fixtures/actual_rules_progress_sample.json").read_text(
            encoding="utf-8"
        )
    )
    inputs = sample["input"]
    expected = sample["expected_output"]
    result = evaluate_rules_progress(
        actual_rules,
        inputs["student_profile"],
        inputs["student_snapshot"],
        scope=inputs["scope"],
        personal_targets=inputs["personal_targets"],
    )

    category = next(item for item in result["confirmed_by_criterion"] if item["code"] == "C1")
    actual_rules_output = [
        {
            "rule_id": item["rule_id"],
            "criterion_id": item["criterion_id"],
            "points": item["points"],
        }
        for item in result["rule_evaluation"]["matched_rules"]
    ]
    assert result["rule_resolution"] == expected["rule_resolution"]
    assert result["confirmed_total"] == expected["confirmed_total"]
    assert result["pending_items"] == expected["pending_items"]
    assert actual_rules_output == expected["matched_rules"]
    for key, value in expected["category"].items():
        assert category[key] == value


def test_actual_duplicate_condition_is_only_counted_once(actual_rules):
    result = evaluate_rule_conditions(
        actual_rules,
        {"course_evaluation_completion_rate": 0.75},
    )
    assert [item["rule_id"] for item in result["matched_rules"]] == ["R22"]
    assert result["rule_points_total"] == 5
    assert result["skipped_rules"] == []
    assert result["needs_review"] is False


def test_duration_bucket_is_explicit_not_guessed(actual_rules):
    result = evaluate_rule_conditions(
        actual_rules,
        {
            "semester_gpa": 9.0,
            "volunteer_hours_per_activity": 30,
        },
    )
    assert [item["rule_id"] for item in result["matched_rules"]] == ["R1204"]
    assert result["relevant_configuration_issues"] == []
    assert result["needs_review"] is False


@pytest.mark.parametrize(
    ("status", "evidence_status", "expected_status"),
    [
        ("PENDING", "VERIFIED", "PENDING"),
        ("CONFIRMED", None, "NEEDS_VERIFICATION"),
    ],
)
def test_unconfirmed_snapshot_is_not_scored(
    actual_rules, status, evidence_status, expected_status
):
    result = evaluate_rules_progress(
        actual_rules,
        {"university": "HCMUS"},
        {
            "record_id": "semester-2026-1",
            "status": status,
            "evidence_status": evidence_status,
            "values": {"semester_gpa": 8.5, "academic_exam_violations": 0},
        },
        scope={"universities": ["HCMUS"]},
        personal_targets={"C1": 30},
    )
    assert result["confirmed_total"] == 0
    assert result["rule_evaluation"] is None
    assert result["pending_items"][0]["status"] == expected_status


def test_bridge_rejects_unallocated_existing_score(actual_rules):
    with pytest.raises(DRLEngineError, match="need category allocation"):
        evaluate_rules_progress(
            actual_rules,
            {"university": "HCMUS"},
            {
                "status": "CONFIRMED",
                "evidence_status": "VERIFIED",
                "values": {"current_confirmed_score": 96},
            },
            scope={"universities": ["HCMUS"]},
        )


def _scope_aware_config():
    return {
        "regulation": {
            "regulation_id": "SYNTHETIC",
            "effective_from": "SYNTHETIC-TERM",
            "status": "verified",
            "scope": {
                "university": "HCMUS",
                "student_type": "full_time",
                "faculty": None,
                "cohort": None,
                "program": None,
            },
        },
        "scoring_model": {
            "status": "verified",
            "semester_score_min": 0,
            "semester_score_max": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": "R-SCOPE",
                "criterion_id": "1.1",
                "category_id": "C1",
                "condition": {"field": "eligible", "operator": "equals", "value": True},
                "points": 10,
                "unit": "per_semester",
                "status": "verified",
            }
        ],
    }


def test_bridge_reads_singular_regulation_scope_without_duplicate_scope_argument():
    result = evaluate_rules_progress(
        _scope_aware_config(),
        {"university": "HCMUS", "student_type": "full_time"},
        {
            "status": "CONFIRMED",
            "evidence_status": "VERIFIED",
            "values": {"eligible": True},
        },
    )

    assert result["rule_resolution"] == "APPLICABLE"
    assert result["confirmed_total"] == 10
    assert result["category_scores"] == [
        {"category_id": "C1", "raw_score": 10, "cap": 30, "score": 10}
    ]
    assert result["criterion_scores"] == [
        {
            "criterion_id": "1.1",
            "category_id": "C1",
            "raw_score": 10,
            "cap": None,
            "score": 10,
        }
    ]


def test_bridge_rejects_api_scope_that_conflicts_with_regulation_scope():
    with pytest.raises(DRLEngineError, match="conflicts with regulation.scope"):
        evaluate_rules_progress(
            _scope_aware_config(),
            {"university": "HCMUS", "student_type": "full_time"},
            {
                "status": "CONFIRMED",
                "evidence_status": "VERIFIED",
                "values": {"eligible": True},
            },
            scope={"universities": ["OTHER"]},
        )


def test_category_cap_is_not_reused_as_a_criterion_cap():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "semester_score_max": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": "R-A",
                "criterion_id": "1.9",
                "category_id": "C1",
                "condition": {"field": "a", "operator": "equals", "value": True},
                "points": 20,
                "unit": "per_semester",
            },
            {
                "rule_id": "R-B",
                "criterion_id": "1.9",
                "category_id": "C1",
                "condition": {"field": "b", "operator": "equals", "value": True},
                "points": 20,
                "unit": "per_semester",
            },
        ],
    }

    result = evaluate_rule_conditions(config, {"a": True, "b": True})

    assert result["criterion_scores"] == [
        {
            "criterion_id": "1.9",
            "category_id": "C1",
            "raw_score": 40,
            "cap": None,
            "score": 40,
        }
    ]
    assert result["category_scores"] == [
        {"category_id": "C1", "raw_score": 40, "cap": 30, "score": 30}
    ]


def test_explicit_criterion_cap_is_applied_before_the_category_cap():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "semester_score_max": 100,
            "category_caps": [{"category_id": "C1", "max_score": 30}],
        },
        "rules": [
            {
                "rule_id": rule_id,
                "criterion_id": "1.9",
                "category_id": "C1",
                "condition": {"field": field, "operator": "equals", "value": True},
                "points": 20,
                "unit": "per_semester",
                "criterion_max_score": 25,
            }
            for rule_id, field in (("R-A", "a"), ("R-B", "b"))
        ],
    }

    result = evaluate_rule_conditions(config, {"a": True, "b": True})

    assert result["criterion_scores"][0] == {
        "criterion_id": "1.9",
        "category_id": "C1",
        "raw_score": 40,
        "cap": 25,
        "score": 25,
    }
    assert result["category_scores"] == [
        {"category_id": "C1", "raw_score": 25, "cap": 30, "score": 25}
    ]
    assert result["final_score"] == 25


def test_unit_semantics_distinguish_repeatable_entities_from_period_awards():
    config = {
        "scoring_model": {
            "semester_score_min": 0,
            "semester_score_max": 100,
            "category_caps": [{"category_id": "C3", "max_score": 100}],
        },
        "rules": [
            {
                "rule_id": "ACTIVITY",
                "criterion_id": "3.1",
                "category_id": "C3",
                "condition": {"field": "activities", "operator": "count_greater_than", "value": 0},
                "points": 2,
                "unit": "per_activity",
            },
            {
                "rule_id": "ACTIVITY_PERIOD",
                "criterion_id": "3.2",
                "category_id": "C3",
                "condition": {"field": "period_activities", "operator": "count_greater_than", "value": 0},
                "points": 3,
                "unit": "per_activity_period",
            },
            {
                "rule_id": "SEMESTER",
                "criterion_id": "3.3",
                "category_id": "C3",
                "condition": {"field": "semester_events", "operator": "count_greater_than", "value": 0},
                "points": 4,
                "unit": "per_semester",
            },
            {
                "rule_id": "CERTIFICATE",
                "criterion_id": "3.4",
                "category_id": "C3",
                "condition": {"field": "certificates", "operator": "count_greater_than", "value": 0},
                "points": 5,
                "unit": "per_certificate_or_activity",
            },
        ],
    }

    result = evaluate_rule_conditions(
        config,
        {
            "activities": 3,
            "period_activities": 3,
            "semester_events": 3,
            "certificates": 3,
        },
    )

    assert {
        item["rule_id"]: (item["multiplier"], item["points"])
        for item in result["matched_rules"]
    } == {
        "ACTIVITY": (3, 6),
        "ACTIVITY_PERIOD": (1, 3),
        "SEMESTER": (1, 4),
        "CERTIFICATE": (3, 15),
    }
