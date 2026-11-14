"""Project SP1 v2 store records onto the SP3 v0.2 activity contract (ADR-0002 D16).

SP3 accepts an activity with exactly 14 fields and a 4-field source. This module builds that
projection deterministically, keeps everything else in a sidecar, and proposes rule-based
evidence. Nothing here is human review: every proposed evidence value is labelled
AUTO_CHECK_LABEL, and every value that is a team default is listed under "derived".

Team conventions (decided 2026-11-14, pending agreement of the SP3 owner where they touch SP3):
  C1 completion requirements not stated  -> the string "NOT_STATED" (never "none required")
  C2 end missing, start time stated      -> start + duration_minutes (stated or team default)
  C3 registration deadline not stated    -> the activity start
  C4 source / term / eligibility         -> derived by rule, labelled as automatic checks

Identity (D19): the handed-over activity_id is the announcement's post_id, which every other module already
keys on (Ngoc's activity_features.json, the source store, deduplication). SP1's own TMP- id stays in the
store and in the sidecar as sp1_activity_id, so a record can still be traced back to its draft.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from urllib.parse import urlparse

NOT_STATED = "NOT_STATED"
AUTO_CHECK_LABEL = "auto_checked_not_human_reviewed"
ACTIVITY_FIELDS = ("activity_id", "source", "title", "domain", "start", "end", "registration_deadline", "mode",
                   "location", "points", "mandatory", "audience", "fee", "completion_requirements")
SOURCE_FIELDS = ("publisher", "platform", "URL_post", "URL_registration")
DOMAINS = {"academic", "volunteer", "culture_sports", "skills", "career", "other"}
MODES = {"online", "offline", "hybrid"}
_DURATION_OK = re.compile(r"^(stated|default_)")
_BARE_URL = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}/\S+$", re.IGNORECASE)


def _http_url(value) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _fee(fee, derived, blocked, warnings):
    if isinstance(fee, dict):
        if fee.get("deposit") or fee.get("per") == "team":
            blocked.append("fee_not_per_person")
            return None
        if fee.get("per") != "person":
            warnings.append("fee_unit_unknown")
        derived["fee"] = f"flattened:{fee.get('per')}"
        return fee["amount_vnd"]
    return fee


def _completion(items, derived):
    if not items:
        derived["completion_requirements"] = "team_convention:not_stated"
        return NOT_STATED
    return json.dumps(items, ensure_ascii=False, sort_keys=True)


def project(record: dict) -> dict:
    """Return {"activity": 14-field object or None, "blocked", "derived", "warnings", "schedule", "sidecar"}."""
    a = record["activity"]
    blocked, warnings, derived = [], [], {}
    if record.get("duplicate_of"):
        blocked.append("duplicate")
    if a["post_type"] != "activity":
        blocked.append("not_an_activity")
    if a["meta"]["status"] == "failed":
        blocked.append("failed_status")
    if not a["title"]:
        blocked.append("missing_title")
    if a["mode"] not in MODES:
        blocked.append("missing_mode")
    if not _http_url(a["source"].get("URL_post")):
        blocked.append("invalid_source_url")

    defaults = a["meta"].get("time_defaults") or {}
    start, end = a["window"]["open"], a["window"]["close"]
    duration, duration_source = a.get("duration_minutes"), a.get("duration_source") or ""
    start_timed = bool(start) and "window_open" not in defaults
    usable_duration = isinstance(duration, int) and duration > 0 and bool(_DURATION_OK.match(duration_source))
    if start_timed and end is None and usable_duration:                                   # C2
        end = (datetime.fromisoformat(start) + timedelta(minutes=duration)).isoformat()
        derived["end"] = f"start_plus_duration:{duration_source}"
    deadline = a["registration_deadline"]
    if deadline is None and start:                                                        # C3
        deadline = start
        derived["registration_deadline"] = "team_convention:deadline_at_start"

    schedule = None
    if a["mode"] == "online" and start and end and end > start and usable_duration:
        span = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds() // 60)
        schedule = {"type": "FLEXIBLE_WINDOW", "duration_minutes": min(duration, span)}
    if a.get("multi_session"):
        warnings.append("multi_session_first_block_only")
    if "window_open" in defaults and a["mode"] != "online":
        warnings.append("start_time_not_stated")

    registration_url = a["registration_url"]
    if registration_url and not _http_url(registration_url):
        if _BARE_URL.match(registration_url):
            registration_url = "https://" + registration_url
            derived["source.URL_registration"] = "scheme_added:https"
        else:
            registration_url = None
            warnings.append("registration_url_dropped_invalid")
    text = (a["audience"].get("text") or "").split("\n")[0].strip()
    fee = _fee(a["fee"], derived, blocked, warnings)
    for field, rule in a["meta"].get("derived", {}).items():
        if field in ("mandatory", "fee", "audience") and rule.startswith("team_default"):
            derived.setdefault(field, rule)

    legacy = None
    if not blocked:
        legacy = {
            "activity_id": a["source"]["post_id"],
            "source": {"publisher": a["source"]["publisher"], "platform": a["source"]["platform"],
                       "URL_post": a["source"]["URL_post"], "URL_registration": registration_url},
            "title": a["title"], "domain": a["domain"], "start": start, "end": end,
            "registration_deadline": deadline, "mode": a["mode"],
            "location": None if a["mode"] == "online" else a["location"],
            "points": a["points_announced"], "mandatory": a["mandatory"],
            "audience": [text] if text else None, "fee": fee,
            "completion_requirements": _completion(a["completion_requirements"], derived),
        }
        problems = contract_problems(legacy)
        if problems:
            blocked.extend(f"contract:{p}" for p in problems)
            legacy = None
    sidecar = {
        "post_id": a["source"]["post_id"], "sp1_activity_id": a["activity_id"],
        "activity_type": record.get("activity_type"),
        "review": record.get("review"), "date_posted": a["source"].get("date_posted"),
        "sources": record.get("sources", [a["source"]]), "status": a["meta"]["status"], "flags": a["meta"]["flags"],
        "campus": a["campus"], "audience": a["audience"], "fee": a["fee"], "join_url": a["join_url"],
        "completion_requirements": a["completion_requirements"], "multi_session": a.get("multi_session"),
        "semester_by_program": a["semester_by_program"], "duration_minutes": duration,
        "duration_source": duration_source, "time_defaults": defaults, "recognition_stated": a["recognition_stated"],
        "drl_recognized": a["drl_recognized"], "possible_duplicates": record.get("possible_duplicates", []),
    }
    return {"activity": legacy, "blocked": blocked, "derived": derived, "warnings": warnings,
            "schedule": schedule, "sidecar": sidecar}


def contract_problems(activity: dict) -> list[str]:
    """Mirror of the SP3 v0.2 activity validator (src/sp3/feasibility.py on the SP3 branch)."""
    problems = []
    if set(activity) != set(ACTIVITY_FIELDS):
        return ["fields"]
    source = activity["source"]
    if not isinstance(source, dict) or set(source) != set(SOURCE_FIELDS):
        return ["source.fields"]
    for key in ("publisher", "platform"):
        if not isinstance(source[key], str) or not source[key].strip():
            problems.append(f"source.{key}")
    if not _http_url(source["URL_post"]):
        problems.append("source.URL_post")
    if source["URL_registration"] is not None and not _http_url(source["URL_registration"]):
        problems.append("source.URL_registration")
    for key in ("activity_id", "title", "completion_requirements"):
        if not isinstance(activity[key], str) or not activity[key].strip():
            problems.append(key)
    if activity["domain"] is not None and activity["domain"] not in DOMAINS:
        problems.append("domain")
    for key in ("start", "end", "registration_deadline"):
        value = activity[key]
        if value is None:
            continue
        try:
            if datetime.fromisoformat(value).utcoffset() is None:
                problems.append(key)
        except (TypeError, ValueError):
            problems.append(key)
    if activity["mode"] not in MODES:
        problems.append("mode")
    if activity["location"] is not None and not isinstance(activity["location"], str):
        problems.append("location")
    if activity["mode"] == "online" and activity["location"] is not None:
        problems.append("location")
    for key, nullable in (("points", True), ("fee", False)):
        value = activity[key]
        if value is None:
            if not nullable:
                problems.append(key)
        elif isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
            problems.append(key)
    if not isinstance(activity["mandatory"], bool):
        problems.append("mandatory")
    audience = activity["audience"]
    if audience is not None and (not isinstance(audience, list) or any(not isinstance(x, str) for x in audience)):
        problems.append("audience")
    return problems


def eligibility(audience: dict, profile: dict) -> str:
    """ELIGIBLE / INELIGIBLE from structured audience restrictions and a synthetic profile; else NEEDS_REVIEW."""
    cohorts, programs = audience.get("cohorts") or [], audience.get("programs") or []
    if cohorts and profile.get("cohort") is None or programs and profile.get("program") is None:
        return "NEEDS_REVIEW"
    if cohorts and profile["cohort"] not in cohorts:
        return "INELIGIBLE"
    if programs and profile["program"] not in programs:
        return "INELIGIBLE"
    if re.search(r"giáo viên", audience.get("text") or "", re.IGNORECASE):
        return "NEEDS_REVIEW"   # aimed at school teachers: a person confirms that students may take part
    if cohorts or programs or audience.get("all_students"):
        return "ELIGIBLE"
    return "NEEDS_REVIEW"   # restricted in free text only (for example one faculty): not decided by rule


def auto_evidence(projections: list[dict], profile: dict, term_id: str) -> dict:
    """Rule-based evidence in the shape of SP3 FeasibilityEvidence, for projected activities only."""
    evidence = {"label": AUTO_CHECK_LABEL, "term_verified": None, "eligibility_by_activity": {},
                "term_scope_by_activity": {}, "source_review_by_activity": {}, "schedule_by_activity": {}}
    program = profile.get("program", "standard")
    for item in projections:
        if item["activity"] is None:
            continue
        aid, side = item["activity"]["activity_id"], item["sidecar"]
        evidence["eligibility_by_activity"][aid] = eligibility(side["audience"], profile)
        semester = (side["semester_by_program"] or {}).get(program)
        evidence["term_scope_by_activity"][aid] = (
            "NEEDS_REVIEW" if semester in (None, "insufficient_data") else
            "IN_SCOPE" if semester == term_id else "OUT_OF_SCOPE")
        evidence["source_review_by_activity"][aid] = True if side["status"] == "valid" else None
        if item["schedule"]:
            evidence["schedule_by_activity"][aid] = item["schedule"]
    return evidence
