"""Dedicated tests for SP3 Outer Planner optimizations (Exact vs Greedy vs Beam v1 vs Guided v2)."""
from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from schedule_optimization.scenarios import get_all_planner_scenarios
from sp3.plan_checker import check_plan
from sp3.planner import build_plan


def _by_id(scenario_id: str):
    for sc in get_all_planner_scenarios():
        if sc.id == scenario_id:
            return sc
    raise KeyError(scenario_id)


@pytest.mark.parametrize("method", ["greedy", "beam_v1", "guided_v2"])
@pytest.mark.parametrize("scenario", get_all_planner_scenarios(), ids=lambda s: s.id)
def test_all_methods_pass_plan_checker_contract(scenario, method):
    scorer = scenario.scorer_factory()
    output = build_plan(
        scenario.planner_input,
        scorer,
        personalization_strategy=scenario.personalization_strategy,
        preference_utility=scenario.preference_utility,
        search_method=method,
    )
    checker_scorer = scenario.scorer_factory()
    violations = check_plan(scenario.planner_input, output, checker_scorer)
    assert violations == [], f"Contract violations for {scenario.id}/{method}: {violations}"


@pytest.mark.parametrize("scenario_id", ["small_exact", "medium_exact"])
def test_guided_v2_matches_exact_optimum_on_verifiable_scenarios(scenario_id):
    sc = _by_id(scenario_id)
    exact_out = build_plan(sc.planner_input, sc.scorer_factory(), search_method="exact")
    v2_out = build_plan(sc.planner_input, sc.scorer_factory(), search_method="guided_v2")

    assert exact_out["status"] == "TARGET_MET"
    assert exact_out["search"]["optimality_proven"] is True
    assert v2_out["status"] == "TARGET_MET"
    assert v2_out["search"]["optimality_proven"] is False  # heuristic soundness
    # Zero optimality gap on activity count and projected score
    assert len(v2_out["selected_activities"]) == len(exact_out["selected_activities"])
    assert v2_out["score_summary"]["projected_total"] >= exact_out["score_summary"]["projected_total"]


def test_guided_v2_fixes_multicategory_blindspot():
    """Beam v1's top-20 singleton cap misses C4 when 26 C1 items dominate; Guided v2 meets all targets."""
    sc = _by_id("multicat_blindspot")
    v2_out = build_plan(sc.planner_input, sc.scorer_factory(), search_method="guided_v2")
    assert v2_out["status"] == "TARGET_MET"
    assert v2_out["score_summary"]["remaining_by_category"]["C4"] == 0
    assert v2_out["score_summary"]["remaining_by_category"]["C3"] == 0
    assert v2_out["score_summary"]["remaining_by_category"]["C1"] == 0


def test_guided_v2_preserves_replan_stability():
    """During replan, Guided v2 keeps the 3 retained activities (0 set_changes) instead of churning."""
    sc = _by_id("replan_stability")
    v2_out = build_plan(sc.planner_input, sc.scorer_factory(), search_method="guided_v2")
    assert v2_out["status"] == "TARGET_MET"
    selected_ids = {item["activity_id"] for item in v2_out["selected_activities"]}
    assert selected_ids == {"RP-00", "RP-01", "RP-02"}
    assert all(item["change"] == "KEPT" for item in v2_out["selected_activities"])
    assert v2_out["dropped_activities"] == []


def test_guided_v2_optimizes_preference_first_utility():
    sc = _by_id("pref_first")
    v1_out = build_plan(
        sc.planner_input,
        sc.scorer_factory(),
        personalization_strategy=sc.personalization_strategy,
        preference_utility=sc.preference_utility,
        search_method="beam_v1",
    )
    v2_out = build_plan(
        sc.planner_input,
        sc.scorer_factory(),
        personalization_strategy=sc.personalization_strategy,
        preference_utility=sc.preference_utility,
        search_method="guided_v2",
    )
    assert v2_out["status"] == "TARGET_MET"
    v1_ids = tuple(sorted(a["activity_id"] for a in v1_out["selected_activities"]))
    v2_ids = tuple(sorted(a["activity_id"] for a in v2_out["selected_activities"]))
    v1_util = sc.preference_utility(v1_ids, {})
    v2_util = sc.preference_utility(v2_ids, {})
    assert v2_util >= v1_util
    # With 5 high-utility (10.0 each) preferred items available, utility should reach >= 40.0
    assert v2_util >= 40.0


def test_guided_v2_optimizes_minimum_effort_duration():
    sc = _by_id("min_effort")
    v2_out = build_plan(
        sc.planner_input,
        sc.scorer_factory(),
        personalization_strategy=sc.personalization_strategy,
        preference_utility=sc.preference_utility,
        search_method="guided_v2",
    )
    assert v2_out["status"] == "TARGET_MET"
    selected_ids = [a["activity_id"] for a in v2_out["selected_activities"]]
    # Short 30m activities are ME-24..ME-35; optimal 3-activity plan takes 90 minutes total!
    assert all(int(aid.split("-")[1]) >= 24 for aid in selected_ids)


def test_guided_v2_determinism_and_budget_cap():
    sc = _by_id("large_80")
    out1 = build_plan(sc.planner_input, sc.scorer_factory(), max_evaluations=200, search_method="guided_v2")
    out2 = build_plan(sc.planner_input, sc.scorer_factory(), max_evaluations=200, search_method="guided_v2")
    assert out1 == out2
    assert out1["search"]["evaluated_subsets"] <= 200
    assert out1["status"] == "TARGET_MET"
