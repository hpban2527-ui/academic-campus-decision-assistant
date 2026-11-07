"""Seeded property tests: planner vs. checker and independent brute-force oracles.

Scores come from CappedAdditiveScorer, a toy model; NOT real SP2 scoring.
The fixed-schedule oracle enumerates subsets with itertools; the replan
oracle also tries every 15-minute grid placement of every flexible activity.
Neither imports the planner, the scheduler or the checker.
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

from planner_doubles import (
    CappedAdditiveScorer,
    fixed_schedule,
    flexible_schedule,
    keep,
    make_activity,
    make_candidate,
    make_planner_input,
    make_previous_plan,
)
from sp3.plan_checker import check_plan
from sp3.planner import build_plan

INSTANCES = 100
REPLAN_INSTANCES = 100
DOMAINS = ["academic", "volunteer", "culture_sports", "skills", "career", "other"]
MODES = ["online", "offline", "hybrid"]
REVIEW_CODES = ["MISSING_ELIGIBILITY", "TERM_UNVERIFIED", "NEEDS_SOURCE_REVIEW"]
INFEASIBLE_CODES = ["DEADLINE_PASSED", "OUTSIDE_AVAILABILITY", "INELIGIBLE"]


def _iso(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%S+07:00")


def _targets(rng, categories, scores, max_total):
    # Targets near the baseline mix reachable, already-met and unreachable cases.
    category_targets = {c: max(0, scores[c] + rng.randint(-2, 12)) for c in categories if rng.random() < 0.6}
    baseline_total = min(sum(scores.values()), max_total)
    total_target = rng.choice([None, baseline_total + rng.randint(-2, 15)])
    if not category_targets and total_target is None:
        total_target = baseline_total + rng.randint(0, 15)
    return category_targets, None if total_target is None else max(0, total_target)


def _scores(rng):
    categories = ["C1", "C2", "C3"][: rng.randint(1, 3)]
    caps = {c: rng.choice([10, 20, 30]) for c in categories}
    scores = {c: rng.randint(0, caps[c]) for c in categories}
    max_total = rng.choice([100, rng.randint(max(1, sum(scores.values()) - 5), sum(caps.values()))])
    return categories, caps, scores, max_total


def random_instance(rng: random.Random):
    """Fixed single-session schedules, no previous plan (the v0.1 shape of the problem)."""
    categories, caps, scores, max_total = _scores(rng)
    names = rng.sample(["A", "B", "C", "D", "E", "F", "G", "H", "K", "M"], rng.randint(0, 8))
    candidates, model, intervals, statuses = [], {}, {}, {}
    for name in names:
        start = datetime(2026, 11, rng.randint(2, 4), rng.randint(8, 18), rng.choice([0, 30]))
        end = start + timedelta(minutes=rng.choice([30, 60, 90, 120]))
        status = rng.choices(["FEASIBLE", "NEEDS_REVIEW", "INFEASIBLE"], weights=[8, 1, 1])[0]
        codes = {"FEASIBLE": [], "NEEDS_REVIEW": [rng.choice(REVIEW_CODES)], "INFEASIBLE": [rng.choice(INFEASIBLE_CODES)]}[status]
        activity = make_activity(name, _iso(start), _iso(end), domain=rng.choice(DOMAINS + [None]), mode=rng.choice(MODES))
        candidates.append(make_candidate(activity, status, codes))
        model[name] = (rng.choice(categories), rng.choice([0, 1, 2, 3, 5, 8]))
        intervals[name] = (start, end)
        statuses[name] = status
    feasible = [n for n in names if statuses[n] == "FEASIBLE"]
    included = [n for n in feasible if rng.random() < 0.1]
    pairs = set()
    for left, right in combinations(sorted(names), 2):
        (s1, e1), (s2, e2) = intervals[left], intervals[right]
        # Section 6.5: every overlapping FIXED pair is listed, whatever its status.
        if (s1 < e2 and s2 < e1) or rng.random() < 0.12:
            pairs.add((left, right))
    category_targets, total_target = _targets(rng, categories, scores, max_total)
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
    """Independent section 9 ranking tuple for one subset without a previous plan."""
    request = {k: deepcopy(planner_input[k]) for k in ("contract_version", "request_id", "context", "baseline")}
    result = scorer({**request, "selected_activity_ids": sorted(ids), "attribution_order": sorted(ids)})["result"]
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
    return (category_gap, total_gap, 0, 0, len(ids), -preference, minutes, tuple(sorted(ids)))


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


@pytest.mark.parametrize("seed", range(30))
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


# Mixed fixed/flexible schedules with a previous plan and keep requests ----------------

GRID_BASE = datetime(2026, 11, 2, 8, 0)
GRID_SLOTS = 24  # 15-minute slots, 08:00-14:00


def _slot(index: int) -> str:
    return _iso(GRID_BASE + timedelta(minutes=15 * index))


def replan_instance(rng: random.Random):
    """Grid instance in slots plus the planner_input built from it."""
    categories, caps, scores, max_total = _scores(rng)
    busy = set()
    for _ in range(rng.randint(0, 3)):
        start = rng.randint(0, GRID_SLOTS - 1)
        busy |= set(range(start, start + rng.randint(1, 5)))
    free = [cell for cell in range(GRID_SLOTS) if cell not in busy]
    spec = {"free": set(free), "activities": {}, "previous": {}, "keep": []}
    names = rng.sample(list("ABCDEFG"), rng.randint(1, 7))
    for name in sorted(names):
        if rng.random() < 0.45:
            start = rng.randint(0, GRID_SLOTS - 2)
            blocks = [(start, min(GRID_SLOTS, start + rng.randint(1, 4)))]
            if rng.random() < 0.25 and blocks[0][1] + 2 < GRID_SLOTS:
                second = rng.randint(blocks[0][1], GRID_SLOTS - 1)
                blocks.append((second, min(GRID_SLOTS, second + rng.randint(1, 3))))
            spec["activities"][name] = ("FIXED", tuple(blocks))
        else:
            window_start = rng.randint(0, GRID_SLOTS - 4)
            window_end = min(GRID_SLOTS, window_start + rng.randint(4, 16))
            spec["activities"][name] = ("FLEXIBLE", (window_start, window_end), rng.randint(1, min(4, window_end - window_start)))
    available = []
    for cell in free:
        if available and available[-1][1] == cell:
            available[-1] = (available[-1][0], cell + 1)
        else:
            available.append((cell, cell + 1))

    candidates, model, statuses = [], {}, {}
    for name, activity_spec in spec["activities"].items():
        alone = _fits_alone(spec, activity_spec)
        status, codes, progress = ("FEASIBLE", [], "NOT_STARTED") if alone else ("INFEASIBLE", ["OUTSIDE_AVAILABILITY"], "NOT_STARTED")
        roll = rng.random()
        if roll < 0.07:
            status, codes = "NEEDS_REVIEW", [rng.choice(REVIEW_CODES)]
        elif roll < 0.12:
            status, codes, progress = "INFEASIBLE", ["ALREADY_COMPLETED"], "COMPLETED"
        elif roll < 0.17:
            status, codes, progress = "INFEASIBLE", ["CANCELLED"], "CANCELLED"
        if activity_spec[0] == "FIXED":
            schedule = fixed_schedule(*((_slot(s), _slot(e)) for s, e in activity_spec[1]))
            start, end = _slot(activity_spec[1][0][0]), _slot(activity_spec[1][-1][1])
        else:
            schedule = flexible_schedule(_slot(activity_spec[1][0]), _slot(activity_spec[1][1]), activity_spec[2] * 15)
            start, end = _slot(activity_spec[1][0]), _slot(activity_spec[1][1])
        activity = make_activity(name, start, end, domain=rng.choice(DOMAINS), mode=rng.choice(MODES))
        registration = "REGISTERED" if rng.random() < 0.3 else "NOT_REGISTERED"
        candidates.append(make_candidate(activity, status, codes, schedule=schedule, registration=registration, progress=progress))
        model[name] = (rng.choice(categories), rng.choice([0, 1, 2, 3, 5, 8]))
        statuses[name] = (status, progress)
    pairs = set()
    fixed = [n for n, s in spec["activities"].items() if s[0] == "FIXED"]
    for left, right in combinations(sorted(spec["activities"]), 2):
        overlapping = left in fixed and right in fixed and any(
            a < d and c < b for a, b in spec["activities"][left][1] for c, d in spec["activities"][right][1]
        )
        if overlapping or rng.random() < 0.05:
            pairs.add((left, right))
    spec["conflicts"] = {frozenset(pair) for pair in pairs}
    spec["statuses"] = statuses

    previous_plan, keep_requests = None, []
    if rng.random() < 0.75:
        chosen = [n for n in sorted(spec["activities"]) if rng.random() < 0.5]
        if rng.random() < 0.15:
            chosen.append("Z")  # no longer listed
        blocks = {}
        for name in chosen:
            activity_spec = spec["activities"].get(name)
            if activity_spec is None:
                start = rng.randint(0, GRID_SLOTS - 2)
                blocks[name] = ((start, start + 1),)
            elif activity_spec[0] == "FIXED":
                shift = 0 if rng.random() < 0.8 else rng.choice([-1, 1])
                blocks[name] = tuple((s + shift, e + shift) for s, e in activity_spec[1])
            else:
                (low, high), duration = activity_spec[1], activity_spec[2]
                start = rng.randint(low, high - duration) if rng.random() < 0.85 else rng.randint(max(0, low - 2), high)
                blocks[name] = ((start, start + duration),)
        spec["previous"] = blocks
        previous_plan = make_previous_plan({n: [(_slot(s), _slot(e)) for s, e in b] for n, b in blocks.items()})
        if blocks and rng.random() < 0.35:
            spec["keep"] = rng.sample(sorted(blocks), rng.randint(1, min(2, len(blocks))))
            keep_requests = keep(*spec["keep"])
    included = [n for n in spec["activities"] if statuses[n] == ("FEASIBLE", "NOT_STARTED") and rng.random() < 0.08]
    spec["included"] = set(included)
    category_targets, total_target = _targets(rng, categories, scores, max_total)
    planner_input = make_planner_input(
        candidates, scores=scores, caps=caps, max_total=max_total, included=included,
        category_targets=category_targets, total_target=total_target,
        preferred_domains=rng.sample(DOMAINS, rng.randint(0, 2)),
        preferred_modes=rng.sample(MODES, rng.randint(0, 2)),
        max_activities=rng.choice([None, None, 1, 2, 3, 4]),
        max_duration_minutes=rng.choice([None, None, 30, 60, 120, 180]),
        conflict_pairs=[list(pair) for pair in sorted(pairs)],
        available=[(_slot(s), _slot(e)) for s, e in available],
        previous_plan=previous_plan,
        keep_requests=keep_requests,
    )
    return planner_input, model, spec


def _fits_alone(spec, activity_spec) -> bool:
    free = spec["free"]
    if activity_spec[0] == "FIXED":
        return all(set(range(s, e)) <= free for s, e in activity_spec[1])
    (low, high), duration = activity_spec[1], activity_spec[2]
    return any(set(range(s, s + duration)) <= free for s in range(low, high - duration + 1))


def grid_min_changes(spec, ids) -> int | None:
    """Minimum time changes over every valid grid placement of ``ids``; None if none exists."""
    activities, previous, kept = spec["activities"], spec["previous"], set(spec["keep"])
    taken: set[int] = set()
    changes = 0
    flexible = []
    for name in sorted(ids):
        activity_spec = activities[name]
        if name in kept:
            blocks = previous[name]
        elif activity_spec[0] == "FIXED":
            blocks = activity_spec[1]
            changes += name in previous and previous[name] != blocks
        else:
            flexible.append(name)
            continue
        for s, e in blocks:
            cells = set(range(s, e))
            if not cells <= spec["free"] or cells & taken:
                return None
            taken |= cells
    best = [None]

    def place(index: int, used: set[int], count: int) -> None:
        if best[0] is not None and count >= best[0]:
            return
        if index == len(flexible):
            best[0] = count
            return
        name = flexible[index]
        (low, high), duration = activities[name][1], activities[name][2]
        for start in range(low, high - duration + 1):
            cells = set(range(start, start + duration))
            if cells <= spec["free"] and not cells & used:
                moved = name in previous and previous[name] != ((start, start + duration),)
                place(index + 1, used | cells, count + moved)

    place(0, taken, changes)
    return best[0]


def replan_oracle(planner_input, spec, scorer):
    """Best section 9 rank over every valid superset of the kept set, and the valid count."""
    goals, preferences, limits = planner_input["goals"], planner_input["preferences"], planner_input["limits"]
    candidates = {c["activity"]["activity_id"]: c for c in planner_input["candidates"]}
    eligible = sorted(n for n, (status, progress) in spec["statuses"].items() if status == "FEASIBLE" and progress == "NOT_STARTED" and n not in spec["included"])
    kept = set(spec["keep"])
    retained = {
        n for n in spec["previous"]
        if n not in spec["included"] and not (n in spec["statuses"] and spec["statuses"][n][1] == "COMPLETED")
    }
    minutes = {
        n: sum(e - s for s, e in a[1]) * 15 if a[0] == "FIXED" else a[2] * 15
        for n, a in spec["activities"].items()
    }
    ranks = {}
    for size in range(len(eligible) + 1):
        for ids in combinations(eligible, size):
            if not kept <= set(ids) or any(frozenset(pair) in spec["conflicts"] for pair in combinations(ids, 2)):
                continue
            if limits["max_activities"] is not None and size > limits["max_activities"]:
                continue
            if limits["max_duration_minutes"] is not None and sum(minutes[i] for i in ids) > limits["max_duration_minutes"]:
                continue
            time_changes = grid_min_changes(spec, ids)
            if time_changes is None:
                continue
            request = {k: deepcopy(planner_input[k]) for k in ("contract_version", "request_id", "context", "baseline")}
            result = scorer({**request, "selected_activity_ids": list(ids), "attribution_order": list(ids)})["result"]
            category_gap = sum(max(0, t - result["category_after"][c]) for c, t in goals["category_targets"].items())
            total_gap = 0 if goals["total_target"] is None else max(0, goals["total_target"] - result["total_after"])
            preference = sum(
                (candidates[i]["activity"]["domain"] in preferences["preferred_domains"]) + (candidates[i]["activity"]["mode"] in preferences["preferred_modes"])
                for i in ids
            )
            if planner_input["previous_plan"] is None:
                set_changes, time_changes = 0, 0
            else:
                set_changes = len(retained - set(ids)) + len(set(ids) - retained)
            ranks[ids] = (category_gap, total_gap, set_changes, time_changes, size, -preference, sum(minutes[i] for i in ids), ids)
    return ranks


@pytest.mark.parametrize("seed", range(REPLAN_INSTANCES))
def test_replan_planner_matches_grid_oracle_and_passes_checker(seed):
    planner_input, model, spec = replan_instance(random.Random(70_000 + seed))
    snapshot = deepcopy(planner_input)
    output = build_plan(planner_input, CappedAdditiveScorer(model))

    assert output["status"] not in ("ERROR", "NEEDS_DATA"), output["errors"]
    assert check_plan(planner_input, output, CappedAdditiveScorer(model), input_snapshot=snapshot) == []
    if output["status"] == "KEEP_CONFLICT":
        assert spec["keep"] and output["keep_conflicts"]
        return

    ranks = replan_oracle(planner_input, spec, CappedAdditiveScorer(model))
    chosen = tuple(sorted(entry["activity_id"] for entry in output["selected_activities"]))
    assert ranks[chosen] == min(ranks.values())
    moved = sum(entry["change"] == "MOVED" for entry in output["selected_activities"])
    assert moved == ranks[chosen][3]
    assert output["search"]["optimality_proven"] is True
    if output["search"]["complete"]:
        assert output["search"]["evaluated_subsets"] == len(ranks)


def test_replan_instances_cover_the_interesting_cases():
    statuses, kinds = set(), set()
    for seed in range(REPLAN_INSTANCES):
        planner_input, model, spec = replan_instance(random.Random(70_000 + seed))
        output = build_plan(planner_input, CappedAdditiveScorer(model))
        statuses.add(output["status"])
        kinds |= {entry["change"] for entry in output["selected_activities"]}
        kinds |= {"DROPPED_" + entry["code"] for entry in output["dropped_activities"]}
        kinds |= {"EXCLUDED_" + entry["code"] for entry in output["excluded_candidates"]}
        kinds |= {entry["schedule_type"] for entry in output["selected_activities"]}
    assert {"TARGET_MET", "PARTIAL", "KEEP_CONFLICT"} <= statuses
    assert {"KEPT", "MOVED", "ADDED", "FIXED", "FLEXIBLE_WINDOW", "EXCLUDED_NO_TIME", "DROPPED_NOT_LISTED"} <= kinds
    assert {"DROPPED_LOWER_PRIORITY", "DROPPED_NO_LONGER_FEASIBLE", "DROPPED_CANCELLED"} & kinds
