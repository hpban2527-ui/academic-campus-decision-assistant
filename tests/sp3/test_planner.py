"""Planner tests with static/toy scorers; NOT real SP2 scoring tests."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import random
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import (
    CappedAdditiveScorer,
    StaticTableScorer,
    at,
    flexible_schedule,
    make_activity,
    make_candidate,
    make_planner_input,
    static_result,
)
from sp3.contract import ContractError
from sp3.plan_checker import check_plan
from sp3.planner import build_plan
from sp3.scorer_adapter import ScorerAdapter

FIXTURES = Path(__file__).resolve().parent / "fixtures"
CONTRACT_EXAMPLES = json.loads((FIXTURES / "contract_examples.json").read_text(encoding="utf-8"))["examples"]


def scenario(specs, *, scores=None, caps=None, **input_kwargs):
    """Build planner_input plus a CappedAdditiveScorer from compact specs.

    Each spec: (id, points, start, end) with optional keys in a trailing dict:
    category, domain, mode, status. Schedules are FIXED [start, end).
    """
    candidates, model = [], {}
    for spec in specs:
        activity_id, points, start, end, *rest = spec
        options = rest[0] if rest else {}
        activity = make_activity(activity_id, start, end, domain=options.get("domain", "academic"), mode=options.get("mode", "online"))
        candidates.append(make_candidate(activity, options.get("status", "FEASIBLE")))
        model[activity_id] = (options.get("category", "C1"), points)
    planner_input = make_planner_input(
        candidates, scores=scores or {"C1": 20}, caps=caps or {"C1": 30}, **input_kwargs,
    )
    return planner_input, CappedAdditiveScorer(model)


def plan(planner_input, scorer, **kwargs):
    """Run the planner, assert inputs are untouched and the checker passes."""
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, scorer, **kwargs)
    assert planner_input == snapshot
    if output["status"] not in ("ERROR", "NEEDS_DATA"):
        assert check_plan(planner_input, output, scorer, input_snapshot=snapshot) == []
    return output


def selected_ids(output):
    return [entry["activity_id"] for entry in output["selected_activities"]]


def exclusions(output):
    return {entry["activity_id"]: entry["code"] for entry in output["excluded_candidates"]}


def warning_codes(output):
    return [warning["code"] for warning in output["warnings"]]


def expected_plan_version(based_on, selected):
    """Section 10.2 plan_version, computed here independently of the implementation."""
    payload = {
        "based_on": based_on,
        "selected_activities": sorted(
            ({"activity_id": e["activity_id"], "scheduled_blocks": e["scheduled_blocks"]} for e in selected),
            key=lambda item: item["activity_id"],
        ),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sp3plan-" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


# 1. Contract section 9 examples ------------------------------------------

@pytest.mark.parametrize("example", CONTRACT_EXAMPLES, ids=[e["name"] for e in CONTRACT_EXAMPLES])
def test_contract_examples_reproduce_expected_projection(example):
    planner_input = deepcopy(example["planner_input"])
    scorer = StaticTableScorer(example["score_table"])
    output = build_plan(planner_input, scorer)
    expected = example["expected"]

    assert output["status"] == expected["status"]
    assert [
        {
            **{key: entry[key] for key in ("activity_id", "schedule_type", "scheduled_blocks", "registration", "change")},
            "reasons": [{key: reason[key] for key in ("code", "category_id", "projected_added")} for reason in entry["reasons"]],
        }
        for entry in output["selected_activities"]
    ] == expected["selected"]
    assert [{"activity_id": e["activity_id"], "code": e["code"]} for e in output["excluded_candidates"]] == expected["excluded"]
    assert output["score_summary"] == expected["score_summary"]
    assert output["feasibility_conclusion"] == expected["feasibility_conclusion"]
    assert output["search"] == expected["search"]
    assert output["proof"] == expected["proof"]
    assert warning_codes(output) == expected["warning_codes"]
    for field in ("dropped_activities", "pending_confirmation", "keep_conflicts", "score_comparison", "based_on"):
        assert output[field] == expected[field], field
    assert output["plan_version"] == expected_plan_version(expected["based_on"], expected["selected"])
    assert scorer.call_count == expected["search"]["evaluated_subsets"]
    assert len(set(scorer.calls)) == scorer.call_count
    assert output["errors"] == []
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)
    assert (output["contract_version"], output["request_id"], output["context"]) == (
        planner_input["contract_version"], planner_input["request_id"], planner_input["context"],
    )
    for entry in output["selected_activities"]:
        candidate = next(c for c in planner_input["candidates"] if c["activity"]["activity_id"] == entry["activity_id"])
        assert (entry["title"], entry["scheduled_blocks"]) == (candidate["activity"]["title"], candidate["schedule"]["fixed_blocks"])
    assert check_plan(planner_input, output, scorer, input_snapshot=example["planner_input"]) == []


# 2. ALREADY_MET and NO_FEASIBLE_CANDIDATES --------------------------------

def test_already_met_returns_empty_plan_after_one_evaluation():
    planner_input, scorer = scenario([("A", 5, at(2, 9), at(2, 10))], category_targets={"C1": 15}, total_target=20)
    output = plan(planner_input, scorer)
    assert output["status"] == "ALREADY_MET"
    assert output["feasibility_conclusion"] == "REACHABLE"
    assert output["selected_activities"] == []
    assert exclusions(output) == {"A": "LOWER_PRIORITY"}
    assert output["search"] == {"complete": False, "optimality_proven": True, "evaluated_subsets": 1, "limit_reason": "ALREADY_MET"}
    assert output["proof"] is None
    assert "SEARCH_INCOMPLETE" not in warning_codes(output)
    assert output["score_summary"]["remaining_by_category"] == {"C1": 0}
    assert output["score_summary"]["remaining_total"] == 0
    assert scorer.call_count == 1 + 1  # planner plus checker re-score


@pytest.mark.parametrize("statuses", [[], ["INFEASIBLE"], ["NEEDS_REVIEW", "INFEASIBLE"]])
def test_no_feasible_candidates_is_proven_after_empty_set(statuses):
    specs = [(f"X{i}", 5, at(2, 9 + i), at(2, 10 + i), {"status": status}) for i, status in enumerate(statuses)]
    planner_input, scorer = scenario(specs, category_targets={"C1": 25})
    output = plan(planner_input, scorer)
    assert output["status"] == "NO_FEASIBLE_CANDIDATES"
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert output["search"] == {"complete": True, "optimality_proven": True, "evaluated_subsets": 1, "limit_reason": None}
    assert output["proof"] == {"kind": "EXHAUSTIVE_SEARCH", "evaluated_subsets": 1}
    assert output["score_summary"]["remaining_by_category"] == {"C1": 5}


def test_only_already_counted_candidates_also_means_no_feasible_candidates():
    planner_input, scorer = scenario([("OLD", 5, at(2, 9), at(2, 10))], category_targets={"C1": 25}, included=["OLD"])
    output = plan(planner_input, scorer)
    assert output["status"] == "NO_FEASIBLE_CANDIDATES"
    assert exclusions(output) == {"OLD": "ALREADY_COUNTED"}


# 3. Pre-search exclusions --------------------------------------------------

def test_pre_search_exclusions_follow_contract_order_and_warn_about_pending_review():
    review = make_candidate(make_activity("R", None, None), "NEEDS_REVIEW", ["MISSING_SCHEDULE"], binding=None)
    infeasible = make_candidate(make_activity("I", at(2, 9), at(2, 10)), "INFEASIBLE", ["DEADLINE_PASSED", "INELIGIBLE"])
    counted = make_candidate(make_activity("C", at(3, 9), at(3, 10)))
    usable = make_candidate(make_activity("U", at(4, 9), at(4, 10)))
    planner_input = make_planner_input(
        [review, infeasible, counted, usable], scores={"C1": 20}, caps={"C1": 30},
        # R and I are also listed as counted: review/feasibility codes still win.
        included=["C", "I", "R"], category_targets={"C1": 25},
    )
    scorer = CappedAdditiveScorer({"U": ("C1", 5)})
    output = plan(planner_input, scorer)
    assert exclusions(output) == {"R": "NEEDS_REVIEW", "I": "NOT_FEASIBLE", "C": "ALREADY_COUNTED"}
    assert selected_ids(output) == ["U"]
    assert "PENDING_CANDIDATES" in warning_codes(output)
    messages = {e["activity_id"]: e["message"] for e in output["excluded_candidates"]}
    assert "MISSING_SCHEDULE" in messages["R"]
    assert "DEADLINE_PASSED" in messages["I"] and "INELIGIBLE" in messages["I"]


def test_excluded_candidates_are_never_sent_to_the_scorer():
    review = make_candidate(make_activity("R", at(2, 9), at(2, 10)), "NEEDS_REVIEW")
    usable = make_candidate(make_activity("U", at(3, 9), at(3, 10)))
    planner_input = make_planner_input([review, usable], scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    scorer = StaticTableScorer([
        {"selected_activity_ids": [], "result": static_result({"C1": 20}, {"C1": 20}, 100, 20, [])},
        {"selected_activity_ids": ["U"], "result": static_result({"C1": 20}, {"C1": 25}, 100, 20, [("U", "C1", 5)])},
    ])
    output = build_plan(planner_input, scorer)
    assert scorer.calls == [(), ("U",)]
    assert output["status"] == "PARTIAL"


# 4. CONFLICT ---------------------------------------------------------------

def test_conflict_exclusion_only_refers_to_a_selected_activity():
    # A overlaps B; B overlaps C; C only touches A (half-open, no overlap).
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(2, 9, 30), at(2, 10, 30)), ("C", 1, at(2, 10), at(2, 11))],
        category_targets={"C1": 25}, conflict_pairs=[["A", "B"], ["B", "C"]],
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "CONFLICT", "C": "LOWER_PRIORITY"}
    message = next(e["message"] for e in output["excluded_candidates"] if e["activity_id"] == "B")
    assert "A" in message


def test_declared_conflict_between_non_overlapping_activities_is_respected():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 30}, conflict_pairs=[["A", "B"]],
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "CONFLICT"}
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert output["search"]["evaluated_subsets"] == 3


# 5. LIMIT ------------------------------------------------------------------

def test_limit_exclusion_for_max_activities():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 30}, max_activities=1,
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "LIMIT"}
    assert output["status"] == "PARTIAL"
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert output["search"]["evaluated_subsets"] == 3


def test_limit_exclusion_for_max_duration_minutes():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 30}, max_duration_minutes=90,
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "LIMIT"}
    assert "duration" in output["excluded_candidates"][0]["message"]


def test_duration_limit_is_inclusive():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 30}, max_duration_minutes=120,
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A", "B"]
    assert output["status"] == "TARGET_MET"


@pytest.mark.parametrize("limit", [{"max_activities": 0}, {"max_duration_minutes": 0}])
def test_zero_limit_is_a_real_limit(limit):
    planner_input, scorer = scenario([("A", 5, at(2, 9), at(2, 10))], category_targets={"C1": 25}, **limit)
    output = plan(planner_input, scorer)
    assert output["selected_activities"] == []
    assert exclusions(output) == {"A": "LIMIT"}
    assert output["status"] == "PARTIAL"
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert output["proof"] == {"kind": "EXHAUSTIVE_SEARCH", "evaluated_subsets": 1}


def test_null_limits_mean_no_limit():
    specs = [(f"A{i}", 1, at(2 + i, 9), at(2 + i, 18)) for i in range(4)]
    planner_input, scorer = scenario(specs, category_targets={"C1": 24})
    output = plan(planner_input, scorer)
    assert len(selected_ids(output)) == 4
    assert output["status"] == "TARGET_MET"


# 6. Ranking ----------------------------------------------------------------

def test_category_gaps_rank_before_total_gap():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10), {"category": "C1"}), ("B", 10, at(3, 9), at(3, 10), {"category": "C2"})],
        scores={"C1": 20, "C2": 10}, caps={"C1": 30, "C2": 20},
        category_targets={"C1": 25}, total_target=45, max_activities=1,
    )
    output = plan(planner_input, scorer)
    # A: category gap 0, total gap 10. B: category gap 5, total gap 5.
    assert selected_ids(output) == ["A"]
    assert output["score_summary"]["remaining_total"] == 10


def test_fewer_activities_rank_before_preference():
    planner_input, scorer = scenario(
        [
            ("A", 5, at(2, 9), at(2, 10), {"domain": "academic"}),
            ("B", 3, at(3, 9), at(3, 10), {"domain": "skills"}),
            ("C", 2, at(4, 9), at(4, 10), {"domain": "skills"}),
        ],
        category_targets={"C1": 25}, preferred_domains=["skills"],
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "LOWER_PRIORITY", "C": "LOWER_PRIORITY"}


def test_preference_ranks_before_duration():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10), {"mode": "offline"}), ("B", 5, at(3, 9), at(3, 11), {"mode": "online"})],
        category_targets={"C1": 25}, preferred_modes=["online"],
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["B"]
    reasons = output["selected_activities"][0]["reasons"]
    assert [r["code"] for r in reasons] == ["GOAL_CONTRIBUTION", "PREFERENCE_MATCH"]
    assert reasons[1]["category_id"] is None and reasons[1]["projected_added"] is None


def test_duration_ranks_before_activity_id():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 11)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 25},
    )
    assert selected_ids(plan(planner_input, scorer)) == ["B"]


def test_activity_id_is_the_final_tie_break():
    planner_input, scorer = scenario(
        [("B", 5, at(2, 9), at(2, 10)), ("A", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 25},
    )
    assert selected_ids(plan(planner_input, scorer)) == ["A"]


def test_preference_points_count_domain_and_mode_separately():
    planner_input, scorer = scenario(
        [
            ("A", 5, at(2, 9), at(2, 10), {"domain": "skills", "mode": "offline"}),
            ("B", 5, at(3, 9), at(3, 12), {"domain": "skills", "mode": "online"}),
        ],
        category_targets={"C1": 25}, preferred_domains=["skills"], preferred_modes=["online"],
    )
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["B"]
    assert [r["message"] for r in output["selected_activities"][0]["reasons"][1:]] == [
        "Matches preferred domain skills.", "Matches preferred mode online.",
    ]


def test_selected_activities_are_presented_in_start_time_order():
    planner_input, scorer = scenario(
        [("A", 5, at(3, 9), at(3, 10)), ("B", 5, at(2, 9), at(2, 10))],
        category_targets={"C1": 30},
    )
    assert selected_ids(plan(planner_input, scorer)) == ["B", "A"]


# 7. Whole-set scoring --------------------------------------------------------

def test_rule_counted_once_per_term_does_not_add_a_second_activity():
    candidates = [make_candidate(make_activity("A", at(2, 9), at(2, 10))), make_candidate(make_activity("B", at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    before = {"C1": 20}
    scorer = StaticTableScorer([
        {"selected_activity_ids": [], "result": static_result(before, before, 100, 20, [])},
        {"selected_activity_ids": ["A"], "result": static_result(before, {"C1": 25}, 100, 20, [("A", "C1", 5)])},
        {"selected_activity_ids": ["B"], "result": static_result(before, {"C1": 25}, 100, 20, [("B", "C1", 5)])},
        # Per-term rule: the whole set scores exactly like [A].
        {"selected_activity_ids": ["A", "B"], "result": static_result(before, {"C1": 25}, 100, 20, [("A", "C1", 5), ("B", "C1", 0)])},
    ])
    output = plan(planner_input, scorer)
    assert selected_ids(output) == ["A"]
    assert exclusions(output) == {"B": "LOWER_PRIORITY"}
    assert output["score_summary"]["projected_by_category"] == {"C1": 25}
    assert output["score_summary"]["remaining_by_category"] == {"C1": 5}
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert ("A", "B") in scorer.calls


# 8. Evaluation budget --------------------------------------------------------

def test_budget_exhaustion_reports_incomplete_search_without_proof():
    specs = [(name, 1, at(2 + i, 9), at(2 + i, 10)) for i, name in enumerate("ABC")]
    planner_input, scorer = scenario(specs, category_targets={"C1": 30})
    output = plan(planner_input, scorer, max_evaluations=3)
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 3, "limit_reason": "EVALUATION_LIMIT"}
    assert output["status"] == "PARTIAL"
    assert output["feasibility_conclusion"] == "UNDETERMINED"
    assert output["proof"] is None
    assert "SEARCH_INCOMPLETE" in warning_codes(output)
    assert scorer.call_count == 3 + 1  # planner plus checker re-score


def test_budget_equal_to_valid_subset_count_completes_the_search():
    planner_input, scorer = scenario(
        [("A", 1, at(2, 9), at(2, 10)), ("B", 1, at(3, 9), at(3, 10))], category_targets={"C1": 30},
    )
    output = plan(planner_input, scorer, max_evaluations=4)
    assert output["search"]["complete"] is True
    assert output["feasibility_conclusion"] == "PROVEN_UNREACHABLE"
    assert "SEARCH_INCOMPLETE" not in warning_codes(output)


def test_budget_exhaustion_after_finding_a_plan_reports_target_met_without_optimality():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))], category_targets={"C1": 25},
    )
    output = plan(planner_input, scorer, max_evaluations=2)
    assert output["status"] == "TARGET_MET"
    assert output["feasibility_conclusion"] == "REACHABLE"
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 2, "limit_reason": "EVALUATION_LIMIT"}
    assert exclusions(output) == {"B": "LOWER_PRIORITY"}
    assert "evaluation budget" in output["excluded_candidates"][0]["message"]


def test_budget_only_covering_the_empty_set():
    planner_input, scorer = scenario([("A", 5, at(2, 9), at(2, 10))], category_targets={"C1": 25})
    output = plan(planner_input, scorer, max_evaluations=1)
    assert output["selected_activities"] == []
    assert output["search"]["limit_reason"] == "EVALUATION_LIMIT"
    assert output["feasibility_conclusion"] == "UNDETERMINED"


@pytest.mark.parametrize("budget", [0, -1, True, 2.0])
def test_invalid_budget_is_rejected(budget):
    planner_input, scorer = scenario([("A", 5, at(2, 9), at(2, 10))], category_targets={"C1": 25})
    with pytest.raises(ValueError):
        build_plan(planner_input, scorer, max_evaluations=budget)


def test_score_plan_must_be_callable():
    planner_input, _ = scenario([("A", 5, at(2, 9), at(2, 10))], category_targets={"C1": 25})
    with pytest.raises(TypeError):
        build_plan(planner_input, None)


# 9. Dominance pruning ----------------------------------------------------------

def test_dominance_pruning_keeps_optimality_and_matches_unpruned_best():
    from itertools import combinations

    specs = [
        ("A", 3, at(2, 9), at(2, 10), {"domain": "skills"}),
        ("B", 2, at(2, 11), at(2, 13)),
        ("C", 5, at(3, 9), at(3, 10), {"domain": "skills"}),
        ("D", 4, at(3, 11), at(3, 12)),
        ("E", 1, at(4, 9), at(4, 10)),
        ("F", 5, at(4, 11), at(4, 14)),
    ]
    planner_input, scorer = scenario(specs, category_targets={"C1": 28}, preferred_domains=["skills"])
    output = plan(planner_input, scorer)

    # Unpruned reference: rank every subset with the same scorer.
    by_id = {s[0]: s for s in specs}

    def rank(ids):
        request = {k: planner_input[k] for k in ("contract_version", "request_id", "context", "baseline")}
        result = scorer({**request, "selected_activity_ids": list(ids), "attribution_order": list(ids)})["result"]
        gap = max(0, 28 - result["category_after"]["C1"])
        preference = sum(1 for i in ids if len(by_id[i]) > 4 and by_id[i][4].get("domain") == "skills")
        minutes = sum((int(by_id[i][3][11:13]) - int(by_id[i][2][11:13])) * 60 for i in ids)
        return (gap, 0, len(ids), -preference, minutes, tuple(ids))

    best = min(rank(ids) for size in range(7) for ids in combinations("ABCDEF", size))
    assert tuple(selected_ids(output)) == tuple(sorted(best[5], key=lambda i: by_id[i][2]))
    assert output["status"] == "TARGET_MET"
    assert output["search"] == {"complete": False, "optimality_proven": True, "evaluated_subsets": 1 + 6 + 15, "limit_reason": None}
    assert output["proof"] is None
    assert "SEARCH_INCOMPLETE" in warning_codes(output)


def test_no_pruning_claim_when_no_larger_valid_subset_exists():
    planner_input, scorer = scenario(
        [("A", 5, at(2, 9), at(2, 10)), ("B", 5, at(3, 9), at(3, 10))],
        category_targets={"C1": 25}, max_activities=1,
    )
    output = plan(planner_input, scorer)
    assert output["search"] == {"complete": True, "optimality_proven": True, "evaluated_subsets": 3, "limit_reason": None}
    assert "SEARCH_INCOMPLETE" not in warning_codes(output)


# 10. Scorer failures ------------------------------------------------------------

def _two_candidate_input():
    candidates = [make_candidate(make_activity("A", at(2, 9), at(2, 10))), make_candidate(make_activity("B", at(3, 9), at(3, 10)))]
    return make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})


def _empty_row():
    return {"selected_activity_ids": [], "result": static_result({"C1": 20}, {"C1": 20}, 100, 20, [])}


def assert_failure(output, status, evaluated):
    assert output["status"] == status
    assert output["selected_activities"] == []
    assert output["excluded_candidates"] == []
    assert output["score_summary"] is None
    assert output["proof"] is None
    assert (output["dropped_activities"], output["keep_conflicts"], output["score_comparison"], output["plan_version"]) == ([], [], None, None)
    assert output["feasibility_conclusion"] == "UNDETERMINED"
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": evaluated, "limit_reason": "SP2_FAILURE"}
    assert warning_codes(output)[:2] == ["DEMO_ONLY", "TRAVEL_NOT_MODELED"]
    assert (output["mode"], output["official_award_verified"]) == ("DEMO_ONLY", False)


def test_scorer_needs_review_becomes_needs_data_without_scores():
    issue = {"code": "MISSING_BINDING", "message": "No trusted binding for this activity.", "activity_id": "A"}
    scorer = StaticTableScorer([_empty_row(), {"selected_activity_ids": ["A"], "evaluation_status": "NEEDS_REVIEW", "errors": [issue]}])
    output = build_plan(_two_candidate_input(), scorer)
    assert_failure(output, "NEEDS_DATA", 2)
    assert output["errors"] == [issue]


def test_scorer_error_on_empty_set_becomes_error():
    issue = {"code": "BASELINE_MISMATCH", "message": "Baseline differs from the engine.", "activity_id": None}
    scorer = StaticTableScorer([{"selected_activity_ids": [], "evaluation_status": "ERROR", "errors": [issue]}])
    output = build_plan(_two_candidate_input(), scorer)
    assert_failure(output, "ERROR", 1)
    assert output["errors"] == [issue]


def test_unlisted_static_set_fails_instead_of_inventing_a_score():
    scorer = StaticTableScorer([_empty_row()])
    output = build_plan(_two_candidate_input(), scorer)
    assert_failure(output, "ERROR", 2)
    assert output["errors"][0]["code"] == "UNSPECIFIED_SET"


def test_adapter_backend_failure_propagates_as_error():
    def backend(request):
        raise RuntimeError("secret-token leaked")

    output = build_plan(_two_candidate_input(), ScorerAdapter(backend).score_plan)
    assert_failure(output, "ERROR", 1)
    assert output["errors"][0]["code"] == "SP2_BACKEND_FAILURE"
    assert "secret-token" not in json.dumps(output)


def test_raising_scorer_is_an_error_without_leaking_exception_text():
    def scorer(request):
        raise ValueError("private student record")

    output = build_plan(_two_candidate_input(), scorer)
    assert_failure(output, "ERROR", 1)
    assert output["errors"][0]["code"] == "SP2_CALL_FAILED"
    assert "private" not in json.dumps(output)


@pytest.mark.parametrize("corrupt", [
    lambda r: r.update(request_id="another"),
    lambda r: r["context"].update(student_id="another"),
    lambda r: r.update(selected_activity_ids=["B"]),
    lambda r: r.update(official_award_verified=True),
    lambda r: r.update(evaluation_status="NEEDS_DATA"),
    lambda r: r["result"].update(total_after=99),
])
def test_malformed_scorer_response_is_an_error(corrupt):
    inner = StaticTableScorer([_empty_row()])

    def scorer(request):
        response = inner(request)
        corrupt(response)
        return response

    output = build_plan(_two_candidate_input(), scorer)
    assert_failure(output, "ERROR", 1)
    assert output["errors"][0]["code"] == "SP2_INVALID_RESPONSE"


def test_failure_keeps_pending_candidates_warning():
    candidates = [make_candidate(make_activity("R", at(2, 9), at(2, 10)), "NEEDS_REVIEW"), make_candidate(make_activity("A", at(3, 9), at(3, 10)))]
    planner_input = make_planner_input(candidates, scores={"C1": 20}, caps={"C1": 30}, category_targets={"C1": 30})
    output = build_plan(planner_input, StaticTableScorer([_empty_row()]))
    assert "PENDING_CANDIDATES" in warning_codes(output)


# 11. Invalid input ---------------------------------------------------------------

def _valid_input():
    candidates = [
        make_candidate(make_activity("A", at(2, 9), at(2, 10))),
        make_candidate(make_activity("B", at(2, 9, 30), at(2, 11))),
        make_candidate(make_activity("R", None, None), "NEEDS_REVIEW", ["MISSING_SCHEDULE"], binding=None),
    ]
    return make_planner_input(
        candidates, scores={"C1": 20, "C2": 10}, caps={"C1": 30, "C2": 20},
        category_targets={"C1": 25}, conflict_pairs=[["A", "B"]],
    )


def _candidate(data, activity_id):
    return next(c for c in data["candidates"] if c["activity"]["activity_id"] == activity_id)


def _block(data, activity_id):
    return _candidate(data, activity_id)["schedule"]["fixed_blocks"][0]


INVALID_INPUTS = {
    "unexpected_top_level_field": lambda d: d.update(extra=True),
    "missing_goals": lambda d: d.pop("goals"),
    "duplicate_activity_ids": lambda d: d["candidates"].append(deepcopy(d["candidates"][0])),
    "unknown_feasibility_status": lambda d: _candidate(d, "A")["feasibility"].update(status="APPROVED"),
    "feasible_with_reason_codes": lambda d: _candidate(d, "A")["feasibility"].update(reason_codes=["INELIGIBLE"]),
    "feasible_without_binding": lambda d: _candidate(d, "A").update(score_binding_ref=None),
    "review_without_reason_codes": lambda d: _candidate(d, "R")["feasibility"].update(reason_codes=[]),
    "lowercase_reason_code": lambda d: _candidate(d, "R")["feasibility"].update(reason_codes=["missing"]),
    "feasible_starts_before_as_of": lambda d: _block(d, "A").update(start=at(1, 7)),
    "feasible_outside_window": lambda d: _block(d, "A").update(end=at(9, 10)),
    "feasible_with_passed_deadline": lambda d: _candidate(d, "A")["activity"].update(registration_deadline=at(1, 8)),
    "feasible_without_deadline": lambda d: _candidate(d, "A")["activity"].update(registration_deadline=None),
    "feasible_end_before_start": lambda d: _block(d, "A").update(end=at(2, 8)),
    "timestamp_without_offset": lambda d: _candidate(d, "A")["activity"].update(start="2026-11-02T09:00:00"),
    "block_timestamp_without_offset": lambda d: _block(d, "A").update(start="2026-11-02T09:00:00"),
    "feasible_outside_availability": lambda d: d.update(available_intervals=[{"start": at(2, 9, 30), "end": at(3, 0)}]),
    "feasible_without_schedule": lambda d: _candidate(d, "A").update(schedule=None),
    "feasible_flexible_without_contiguous_slot": lambda d: (
        _candidate(d, "A").update(schedule=flexible_schedule(at(2, 8), at(2, 12), 60)),
        _candidate(d, "B").update(schedule=flexible_schedule(at(2, 8), at(2, 12), 30)),
        d.update(available_intervals=[{"start": at(2, 8), "end": at(2, 8, 30)}, {"start": at(2, 10), "end": at(2, 10, 30)}]),
    ),
    "flexible_duration_longer_than_window": lambda d: _candidate(d, "R").update(schedule=flexible_schedule(at(2, 9), at(2, 10), 61)),
    "unknown_schedule_type": lambda d: _candidate(d, "R").update(schedule={"type": "ASYNCHRONOUS", "duration_minutes": 30}),
    "unsorted_fixed_blocks": lambda d: _candidate(d, "R").update(schedule={"type": "FIXED", "fixed_blocks": [
        {"start": at(3, 9), "end": at(3, 10)}, {"start": at(2, 9), "end": at(2, 10)}]}),
    "missing_participation": lambda d: _candidate(d, "A").pop("participation"),
    "in_progress_participation": lambda d: _candidate(d, "A")["participation"].update(progress="IN_PROGRESS"),
    "v0_1_candidate_shape": lambda d: [_candidate(d, a).pop(k) for a in "ABR" for k in ("participation", "schedule")],
    "missing_available_intervals": lambda d: d.pop("available_intervals"),
    "reversed_available_interval": lambda d: d.update(available_intervals=[{"start": at(3, 0), "end": at(2, 0)}]),
    "missing_overlap_conflict_for_review_candidate": lambda d: _candidate(d, "R").update(
        schedule={"type": "FIXED", "fixed_blocks": [{"start": at(2, 9, 45), "end": at(2, 10, 15)}]},
    ),
    "previous_plan_without_version": lambda d: d.update(previous_plan={"based_on": {}, "selected_activities": []}),
    "keep_without_previous_plan": lambda d: d.update(keep_requests=[{"activity_id": "A", "mode": "KEEP_TIME"}]),
    "keep_activity_mode": lambda d: d.update(
        previous_plan={"plan_version": "sp3plan-00000000000000aa", "based_on": {
            "calendar_version": "c", "dataset_version": "d", "ruleset_version": "r", "baseline_ref": "b", "previous_plan_version": None,
        }, "selected_activities": [{"activity_id": "A", "scheduled_blocks": [{"start": at(2, 9), "end": at(2, 10)}]}]},
        keep_requests=[{"activity_id": "A", "mode": "KEEP_ACTIVITY"}],
    ),
    "activity_extra_field": lambda d: _candidate(d, "A")["activity"].update(planner_note="x"),
    "unsupported_mode": lambda d: _candidate(d, "A")["activity"].update(mode="remote"),
    "unsorted_conflict_pair": lambda d: d.update(conflict_pairs=[["B", "A"]]),
    "self_conflict_pair": lambda d: d.update(conflict_pairs=[["A", "A"], ["A", "B"]]),
    "unknown_conflict_id": lambda d: d.update(conflict_pairs=[["A", "B"], ["A", "Z"]]),
    "repeated_conflict_pair": lambda d: d.update(conflict_pairs=[["A", "B"], ["A", "B"]]),
    "missing_overlap_conflict": lambda d: d.update(conflict_pairs=[]),
    "no_targets": lambda d: d["goals"].update(category_targets={}),
    "unknown_target_category": lambda d: d["goals"]["category_targets"].update(C9=5),
    "negative_target": lambda d: d["goals"].update(total_target=-1),
    "boolean_target": lambda d: d["goals"].update(total_target=True),
    "unsupported_domain_preference": lambda d: d["preferences"].update(preferred_domains=["sports"]),
    "duplicate_mode_preference": lambda d: d["preferences"].update(preferred_modes=["online", "online"]),
    "negative_max_activities": lambda d: d["limits"].update(max_activities=-1),
    "boolean_max_activities": lambda d: d["limits"].update(max_activities=True),
    "float_max_activities": lambda d: d["limits"].update(max_activities=1.0),
    "nan_max_duration": lambda d: d["limits"].update(max_duration_minutes=float("nan")),
    "score_above_cap": lambda d: d["baseline"]["category_scores"].update(C1=31),
    "total_inconsistent": lambda d: d["baseline"].update(total_score=29),
    "cap_categories_differ": lambda d: d["baseline"].update(category_caps={"C1": 30}),
    "duplicate_included_ids": lambda d: d["baseline"].update(included_activity_ids=["X", "X"]),
}


@pytest.mark.parametrize("corrupt", INVALID_INPUTS.values(), ids=INVALID_INPUTS.keys())
def test_invalid_internal_input_returns_error_without_scoring(corrupt):
    data = _valid_input()
    corrupt(data)
    snapshot = deepcopy(data)
    scorer = StaticTableScorer([])
    output = build_plan(data, scorer)
    assert data == snapshot
    assert scorer.call_count == 0
    assert output["status"] == "ERROR"
    assert output["search"] == {"complete": False, "optimality_proven": False, "evaluated_subsets": 0, "limit_reason": "INVALID_INPUT"}
    assert output["errors"][0]["code"] == "INVALID_INPUT"
    assert output["errors"][0]["activity_id"] is None
    assert output["context"] == data["context"]
    assert output["score_summary"] is None and output["proof"] is None
    assert output["selected_activities"] == [] and output["excluded_candidates"] == []


def test_invalid_input_messages_do_not_echo_payload_values():
    data = _valid_input()
    _candidate(data, "A")["activity"]["mode"] = "secret-student-value"
    output = build_plan(data, StaticTableScorer([]))
    assert "secret-student-value" not in json.dumps(output)
    assert output["errors"][0]["message"].startswith("planner_input.candidates[")


def test_valid_input_fixture_is_actually_valid():
    data = _valid_input()
    scorer = CappedAdditiveScorer({"A": ("C1", 5), "B": ("C1", 5)})
    assert plan(data, scorer)["status"] == "TARGET_MET"


UNUSABLE_CONTEXTS = {
    "not_an_object": lambda d: [],
    "unsupported_version": lambda d: {**d, "contract_version": "sp3-planner/0.1"},
    "missing_version": lambda d: {k: v for k, v in d.items() if k != "contract_version"},
    "blank_request_id": lambda d: {**d, "request_id": " "},
    "missing_context": lambda d: {k: v for k, v in d.items() if k != "context"},
    "context_missing_field": lambda d: {**d, "context": {k: v for k, v in d["context"].items() if k != "baseline_ref"}},
    "context_unsupported_timezone": lambda d: {**d, "context": {**d["context"], "timezone": "UTC"}},
    "context_reversed_window": lambda d: {**d, "context": {**d["context"], "window_end": d["context"]["window_start"]}},
}


@pytest.mark.parametrize("corrupt", UNUSABLE_CONTEXTS.values(), ids=UNUSABLE_CONTEXTS.keys())
def test_unusable_context_raises_contract_error(corrupt):
    scorer = StaticTableScorer([])
    with pytest.raises(ContractError):
        build_plan(corrupt(_valid_input()), scorer)
    assert scorer.call_count == 0


# 12. Determinism -----------------------------------------------------------------

def test_shuffled_candidates_and_conflicts_give_identical_output():
    specs = [
        ("A", 3, at(2, 9), at(2, 10), {"domain": "skills"}),
        ("B", 2, at(2, 9, 30), at(2, 11)),
        ("C", 4, at(3, 9), at(3, 10)),
        ("D", 4, at(3, 9), at(3, 10), {"mode": "offline"}),
        ("E", 1, at(4, 9), at(4, 10), {"status": "NEEDS_REVIEW"}),
        ("F", 2, at(4, 9, 30), at(4, 12)),
    ]
    planner_input, scorer = scenario(
        specs, category_targets={"C1": 28}, preferred_domains=["skills", "academic"], preferred_modes=["online"],
        conflict_pairs=[["A", "B"], ["C", "D"], ["E", "F"]], max_activities=3,
    )
    reference = plan(planner_input, scorer)
    rng = random.Random(20261101)
    for _ in range(10):
        shuffled = deepcopy(planner_input)
        rng.shuffle(shuffled["candidates"])
        rng.shuffle(shuffled["conflict_pairs"])
        rng.shuffle(shuffled["preferences"]["preferred_domains"])
        assert plan(shuffled, scorer) == reference
