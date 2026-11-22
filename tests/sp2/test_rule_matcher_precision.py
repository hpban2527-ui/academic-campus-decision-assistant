"""Regression cases for matcher false positives found on real announcements (2026-11-14). Synthetic text."""

from __future__ import annotations

import json
from pathlib import Path

from sp2.rule_matcher import match_activity_to_rule

RULES = json.loads((Path(__file__).resolve().parents[2] / "data" / "drl_rules.json").read_text(encoding="utf-8"))


def match(title, text, domain="academic"):
    record = {"title": title, "domain": domain, "mode": "offline", "completion_requirements": "NOT_STATED"}
    return match_activity_to_rule(record, text, RULES).as_dict()


def test_general_support_wording_is_not_a_donation():
    out = match("Seminar học thuật về tối ưu hóa", "Cảm ơn các bạn đã luôn ủng hộ chương trình của Khoa.")
    assert out["rule_id"] == "R19"


def test_explicit_donation_wording_still_matches_the_donation_rule():
    out = match("Chung tay vì miền Trung", "Kêu gọi quyên góp sách vở cho học sinh vùng lũ.", "volunteer")
    assert out["rule_id"] == "R45"


def test_seminar_webinar_and_talkshow_are_recognised_as_seminars():
    for title in ("Seminar Toán tài chính", "Webinar quản trị rủi ro", "Talkshow ngành Hóa trong kỷ nguyên số"):
        assert match(title, "Thời gian: 14h00 ngày 02/11/2026. Địa điểm: phòng F207.")["rule_id"] == "R19"


def test_fallback_never_proposes_role_level_or_duration_rules():
    # Words from organiser, delegate and long-term volunteer rule names appear, but no participation signal.
    out = match("Thông báo", "Thành viên ban tổ chức các hoạt động tình nguyện cấp trường dài hạn từ 1 tuần "
                             "trở lên; đại biểu giao lưu trao đổi văn hóa quốc tế.", None)
    by_id = {rule["rule_id"]: rule for rule in RULES["rules"]}
    if out["method"] == "rule_name_token_overlap":
        assert by_id[out["rule_id"]]["condition"]["operator"] == "count_greater_than"
    assert out["rule_id"] not in {"R4303", "R4401", "R4403", "R1701", "R313"} or out["method"] == "catalog_signal_match"
