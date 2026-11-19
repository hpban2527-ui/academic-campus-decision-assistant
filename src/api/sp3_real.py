"""SP3 on the real SP1 store (HK1 2026-2027) with a synthetic student.

The default web demo keeps its synthetic fixture.  This module backs the
"real store" switch: it plans over the activities handed over in
data/handover/ (built by scripts/build_handover.py and build_bindings.py).

What is real: the activities (from scraped announcements), their score
bindings (rule-based or reviewed by hand) and the encoded regulation.
What is synthetic: the student, their baseline facts and free time.
Nothing here is an official DRL award.
"""

from __future__ import annotations

import csv
import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from personalization.models import PlanningStrategy, StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import load_activity_features
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter
from sp3.availability import resolve_availability

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
HANDOVER = DATA / "handover"
FIXTURE = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"

DATA_SOURCE = "SP1-STORE-V2"
TERM = {"id": "HK1_2026_2027", "start": "2026-08-29", "end": "2026-11-15"}
# Demo clock: the planner looks at the rest of HK1 from this date.
AS_OF = "2026-10-01T08:00:00+07:00"
WINDOW_START = "2026-10-01T00:00:00+07:00"
WINDOW_END = "2026-11-16T00:00:00+07:00"
# Synthetic free time: every day 07:00-21:00, minus the busy slots the student ticks.
DAY_START_HOUR, DAY_END_HOUR = 7, 21
STUDENT_ID = "synthetic-student-k24"
BASELINE_REF = "synthetic-baseline-k24"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _load_base() -> dict:
    activities = _json(HANDOVER / "activities_sp3.json")
    sidecar = _json(HANDOVER / "sidecar.json")
    bindings = _json(HANDOVER / "bindings.json")
    rules = _json(DATA / "drl_rules.json")
    fixture = _json(FIXTURE)
    facts = deepcopy(fixture["scoring_data"]["baselines"][0]["facts"])
    for binding in bindings["bindings"]:
        if binding["operation"] == "INCREMENT":
            facts.setdefault(binding["field"], 0)
    scoring = {
        "label": "real-activities-synthetic-student",
        "dataset_version": "sp1-store-v2",
        "ruleset_version": fixture["scoring_data"]["ruleset_version"],
        "ruleset": rules,
        "baselines": [{"student_id": STUDENT_ID, "baseline_ref": BASELINE_REF, "facts": facts}],
        "activities": activities,
        "bindings": bindings["bindings"],
    }
    return {
        "activities": activities,
        "sidecar": sidecar,
        "bindings": bindings,
        "binding_by_id": {b["activity_id"]: b for b in bindings["bindings"]},
        "scoring": scoring,
        "planner": deepcopy(fixture["planner"]),
        "evidence": {k: v for k, v in sidecar["demo_evidence"].items() if k != "label"},
    }


def _features():
    return load_activity_features(HANDOVER / "activity_features_sp1.json")


def _queue_reasons() -> dict[str, list[str]]:
    path = DATA / "review" / "queue.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["post_id"]: [r.strip() for r in row["reasons"].split(";") if r.strip()]
                for row in csv.DictReader(handle)}


def _score_callback(data: dict):
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(deepcopy(data["scoring"])))).score_plan


def real_catalog() -> dict:
    """Handed-over activities with their binding and review state; blocked posts as drafts."""
    data = _load_base()
    queue = _queue_reasons()
    side = data["sidecar"]["activities"]
    rows = []
    for activity in data["activities"]:
        aid = activity["activity_id"]
        binding = data["binding_by_id"].get(aid)
        meta = side.get(aid, {})
        reasons = queue.get(aid, [])
        how = "reviewed" if binding and binding["binding_ref"].startswith("reviewed-") else "auto"
        notes = (f"Rule {binding['rule_id']} ({how})" if binding else "No score rule bound")
        if reasons:
            notes += " | queue: " + ", ".join(reasons)
        rows.append({
            "activity": activity,
            "data_qa": {"status": "reviewed" if meta.get("review") else "auto_checked",
                        "semester": TERM["id"], "notes": notes},
            "publication_status": "PLANNABLE" if binding else "REVIEW_REQUIRED",
            "score_binding_verified": False,
            "score_binding": ({"rule_id": binding["rule_id"], "binding_ref": binding["binding_ref"]}
                              if binding else None),
            "activity_type": meta.get("activity_type"),
            "review_reasons": reasons,
            "live_revision": None,      # kept for response compatibility; live ingestion was removed
        })
    store = {r["activity"]["source"]["post_id"]: r for r in _json(DATA / "activity_store_v2.json")["records"]}
    drafts = []
    for blocked in _json(HANDOVER / "blocked.json"):
        record = store.get(blocked["post_id"], {}).get("activity", {})
        drafts.append({
            "activity": {"activity_id": blocked["post_id"], "title": record.get("title")},
            "review_flags": blocked["reasons"],
            "publication_status": "NOT_HANDED_OVER",
            "score_binding_verified": False,
        })
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": DATA_SOURCE,
        "live_published": {},       # kept for response compatibility; live ingestion was removed
        "term": TERM,
        "source_dataset": {"path": "data/raw/source.json", "total_posts": len(store),
                           "status": "SP1_V2_STORE", "handed_over": len(rows),
                           "bound": sum(1 for r in rows if r["score_binding"])},
        "activity_count": len(rows),
        "unstructured_new_posts": len(drafts),
        "new_post_drafts": drafts,
        "new_post_errors": [],
        "activities": rows,
        "note": "Real announcements; score bindings are rule-based or reviewed by hand. Student is synthetic.",
    }


