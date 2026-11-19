"""SP3 on the operational activity dataset (real announcements, synthetic student).

The "real data" source of the web app reads exactly one generated file,
data/operational/activity_dataset.json (built by scripts/update_activity_data.py). Catalog and planning
use the same loaded version, and the version is returned with every response. A new build replaces the
file atomically; the loader notices the replacement and reloads it as a whole, so a request never sees
a mixture of two builds.

Only data-ready canonical activities become planner candidates. Every other post is still listed, with
its machine-readable reasons. What the dataset does not establish stays a separate SP3 gate:
student eligibility, term scope, the score binding, the registration deadline and the demo clock.

What is real: the activities (from announcements), the score bindings (rule-based or reviewed) and the
encoded regulation. What is synthetic: the student (K24, standard program, FIT), the baseline facts and
the free time. The planner clock is a labelled historical demo clock (2026-10-01): many announcements
are in the past, and dates are never rewritten to make a plan non-empty. Nothing is an official award.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
from copy import deepcopy
from datetime import date, datetime, timedelta
from pathlib import Path

from api.plan_completion import AccountPlanScoring
from personalization.models import PlanningStrategy, StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import ActivityFeatures
from sp1 import audience as audience_rules
from sp1.operational import DATASET_PATH, READY_STATUSES, message
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter
from sp3.availability import resolve_availability

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
FIXTURE = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"

DATA_SOURCE = "OPERATIONAL-DATASET"
TERM = {"id": "HK1_2026_2027", "start": "2026-08-29", "end": "2026-11-15"}
# Labelled historical demo clock: the planner looks at the rest of HK1 from this date.
AS_OF = "2026-10-01T08:00:00+07:00"
CLOCK = {"as_of": AS_OF, "label": "historical_demo_clock",
         "note": "Announcements are from a past semester; the demo plans as of this date. Dates are not shifted."}
WINDOW_START = "2026-10-01T00:00:00+07:00"
WINDOW_END = "2026-11-16T00:00:00+07:00"
DAY_START_HOUR, DAY_END_HOUR = 7, 21
STUDENT_ID = "synthetic-student-k24"
BASELINE_REF = "synthetic-baseline-k24"
PROFILE = {"cohort": "K24", "program": "standard", "faculty": "FIT"}

_lock = threading.Lock()
_cache: dict = {"key": None, "data": None}


def dataset_path() -> Path:
    return Path(os.environ.get("UNILIFE_ACTIVITY_DATASET") or DATASET_PATH)


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _term_scope(start: str) -> str:
    day = date.fromisoformat(start[:10])
    return "IN_SCOPE" if date.fromisoformat(TERM["start"]) <= day <= date.fromisoformat(TERM["end"]) else "OUT_OF_SCOPE"


def _prepare(dataset: dict) -> dict:
    records = dataset["records"]
    ready = [r for r in records if r["status"] in READY_STATUSES and r["duplicate_of"] is None]
    activities = [deepcopy(r["sp3_activity"]) for r in ready]
    bindings = [deepcopy(r["binding"]) for r in ready if r["binding"]]
    rules = _json(DATA / "drl_rules.json")
    fixture = _json(FIXTURE)
    facts = deepcopy(fixture["scoring_data"]["baselines"][0]["facts"])
    for binding in bindings:
        if binding["operation"] == "INCREMENT":
            facts.setdefault(binding["field"], 0)
    evidence = {
        "term_verified": None,
        "eligibility_by_activity": {r["post_id"]: audience_rules.eligibility(r["audience"], PROFILE) for r in ready},
        "term_scope_by_activity": {r["post_id"]: _term_scope(r["sp3_activity"]["start"]) for r in ready},
        # Data readiness was checked by the user-agreed policy against the source (not by a person).
        "source_review_by_activity": {r["post_id"]: True for r in ready},
        "schedule_by_activity": {r["post_id"]: deepcopy(r["sp3_schedule"]) for r in ready},
        "deadline_unstated_by_activity": {r["post_id"]: True for r in ready
                                          if not r["acceptance"]["accepted_record"].get("registration_deadline")},
    }
    return {
        "dataset": dataset, "records": records, "ready": ready, "activities": activities,
        "binding_by_id": {b["activity_id"]: b for b in bindings},
        "features": {r["post_id"]: ActivityFeatures(frozenset(r["features"]["topics"]), r["features"]["campus_id"],
                                                    frozenset(r["features"]["time_tags"])) for r in ready},
        "scoring": {"label": "operational-activities-synthetic-student",
                    "dataset_version": dataset["dataset_version"],
                    "ruleset_version": fixture["scoring_data"]["ruleset_version"], "ruleset": rules,
                    "baselines": [{"student_id": STUDENT_ID, "baseline_ref": BASELINE_REF, "facts": facts}],
                    "activities": activities, "bindings": bindings},
        "planner": deepcopy(fixture["planner"]),
        "evidence": evidence,
    }


def _load_base() -> dict:
    """The prepared dataset; reloaded as a whole when the file is replaced."""
    path = dataset_path()
    stat = path.stat()
    key = (str(path), stat.st_mtime_ns, stat.st_size)
    with _lock:
        if _cache["key"] != key:
            _cache["data"] = _prepare(_json(path))
            _cache["key"] = key
        return _cache["data"]


def _score_callback(data: dict):
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(deepcopy(data["scoring"])))).score_plan


def _messages(codes: list[str]) -> list[dict]:
    return [{"code": code, "message": message(code)} for code in codes]


def dataset_info(data: dict | None = None) -> dict:
    data = data or _load_base()
    ds = data["dataset"]
    return {"path": str(dataset_path().relative_to(ROOT)) if ROOT in dataset_path().parents else str(dataset_path()),
            "dataset_version": ds["dataset_version"], "generated_at": ds["generated_at"],
            "schema": ds["schema"], "activity_contract": ds["activity_contract"], "summary": ds["summary"]}


def real_catalog() -> dict:
    """Schedulable activities with warnings, and every other post with its reasons (same dataset version)."""
    data = _load_base()
    rows = []
    for record in data["ready"]:
        activity = record["sp3_activity"]
        binding = data["binding_by_id"].get(record["post_id"])
        decision = record["binding_decision"] or {}
        notes = (f"Rule {binding['rule_id']} ({decision.get('label')})" if binding
                 else "No supported score rule: not counted toward the point target")
        rows.append({
            "activity": activity,
            "data_qa": {"status": record["status"], "semester": TERM["id"], "notes": notes},
            "publication_status": "SCHEDULABLE" if binding else "SCHEDULABLE_NO_SCORE_BINDING",
            "score_binding_verified": False,
            "score_binding": ({"rule_id": binding["rule_id"], "binding_ref": binding["binding_ref"],
                               "category_id": decision.get("category_id"),
                               "points_from_rules": decision.get("points_from_rules")} if binding else None),
            "activity_type": record["activity_type"],
            "schedule": record["sp3_schedule"],
            "fee_known": activity["fee"] is not None,
            "domain_known": activity["domain"] is not None,
            "warnings": _messages(record["warnings"]),
            "aliases": record["aliases"],
            "dimensions": record["dimensions"],
            "extraction": {"method": record["extraction"]["method"], "label": record["extraction"]["label"]},
            "review_reasons": [],
            "live_revision": None,
        })
    excluded = []
    for record in data["records"]:
        if record["status"] in READY_STATUSES and record["duplicate_of"] is None:
            continue
        accepted = (record.get("acceptance") or {}).get("accepted_record") or {}
        excluded.append({
            "post_id": record["post_id"], "position": record["position"], "status": record["status"],
            "title": accepted.get("title"), "url": record["source"]["url"],
            "reasons": _messages(record["reasons"]), "warnings": _messages(record["warnings"]),
            "duplicate_of": record["duplicate_of"], "extraction_method": record["extraction"]["method"],
        })
    drafts = [{"activity": {"activity_id": e["post_id"], "title": e["title"]},
               "review_flags": [r["code"] for r in e["reasons"]] or [e["status"]],
               "reason_messages": [r["message"] for r in e["reasons"]],
               "publication_status": e["status"], "score_binding_verified": False} for e in excluded]
    info = dataset_info(data)
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": DATA_SOURCE,
        "dataset": info,
        "live_published": {},
        "term": TERM,
        "clock": CLOCK,
        "source_dataset": {"path": info["path"], "total_posts": info["summary"]["posts"],
                           "status": "OPERATIONAL_DATASET", "handed_over": len(rows),
                           "bound": sum(1 for r in rows if r["score_binding"])},
        "activity_count": len(rows),
        "unstructured_new_posts": len(drafts),
        "new_post_drafts": drafts,
        "new_post_errors": [],
        "excluded": excluded,
        "activities": rows,
        "note": ("Real announcements processed by AI/model extraction and the agreed data policy (not human review, "
                 "not gold). Missing organizer facts stay unknown. Student is synthetic; points are DEMO_ONLY."),
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
          preference: StudentPreference | None, data: dict, availability_request: dict | None = None,
          account: AccountPlanScoring | None = None) -> dict:
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
        "dataset_version": data["dataset"]["dataset_version"], "ruleset_version": data["scoring"]["ruleset_version"],
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
    if account:
        score = account.configure(feasibility["context"], options)
        account.apply_progress(feasibility["candidates"])
    else:
        score = _score_callback(data)
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
        personalized = prepare_personalized_planner_input(planner_input, preference, data["features"])
        planner_input, extra = personalized.planner_input, personalized.build_plan_options
        engine, hard_excluded = personalized.engine, list(personalized.hard_excluded)
        feasibility = {**feasibility, "candidates": deepcopy(planner_input["candidates"])}
    snapshot = deepcopy(planner_input)
    plan = build_plan(planner_input, score, **extra)
    if check_plan(planner_input, plan, score, input_snapshot=snapshot):
        raise RuntimeError("SP3 independent plan check failed on the operational dataset.")
    availability = {"available_intervals": free, "calendar_version": context["calendar_version"]}
    if resolved_availability is not None:
        availability = {**resolved_availability, **availability}
    return {"availability": availability,
            "feasibility": feasibility, "plan": plan, "planner_input": planner_input,
            "engine": engine, "hard_excluded": hard_excluded, "score": score}


def _block_of(plan: dict) -> list[dict[str, str]]:
    """Simulated schedule change: the student becomes busy during the first planned activity."""
    if not plan["selected_activities"]:
        return []
    block = plan["selected_activities"][0]["scheduled_blocks"][0]
    return [{"start": block["start"], "end": block["end"]}]


def _activity_notes(data: dict, plan: dict) -> dict:
    """Data-layer warnings for the planned activities (unknown cost, deadline, defaults, ...)."""
    by_id = {r["post_id"]: r for r in data["ready"]}
    return {item["activity_id"]: _messages(by_id[item["activity_id"]]["warnings"])
            for item in plan["selected_activities"] if item["activity_id"] in by_id}


def real_plan(scenario: str, *, target_total: int | None = None, busy_intervals: list[dict[str, str]] | None = None,
              preference: StudentPreference | None = None, availability_request: dict | None = None,
              include_internal: bool = False, account: AccountPlanScoring | None = None) -> dict:
    """first_plan / replan (first planned slot becomes busy) / what_if_skip (skip a replanned activity)."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if target_total is not None and (type(target_total) is not int or not 0 <= target_total <= 100):
        raise ValueError("target_total must be an integer from 0 to 100")
    target = 80 if target_total is None else target_total
    busy = list(busy_intervals or [])
    data = _load_base()  # One operational dataset snapshot for every step of this request.
    first = _step("first_plan", target, busy, None, preference, data, availability_request, account)
    skip_id = None
    if scenario == "first_plan":
        output = first
    else:
        second = _step(
            "replan", target, busy + _block_of(first["plan"]), first["plan"], preference, data, availability_request, account
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
            preview = what_if_skip(second["planner_input"], skip_id, second["score"], **options)
            cancelled = deepcopy(second["planner_input"])
            for candidate in cancelled["candidates"]:
                if candidate["activity"]["activity_id"] == skip_id:
                    candidate["participation"]["progress"] = "CANCELLED"
            if check_plan(cancelled, preview, second["score"]):
                raise RuntimeError("SP3 what-if check failed on the operational dataset.")
            output = {**second, "plan": preview}
    if skip_id is None and scenario != "first_plan" and output["plan"]["selected_activities"]:
        skip_id = output["plan"]["selected_activities"][-1]["activity_id"]
    elif scenario == "first_plan":
        skip_id = None
    result = {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": DATA_SOURCE,
        "dataset": {"dataset_version": data["dataset"]["dataset_version"],
                    "generated_at": data["dataset"]["generated_at"]},
        "live_published": {},
        "scenario": ("personalized_" if preference is not None else "") + scenario,
        "term": TERM["id"],
        "as_of": AS_OF,
        "clock": CLOCK,
        "requested_total_target": target,
        "what_if_skip_activity_id": skip_id,
        "simulated_change": _block_of(first["plan"]) if scenario != "first_plan" else [],
        "availability": output["availability"],
        "feasibility": output["feasibility"],
        "plan": output["plan"],
        "activity_warnings": _activity_notes(data, output["plan"]),
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
        result["_score_callback"] = output["score"]
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
    account: AccountPlanScoring | None = None,
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
                account=account,
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
