from copy import deepcopy
from datetime import datetime, timedelta

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


# ---------------------------------------------------------------- policy 1.1: uncertain end of a fixed event

def _uncertain_end(**updates):
    values = {"window_open": "2026-10-30T14:00+07:00", "window_close": "2026-10-30T16:00+07:00", **updates}
    item = row(**values)
    item["unsure"] = ["window_close"]
    return item


def test_certain_start_with_uncertain_end_is_scheduled_with_the_team_default_offline():
    result = assess_activity(_uncertain_end())
    assert result["ready_for_scheduling"] and result["status"] == "READY_WITH_WARNINGS"
    assert result["schedule"] == {"type": "FIXED", "start": "2026-10-30T14:00:00+07:00",
                                  "end": "2026-10-30T16:00:00+07:00", "duration_source": "team_default"}
    assert "uncertain_end_time_default_used" in result["warnings"] and "fixed_duration_default" in result["warnings"]
    assert result["accepted_record"]["window_close"] is None          # the uncertain end is ignored, not trusted


def test_the_ignored_end_never_leaks_into_the_schedule():
    item = _uncertain_end()
    item["record"]["window_close"] = "2026-10-30T20:00+07:00"        # a different, uncertain value
    result = assess_activity(item)
    assert result["schedule"]["end"] == "2026-10-30T16:00:00+07:00"
    assert item["record"]["window_close"] == "2026-10-30T20:00+07:00"  # the AI proposal itself is untouched


def test_uncertain_end_online_uses_30_minutes_and_a_stated_duration_wins():
    online = assess_activity(_uncertain_end(mode="online", location=None))
    assert online["schedule"]["end"] == "2026-10-30T14:30:00+07:00"
    stated = assess_activity(_uncertain_end(duration_minutes_stated=90))
    assert stated["schedule"]["end"] == "2026-10-30T15:30:00+07:00"
    assert stated["schedule"]["duration_source"] == "stated_duration"
    assert "uncertain_end_time_default_used" in stated["warnings"] and "fixed_duration_default" not in stated["warnings"]


def test_uncertain_end_still_blocks_a_flexible_quiz():
    item = _uncertain_end(mode="online", location=None, window_open="2026-10-30T08:00+07:00")
    item["source_text"] = "Thi trắc nghiệm trực tuyến trong thời gian mở cổng."
    result = assess_activity(item)
    assert not result["ready_for_scheduling"] and result["schedule"] is None
    assert "uncertain:window_close" in result["reasons"]
    assert "uncertain_end_time_default_used" not in result["warnings"]


def test_uncertain_end_still_blocks_without_a_certain_start_date_and_time():
    date_only = _uncertain_end(window_open="2026-10-30")
    result = assess_activity(date_only)
    assert not result["ready_for_scheduling"] and "uncertain:window_close" in result["reasons"]
    no_start = _uncertain_end(window_open=None)
    assert not assess_activity(no_start)["ready_for_scheduling"]
    both = _uncertain_end()
    both["unsure"] = ["window_open", "window_close"]
    result = assess_activity(both)
    assert not result["ready_for_scheduling"]
    assert {"uncertain:window_open", "uncertain:window_close"} <= set(result["reasons"])


def test_uncertain_end_is_not_ignored_when_another_schedule_field_is_also_uncertain():
    item = _uncertain_end(duration_minutes_stated=90)
    item["unsure"] = ["window_close", "duration_minutes_stated"]
    result = assess_activity(item)
    assert not result["ready_for_scheduling"] and "uncertain:window_close" in result["reasons"]


def test_other_uncertain_core_fields_still_block_next_to_an_uncertain_end():
    item = _uncertain_end()
    item["unsure"] = ["window_close", "mode"]
    assert "uncertain:mode" in assess_activity(item)["reasons"]


# ---------------------------------------------------------------- policy 1.1: uncertain completion requirements

REQUIREMENT = {"type": "attendance", "threshold": None, "unit": None, "deadline": None}


def test_uncertain_completion_requirements_is_soft_and_unknown_not_completed():
    item = row(completion_requirements=[REQUIREMENT])
    item["unsure"] = ["completion_requirements"]
    result = assess_activity(item)
    assert result["ready_for_scheduling"] and result["status"] == "READY_WITH_WARNINGS"
    assert result["accepted_record"]["completion_requirements"] is None       # unknown, not [] and not the AI list
    assert "uncertain_soft:completion_requirements" in result["warnings"]
    assert not any("completion_requirements" in reason for reason in result["reasons"])
    assert item["record"]["completion_requirements"] == [REQUIREMENT]        # AI proposal untouched


