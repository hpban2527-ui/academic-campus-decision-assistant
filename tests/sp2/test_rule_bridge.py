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
    assert {item["code"] for item in issues} == {
        "DUPLICATE_CONDITION",
        "RANGE_BOUND_NOT_NUMERIC",
    }


def test_actual_rules_match_gpa_and_violation_rules(actual_rules):
    result = evaluate_rule_conditions(
        actual_rules,
        {"semester_gpa": 8.5, "academic_exam_violations": 0},
    )
    assert [item["rule_id"] for item in result["matched_rules"]] == ["R11", "R1203"]
    assert [item["points"] for item in result["matched_rules"]] == [15, 10]
    assert result["category_scores"] == [
        {"category_id": "C1", "raw_score": 25, "cap": 30, "score": 25}
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
    assert result["skipped_rules"] == [
        {"rule_id": "R23", "reason": "same condition already matched by R22"}
    ]
    assert result["needs_review"] is True


def test_broken_actual_rule_is_reported_without_stopping_other_rules(actual_rules):
    result = evaluate_rule_conditions(
        actual_rules,
        {
            "semester_gpa": 9.0,
            "volunteer_hours_per_activity": 30,
        },
    )
    assert [item["rule_id"] for item in result["matched_rules"]] == ["R1204"]
    assert result["relevant_configuration_issues"][0]["code"] == (
        "RANGE_BOUND_NOT_NUMERIC"
    )
    assert result["needs_review"] is True


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
