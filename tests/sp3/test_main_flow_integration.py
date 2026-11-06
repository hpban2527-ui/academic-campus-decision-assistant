"""Main-flow integration: availability -> feasibility -> planner -> scorer -> SP2.

The upstream availability and feasibility outputs in the fixture were produced
by the real ``resolve_availability`` and ``assess_feasibility`` at the commit
recorded in ``upstream.commit`` and are consumed here verbatim: the planner
input is assembled the way the backend will assemble it, without rewriting a
single candidate field. Scores come from the real SP2 engine and the real
``data/drl_rules.json``; the student, activities, evidence and bindings are
synthetic (label SYNTHETIC-DEMO). Every expected value was derived by hand
(see the fixture's ``derivation``), not recorded from the implementation.

The flow covered is the one a student goes through:

1. first plan from a weekly timetable;
2. new busy time and a registration, then replan against the active plan;
3. ``what_if_skip`` preview on that replan input;
4. keep requests that the new timetable no longer allows.

The last test re-runs the upstream modules to detect drift between the stored
outputs and the current feasibility code. Those modules live on another
branch, so it runs only once both branches are integrated (contract §13).
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from sp3.plan_checker import check_plan
from sp3.planner import build_plan, what_if_skip
from sp3.projected_scorer import InMemoryScoringData, ProjectedScorer
from sp3.scorer_adapter import ScorerAdapter

FIXTURE = json.loads((Path(__file__).resolve().parent / "fixtures" / "main_flow_integration.json").read_text(encoding="utf-8"))
RULES = json.loads((REPO / FIXTURE["ruleset_source"]).read_text(encoding="utf-8"))
STEPS = FIXTURE["steps"]
EXPECTED = FIXTURE["expected"]


# --- Backend-style assembly (contract section 7) ------------------------------------


def planner_input(step: str, *, previous_output=None, keep_requests=()):
    """Assemble planner_input from stored upstream outputs without rewriting them."""
    feasibility = STEPS[step]["feasibility_response"]
    availability = STEPS[step]["availability_response"]
    previous_plan = None
    if previous_output is not None:
        previous_plan = {
            "plan_version": previous_output["plan_version"],
            "based_on": deepcopy(previous_output["based_on"]),
            "selected_activities": [
                {"activity_id": entry["activity_id"], "scheduled_blocks": deepcopy(entry["scheduled_blocks"])}
                for entry in previous_output["selected_activities"]
            ],
        }
    return {
        "contract_version": feasibility["contract_version"],
        "request_id": f"main-flow-{step}",
        "context": deepcopy(feasibility["context"]),
        **deepcopy(FIXTURE["planner"]),
        "candidates": deepcopy(feasibility["candidates"]),
        "conflict_pairs": deepcopy(feasibility["conflict_pairs"]),
        "available_intervals": deepcopy(availability["available_intervals"]),
        "previous_plan": previous_plan,
        "keep_requests": [dict(request) for request in keep_requests],
    }


def real_score_plan():
    """A fresh adapter over the projected scorer, the real engine and the real rules."""
    data = deepcopy(FIXTURE["scoring_data"])
    data["ruleset"] = deepcopy(RULES)
    return ScorerAdapter(ProjectedScorer(InMemoryScoringData(data))).score_plan


def independent_plan_version(output) -> str:
    """Contract section 10.2 hash, recomputed without importing the implementation."""
    planned = sorted(
        (
            {"activity_id": entry["activity_id"], "scheduled_blocks": sorted(entry["scheduled_blocks"], key=lambda b: b["start"])}
            for entry in output["selected_activities"]
        ),
        key=lambda entry: entry["activity_id"],
    )
    payload = {"based_on": output["based_on"], "selected_activities": planned}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sp3plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def plan_and_check(data, plan=build_plan, *args):
    """Run one planning call and the independent checker; inputs must stay unchanged."""
    snapshot = deepcopy(data)
    output = plan(data, *args, real_score_plan())
    assert data == snapshot, "planning must not mutate its input"
    if plan is build_plan:
        assert check_plan(data, output, real_score_plan(), input_snapshot=snapshot) == []
    return output


def assert_matches(output, expected, *, step: str, previous_plan_version):
    assert output["status"] == expected["status"], output["errors"]
    assert output["feasibility_conclusion"] == expected["feasibility_conclusion"]
    assert [
        {
            "activity_id": entry["activity_id"],
            "schedule_type": entry["schedule_type"],
            "scheduled_blocks": entry["scheduled_blocks"],
            "registration": entry["registration"],
            "change": entry["change"],
            "category_id": entry["reasons"][0]["category_id"],
            "projected_added": entry["reasons"][0]["projected_added"],
            "preference_matches": sum(reason["code"] == "PREFERENCE_MATCH" for reason in entry["reasons"]),
        }
        for entry in output["selected_activities"]
    ] == expected["selected"]
    assert all(entry["reasons"][0]["code"] == "GOAL_CONTRIBUTION" for entry in output["selected_activities"])
    assert {entry["activity_id"]: entry["code"] for entry in output["excluded_candidates"]} == expected["excluded"]
    assert output["score_summary"] == expected["score_summary"]
    assert output["search"] == expected["search"]
    assert output["proof"] == expected["proof"]
    assert [warning["code"] for warning in output["warnings"]] == expected["warning_codes"]
    assert output["pending_confirmation"] == expected["pending_confirmation"]
    assert {
        entry["activity_id"]: {"code": entry["code"], "registered": entry["registered"]}
        for entry in output["dropped_activities"]
    } == expected["dropped"]
    assert output["score_comparison"] == expected["score_comparison"]
    assert output["keep_conflicts"] == []
    context = STEPS[step]["feasibility_response"]["context"]
    assert output["based_on"] == {
        "calendar_version": STEPS[step]["availability_response"]["calendar_version"],
        "dataset_version": context["dataset_version"],
        "ruleset_version": context["ruleset_version"],
        "baseline_ref": context["baseline_ref"],
        "previous_plan_version": previous_plan_version,
    }
    assert output["plan_version"] == independent_plan_version(output)
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)


# --- Fixture provenance -------------------------------------------------------------


def test_fixture_is_synthetic_and_upstream_outputs_are_linked():
    assert FIXTURE["label"] == FIXTURE["scoring_data"]["label"] == "SYNTHETIC-DEMO"
    assert FIXTURE["upstream"]["commit"]
    for step in STEPS.values():
        feasibility, availability = step["feasibility_response"], step["availability_response"]
        assert feasibility["contract_version"] == "sp3-planner/0.2"
        assert availability["availability_version"] == "sp3-availability/0.2"
        # The planner relies on these links; the backend guarantees them in production.
        assert feasibility["context"]["calendar_version"] == availability["calendar_version"]
        assert step["feasibility_request"]["available_intervals"] == availability["available_intervals"]
        assert feasibility["context"]["term_id"] == "SYNTHETIC-DEMO"
    assert STEPS["step1"]["availability_response"]["calendar_version"] != STEPS["step2"]["availability_response"]["calendar_version"]


# --- 1. First plan -------------------------------------------------------------------


def test_main_flow_first_plan_schedules_fixed_and_flexible_activities_together():
    output = plan_and_check(planner_input("step1"))
    assert_matches(output, EXPECTED["step1"], step="step1", previous_plan_version=None)


# --- 2. Replan after new busy time and a registration --------------------------------


def test_main_flow_replan_keeps_moves_adds_and_drops_with_reasons():
    first = plan_and_check(planner_input("step1"))
    second = plan_and_check(planner_input("step2", previous_output=first))
    assert_matches(second, EXPECTED["step2"], step="step2", previous_plan_version=first["plan_version"])
    assert second["plan_version"] != first["plan_version"]


def test_main_flow_replan_never_reuses_a_block_that_became_busy():
    first = plan_and_check(planner_input("step1"))
    second = plan_and_check(planner_input("step2", previous_output=first))
    busy = STEPS["step2"]["availability_request"]["busy_intervals"]
    for entry in second["selected_activities"]:
        for block in entry["scheduled_blocks"]:
            for interval in busy:
                assert not (block["start"] < interval["end"] and interval["start"] < block["end"]), (entry["activity_id"], block)


# --- 3. What-if preview --------------------------------------------------------------


def test_main_flow_what_if_skip_is_a_read_only_preview_with_a_proven_gap():
    first = plan_and_check(planner_input("step1"))
    data = planner_input("step2", previous_output=first)
    preview = plan_and_check(data, what_if_skip, "QUIZ-L")
    assert_matches(preview, EXPECTED["what_if_skip_quiz_l"], step="step2", previous_plan_version=first["plan_version"])
    candidate = next(c for c in data["candidates"] if c["activity"]["activity_id"] == "QUIZ-L")
    assert candidate["participation"]["progress"] == "NOT_STARTED"
    # The preview is a normal plan for the skipped state; check it against that state.
    skipped = deepcopy(data)
    next(c for c in skipped["candidates"] if c["activity"]["activity_id"] == "QUIZ-L")["participation"]["progress"] = "CANCELLED"
    assert check_plan(skipped, preview, real_score_plan()) == []


# --- 4. Keep requests the new timetable no longer allows -----------------------------


def test_main_flow_keep_requests_broken_by_new_busy_time_are_reported_not_released():
    first = plan_and_check(planner_input("step1"))
    expected = EXPECTED["keep_conflict"]
    output = plan_and_check(planner_input("step2", previous_output=first, keep_requests=expected["keep_requests"]))
    assert output["status"] == "KEEP_CONFLICT"
    assert [{"activity_id": c["activity_id"], "code": c["code"]} for c in output["keep_conflicts"]] == expected["keep_conflicts"]
    assert output["selected_activities"] == []
    assert output["score_summary"] is None and output["proof"] is None
    assert output["feasibility_conclusion"] == "UNDETERMINED"
    assert output["search"]["limit_reason"] == "KEEP_CONFLICT"


# --- Upstream drift check (after branch integration) ---------------------------------


_UPSTREAM_PRESENT = all(
    importlib.util.find_spec(name) is not None for name in ("sp3.availability", "sp3.feasibility")
)


@pytest.mark.skipif(not _UPSTREAM_PRESENT, reason="availability/feasibility live on another branch until integration (contract §13)")
def test_stored_upstream_outputs_match_the_current_feasibility_code():
    from sp3.availability import resolve_availability
    from sp3.feasibility import FeasibilityEvidence, assess_feasibility

    for name, step in STEPS.items():
        context = step["feasibility_request"]["context"]
        resolved = resolve_availability(
            deepcopy(step["availability_request"]),
            window_start=context["window_start"],
            window_end=context["window_end"],
        )
        assert resolved == step["availability_response"], name
        response = assess_feasibility(deepcopy(step["feasibility_request"]), evidence=FeasibilityEvidence(**deepcopy(FIXTURE["evidence"])))
        assert response == step["feasibility_response"], name
