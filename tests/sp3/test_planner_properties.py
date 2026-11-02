"""Seeded property tests: planner vs. checker and a brute-force itertools oracle.

Scores come from CappedAdditiveScorer, a toy model; NOT real SP2 scoring.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from itertools import combinations
from pathlib import Path
import random
import sys

import pytest

# Match this branch's src layout without requiring an installed package.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from planner_doubles import CappedAdditiveScorer, make_activity, make_candidate, make_planner_input
from sp3.plan_checker import check_plan
from sp3.planner import build_plan

INSTANCES = 300
DOMAINS = ["academic", "volunteer", "culture_sports", "skills", "career", "other"]
MODES = ["online", "offline", "hybrid"]
REVIEW_CODES = ["MISSING_ELIGIBILITY", "TERM_UNVERIFIED", "NEEDS_SOURCE_REVIEW"]
INFEASIBLE_CODES = ["DEADLINE_PASSED", "OUTSIDE_AVAILABILITY", "INELIGIBLE"]


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S+07:00")


def random_instance(rng: random.Random):
    categories = ["C1", "C2", "C3"][: rng.randint(1, 3)]
    caps = {c: rng.choice([10, 20, 30]) for c in categories}
    scores = {c: rng.randint(0, caps[c]) for c in categories}
    max_total = rng.choice([100, rng.randint(max(1, sum(scores.values()) - 5), sum(caps.values()))])
    names = rng.sample(["A", "B", "C", "D", "E", "F", "G", "H", "K", "M"], rng.randint(0, 8))
    candidates, model, intervals, statuses = [], {}, {}, {}
    for name in names:
        start = datetime(2026, 11, rng.randint(2, 4), rng.randint(8, 18), rng.choice([0, 30]))
        end = start + timedelta(minutes=rng.choice([30, 60, 90, 120]))
        status = rng.choices(["FEASIBLE", "NEEDS_REVIEW", "INFEASIBLE"], weights=[8, 1, 1])[0]
        codes = {"FEASIBLE": [], "NEEDS_REVIEW": [rng.choice(REVIEW_CODES)], "INFEASIBLE": [rng.choice(INFEASIBLE_CODES)]}[status]
        activity = make_activity(name, _iso(start), _iso(end), domain=rng.choice(DOMAINS + [None]), mode=rng.choice(MODES))
        candidates.append(make_candidate(activity, status, codes))
        model[name] = (rng.choice(categories), rng.choice([0, 1, 2, 3, 5, 8]), _iso(start))
        intervals[name] = (start, end)
        statuses[name] = status
    feasible = [n for n in names if statuses[n] == "FEASIBLE"]
    included = [n for n in feasible if rng.random() < 0.1]
    pairs = set()
    for left, right in combinations(sorted(names), 2):
        (s1, e1), (s2, e2) = intervals[left], intervals[right]
        overlapping = s1 < e2 and s2 < e1
        if (overlapping and statuses[left] == statuses[right] == "FEASIBLE") or rng.random() < 0.12:
            pairs.add((left, right))
    # Targets near the baseline mix reachable, already-met and unreachable cases.
    category_targets = {c: scores[c] + rng.randint(-2, 12) for c in categories if rng.random() < 0.6}
    category_targets = {c: max(0, t) for c, t in category_targets.items()}
    baseline_total = min(sum(scores.values()), max_total)
    total_target = rng.choice([None, baseline_total + rng.randint(-2, 15)])
    if not category_targets and total_target is None:
        total_target = baseline_total + rng.randint(0, 15)
    if total_target is not None:
        total_target = max(0, total_target)
    planner_input = make_planner_input(
        candidates, scores=scores, caps=caps, max_total=max_total, included=included,
        category_targets=category_targets, total_target=total_target,
        preferred_domains=rng.sample(DOMAINS, rng.randint(0, 2)),
        preferred_modes=rng.sample(MODES, rng.randint(0, 2)),
        max_activities=rng.choice([None, None, 0, 1, 2, 3, 4]),
        max_duration_minutes=rng.choice([None, None, 0, 60, 120, 180, 240]),
        conflict_pairs=[list(pair) for pair in sorted(pairs)],
    )
    return planner_input, model


def oracle_rank(planner_input, scorer, ids):
    """Independent section-6 ranking tuple for one subset."""
    request = {k: deepcopy(planner_input[k]) for k in ("contract_version", "request_id", "context", "baseline")}
    result = scorer({**request, "selected_activity_ids": sorted(ids)})["result"]
    goals, preferences = planner_input["goals"], planner_input["preferences"]
    activities = {c["activity"]["activity_id"]: c["activity"] for c in planner_input["candidates"]}
    category_gap = sum(max(0, t - result["category_after"][c]) for c, t in goals["category_targets"].items())
    total_gap = 0 if goals["total_target"] is None else max(0, goals["total_target"] - result["total_after"])
    preference = sum(
        (activities[i]["domain"] in preferences["preferred_domains"]) + (activities[i]["mode"] in preferences["preferred_modes"])
        for i in ids
    )
    minutes = sum(
        (datetime.fromisoformat(activities[i]["end"]) - datetime.fromisoformat(activities[i]["start"])).total_seconds() / 60
        for i in ids
    )
    return (category_gap, total_gap, len(ids), -preference, minutes, tuple(sorted(ids)))


def oracle_best(planner_input, scorer):
    included = set(planner_input["baseline"]["included_activity_ids"])
    eligible = sorted(
        c["activity"]["activity_id"] for c in planner_input["candidates"]
        if c["feasibility"]["status"] == "FEASIBLE" and c["activity"]["activity_id"] not in included
    )
    conflicts = {frozenset(pair) for pair in planner_input["conflict_pairs"]}
    limits = planner_input["limits"]
    activities = {c["activity"]["activity_id"]: c["activity"] for c in planner_input["candidates"]}
    valid = []
    for size in range(len(eligible) + 1):
        for ids in combinations(eligible, size):
            if any(frozenset(pair) in conflicts for pair in combinations(ids, 2)):
                continue
            if limits["max_activities"] is not None and size > limits["max_activities"]:
                continue
            minutes = sum(
                (datetime.fromisoformat(activities[i]["end"]) - datetime.fromisoformat(activities[i]["start"])).total_seconds() / 60
                for i in ids
            )
            if limits["max_duration_minutes"] is not None and minutes > limits["max_duration_minutes"]:
                continue
            valid.append(ids)
    return min(oracle_rank(planner_input, scorer, ids) for ids in valid), len(valid)


@pytest.mark.parametrize("seed", range(INSTANCES))
def test_planner_matches_oracle_and_passes_checker(seed):
    rng = random.Random(seed)
    planner_input, model = random_instance(rng)
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, CappedAdditiveScorer(model))

    assert output["status"] not in ("ERROR", "NEEDS_DATA"), output["errors"]
    assert check_plan(planner_input, output, CappedAdditiveScorer(model), input_snapshot=snapshot) == []

    best, valid_count = oracle_best(planner_input, CappedAdditiveScorer(model))
    chosen = [entry["activity_id"] for entry in output["selected_activities"]]
    assert oracle_rank(planner_input, CappedAdditiveScorer(model), chosen) == best
    assert output["search"]["optimality_proven"] is True
    assert output["search"]["evaluated_subsets"] <= valid_count
    if output["search"]["complete"]:
        assert output["search"]["evaluated_subsets"] == valid_count

    if seed % 10 == 0:
        shuffled = deepcopy(planner_input)
        rng.shuffle(shuffled["candidates"])
        rng.shuffle(shuffled["conflict_pairs"])
        assert build_plan(shuffled, CappedAdditiveScorer(model)) == output


@pytest.mark.parametrize("seed", range(100))
def test_small_budgets_never_overclaim(seed):
    rng = random.Random(10_000 + seed)
    planner_input, model = random_instance(rng)
    budget = rng.randint(1, 12)
    output = build_plan(planner_input, CappedAdditiveScorer(model), max_evaluations=budget)

    assert check_plan(planner_input, output, CappedAdditiveScorer(model)) == []
    assert output["search"]["evaluated_subsets"] <= budget
    if output["search"]["limit_reason"] == "EVALUATION_LIMIT":
        assert output["search"]["optimality_proven"] is False
        assert output["feasibility_conclusion"] != "PROVEN_UNREACHABLE"
        assert output["proof"] is None
