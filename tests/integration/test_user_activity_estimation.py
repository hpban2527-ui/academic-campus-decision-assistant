"""User-facing estimation regressions for catalog posts without announced points."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from api.server import EvaluationRequest, evaluate_announcement, reset_session_state  # noqa: E402
from sp2.rule_matcher import match_activity_to_rule  # noqa: E402


@pytest.fixture(autouse=True)
def fresh_session():
    reset_session_state()


def _blit_post() -> dict:
    posts = json.loads((ROOT / "data" / "source_posts.json").read_text(encoding="utf-8"))
    return next(post for post in posts if "BẢN LĨNH IT 2026] - MỞ FORM" in post["raw_content"])


def _health_exam_post() -> dict:
    posts = json.loads((ROOT / "data" / "source_posts.json").read_text(encoding="utf-8"))
    return next(post for post in posts if "ĐĂNG KÝ LỊCH KHÁM SỨC KHỎE ĐỊNH KỲ" in post["raw_content"])


def _request(post: dict, *, exact_identity: bool = False, evidence: bool = False) -> EvaluationRequest:
    return EvaluationRequest(
        post_id=post["post_id"] if exact_identity else "user-pasted-copy-with-new-id",
        publisher=post["publisher"],
        platform="facebook",
        date_posted="2026-09-17",
        url=post["url"] if exact_identity else "https://example.com/user-pasted-copy-with-new-id",
        raw_content=post["raw_content"],
        has_evidence=evidence,
        student_id="new-user-estimation-test",
        simulate_demo=True,
    )


def test_catalog_content_can_be_estimated_for_a_student_without_announced_points():
    result = evaluate_announcement(_request(_blit_post()))

    assert result["dedup"]["is_duplicate"] is False
    assert result["dedup"]["catalog_match"] is True
    assert result["rule_match"]["point_source"] == "drl_rules.json"
    assert result["sp2"]["rule"]["rule_id"] == "R16"
    assert result["sp2"]["decision"] == "PROJECTED"
    assert result["sp2"]["projected_added"] == 5
    assert result["sp2"]["estimate_requires_review"] is True
    assert result["commit"]["kind"] == "review"


def test_incomplete_catalog_post_cannot_become_confirmed_from_user_checkbox():
    result = evaluate_announcement(_request(_blit_post(), evidence=True))

    assert result["sp2"]["decision"] == "PROJECTED"
    assert result["sp2"]["confirmed_added"] == 0
    assert result["sp2"]["projected_added"] == 5
    assert result["commit"]["kind"] == "review"


def test_exact_catalog_identity_is_still_rejected_as_duplicate_ingestion():
    result = evaluate_announcement(_request(_blit_post(), exact_identity=True))

    assert result["dedup"]["is_duplicate"] is True
    assert result["dedup"]["match_kind"] == "exact_identity"
    assert result["sp2"]["decision"] == "REJECTED_DUPLICATE"


def test_matcher_takes_points_from_supplied_rule_catalog_not_hardcoded_value():
    config = {
        "rules": [
            {
                "rule_id": "R19",
                "criterion_id": "1.9",
                "category_id": "C1",
                "name": "Tham gia hội thảo kỹ năng",
                "points": 7,
                "unit": "per_activity",
                "status": "verified",
            }
        ]
    }
    match = match_activity_to_rule(
        {"title": "Workshop kỹ năng học tập", "domain": "skills"},
        "Sinh viên tham gia workshop kỹ năng quản lý thời gian.",
        config,
    )

    assert match.rule is not None
    assert match.rule["rule_id"] == "R19"
    assert match.rule["points"] == 7


def test_periodic_health_exam_is_not_assumed_to_award_drl_points():
    result = evaluate_announcement(_request(_health_exam_post()))

    assert result["dedup"]["catalog_match"] is True
    assert result["rule_match"]["method"] == "uncertain_health_exam"
    assert result["rule_match"]["rule_id"] is None
    assert result["sp2"]["rule"] is None
    assert result["sp2"]["decision"] == "NEEDS_REVIEW"
    assert result["sp2"]["projected_added"] == 0
    assert result["sp2"]["confirmed_added"] == 0
    assert result["commit"]["kind"] == "review"
