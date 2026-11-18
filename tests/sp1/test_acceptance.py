from copy import deepcopy

from sp1.acceptance import assess_activity


BASE = {"record": {"post_type": "activity", "title": "Workshop", "mode": "offline", "domain": "skills",
    "window_open": "2026-10-30T14:00+07:00", "window_close": "2026-10-30T16:00+07:00",
    "duration_minutes_stated": None, "fee": None, "registration_url": None,
    "registration_deadline": None, "location": "Room A", "multi_session": False,
    "mandatory_stated": None}, "unsure": [], "source_text": "Workshop; đăng ký tại văn phòng.",
    "review": {"status": "pending"}}


def row(**updates):
    result = deepcopy(BASE)
    result["record"].update(updates)
    return result


def test_unknown_fee_domain_and_no_link_do_not_block_calendar_or_become_free():
    item = row(domain=None)
    item["unsure"] = ["domain", "fee"]
    result = assess_activity(item)
    assert result["status"] == "READY_WITH_WARNINGS"
    assert result["accepted_record"]["fee"] is None and not result["budget_known"]
    assert not result["human_approved"] and not result["scoring_verified"]
    assert "registration_link_missing" in result["warnings"]


def test_missing_fixed_time_is_automatically_excluded_even_if_post_was_reviewed():
    item = row(window_open="2026-10-30", window_close=None)
    item["review"] = {"status": "approved"}
    result = assess_activity(item)
    assert not result["ready_for_scheduling"] and result["schedule"] is None
    assert "missing_fixed_start_time" in result["reasons"]


def test_date_only_quiz_window_can_be_scheduled_but_webinar_cannot():
    item = row(mode="online", window_open="2026-10-30", window_close="2026-11-02", location=None)
    item["source_text"] = "Thi trắc nghiệm trực tuyến trong thời gian mở cổng."
    result = assess_activity(item)
    assert result["ready_for_scheduling"]
    assert result["schedule"]["type"] == "FLEXIBLE_WINDOW"
    assert result["schedule"]["duration_minutes"] == 30
    item["source_text"] = "Webinar Zoom có phần trắc nghiệm."
    assert not assess_activity(item)["ready_for_scheduling"]


def test_quiz_does_not_shrink_stated_duration_to_fit_window():
    item = row(mode="online", window_open="2026-10-30T14:00+07:00",
               window_close="2026-10-30T14:20+07:00", duration_minutes_stated=40)
    item["source_text"] = "Quiz 40 phút."
    assert "quiz_duration_exceeds_window" in assess_activity(item)["reasons"]


def test_uncertain_cost_abstains_and_scoped_mandatory_is_not_silently_scheduled():
    item = row(fee={"amount_vnd": 50000, "per": "person", "deposit": False})
    item["unsure"] = ["fee", "mandatory_stated"]
    result = assess_activity(item)
    assert result["accepted_record"]["fee"] is None
    assert item["record"]["fee"]["amount_vnd"] == 50000
    assert "uncertain:mandatory_stated" in result["reasons"]


def test_unscheduled_mandatory_still_warns_and_missing_end_uses_explicit_team_default():
    result = assess_activity(row(window_open=None, mandatory_stated=True))
    assert "mandatory_unscheduled" in result["warnings"]
    result = assess_activity(row(window_close=None))
    assert result["schedule"]["end"] == "2026-10-30T16:00:00+07:00"
    assert "fixed_duration_default" in result["warnings"]
