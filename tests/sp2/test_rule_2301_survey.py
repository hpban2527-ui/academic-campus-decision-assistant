"""Criterion 2.3 (STSV2025): survey rounds, added next to the quarantined R23."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from sp2 import audit_rules_config, evaluate_rule_conditions
from sp2.rule_matcher import match_activity_to_rule

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def rules():
    return json.loads((ROOT / "data" / "drl_rules.json").read_text(encoding="utf-8"))


def _rule(rules, rule_id):
    return next(r for r in rules["rules"] if r["rule_id"] == rule_id)


def test_r2301_is_valid_and_r23_stays_quarantined(rules):
    r2301 = _rule(rules, "R2301")
    assert r2301["criterion_id"] == "2.3" and r2301["category_id"] == "C2"
    assert r2301["status"] == "verified" and r2301["points"] == 5
    assert r2301["source"]["document_id"] == "STSV2025"
    assert _rule(rules, "R23")["status"] == "needs_review"
    assert not [i for i in audit_rules_config(rules) if "R2301" in json.dumps(i, ensure_ascii=False)]


def test_one_survey_round_gives_five_points(rules):
    result = evaluate_rule_conditions(rules, {"institutional_survey_rounds_completed": 1})
    assert [m["rule_id"] for m in result["matched_rules"]] == ["R2301"]
    assert result["rule_points_total"] == 5


def test_survey_rounds_repeat_and_respect_the_c2_cap(rules):
    two = evaluate_rule_conditions(rules, {"institutional_survey_rounds_completed": 2})
    assert two["rule_points_total"] == 10
    many = evaluate_rule_conditions(rules, {"institutional_survey_rounds_completed": 9})
    c2_cap = next(c["max_score"] for c in rules["scoring_model"]["category_caps"] if c["category_id"] == "C2")
    assert many["rule_points_total"] <= c2_cap


def test_zero_rounds_gives_nothing(rules):
    result = evaluate_rule_conditions(rules, {"institutional_survey_rounds_completed": 0})
    assert result["matched_rules"] == []


def test_r23_field_alone_still_awards_nothing(rules):
    result = evaluate_rule_conditions(rules, {"institutional_social_survey_participation": True})
    assert result["rule_points_total"] == 0
    assert any(s["rule_id"] == "R23" for s in result["skipped_rules"])


@pytest.mark.parametrize("text", [
    "THƯ MỜI THAM GIA KHẢO SÁT chất lượng dịch vụ hỗ trợ sinh viên năm 2026",
    "Nhà trường lấy ý kiến sinh viên về hoạt động đào tạo, điền phiếu khảo sát tại link",
])
def test_matcher_binds_survey_posts_to_r2301(rules, text):
    match = match_activity_to_rule({"title": text}, text, rules).as_dict()
    assert match["rule_id"] == "R2301"


@pytest.mark.parametrize("text, expected", [
    ("Chuyến khảo sát thực địa môn Địa chất tại Vũng Tàu, đăng ký tham gia", None),
    ("Chương trình hiến máu tình nguyện, mời sinh viên tham gia khảo sát sức khỏe trước khi hiến", "R42"),
])
def test_matcher_does_not_steal_other_activities(rules, text, expected):
    match = match_activity_to_rule({"title": text}, text, rules).as_dict()
    assert match["rule_id"] != "R2301"
    if expected:
        assert match["rule_id"] == expected
