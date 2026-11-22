"""Trusted activity data and SP2 scoring for the demo account's confirmed plan."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache, partial
from typing import Any

from api.lead_contract import canonical_url
from sp2.drl_engine import evaluate_rule_conditions
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter


def timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.utcoffset() is not None else None


def completion_clock() -> datetime:
    return timestamp(os.environ.get("UNILIFE_COMPLETION_AS_OF")) or datetime.now().astimezone()


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
        mode = activity["mode"]
        if mode not in {"offline", "online"} or "proof_upload" in requirement_types:
            return {"status": "UNSUPPORTED"}
        quiz = "quiz" in requirement_types
        if mode == "online" and not quiz:
            return {"status": "NEEDS_REVIEW" if not requirements else "UNSUPPORTED"}

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
        if None in thresholds:
            return {"status": "NEEDS_REVIEW"}
        conditions = [_REQUIREMENT_LABELS[row["type"]] for row in requirements if row.get("type") in _REQUIREMENT_LABELS]
        if mode == "offline":
            question = "Bạn đã tham gia hoạt động này"
        else:
            question = "Bạn đã tham gia làm quiz"
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
        if activity["mode"] == "offline":
            if "window_open" in defaults or "window_close" in defaults:
                return None
            schedule = self.evidence.get("schedule_by_activity", {}).get(activity["activity_id"], {})
            if schedule.get("type") == "FIXED":
                return timestamp(schedule["fixed_blocks"][0]["end"])
            if derived_end.startswith("start_plus_duration:default_"):
                return None
            start, end = timestamp(activity.get("start")), timestamp(activity.get("end"))
            return end if start and end and start.date() == end.date() and start < end else None

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


def completion_catalog(source: str) -> CompletionCatalog:
    if source == "real":
        from api.sp3_real import _load_base

        data = _load_base()
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

    def __init__(self, catalog: CompletionCatalog, student_id: str, current: dict, entries: list[dict], term: str):
        self.catalog = catalog
        self.student_id = student_id
        base = deepcopy(catalog.planner["baseline"])
        caps = base["category_caps"]
        self.entries = {
            activity_id: entry for entry in reversed(entries)
            if (not entry.get("term_id") or entry["term_id"] == term)
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
        self.engine = partial(evaluate_rule_conditions, apply_default_awards=True, category_score_offsets=offsets)
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
