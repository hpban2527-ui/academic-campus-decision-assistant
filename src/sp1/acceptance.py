"""User-agreed routing of AI-extracted facts, separate from human approval and gold.

This policy produces a data-readiness catalog, not a student-specific SP3 plan.
Missing organizer facts never become invented clock times, deadlines or free fees.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]


def load_policy():
    return json.loads((ROOT / "data/config/activity_acceptance_v1.json").read_text(encoding="utf-8"))


def _moment(value, *, closing=False):
    if value is None:
        return None
    if "T" not in value:
        value += "T23:59+07:00" if closing else "T00:00+07:00"
    return datetime.fromisoformat(value)


# Schedule inputs: when window_close is the only one of these that is uncertain, a fixed event can still
# be scheduled from its certain start (policy 1.1).
TIMING_FIELDS = {"window_open", "window_close", "duration_minutes_stated"}
# Fields whose year may have been taken from the posting date (sp1.dates); see _inferred_year_problems.
YEAR_INFERRED_FIELDS = ("window_open", "window_close", "registration_deadline")


def _posted_date(value):
    """The posting day as a date, or None when it is missing or unreadable."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value).date()
    except ValueError:
        return None


def _inferred_year_problems(record: dict, inferred: set, posted, limits: dict) -> list[str]:
    """A date whose year was inferred from the posting date must lie between the look-back used by that rule
    (a date more than N days before the post moves to the next year) and the maximum distance from the post."""
    for field in YEAR_INFERRED_FIELDS:
        value = record.get(field)
        if field not in inferred or not isinstance(value, str):
            continue
        try:
            day = _moment(value, closing=field != "window_open").date()
        except ValueError:
            continue
        delta = (day - posted).days
        if delta < -limits["inferred_year_lookback_days"] or delta > limits["max_days_event_from_post"]:
            return ["inferred_year_inconsistent_with_post_date"]
    return []


def _deadline_after_start(deadline, start) -> bool:
    """A stated registration deadline later than the event start (compared by day unless both have a time)."""
    if not isinstance(deadline, str) or not isinstance(start, str):
        return False
    try:
        if "T" in deadline and "T" in start:
            return datetime.fromisoformat(deadline) > datetime.fromisoformat(start)
    except ValueError:
        return False
    return deadline[:10] > start[:10]


