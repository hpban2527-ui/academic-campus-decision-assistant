import csv

import pytest

from sp1.review import DECISION_COLUMNS, LABEL, apply_decision, load_decisions, parse_decision, text_fingerprint

TEXT = "Workshop\nThời gian: 08g00 ngày 18/10/2026"
TYPES, RULES = {"seminar_workshop", "other"}, {"R19", "R46"}


def row(**values):
    base = dict.fromkeys(DECISION_COLUMNS, "")
    base.update(post_id="p1", text_sha256=text_fingerprint(TEXT), reviewer="admin-a", reviewed_at="2026-11-15")
    base.update(values)
    return base


def layer():
    return {"record": {"post_type": "activity", "mode": None, "location": "Room A", "window_open": "2026-10-18",
                       "window_close": None, "registration_deadline": None, "title": "Workshop"},
            "flags": ["needs_review:mode", "invalid_value:window_open", "end_before_start", "campus_unknown"],
            "year_inferred": ["window_open"], "evidence": {}}


def test_row_without_a_decision_is_ignored_and_invalid_rows_are_rejected():
    assert parse_decision(row(), TYPES, RULES) is None
    with pytest.raises(ValueError, match="set_mode"):
        parse_decision(row(set_mode="zoom"), TYPES, RULES)
    with pytest.raises(ValueError, match="set_window_open"):
        parse_decision(row(set_window_open="18/10/2026"), TYPES, RULES)
    with pytest.raises(ValueError, match="verified rule"):
        parse_decision(row(set_rule_id="R9999"), TYPES, RULES)
    with pytest.raises(ValueError, match="reviewer"):
        parse_decision(row(reviewer="", approve="yes"), TYPES, RULES)


def test_set_fields_replace_values_and_clear_only_their_flags():
    decision = parse_decision(row(set_mode="offline", set_window_open="2026-10-18 08:00", set_rule_id="R19"), TYPES, RULES)
    data = layer()
    note = apply_decision(data, decision, TEXT)
    assert data["record"]["mode"] == "offline" and data["record"]["window_open"] == "2026-10-18T08:00+07:00"
    assert data["flags"] == ["campus_unknown"] and data["year_inferred"] == []
    assert note["label"] == LABEL == "reviewed" and note["rule_id"] == "R19" and note["fields_set"] == ["mode", "window_open"]
    assert note["reviewer"] == "admin-a" and note["approved"] is False


def test_approve_clears_review_flags_but_keeps_informational_ones():
    data = layer()
    apply_decision(data, parse_decision(row(approve="yes"), TYPES, RULES), TEXT)
    assert data["flags"] == ["campus_unknown"] and data["record"]["mode"] is None


def test_decision_is_ignored_when_the_announcement_text_changed():
    data = layer()
    before = {"record": dict(data["record"]), "flags": list(data["flags"])}
    note = apply_decision(data, parse_decision(row(set_mode="online"), TYPES, RULES), TEXT + " (đã cập nhật)")
    assert note["stale"] is True and data["record"] == before["record"] and data["flags"] == before["flags"]


def test_setting_online_drops_the_location():
    data = layer()
    apply_decision(data, parse_decision(row(set_mode="online"), TYPES, RULES), TEXT)
    assert data["record"]["location"] is None


def test_load_reports_problems_with_line_numbers(tmp_path):
    path = tmp_path / "decisions.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, DECISION_COLUMNS)
        writer.writeheader()
        writer.writerows([row(approve="yes"), row(post_id="p2", set_mode="bad"), row(approve="x"), row(post_id="p3")])
    decisions, problems = load_decisions(path, TYPES, RULES)
    assert list(decisions) == ["p1"]
    assert [(p["line"], p["post_id"]) for p in problems] == [(3, "p2"), (4, "p1")]
    assert load_decisions(tmp_path / "missing.csv", TYPES, RULES) == ({}, [])