def _free_time(busy: list[dict[str, str]]) -> list[dict[str, str]]:
    day = datetime.fromisoformat(WINDOW_START)
    end = datetime.fromisoformat(WINDOW_END)
    cover = sorted((datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"])) for b in busy)
    out = []
    while day < end:
        cursor, stop = day + timedelta(hours=DAY_START_HOUR), day + timedelta(hours=DAY_END_HOUR)
        for s, e in cover:
            if e <= cursor or s >= stop:
                continue
            if s > cursor:
                out.append((cursor, s))
            cursor = max(cursor, e)
        if cursor < stop:
            out.append((cursor, stop))
        day += timedelta(days=1)
    return [{"start": s.isoformat(), "end": e.isoformat()} for s, e in out]


def _subtract_busy(available: list[dict[str, str]], busy: list[dict[str, str]]) -> list[dict[str, str]]:
    remaining = [(datetime.fromisoformat(item["start"]), datetime.fromisoformat(item["end"])) for item in available]
    for blocked in busy:
        start, end = datetime.fromisoformat(blocked["start"]), datetime.fromisoformat(blocked["end"])
        updated = []
        for free_start, free_end in remaining:
            if end <= free_start or start >= free_end:
                updated.append((free_start, free_end))
                continue
            if free_start < start:
                updated.append((free_start, start))
            if end < free_end:
                updated.append((end, free_end))
        remaining = updated
    return [{"start": start.isoformat(), "end": end.isoformat()} for start, end in remaining]


def _previous(plan: dict | None) -> dict | None:
    if plan is None:
        return None
    return {
        "plan_version": plan["plan_version"],
        "based_on": deepcopy(plan["based_on"]),
        "selected_activities": [{"activity_id": a["activity_id"], "scheduled_blocks": deepcopy(a["scheduled_blocks"])}
                                for a in plan["selected_activities"]],
    }


def _step(name: str, target_total: int, busy: list[dict[str, str]], previous: dict | None,
          preference: StudentPreference | None, availability_request: dict | None = None) -> dict:
    data = _load_base()
    resolved_availability = None
    if (
        isinstance(availability_request, dict)
        and "available_intervals" in availability_request
        and "calendar_version" in availability_request
        and "weekly_blocks" not in availability_request
    ):
        resolved_availability = deepcopy(availability_request)
        free = _subtract_busy(resolved_availability["available_intervals"], busy)
        calendar_version = resolved_availability["calendar_version"]
    elif availability_request is not None:
        normalized_request = deepcopy(availability_request) if isinstance(availability_request, dict) else availability_request
        if (
            isinstance(normalized_request, dict)
            and normalized_request.get("apply_scope") == "SEMESTER_WEEKLY"
            and isinstance(normalized_request.get("effective_from"), str)
            and normalized_request.get("effective_from") == "2026-11-09"
        ):
            normalized_request["effective_from"] = WINDOW_START[:10]
        resolved_availability = resolve_availability(
            normalized_request, window_start=WINDOW_START, window_end=WINDOW_END
        )
        free = _subtract_busy(resolved_availability["available_intervals"], busy)
        calendar_version = resolved_availability["calendar_version"]
    else:
        free = _free_time(busy)
        calendar_version = f"synthetic-free-{len(busy)}-busy"
    context = {
        "student_id": STUDENT_ID, "term_id": TERM["id"], "window_start": WINDOW_START, "window_end": WINDOW_END,
        "as_of": AS_OF, "timezone": "Asia/Ho_Chi_Minh", "baseline_ref": BASELINE_REF,
        "dataset_version": "sp1-store-v2", "ruleset_version": data["scoring"]["ruleset_version"],
        "calendar_version": calendar_version,
    }
    request = {
        "contract_version": "sp3-planner/0.2", "request_id": "real-" + name, "context": context,
        "activities": [{"activity": deepcopy(a),
                        "score_binding_ref": (data["binding_by_id"].get(a["activity_id"]) or {}).get("binding_ref"),
                        "participation": {"registration": "NOT_REGISTERED", "progress": "NOT_STARTED"}}
                       for a in data["activities"]],
        "available_intervals": free,
    }
    feasibility = assess_feasibility(request, evidence=FeasibilityEvidence(**deepcopy(data["evidence"])))
    options = deepcopy(data["planner"])
    options["goals"] = {"total_target": target_total, "category_targets": {}}
    options["preferences"] = {"preferred_domains": [], "preferred_modes": []}
    planner_input = {
        "contract_version": feasibility["contract_version"], "request_id": "real-" + name,
        "context": deepcopy(feasibility["context"]), **options,
        "candidates": deepcopy(feasibility["candidates"]), "conflict_pairs": deepcopy(feasibility["conflict_pairs"]),
        "available_intervals": deepcopy(free), "previous_plan": _previous(previous), "keep_requests": [],
    }
    extra, engine, hard_excluded = {}, None, []
    if preference is not None:
        features = _features()
        personalized = prepare_personalized_planner_input(planner_input, preference, features)
        planner_input, extra = personalized.planner_input, personalized.build_plan_options
        engine, hard_excluded = personalized.engine, list(personalized.hard_excluded)
        feasibility = {**feasibility, "candidates": deepcopy(planner_input["candidates"])}
    snapshot = deepcopy(planner_input)
    plan = build_plan(planner_input, _score_callback(data), **extra)
    if check_plan(planner_input, plan, _score_callback(data), input_snapshot=snapshot):
        raise RuntimeError("SP3 independent plan check failed on the real store.")
    availability = {"available_intervals": free, "calendar_version": context["calendar_version"]}
    if resolved_availability is not None:
        availability = {**resolved_availability, **availability}
    return {"availability": availability,
            "feasibility": feasibility, "plan": plan, "planner_input": planner_input,
            "engine": engine, "hard_excluded": hard_excluded, "data": data}


def _block_of(plan: dict) -> list[dict[str, str]]:
    """Simulated schedule change: the student becomes busy during the first planned activity."""
    if not plan["selected_activities"]:
        return []
    block = plan["selected_activities"][0]["scheduled_blocks"][0]
    return [{"start": block["start"], "end": block["end"]}]


def real_plan(scenario: str, *, target_total: int | None = None, busy_intervals: list[dict[str, str]] | None = None,
              preference: StudentPreference | None = None, availability_request: dict | None = None,
              include_internal: bool = False) -> dict:
    """first_plan / replan (first planned slot becomes busy) / what_if_skip (skip a replanned activity)."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if target_total is not None and (type(target_total) is not int or not 0 <= target_total <= 100):
        raise ValueError("target_total must be an integer from 0 to 100")
    target = 80 if target_total is None else target_total
    busy = list(busy_intervals or [])
    first = _step("first_plan", target, busy, None, preference, availability_request)
    skip_id = None
    if scenario == "first_plan":
        output = first
    else:
        second = _step(
            "replan", target, busy + _block_of(first["plan"]), first["plan"], preference, availability_request
        )
        if scenario == "replan":
            output = second
        else:
            chosen = second["plan"]["selected_activities"]
            if not chosen:
                raise ValueError("the replanned schedule has no activity to skip")
            skip_id = chosen[-1]["activity_id"]
            options = {}
            if preference is not None and second["engine"] is not None:
                options = {"preference_utility": second["engine"].score_set,
                           "personalization_strategy": preference.strategy.value}
            preview = what_if_skip(second["planner_input"], skip_id, _score_callback(second["data"]), **options)
            cancelled = deepcopy(second["planner_input"])
            for candidate in cancelled["candidates"]:
                if candidate["activity"]["activity_id"] == skip_id:
                    candidate["participation"]["progress"] = "CANCELLED"
            if check_plan(cancelled, preview, _score_callback(second["data"])):
                raise RuntimeError("SP3 what-if check failed on the real store.")
            output = {**second, "plan": preview}
    if skip_id is None and scenario != "first_plan" and output["plan"]["selected_activities"]:
        skip_id = output["plan"]["selected_activities"][-1]["activity_id"]
    elif scenario == "first_plan":
        skip_id = None
    result = {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": DATA_SOURCE,
        "live_published": {},       # kept for response compatibility; live ingestion was removed
        "scenario": ("personalized_" if preference is not None else "") + scenario,
        "term": TERM["id"],
        "as_of": AS_OF,
        "requested_total_target": target,
        "what_if_skip_activity_id": skip_id,
        "simulated_change": _block_of(first["plan"]) if scenario != "first_plan" else [],
        "availability": output["availability"],
        "feasibility": output["feasibility"],
        "plan": output["plan"],
    }
    if preference is not None:
        plan = output["plan"]
        selected = [item["activity_id"] for item in plan["selected_activities"]]
        contributions = []
        for item in plan["selected_activities"]:
            goal = next((r for r in item["reasons"] if r["code"] == "GOAL_CONTRIBUTION"), None)
            if goal is not None:
                contributions.append({"activity_id": item["activity_id"], "category_id": goal["category_id"]})
        breakdown = output["engine"].selected_breakdown({"contributions": contributions}, selected)
        unknown_fees = []
        if preference.limits.max_fee is not None:
            unknown_fees = sorted(aid for aid, a in output["engine"].activities.items() if a.get("fee") is None)
        result["preference_confirmed"] = True
        result["personalization"] = {
            "algorithm": "weighted-deterministic-v1",
            "strategy": preference.strategy.value,
            "total_utility": sum(item["utility"] for item in breakdown),
            "selected_breakdown": breakdown,
            "hard_excluded": output["hard_excluded"],
            "unknown_fee_activity_ids": unknown_fees,
            "limits_applied": preference.limits.model_dump(mode="json"),
        }
    if include_internal:
        result["_planner_input"] = deepcopy(output["planner_input"])
        result["_engine"] = output["engine"]
        result["_score_callback"] = _score_callback(output["data"])
    return result


def _plan_signature(result: dict) -> str:
    selected = [{"activity_id": item["activity_id"], "scheduled_blocks": item.get("scheduled_blocks", [])}
                for item in result["plan"].get("selected_activities", [])]
    canonical = json.dumps(selected, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def _plan_minutes(plan: dict) -> int:
    return sum(
        round((datetime.fromisoformat(block["end"]) - datetime.fromisoformat(block["start"])).total_seconds() / 60)
        for item in plan.get("selected_activities", []) for block in item.get("scheduled_blocks", [])
    )


def real_plan_options(
    preference: StudentPreference,
    *,
    target_total: int = 80,
    busy_intervals: list[dict[str, str]] | None = None,
    availability_request: dict | None = None,
) -> dict:
    """Run the existing real-source integration for all supported preference strategies."""

    attempted, options, seen = [], [], {}
    for strategy in ("MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"):
        try:
            candidate = preference.model_copy(update={"strategy": PlanningStrategy(strategy)})
            candidate = StudentPreference.model_validate(candidate.model_dump())
            result = real_plan(
                "first_plan", target_total=target_total, busy_intervals=busy_intervals,
                preference=candidate, availability_request=availability_request,
            )
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            attempted.append({"strategy": strategy, "status": "FAILED", "error": str(exc)})
            options.append({"strategy": strategy, "status": "FAILED", "error": str(exc), "result": None})
            continue
        signature = _plan_signature(result)
        duplicate_of = seen.get(signature)
        seen.setdefault(signature, strategy)
        attempted.append({"strategy": strategy, "status": "READY", "signature": signature})
        plan, score = result["plan"], result["plan"].get("score_summary") or {}
        options.append({
            "strategy": strategy, "status": "READY", "signature": signature, "duplicate_of": duplicate_of,
            "projected_total": score.get("projected_total"),
            "target_shortfall": score.get("remaining_total"),
            "target_met": score.get("remaining_total") == 0 if score else False,
            "activity_count": len(plan.get("selected_activities", [])),
            "duration_minutes": _plan_minutes(plan),
            "utility": result["personalization"]["total_utility"],
            "plan": plan, "result": result,
        })
    ready_count = sum(1 for item in options if item.get("status") == "READY")
    return {
        "options": options,
        "attempted": attempted,
        "deduplicated": 0,
        "message": None if ready_count else "Không có chiến lược nào tạo được lịch hợp lệ với dữ liệu hiện tại.",
        "source": "real",
    }
