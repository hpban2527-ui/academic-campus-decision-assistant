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


def assess_activity(row: dict, policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    record = deepcopy(row["record"])
    unsure = set(row.get("unsure", []))
    source = row.get("source_text", "")
    mode = record.get("mode")
    quiz = (mode == "online" and bool(re.search(policy["quiz_pattern"], source, re.I))
            and not re.search(policy["live_pattern"], source, re.I))
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
                    schedule = {"type": "FLEXIBLE_WINDOW", "window_start": opening.isoformat(),
                                "window_end": closing.isoformat(), "duration_minutes": minutes,
                                "duration_source": "stated" if valid_minutes else "team_default",
                                "bounds_precision": "date_only" if "T" not in start or "T" not in end else "time"}
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
                if closing:
                    schedule = {"type": "FIXED", "start": opening.isoformat(), "end": closing.isoformat(),
                                "duration_source": duration_source}
                else:
                    reasons.append("missing_duration")
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
