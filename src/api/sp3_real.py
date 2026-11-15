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
import json
from copy import deepcopy
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path

from api import live_state
from personalization.models import StudentPreference
from personalization.planner_adapter import prepare_personalized_planner_input
from personalization.scoring import ActivityFeatures, load_activity_features
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
HANDOVER = DATA / "handover"
FIXTURE = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"

DATA_SOURCE = "SP1-STORE-V2"
# Original handover dataset plus posts published through the live ingestion workflow (sp1.live_ingest).
LIVE_DATA_SOURCE = "SP1-STORE-V2+LIVE"
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


def _load(live: bool = False) -> dict:
    """The handover dataset; with live=True also the live posts published right now (read per call)."""
    base = _load_base()
    if not live:
        return base
    published = [r for r in live_state.published_records()
                 if r["post_id"] not in {a["activity_id"] for a in base["activities"]}]
    if not published:
        return {**base, "live": {}}
    data = {**base, "activities": list(base["activities"]), "binding_by_id": dict(base["binding_by_id"]),
            "evidence": deepcopy(base["evidence"]), "scoring": deepcopy(base["scoring"]),
            "sidecar": deepcopy(base["sidecar"]), "live": {}}
    for record in published:
        post_id = record["post_id"]
        data["activities"].append(record["activity"])
        data["sidecar"]["activities"][post_id] = record["sidecar"]
        for key, value in record["evidence"].items():
            if value is not None:
                data["evidence"][key][post_id] = value
        binding = record["binding"]
        if binding:
            data["binding_by_id"][post_id] = binding
            data["scoring"]["bindings"].append(binding)
            if binding["operation"] == "INCREMENT":
                data["scoring"]["baselines"][0]["facts"].setdefault(binding["field"], 0)
        data["live"][post_id] = record
    data["scoring"]["activities"] = data["activities"]
    return data


def _features(data: dict):
    features = load_activity_features(HANDOVER / "activity_features_sp1.json")
    for post_id, record in data.get("live", {}).items():
        value = record["features"]
        features[post_id] = ActivityFeatures(frozenset(value["topics"]), value["campus_id"], frozenset(value["time_tags"]))
    return features


def _queue_reasons() -> dict[str, list[str]]:
    path = DATA / "review" / "queue.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return {row["post_id"]: [r.strip() for r in row["reasons"].split(";") if r.strip()]
                for row in csv.DictReader(handle)}


def _score_callback(data: dict):
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(deepcopy(data["scoring"])))).score_plan


def real_catalog(live: bool = False) -> dict:
    """Handed-over activities with their binding and review state; blocked posts as drafts.

    live=True adds the posts published through sp1.live_ingest (marked with live_revision).
    """
    data = _load(live)
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
            "live_revision": (data.get("live", {}).get(aid) or {}).get("revision"),
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
        "data_source": LIVE_DATA_SOURCE if live else DATA_SOURCE,
        "live_published": {pid: r["revision"] for pid, r in data.get("live", {}).items()} if live else {},
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
          preference: StudentPreference | None, live: bool = False) -> dict:
    data = _load(live)
    free = _free_time(busy)
    context = {
        "student_id": STUDENT_ID, "term_id": TERM["id"], "window_start": WINDOW_START, "window_end": WINDOW_END,
        "as_of": AS_OF, "timezone": "Asia/Ho_Chi_Minh", "baseline_ref": BASELINE_REF,
        "dataset_version": "sp1-store-v2", "ruleset_version": data["scoring"]["ruleset_version"],
        "calendar_version": f"synthetic-free-{len(busy)}-busy",
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
        features = _features(data)
        personalized = prepare_personalized_planner_input(planner_input, preference, features)
        planner_input, extra = personalized.planner_input, personalized.build_plan_options
        engine, hard_excluded = personalized.engine, list(personalized.hard_excluded)
        feasibility = {**feasibility, "candidates": deepcopy(planner_input["candidates"])}
    snapshot = deepcopy(planner_input)
    plan = build_plan(planner_input, _score_callback(data), **extra)
    if check_plan(planner_input, plan, _score_callback(data), input_snapshot=snapshot):
        raise RuntimeError("SP3 independent plan check failed on the real store.")
    return {"availability": {"available_intervals": free, "calendar_version": context["calendar_version"]},
            "feasibility": feasibility, "plan": plan, "planner_input": planner_input,
            "engine": engine, "hard_excluded": hard_excluded, "data": data}


def _block_of(plan: dict) -> list[dict[str, str]]:
    """Simulated schedule change: the student becomes busy during the first planned activity."""
    if not plan["selected_activities"]:
        return []
    block = plan["selected_activities"][0]["scheduled_blocks"][0]
    return [{"start": block["start"], "end": block["end"]}]


def real_plan(scenario: str, *, target_total: int | None = None, busy_intervals: list[dict[str, str]] | None = None,
              preference: StudentPreference | None = None, live: bool = False) -> dict:
    """first_plan / replan (first planned slot becomes busy) / what_if_skip (skip a replanned activity)."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    if target_total is not None and (type(target_total) is not int or not 0 <= target_total <= 100):
        raise ValueError("target_total must be an integer from 0 to 100")
    target = 80 if target_total is None else target_total
    busy = list(busy_intervals or [])
    first = _step("first_plan", target, busy, None, preference, live)
    skip_id = None
    if scenario == "first_plan":
        output = first
    else:
        second = _step("replan", target, busy + _block_of(first["plan"]), first["plan"], preference, live)
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
        "data_source": LIVE_DATA_SOURCE if live else DATA_SOURCE,
        "live_published": {pid: r["revision"] for pid, r in output["data"].get("live", {}).items()} if live else {},
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
    return result