def test_certain_completion_requirements_are_kept_and_other_uncertain_fields_still_block():
    kept = assess_activity(row(completion_requirements=[REQUIREMENT]))
    assert kept["accepted_record"]["completion_requirements"] == [REQUIREMENT]
    assert "uncertain_soft:completion_requirements" not in kept["warnings"]
    item = row(completion_requirements=[REQUIREMENT])
    item["unsure"] = ["completion_requirements", "title"]
    blocked = assess_activity(item)
    assert not blocked["ready_for_scheduling"] and "uncertain:title" in blocked["reasons"]


def test_sp3_marker_is_unknown_for_uncertain_completion_and_not_stated_for_silence():
    from sp1.operational import NOT_STATED, UNKNOWN, project_sp3
    post = {"post_id": "p1", "publisher": "Khoa", "platform": "facebook", "url": "https://example.org/p1"}
    accepted = {"title": "Workshop", "mode": "offline", "location": "Room A", "domain": None, "fee": None,
                "mandatory_stated": None, "registration_deadline": None, "registration_url": None,
                "points_stated": None, "completion_requirements": None}
    schedule = {"type": "FIXED", "start": "2026-10-30T14:00:00+07:00", "end": "2026-10-30T16:00:00+07:00",
                "duration_source": "team_default"}
    normalized = {"registration_deadline": None, "meta": {"time_defaults": {}}}
    audience = {"lines": []}
    activity, derived = project_sp3(post, accepted, schedule, normalized, audience, completion_unknown=True)
    assert activity["completion_requirements"] == UNKNOWN == "UNKNOWN"
    assert derived["completion_requirements"] == "marker:unknown"
    activity, derived = project_sp3(post, {**accepted, "completion_requirements": []}, schedule, normalized, audience)
    assert activity["completion_requirements"] == NOT_STATED == "NOT_STATED"
    assert derived["completion_requirements"] == "marker:not_stated"
    activity, _ = project_sp3(post, {**accepted, "completion_requirements": [REQUIREMENT]}, schedule, normalized,
                              audience)
    assert activity["completion_requirements"] not in {"UNKNOWN", "NOT_STATED"}


def test_policy_keeps_the_1_1_rules():
    from sp1.acceptance import load_policy
    policy = load_policy()
    assert policy["version"] >= "activity-acceptance/1.1"                # pinned exactly in the 1.2 test below
    assert "completion_requirements" in policy["soft_fields"]
    assert "uncertain_end_time_default_used" in policy["warnings"]


# ---------------------------------------------------------------- policy 1.2: plausibility checks

def test_fixed_block_over_12_hours_is_excluded_unless_the_duration_is_stated():
    overnight = row(window_open="2026-05-23T04:00+07:00", window_close="2026-05-24T20:30+07:00")
    result = assess_activity(overnight)
    assert not result["ready_for_scheduling"] and result["schedule"] is None
    assert "fixed_duration_over_12h" in result["reasons"]
    edge = assess_activity(row(window_open="2026-05-23T08:00+07:00", window_close="2026-05-23T20:00+07:00"))
    assert edge["ready_for_scheduling"] and edge["schedule"]["type"] == "FIXED"       # exactly 12 h is plausible
    over = assess_activity(row(window_open="2026-05-23T08:00+07:00", window_close="2026-05-23T20:01+07:00"))
    assert "fixed_duration_over_12h" in over["reasons"]
    stated = assess_activity(row(window_open="2026-05-23T04:00+07:00", window_close="2026-05-24T20:30+07:00",
                                 duration_minutes_stated=40 * 60 + 30))
    assert stated["ready_for_scheduling"] and stated["schedule"]["type"] == "FIXED"


def test_a_stated_duration_shorter_than_a_long_offline_window_does_not_justify_one_long_block():
    item = row(window_open="2026-05-23T04:00+07:00", window_close="2026-05-24T20:30+07:00", duration_minutes_stated=45)
    assert "fixed_duration_over_12h" in assess_activity(item)["reasons"]


def test_online_contest_with_a_stated_sitting_inside_a_long_window_is_flexible():
    # Regression: "from 09:00 30/07 to 23:00 03/08 ... 40 questions in 45 minutes" was a 110 h FIXED block.
    item = row(mode="online", location=None, window_open="2026-07-30T09:00+07:00",
               window_close="2026-08-03T23:00+07:00", duration_minutes_stated=45)
    item["source_text"] = "Cuộc thi trực tuyến trên nền tảng Myaloha. Thí sinh trả lời 40 câu hỏi trong vòng 45 phút."
    result = assess_activity(item)
    assert result["ready_for_scheduling"]
    assert result["schedule"] == {"type": "FLEXIBLE_WINDOW", "window_start": "2026-07-30T09:00:00+07:00",
                                  "window_end": "2026-08-03T23:00:00+07:00", "duration_minutes": 45,
                                  "duration_source": "stated", "bounds_precision": "time"}
    assert "online_window_treated_as_flexible" in result["warnings"]
    item["source_text"] += " Tổ chức qua Zoom."
    live = assess_activity(item)                                   # a live session is not a free-choice attempt
    assert not live["ready_for_scheduling"] and "fixed_duration_over_12h" in live["reasons"]
    item["record"]["duration_minutes_stated"] = None
    item["source_text"] = "Cuộc thi trực tuyến."
    assert "fixed_duration_over_12h" in assess_activity(item)["reasons"]     # no stated sitting: nothing to flex


