"""Trusted activity data and SP2 scoring for the demo account's confirmed plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from typing import Any

from api.lead_contract import canonical_url
from api.term_clock import TermClock, as_of_of
from sp2.drl_engine import DRLEngineError, evaluate_rule_conditions
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter


def timestamp(value: str | None) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def completion_clock(term_id: str, clock: TermClock | None = None) -> datetime:
    return timestamp(os.environ.get("UNILIFE_COMPLETION_AS_OF")) or timestamp(clock.as_of if clock else as_of_of(term_id))


def _canonical_url(value: str | None) -> str | None:
    try:
        return canonical_url(value) if value else None
    except ValueError:
        return None


class CompletionCatalog:
    def __init__(self, scoring: dict, planner: dict, evidence: dict, metadata: dict):
        self.scoring = scoring
        self.planner = planner
        self.evidence = evidence
        self.metadata = metadata
        self.activities = {item["activity_id"]: item for item in scoring["activities"]}
        self.bindings = {item["activity_id"]: item for item in scoring["bindings"]}
        self.rules = {item["rule_id"]: item for item in scoring["ruleset"]["rules"]}
        self.sources = {
            activity_id: frozenset(
                url for source in [activity["source"], *metadata.get(activity_id, {}).get("sources", [])]
                if (url := _canonical_url(source.get("URL_post")))
            )
            for activity_id, activity in self.activities.items()
        }
        self.ids_by_url = {url: aid for aid, urls in self.sources.items() for url in urls}

    def entry_activity_id(self, entry: dict) -> str | None:
        activity_id = entry.get("activity_id")
        if activity_id in self.activities:
            return activity_id
        saved_source = entry.get("catalog_entry", {}).get("source", {})
        return self.ids_by_url.get(_canonical_url(saved_source.get("URL_post")))

    def eligibility(self, activity_id: str, now: datetime) -> dict:
        activity = self.activities[activity_id]
        meta = self.metadata.get(activity_id, {})
        requirements = meta.get("completion_requirements", [])
        requirement_types = {row.get("type") for row in requirements}
        quiz = "quiz" in requirement_types

        binding = self.bindings.get(activity_id, {})
        rule = self.rules.get(binding.get("rule_id"), {})
        if (
            not self.evidence["source_review_by_activity"].get(activity_id)
            or meta.get("status", "valid") != "valid"
            or meta.get("flags")
            or rule.get("status") != "verified"
        ):
            return {"status": "NEEDS_REVIEW"}

        end = self._completion_end(activity, meta)
        if end is None:
            return {"status": "MISSING_END"}
        thresholds = [_quiz_threshold(row) for row in requirements if row.get("type") == "quiz" and row.get("threshold") is not None]
        conditions = [_REQUIREMENT_LABELS[row["type"]] for row in requirements if row.get("type") in _REQUIREMENT_LABELS]
        if None in thresholds:
            conditions.append("đạt yêu cầu của bài quiz")
        thresholds = [value for value in thresholds if value is not None]
        # Completion is a student affirmation, not an upload or quiz verification service.
        question = "Bạn đã tham gia làm quiz" if quiz else "Bạn đã hoàn thành hoạt động này"
        if thresholds:
            question += " và đạt " + ", ".join(thresholds)
        if conditions:
            question += " và " + ", ".join(dict.fromkeys(conditions))
        details = activity.get("completion_requirements")
        if details in ("NOT_STATED", "Synthetic completion check.") or (details and details.startswith("[")):
            details = None
        return {
            "status": "READY" if now >= end else "NOT_DUE",
            "available_at": end.isoformat(),
            "question": question + " chưa?",
            "condition": details,
        }

    def _completion_end(self, activity: dict, meta: dict) -> datetime | None:
        defaults = meta.get("time_defaults", {})
        derived_end = meta.get("derived", {}).get("end", "")
        if activity["mode"] == "offline" and ("window_open" in defaults or "window_close" in defaults):
            return None
        schedule = self.evidence.get("schedule_by_activity", {}).get(activity["activity_id"], {})
        if schedule.get("type") == "FIXED":
            ends = [timestamp(block.get("end")) for block in schedule.get("fixed_blocks", [])]
            return max(ends) if ends and all(ends) else None
        if activity["mode"] == "offline":
            if derived_end.startswith("start_plus_duration:default_"):
                return None
            start, end = timestamp(activity.get("start")), timestamp(activity.get("end"))
            return end if start and end and start < end else None

        # A date stated by the source closes at the end of that date. A
        # suggested duration for doing the quiz does not establish its deadline.
        if derived_end.startswith("start_plus_duration:"):
            return None
        start, end = timestamp(activity.get("start")), timestamp(activity.get("end"))
        if start is None or end is None or end <= start:
            return None
        return end + timedelta(minutes=1) if defaults.get("window_close") == "date_only_2359" else end


_REQUIREMENT_LABELS = {
    "check_in": "điểm danh theo yêu cầu",
    "check_out": "điểm danh cuối buổi",
    "survey": "hoàn thành khảo sát",
    "full_attendance": "tham gia đầy đủ",
    "proof_upload": "hoàn thành yêu cầu minh chứng",
}


def _quiz_threshold(requirement: dict) -> str | None:
    threshold, unit = requirement["threshold"], requirement.get("unit")
    if not unit:
        return None
    if unit in {"percent", "%"}:
        return f"{threshold}%"
    denominator = re.fullmatch(r"of (\d+) questions", unit)
    if denominator:
        return f"{threshold}/{denominator[1]} câu"
    return f"{threshold} {unit}"


def completion_catalog(source: str, term_id: str | None = None) -> CompletionCatalog:
    if source == "real":
        from api.sp3_real import _load_base

        data = _load_base(term_id)
        # Use the same current operational snapshot as real-source planning.
        metadata = {
            record["post_id"]: {
                "completion_requirements": deepcopy(record["acceptance"]["accepted_record"].get("completion_requirements") or []),
                "time_defaults": deepcopy(record["normalized"].get("time_defaults") or {}),
                "derived": {"end": record.get("sp3_derived", {}).get("start_end", "")},
            }
            for record in data["ready"]
        }
        return CompletionCatalog(data["scoring"], data["planner"], data["evidence"], metadata)

    return _synthetic_completion_catalog()


def _number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _clean(value: float | int) -> float | int:
    return int(value) if float(value).is_integer() else value


def _apply_category_offsets(result: dict, config: dict, record: dict, offsets: dict[str, float]) -> dict:
    """Add trusted per-category offsets to an SP2 result outside the locked SP2 engine.

    Offsets cover points already on the scoreboard whose rule facts are unavailable. Each offset is added to the
    category's raw (pre-cap) score, then the category cap and the total clamp are re-applied exactly as
    sp2.drl_engine.evaluate_rule_conditions does: score = min(raw, cap) when raw > 0.
    """
    if not offsets:
        return result
    scoring = config["scoring_model"]
    caps = {
        str(item.get("category_id")): item.get("max_score")
        for item in scoring.get("category_caps", [])
        if isinstance(item, dict)
    }
    rows = [dict(row) for row in result["category_scores"]]
    by_id = {row["category_id"]: row for row in rows}
    for category, offset in offsets.items():
        if category not in caps or not _number(offset):
            raise DRLEngineError("category score offsets must be numeric and name a configured category")
        row = by_id.get(category)
        if row is None:
            row = {"category_id": category, "raw_score": 0, "cap": caps[category], "score": 0}
            rows.append(row)
            by_id[category] = row
        raw = row["raw_score"] + offset
        cap = caps[category]
        row["raw_score"] = _clean(raw)
        row["score"] = _clean(min(raw, cap) if _number(cap) and raw > 0 else raw)

    rule_points_total = sum(row["score"] for row in rows)
    raw_total = record.get("current_confirmed_score", 0) + record.get("eligible_extra_points", 0) + rule_points_total
    maximum = scoring.get("max_total_score", scoring.get("semester_score_max", 100))
    minimum = scoring.get("semester_score_min", 0)
    return {
        **result,
        "category_scores": rows,
        "rule_points_total": _clean(rule_points_total),
        "raw_total_before_cap": _clean(raw_total),
        "final_score": _clean(min(maximum, max(minimum, raw_total))),
    }


def _engine_with_offsets(offsets: dict[str, float]):
    """SP2 engine callable for ProjectedScorer: unchanged SP2 evaluation, then the account offsets."""

    def engine(config: dict, record: dict) -> dict:
        result = evaluate_rule_conditions(config, record, apply_default_awards=True)
        return _apply_category_offsets(result, config, record, offsets)

    return engine


@lru_cache(maxsize=1)
def _synthetic_completion_catalog() -> CompletionCatalog:

    from api.sp3_service import DATA, DEMO, _json

    fixture = _json(DEMO)
    scoring = {**fixture["scoring_data"], "ruleset": _json(DATA / "drl_rules.json")}
    quiz_metadata = {
        "QUIZ-M": {"completion_requirements": [{"type": "quiz", "threshold": 8, "unit": "of 10 questions"}]},
        "QUIZ-L": {"completion_requirements": [{"type": "quiz", "threshold": None}]},
    }
    return CompletionCatalog(scoring, fixture["planner"], fixture["evidence"], quiz_metadata)


class AccountPlanScoring:
    """Apply the same trusted facts and scoreboard to replanning and completion."""

    def __init__(self, catalog: CompletionCatalog, student_id: str, current: dict, entries: list[dict], term: str,
                 clock: TermClock | None = None):
        self.catalog = catalog
        self.student_id = student_id
        self.clock = clock
        base = deepcopy(catalog.planner["baseline"])
        caps = base["category_caps"]
        self.entries = {
            activity_id: entry for entry in reversed(entries)
            if entry.get("term_id") == term  # an entry without a term belongs to no term
            and (entry.get("completion_status") == "COMPLETED" or entry.get("confirmed_added", 0) > 0)
            and (activity_id := catalog.entry_activity_id(entry))
        }
        self.facts = {binding["field"]: 0 for binding in catalog.bindings.values() if binding["operation"] == "INCREMENT"}
        for activity_id, entry in self.entries.items():
            binding = catalog.bindings.get(activity_id)
            rule_id = entry.get("catalog_entry", {}).get("rule_id")
            if not binding or rule_id != binding["rule_id"]:
                continue
            field, value = binding["field"], binding["value"]
            self.facts[field] = self.facts.get(field, 0) + value if binding["operation"] == "INCREMENT" else value

        config = catalog.scoring["ruleset"]
        scored = evaluate_rule_conditions(config, self.facts, apply_default_awards=True)
        raw = {row["category_id"]: row["raw_score"] for row in scored["category_scores"]}
        scores = {category: current.get(category, 0) for category in caps}
        offsets = {
            category: value - (min(caps[category], raw_score) if value == caps[category] else raw_score)
            for category, value in scores.items()
            if (raw_score := raw.get(category, 0)) != value
        }
        self.engine = _engine_with_offsets(offsets)
        self.baseline = {
            **base, "category_scores": scores,
            "total_score": min(base["max_total_score"], sum(scores.values())),
            "included_activity_ids": sorted(self.entries),
        }
        baseline_data = json.dumps([self.baseline, self.facts], sort_keys=True).encode()
        self.baseline_ref = "account-" + hashlib.sha256(baseline_data).hexdigest()[:16]

    def apply_progress(self, candidates: list[dict]) -> None:
        for row in candidates:
            if row["activity"]["activity_id"] in self.entries:
                row["participation"]["progress"] = "COMPLETED"

    def configure(self, context: dict, options: dict):
        context.update(student_id=self.student_id, baseline_ref=self.baseline_ref)
        options["baseline"] = deepcopy(self.baseline)
        scoring = {
            **self.catalog.scoring,
            "baselines": [{"student_id": self.student_id, "baseline_ref": self.baseline_ref, "facts": self.facts}],
        }
        return ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring), engine=self.engine)).score_plan

    def score(self, context: dict, activity_ids: list[str]) -> dict[str, Any]:
        context = dict(context)
        scorer = self.configure(context, {})
        return scorer({
            "contract_version": "sp3-planner/0.2",
            "request_id": "confirmed-plan-progress",
            "context": context,
            "baseline": self.baseline,
            "selected_activity_ids": sorted(activity_ids),
            "attribution_order": activity_ids,
        })