def assess_activity(row: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    record = deepcopy(row["record"])
    unsure = set(row.get("unsure", []))
    source = row.get("source_text", "")
    mode = record.get("mode")
    live = bool(re.search(policy["live_pattern"], source, re.I))
    quiz = mode == "online" and bool(re.search(policy["quiz_pattern"], source, re.I)) and not live
    # Policy 1.1: a certain start date+time with an uncertain end only (fixed events, not quizzes): the end is
    # ignored and replaced by the stated duration or the team default. A flexible quiz still needs its end.
    start_value = record.get("window_open")
    ignore_close = (not quiz and unsure & TIMING_FIELDS == {"window_close"}
                    and isinstance(start_value, str) and "T" in start_value)
    if ignore_close:
        record["window_close"] = None
    warning_fields = sorted(unsure & set(policy["soft_fields"]))
    # Keep the AI proposal untouched; operational values abstain on uncertain soft facts.
    for field in warning_fields:
        if field in record and field not in {"multi_session", "duration_minutes_stated"}:
            record[field] = None
    reasons, warnings = [], []
    schedule = None
    kind = record.get("post_type")
    if kind != "activity":
        reasons.append("not_an_activity" if kind == "info_only" else "insufficient_activity_information")
    if not record.get("title"):
        reasons.append("missing_title")
    if mode not in {"online", "offline", "hybrid"}:
        reasons.append("missing_mode")
    critical = sorted(unsure - set(policy["soft_fields"]) - ({"window_close"} if ignore_close else set()))
    reasons.extend("uncertain:" + field for field in critical)
    if record.get("domain") is None:
        warnings.append("domain_unknown")
    fee = record.get("fee")
    budget_known = isinstance(fee, (int, float)) and not isinstance(fee, bool)
    if fee is None:
        warnings.extend(["fee_unknown", "bounded_cost_unknown"])
    elif isinstance(fee, dict):
        budget_known = fee.get("per") == "person" and not fee.get("deposit", False)
        if not budget_known:
            warnings.append("fee_not_per_person")
    if not record.get("registration_url"):
        warnings.append("registration_link_missing")
    if not record.get("registration_deadline"):
        warnings.append("registration_deadline_missing")
    if mode in {"offline", "hybrid"} and not record.get("location"):
        warnings.append("location_unknown")
    if record.get("multi_session"):
        warnings.append("multiple_sessions")
    warnings.extend("uncertain_soft:" + field for field in warning_fields)

    start, end = record.get("window_open"), record.get("window_close")
    try:
        opening, closing = _moment(start), _moment(end, closing=True)
        minutes = record.get("duration_minutes_stated")
        if "duration_minutes_stated" in unsure:
            minutes = None
        valid_minutes = isinstance(minutes, int) and not isinstance(minutes, bool) and minutes > 0
        if ignore_close:
            warnings.append("uncertain_end_time_default_used")
        limits = policy.get("plausibility", {})
        posted = _posted_date(row.get("date_posted"))
        if opening is not None and posted is not None and limits:
            if abs((opening.date() - posted).days) > limits["max_days_event_from_post"]:
                reasons.append("event_far_from_post_date")
        if posted is not None and limits:
            reasons.extend(_inferred_year_problems(record, set(row.get("year_inferred", [])), posted, limits))
        if opening is not None and record.get("registration_deadline") and _deadline_after_start(
                record["registration_deadline"], start):
            warnings.append("registration_deadline_after_start")

        def flexible(duration, duration_source):
            """FLEXIBLE_WINDOW schedule, or None with the reason when the window is implausibly long."""
            # Whole days: a date-only end already carries the 23:59 bound, which must not count as an extra day.
            if limits and (closing - opening).days > limits["max_flexible_window_days"]:
                reasons.append("flexible_window_over_62_days")
                return None
            return {"type": "FLEXIBLE_WINDOW", "window_start": opening.isoformat(),
                    "window_end": closing.isoformat(), "duration_minutes": duration,
                    "duration_source": duration_source,
                    "bounds_precision": "date_only" if "T" not in start or "T" not in end else "time"}

        if opening is None:
            reasons.append("missing_activity_date")
        elif quiz:
            if closing is None:
                reasons.append("missing_quiz_window_end")
            elif closing <= opening:
                reasons.append("invalid_quiz_window")
            else:
                if not valid_minutes:
                    minutes = policy["default_quiz_duration_minutes"]
                    warnings.append("quiz_duration_default")
                if closing - opening < timedelta(minutes=minutes):
                    reasons.append("quiz_duration_exceeds_window")
                else:
                    schedule = flexible(minutes, "stated" if valid_minutes else "team_default")
        elif "T" not in start:
            reasons.append("missing_fixed_start_time")
        else:
            close_timed = end is not None and "T" in end
            if end and not close_timed and end[:10] != start[:10]:
                reasons.append("missing_first_session_end_time")
            elif close_timed and closing <= opening:
                reasons.append("end_before_start")
            else:
                duration_source = "stated_window"
                if not close_timed:
                    if not valid_minutes:
                        minutes = policy["default_fixed_duration_minutes"].get(mode)
                        warnings.append("fixed_duration_default")
                    duration_source = "stated_duration" if valid_minutes else "team_default"
                    closing = opening + timedelta(minutes=minutes) if minutes else None
                if not closing:
                    reasons.append("missing_duration")
                elif (limits and closing - opening > timedelta(hours=limits["max_fixed_hours"])
                      and not (valid_minutes and timedelta(minutes=minutes) >= closing - opening)):
                    # A block this long is not a plausible single sitting unless the post states that duration.
                    if mode == "online" and not live and valid_minutes:
                        # Online, no live platform, a stated sitting shorter than the window: one attempt anywhere
                        # inside the window (e.g. "40 questions in 45 minutes" open for several days).
                        schedule = flexible(minutes, "stated")
                        if schedule:
                            warnings.append("online_window_treated_as_flexible")
                    else:
                        reasons.append("fixed_duration_over_12h")
                else:
                    schedule = {"type": "FIXED", "start": opening.isoformat(), "end": closing.isoformat(),
                                "duration_source": duration_source}
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_schedule_value")
    reasons = list(dict.fromkeys(reasons))
    warnings = list(dict.fromkeys(warnings))
    if reasons:
        schedule = None
        if record.get("mandatory_stated") is True:
            warnings.append("mandatory_unscheduled")
    if kind == "info_only":
        status = "NOT_AN_ACTIVITY"
    elif reasons:
        status = "NOT_SCHEDULABLE"
    else:
        status = "READY_WITH_WARNINGS" if warnings else "READY"
    return {"policy_version": policy["version"], "status": status,
            "ready_for_scheduling": not reasons, "reasons": reasons, "warnings": warnings,
            "uncertain_fields": sorted(unsure), "schedule": schedule,
            "accepted_record": record, "budget_known": budget_known,
            "scoring_verified": False, "student_eligibility_verified": False,
            "human_approved": row.get("review", {}).get("status") == "approved",
            "processing_label": "AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD"}
