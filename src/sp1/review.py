"""Human review decisions for SP1/SP2 records (ADR-0002 D18). Deterministic; no model.

An admin records decisions in a CSV (data/review/decisions.csv). A decision can set stated fields, the
activity type, the scoring rule, or approve a record as it is. Decisions are applied on top of the automatic
result every time the store is built, so they survive re-runs. A decision is tied to the announcement text
by a fingerprint: if the text changes, the decision is ignored and the record returns to the queue.
Reviewed records carry LABEL and the reviewer string verbatim: the label does not claim the reviewer was a
person, so an AI-assisted review stays distinguishable in reports and in the store.
"""

from __future__ import annotations

import csv
import hashlib
import re
from datetime import datetime
from pathlib import Path

LABEL = "reviewed"
SET_FIELDS = ("post_type", "title", "mode", "location", "window_open", "window_close", "registration_deadline")
DECISION_COLUMNS = ("post_id", "text_sha256", "reviewer", "reviewed_at", *(f"set_{f}" for f in SET_FIELDS),
                    "set_activity_type", "set_rule_id", "approve", "note")
POST_TYPES = {"activity", "info_only", "insufficient"}
MODES = {"online", "offline", "hybrid"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}$")
_YES = {"yes", "y", "true", "1", "x", "có", "co"}
# Flags a reviewer can clear by approving the record or by setting the field they concern.
_REVIEWABLE = ("needs_review:", "invalid_value:", "injection_suspected", "candidates_truncated:", "end_before_start")
_FIELD_FLAGS = {"window_open": ("end_before_start",), "window_close": ("end_before_start",)}


def text_fingerprint(raw_text: str) -> str:
    """SHA-256 of the announcement text with line endings normalised."""
    return hashlib.sha256(raw_text.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")).hexdigest()


def _moment(value: str) -> str:
    """'2026-11-06' or '2026-11-06 13:00' -> layer-A format (date, or local time with +07:00)."""
    value = value.strip()
    if _DATE.match(value):
        datetime.strptime(value, "%Y-%m-%d")
        return value
    if _DATETIME.match(value):
        value = value.replace(" ", "T")
        datetime.strptime(value, "%Y-%m-%dT%H:%M")
        return value + "+07:00"
    raise ValueError("use YYYY-MM-DD or YYYY-MM-DD HH:MM")


def parse_decision(row: dict, activity_types: set[str], rule_ids: set[str]) -> dict | None:
    """Validate one CSV row. Returns None for a row without any decision; raises ValueError when invalid."""
    get = lambda key: (row.get(key) or "").strip()
    sets = {field: get(f"set_{field}") for field in SET_FIELDS if get(f"set_{field}")}
    activity_type, rule_id = get("set_activity_type") or None, get("set_rule_id") or None
    approve = get("approve").lower() in _YES
    if not (sets or activity_type or rule_id or approve):
        return None
    for key in ("post_id", "text_sha256", "reviewer", "reviewed_at"):
        if not get(key):
            raise ValueError(f"{key} is required")
    datetime.strptime(get("reviewed_at")[:10], "%Y-%m-%d")
    if "post_type" in sets and sets["post_type"] not in POST_TYPES:
        raise ValueError(f"set_post_type must be one of {sorted(POST_TYPES)}")
    if "mode" in sets and sets["mode"] not in MODES:
        raise ValueError(f"set_mode must be one of {sorted(MODES)}")
    for field in ("window_open", "window_close", "registration_deadline"):
        if field in sets:
            try:
                sets[field] = _moment(sets[field])
            except ValueError as exc:
                raise ValueError(f"set_{field}: {exc}") from exc
    if activity_type and activity_type not in activity_types:
        raise ValueError("set_activity_type is not a known activity type")
    if rule_id and rule_id not in rule_ids:
        raise ValueError("set_rule_id is not a verified rule")
    return {"post_id": get("post_id"), "text_sha256": get("text_sha256"), "reviewer": get("reviewer"),
            "reviewed_at": get("reviewed_at"), "set": sets, "activity_type": activity_type, "rule_id": rule_id,
            "approve": approve, "note": get("note") or None}


def load_decisions(path: Path, activity_types: set[str], rule_ids: set[str]) -> tuple[dict, list[dict]]:
    """Read the decisions CSV. Returns ({post_id: decision}, problems). A missing file means no decisions."""
    decisions, problems = {}, []
    if not Path(path).exists():
        return decisions, problems
    with open(path, encoding="utf-8-sig", newline="") as handle:
        for number, row in enumerate(csv.DictReader(handle), 2):
            try:
                decision = parse_decision(row, activity_types, rule_ids)
            except ValueError as exc:
                problems.append({"line": number, "post_id": (row.get("post_id") or "").strip(), "problem": str(exc)})
                continue
            if decision is None:
                continue
            if decision["post_id"] in decisions:
                problems.append({"line": number, "post_id": decision["post_id"], "problem": "duplicate decision"})
                continue
            decisions[decision["post_id"]] = decision
    return decisions, problems


def apply_decision(layer_a: dict, decision: dict | None, raw_text: str) -> dict | None:
    """Apply a decision to a layer-A record in place. Returns the review note for the store, or None.

    A decision whose fingerprint does not match the current text is not applied ({"stale": True}).
    """
    if decision is None:
        return None
    if decision["text_sha256"] != text_fingerprint(raw_text):
        return {"stale": True, "reviewer": decision["reviewer"], "reviewed_at": decision["reviewed_at"]}
    record = layer_a["record"]
    for field, value in decision["set"].items():
        record[field] = value
        cleared = (f"needs_review:{field}", f"invalid_value:{field}", *_FIELD_FLAGS.get(field, ()))
        layer_a["flags"] = [flag for flag in layer_a["flags"] if flag not in cleared]
        layer_a["year_inferred"] = [key for key in layer_a["year_inferred"] if key != field]
    if record.get("mode") == "online" and "mode" in decision["set"]:
        record["location"] = None
    if decision["approve"]:
        layer_a["flags"] = [flag for flag in layer_a["flags"] if not flag.startswith(_REVIEWABLE)]
    return {"label": LABEL, "stale": False, "reviewer": decision["reviewer"], "reviewed_at": decision["reviewed_at"],
            "fields_set": sorted(decision["set"]), "activity_type": decision["activity_type"],
            "rule_id": decision["rule_id"], "approved": decision["approve"], "note": decision["note"]}
