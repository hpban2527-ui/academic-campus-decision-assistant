"""Test doubles and synthetic input builders for SP3 planner tests.

These are NOT SP2 scorers. StaticTableScorer replays a fixed table and fails
on any unlisted set (contract section 9). CappedAdditiveScorer is a small,
independent model used only for property tests.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import math
from pathlib import Path
import sys
from typing import Any

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

ECHO_FIELDS = ("contract_version", "request_id", "context", "selected_activity_ids")
DEFAULT_CONTEXT = {
    "student_id": "synthetic-student",
    "term_id": "SYNTHETIC-DEMO",
    "window_start": "2026-11-01T00:00:00+07:00",
    "window_end": "2026-11-08T00:00:00+07:00",
    "as_of": "2026-11-01T08:00:00+07:00",
    "timezone": "Asia/Ho_Chi_Minh",
    "baseline_ref": "synthetic-baseline",
    "dataset_version": "synthetic-dataset",
    "ruleset_version": "synthetic-rules",
    "calendar_version": "synthetic-calendar",
}


def envelope(request: dict[str, Any], *, status: str = "OK", result: Any = None, errors: list | None = None) -> dict[str, Any]:
    return {
        **{key: deepcopy(request[key]) for key in ECHO_FIELDS},
        "evaluation_status": status,
        "result": deepcopy(result),
        "errors": deepcopy(errors or []),
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
    }


class StaticTableScorer:
    """Replays a table keyed by the sorted selected-ID tuple; anything else is ERROR."""

    def __init__(self, entries: list[dict[str, Any]]) -> None:
        self.table = {tuple(entry["selected_activity_ids"]): deepcopy(entry) for entry in entries}
        self.calls: list[tuple[str, ...]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        key = tuple(request["selected_activity_ids"])
        self.calls.append(key)
        entry = self.table.get(key)
        if entry is None:
            return envelope(request, status="ERROR", errors=[{
                "code": "UNSPECIFIED_SET", "message": "The static table has no entry for this set.", "activity_id": None,
            }])
        status = entry.get("evaluation_status", "OK")
        if status != "OK":
            return envelope(request, status=status, errors=entry["errors"])
        return envelope(request, result=entry["result"])


def static_result(before: dict[str, float], after: dict[str, float], max_total: float, baseline_total: float, contributions: list[tuple[str, str, float]]) -> dict[str, Any]:
    """Spell out a full section-5 result for a hand-written table row."""
    total_after = min(math.fsum(after.values()), max_total)
    return {
        "category_after": dict(after),
        "category_gain": {c: after[c] - before[c] for c in before},
        "total_after": total_after,
        "total_gain": total_after - baseline_total,
        "contributions": [
            {"activity_id": a, "category_id": c, "rule_id": f"MOCK_R_{a}", "projected_added": p}
            for a, c, p in contributions
        ],
    }


class CappedAdditiveScorer:
    """Independent toy model: per-activity points into one category with caps.

    Contributions are allocated in (start, activity_id) order; each activity
    adds ``min(points, remaining category cap)``. The total is capped by
    max_total_score. ``activities`` maps ID -> (category, points, start).
    """

    def __init__(self, activities: dict[str, tuple[str, float, str]]) -> None:
        self.activities = dict(activities)
        self.call_count = 0

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.call_count += 1
        baseline = request["baseline"]
        before = baseline["category_scores"]
        caps = baseline["category_caps"]
        after = dict(before)
        order = sorted(
            request["selected_activity_ids"],
            key=lambda a: (datetime.fromisoformat(self.activities[a][2]), a),
        )
        contributions = []
        for activity_id in order:
            category, points, _ = self.activities[activity_id]
            added = max(0, min(points, caps[category] - after[category]))
            after[category] += added
            contributions.append({
                "activity_id": activity_id, "category_id": category,
                "rule_id": f"MOCK_{activity_id}", "projected_added": added,
            })
        total_after = min(math.fsum(after.values()), baseline["max_total_score"])
        return envelope(request, result={
            "category_after": after,
            "category_gain": {c: after[c] - before[c] for c in before},
            "total_after": total_after,
            "total_gain": total_after - baseline["total_score"],
            "contributions": contributions,
        })


def make_activity(activity_id: str, start: str | None, end: str | None, *, domain: str | None = "academic", mode: str = "online", deadline: str | None = "2026-11-01T18:00:00+07:00") -> dict[str, Any]:
    return {
        "activity_id": activity_id,
        "source": {
            "publisher": "Synthetic fixture",
            "platform": "fixture",
            "URL_post": f"https://example.invalid/activity/{activity_id}",
            "URL_registration": None,
        },
        "title": f"Synthetic activity {activity_id}",
        "domain": domain,
        "start": start,
        "end": end,
        "registration_deadline": deadline,
        "mode": mode,
        "location": None,
        "points": None,
        "mandatory": False,
        "audience": ["Synthetic students"],
        "fee": 0,
        "completion_requirements": "Synthetic completion requirement.",
    }


def make_candidate(activity: dict[str, Any], status: str = "FEASIBLE", reason_codes: list[str] | None = None, binding: str | None = "binding") -> dict[str, Any]:
    if status != "FEASIBLE" and reason_codes is None:
        reason_codes = ["MISSING_ELIGIBILITY"] if status == "NEEDS_REVIEW" else ["DEADLINE_PASSED"]
    return {
        "activity": activity,
        "score_binding_ref": None if binding is None else f"{binding}-{activity['activity_id']}",
        "feasibility": {"status": status, "reason_codes": list(reason_codes or [])},
    }


def make_planner_input(
    candidates: list[dict[str, Any]],
    *,
    scores: dict[str, float],
    caps: dict[str, float],
    max_total: float = 100,
    included: list[str] | None = None,
    category_targets: dict[str, float] | None = None,
    total_target: float | None = None,
    preferred_domains: list[str] | None = None,
    preferred_modes: list[str] | None = None,
    max_activities: int | None = None,
    max_duration_minutes: float | None = None,
    conflict_pairs: list[list[str]] | None = None,
    request_id: str = "synthetic-request",
) -> dict[str, Any]:
    return {
        "contract_version": "sp3-planner/0.1",
        "request_id": request_id,
        "context": dict(DEFAULT_CONTEXT),
        "baseline": {
            "category_scores": dict(scores),
            "category_caps": dict(caps),
            "total_score": min(math.fsum(scores.values()), max_total),
            "max_total_score": max_total,
            "included_activity_ids": list(included or []),
        },
        "goals": {"total_target": total_target, "category_targets": dict(category_targets or {})},
        "preferences": {"preferred_domains": list(preferred_domains or []), "preferred_modes": list(preferred_modes or [])},
        "limits": {"max_activities": max_activities, "max_duration_minutes": max_duration_minutes},
        "candidates": candidates,
        "conflict_pairs": [list(pair) for pair in (conflict_pairs or [])],
    }


def at(day: int, hour: int, minute: int = 0) -> str:
    """Timestamp on November ``day`` 2026 in the planning timezone."""
    return f"2026-11-{day:02d}T{hour:02d}:{minute:02d}:00+07:00"