def test_flexible_window_longer_than_62_days_is_excluded():
    def quiz(days):
        item = row(mode="online", location=None, window_open="2026-09-01", window_close=None)
        end = (datetime.fromisoformat("2026-09-01") + timedelta(days=days)).date().isoformat()
        item["record"]["window_close"] = end
        item["source_text"] = "Thi trắc nghiệm trực tuyến."
        return assess_activity(item)
    assert quiz(61)["schedule"]["type"] == "FLEXIBLE_WINDOW"
    assert quiz(62)["schedule"]["type"] == "FLEXIBLE_WINDOW"          # 62 whole days (+ the 23:59 bound)
    long = quiz(63)
    assert "flexible_window_over_62_days" in long["reasons"] and long["schedule"] is None


def test_end_not_after_start_is_excluded():
    assert "end_before_start" in assess_activity(row(window_close="2026-10-30T14:00+07:00"))["reasons"]
    assert "end_before_start" in assess_activity(row(window_close="2026-10-30T09:00+07:00"))["reasons"]
    item = row(mode="online", location=None, window_open="2026-11-08", window_close="2026-11-02")
    item["source_text"] = "Thi trắc nghiệm trực tuyến."
    assert "invalid_quiz_window" in assess_activity(item)["reasons"]


def test_deadline_after_start_is_a_warning_only():
    late = assess_activity(row(registration_deadline="2026-10-31T09:00+07:00"))
    assert late["ready_for_scheduling"] and "registration_deadline_after_start" in late["warnings"]
    date_late = assess_activity(row(registration_deadline="2026-11-02"))
    assert date_late["ready_for_scheduling"] and "registration_deadline_after_start" in date_late["warnings"]
    same_day = assess_activity(row(registration_deadline="2026-10-30"))              # date-only on the event day
    assert "registration_deadline_after_start" not in same_day["warnings"]
    before = assess_activity(row(registration_deadline="2026-10-29T12:00+07:00"))
    assert "registration_deadline_after_start" not in before["warnings"]


def _posted(posted, **updates):
    item = row(**updates)
    item["date_posted"] = posted
    return item


def test_event_must_be_within_400_days_of_the_post_date():
    ok = assess_activity(_posted("2025-09-26T00:00:00"))                              # 399 days later
    assert ok["ready_for_scheduling"]
    far = assess_activity(_posted("2025-09-25T00:00:00"))                             # 400 days later is the limit
    assert far["ready_for_scheduling"]
    too_far = assess_activity(_posted("2025-09-24T00:00:00"))
    assert not too_far["ready_for_scheduling"] and "event_far_from_post_date" in too_far["reasons"]
    stale = assess_activity(_posted("2028-01-01T00:00:00"))                           # 428 days before the post
    assert "event_far_from_post_date" in stale["reasons"]
    unknown = assess_activity(row())                                                  # no posting date: not checked
    assert "event_far_from_post_date" not in unknown["reasons"]


def test_inferred_year_must_agree_with_the_post_date():
    item = _posted("2026-12-20T00:00:00", window_open="2026-10-30T14:00+07:00", window_close="2026-10-30T16:00+07:00")
    item["year_inferred"] = ["window_open"]                       # 51 days before the post: inside the 60-day look-back
    assert "inferred_year_inconsistent_with_post_date" not in assess_activity(item)["reasons"]
    item["date_posted"] = "2027-01-20T00:00:00"                   # 82 days before the post: the rule would have chosen 2027
    result = assess_activity(item)
    assert not result["ready_for_scheduling"] and "inferred_year_inconsistent_with_post_date" in result["reasons"]
    item["year_inferred"] = []                                    # a stated year is not judged by this rule
    assert "inferred_year_inconsistent_with_post_date" not in assess_activity(item)["reasons"]
    late = _posted("2025-06-01T00:00:00", registration_deadline="2026-10-01")
    late["year_inferred"] = ["registration_deadline"]
    assert "inferred_year_inconsistent_with_post_date" in assess_activity(late)["reasons"]


def test_policy_version_is_1_2_and_has_the_plausibility_limits():
    from sp1.acceptance import load_policy
    policy = load_policy()
    assert policy["version"] == "activity-acceptance/1.2"
    assert policy["plausibility"] == {"max_fixed_hours": 12, "max_flexible_window_days": 62,
                                      "max_days_event_from_post": 400, "inferred_year_lookback_days": 60}
