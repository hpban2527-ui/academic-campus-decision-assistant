"""Reviewed SP1 activity -> SP2 category scoring.

All results in this adapter are demonstrations against a selected historical
rule set. Review decisions and participation proof must come from trusted
server-side records, never from a request checkbox or keyword classifier.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any, Mapping
from jsonschema import Draft202012Validator, FormatChecker

from sp2 import evaluate_progress


class PipelineError(ValueError):
    pass


def fingerprint(record: Mapping[str, Any]) -> str:
    payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _verified_stamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.tzinfo is not None and dt.utcoffset() is not None
    except ValueError:
        return False


def _score_map(progress: dict) -> dict[str, float]:
    return {x["code"]: x["score"] for x in progress["confirmed_by_criterion"]}


def evaluate_reviewed_activity(
    *,
    record: dict,
    metadata: dict,
    approval: dict,
    participation: dict | None,
    baseline: dict,
    student_profile: dict,
    rules_config: dict,
    schema: dict,
) -> dict:
    """Read-only computation from trusted reviewed records.

    A reviewer-created approval must be stored independently from the
    extractor. Baseline and participation must be server-side fixtures or
    trusted internal records; a public request must not supply these.
    """
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(record)
    event_id = record["activity_id"]
    if metadata.get("is_duplicate") or metadata.get("status") != "valid":
        return {"status": "NEEDS_REVIEW", "reason": "Extraction incomplete or duplicated", "official_award_verified": False}
    if metadata.get("flags"):
        return {"status": "NEEDS_REVIEW", "reason": "Extractor review flags present", "flags": metadata["flags"], "official_award_verified": False}
    if not isinstance(approval, Mapping) or approval.get("decision") != "APPROVED":
        return {"status": "NEEDS_REVIEW", "reason": "Activity has no reviewer approval", "official_award_verified": False}
    if approval.get("activity_id") != event_id or approval.get("fingerprint") != fingerprint(record):
        return {"status": "NEEDS_REVIEW", "reason": "Reviewer approval does not match this activity content", "official_award_verified": False}
    if not approval.get("reviewer_id") or not _verified_stamp(approval.get("reviewed_at")):
        return {"status": "NEEDS_REVIEW", "reason": "Approval lacks reviewer identity/time", "official_award_verified": False}
    if approval.get("source_url") != record["source"]["URL_post"]:
        return {"status": "NEEDS_REVIEW", "reason": "Reviewer source URL mismatch", "official_award_verified": False}
    regulation = rules_config.get("regulation", {})
    if approval.get("regulation_id") != regulation.get("regulation_id"):
        return {"status": "NEEDS_REVIEW", "reason": "Regulation version mismatch", "official_award_verified": False}
    rule = next((x for x in rules_config.get("rules", []) if x.get("rule_id") == approval.get("rule_id")), None)
    if not rule or rule.get("status") != "verified":
        return {"status": "NEEDS_REVIEW", "reason": "Rule is absent or pending regulation verification", "official_award_verified": False}
    if type(rule.get("points")) not in (int, float) or rule["points"] <= 0:
        raise PipelineError("Activity adapter requires an explicit positive-point rule")
    if record.get("points") is not None and record["points"] != rule["points"]:
        return {"status": "NEEDS_REVIEW", "reason": "Announced and regulation points disagree", "official_award_verified": False}
    if not isinstance(baseline, Mapping) or baseline.get("student_id") != student_profile.get("student_id"):
        return {"status": "NEEDS_BASELINE", "reason": "No student-specific category baseline", "official_award_verified": False}
    if baseline.get("regulation_id") != regulation.get("regulation_id"):
        return {"status": "NEEDS_BASELINE", "reason": "Baseline belongs to a different regulation", "official_award_verified": False}
    existing = baseline.get("category_scores")
    included = baseline.get("included_activity_ids")
    if not isinstance(existing, Mapping) or not isinstance(included, list):
        return {"status": "NEEDS_BASELINE", "reason": "Missing category allocation or counted-activity ledger", "official_award_verified": False}
    if event_id in included:
        return {"status": "ALREADY_COUNTED", "reason": "Activity already included in baseline", "official_award_verified": False, "confirmed_added": 0, "projected_added": 0}
    caps = {x["category_id"]: x["max_score"] for x in rules_config["scoring_model"]["category_caps"]}
    if rule["category_id"] not in caps:
        raise PipelineError("Rule category is not in the regulation")
    for cat, current in existing.items():
        if cat not in caps or type(current) not in (int, float) or current < 0 or current > caps[cat]:
            return {"status": "NEEDS_BASELINE", "reason": "Invalid category baseline", "official_award_verified": False}

    rule_set = {
        "rule_set_id": regulation["regulation_id"],
        "version": regulation.get("effective_from"),
        "verified": True,  # Verifies selected demo rule metadata, not official current award.
        "scope": {"universities": ["HCMUS"]},
        "criteria": [
            {"code": c["category_id"], "max_score": c["max_score"]}
            for c in rules_config["scoring_model"]["category_caps"]
        ],
        "topic_requirements": [],
        "min_total_score": rules_config["scoring_model"].get("semester_score_min", 0),
        "max_total_score": rules_config["scoring_model"].get("max_total_score", 100),
    }
    base_records = [
        {"record_id": "baseline-" + cat, "status": "CONFIRMED", "evidence_status": "VERIFIED",
         "criterion_code": cat, "points": score}
        for cat, score in existing.items()
    ]
    base_progress = evaluate_progress(rule_set, student_profile, base_records, require_verified_rules=True)
    event_record = {
        "record_id": "event-" + event_id, "activity_id": event_id,
        "status": "CONFIRMED", "evidence_status": "VERIFIED",
        "criterion_code": rule["category_id"], "points": rule["points"],
    }
    hypothetical = evaluate_progress(rule_set, student_profile, base_records + [event_record], require_verified_rules=True)
    if base_progress["rule_resolution"] != "APPLICABLE" or hypothetical["rule_resolution"] != "APPLICABLE":
        return {"status": "NEEDS_REVIEW", "reason": "Student scope is not applicable", "official_award_verified": False}
    cat = rule["category_id"]
    before = _score_map(base_progress).get(cat, 0)
    after = _score_map(hypothetical).get(cat, before)
    delta = after - before
    confirmed_demo = (
        isinstance(participation, Mapping)
        and participation.get("activity_id") == event_id
        and participation.get("student_id") == student_profile.get("student_id")
        and participation.get("status") == "CONFIRMED"
        and participation.get("evidence_status") == "VERIFIED"
        and participation.get("verifier_id")
        and _verified_stamp(participation.get("verified_at"))
        and participation.get("evidence_ref")
    )
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "status": "DEMO_CONFIRMED" if confirmed_demo else "PROJECTED",
        "activity_id": event_id,
        "student_id": student_profile["student_id"],
        "rule_id": rule["rule_id"],
        "criterion_id": rule["criterion_id"],
        "category_id": cat,
        "category_cap": caps[cat],
        "announced_points": record["points"],
        "rule_points": rule["points"],
        "category_before": before,
        "category_after": after if confirmed_demo else before,
        "hypothetical_category_after": after,
        "remaining_after_hypothetical": max(0, caps[cat] - after),
        "projected_added": 0 if confirmed_demo else delta,
        "confirmed_added": delta if confirmed_demo else 0,
        "confirmed_total_before": base_progress["confirmed_total"],
        "confirmed_total_after": hypothetical["confirmed_total"] if confirmed_demo else base_progress["confirmed_total"],
        "regulation_source": regulation.get("source"),
        "rule_source": rule.get("source"),
        "approval_reviewer": approval["reviewer_id"],
        "notes": "Demo calculation against historical QD1028 rules; not an official university DRL result.",
    }
