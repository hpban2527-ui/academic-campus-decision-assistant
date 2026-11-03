"""SP3 integration: real SP1 catalog and a clearly synthetic planning preview."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from sp3.availability import resolve_availability
from sp3.feasibility import FeasibilityEvidence, assess_feasibility
from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"
QA = ROOT / "DataQA"
DEMO = ROOT / "tests" / "sp3" / "fixtures" / "main_flow_integration.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sp1_catalog() -> dict:
    """Return source records with QA context; never promote them to verified points."""
    activities = _json(DATA / "activities.json")
    reviews = _json(QA / "QA20.json")
    source_posts = _json(QA / "source.json")
    by_id = {item["activity_id"]: item for item in reviews}
    original_ids = {item["activity_id"] for item in activities}
    rows = [
        {
            "activity": item,
            "data_qa": by_id.get(item["activity_id"]),
            "publication_status": "REVIEW_REQUIRED",
            "score_binding_verified": False,
        }
        for item in activities
    ]
    extra = [post for post in source_posts if post["post_id"] not in original_ids]
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "term": {"id": "HK3_2025_2026", "start": "2026-05-18", "end": "2026-08-17"},
        "activity_count": len(rows),
        "unstructured_new_posts": len(extra),
        "activities": rows,
        "note": "New posts need 14-field extraction and human source review before planning.",
    }


def _score_callback(fixture: dict):
    scoring_data = deepcopy(fixture["scoring_data"])
    scoring_data["ruleset"] = _json(DATA / "drl_rules.json")
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(scoring_data))).score_plan


def _step(fixture: dict, name: str, previous: dict | None = None) -> dict:
    stored = fixture["steps"][name]
    feasibility_request = deepcopy(stored["feasibility_request"])
    context = feasibility_request["context"]
    availability = resolve_availability(
        deepcopy(stored["availability_request"]),
        window_start=context["window_start"],
        window_end=context["window_end"],
    )
    feasibility_request["available_intervals"] = availability["available_intervals"]
    feasibility_request["context"]["calendar_version"] = availability["calendar_version"]
    feasibility = assess_feasibility(
        feasibility_request, evidence=FeasibilityEvidence(**deepcopy(fixture["evidence"]))
    )

    # A fixture is evidence of an interface, not a substitute for running upstream code.
    if availability != stored["availability_response"] or feasibility != stored["feasibility_response"]:
        raise RuntimeError("SP3 upstream contract drift; review the fixture before publishing a demo.")

    previous_plan = None
    if previous is not None:
        previous_plan = {
            "plan_version": previous["plan_version"],
            "based_on": deepcopy(previous["based_on"]),
            "selected_activities": [
                {"activity_id": item["activity_id"], "scheduled_blocks": deepcopy(item["scheduled_blocks"])}
                for item in previous["selected_activities"]
            ],
        }
    planner_input = {
        "contract_version": feasibility["contract_version"],
        "request_id": "api-demo-" + name,
        "context": deepcopy(feasibility["context"]),
        **deepcopy(fixture["planner"]),
        "candidates": deepcopy(feasibility["candidates"]),
        "conflict_pairs": deepcopy(feasibility["conflict_pairs"]),
        "available_intervals": deepcopy(availability["available_intervals"]),
        "previous_plan": previous_plan,
        "keep_requests": [],
    }
    plan = build_plan(planner_input, _score_callback(fixture))
    violations = check_plan(planner_input, plan, _score_callback(fixture), input_snapshot=deepcopy(planner_input))
    if violations:
        raise RuntimeError("SP3 independent plan check failed.")
    return {
        "availability": availability,
        "feasibility": feasibility,
        "plan": plan,
        "planner_input": planner_input,
    }


def demo_plan(scenario: str) -> dict:
    """Exercise all SP3 modules and the real SP2 engine on synthetic data only."""
    if scenario not in {"first_plan", "replan", "what_if_skip"}:
        raise ValueError("scenario must be first_plan, replan, or what_if_skip")
    fixture = _json(DEMO)
    first = _step(fixture, "step1")
    if scenario == "first_plan":
        output = first
    else:
        second = _step(fixture, "step2", previous=first["plan"])
        if scenario == "replan":
            output = second
        else:
            preview = what_if_skip(second["planner_input"], "QUIZ-L", _score_callback(fixture))
            if check_plan(
                {**deepcopy(second["planner_input"]),
                 "candidates": [
                     {**deepcopy(item),
                      "participation": {
                          **item["participation"],
                          "progress": "CANCELLED" if item["activity"]["activity_id"] == "QUIZ-L"
                          else item["participation"]["progress"],
                      }}
                     for item in second["planner_input"]["candidates"]
                 ]},
                preview, _score_callback(fixture),
            ):
                raise RuntimeError("SP3 what-if plan check failed.")
            output = {**second, "plan": preview}
    return {
        "mode": "DEMO_ONLY",
        "official_award_verified": False,
        "data_source": "SYNTHETIC-DEMO",
        "scenario": scenario,
        "term": output["feasibility"]["context"]["term_id"],
        "availability": output["availability"],
        "feasibility": output["feasibility"],
        "plan": output["plan"],
    }
