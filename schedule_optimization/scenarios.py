"""Standardized synthetic & real-data scenarios for SP3 Schedule Optimization testing and benchmarking.

All scenarios produce strictly contract-compliant ``sp3-planner/0.2`` inputs so that
every algorithm output can be independently verified by ``sp3.plan_checker.check_plan``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import random
import sys
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from sp3.contract import (
    CONTRACT_VERSION,
    DEMO_MODE,
    EvaluationStatus,
    build_based_on,
    overlaps,
    plan_version,
    timestamp,
    validate_intervals,
    validate_schedule,
)

VN_TZ = timezone(timedelta(hours=7))
BASE_DAY = datetime(2026, 9, 1, 0, 0, tzinfo=VN_TZ)


def iso_at(day_offset: int, hour: int, minute: int = 0) -> str:
    return (BASE_DAY + timedelta(days=day_offset, hours=hour, minutes=minute)).isoformat()


def make_fixed_schedule(start: str, end: str) -> dict[str, Any]:
    return {"type": "FIXED", "fixed_blocks": [{"start": start, "end": end}]}


def make_flexible_schedule(window_start: str, window_end: str, duration_minutes: int) -> dict[str, Any]:
    return {
        "type": "FLEXIBLE_WINDOW",
        "window_start": window_start,
        "window_end": window_end,
        "duration_minutes": duration_minutes,
    }


class CappedMultiTierScorer:
    """Contract-compliant whole-set scorer implementing SP2's subadditive multi-tier caps.

    Each activity maps to ``(category_id, criterion_id, points)``. Points are capped
    first at criterion level, then at category level, then total clamped to [0, 100].
    """

    def __init__(
        self,
        activity_rules: Mapping[str, tuple[str, str, float]],
        category_caps: Mapping[str, float] | None = None,
        criterion_caps: Mapping[str, float] | None = None,
    ) -> None:
        self._rules = dict(activity_rules)
        self._cat_caps = dict(category_caps or {"C1": 30.0, "C2": 25.0, "C3": 25.0, "C4": 25.0, "C5": 10.0})
        self._crit_caps = dict(criterion_caps or {})
        self.calls = 0

    def __call__(self, request: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        baseline = request["baseline"]
        base_cats: dict[str, float] = {k: float(v) for k, v in baseline["category_scores"].items()}
        base_total = float(baseline["total_score"])

        order = list(request["attribution_order"])
        crit_added: dict[str, float] = {}
        cat_scores = dict(base_cats)
        contributions: list[dict[str, Any]] = []

        for aid in order:
            if aid not in self._rules:
                continue
            cat, crit, pts = self._rules[aid]
            prev_cat = cat_scores.get(cat, 0.0)
            crit_cap = self._crit_caps.get(crit, 100.0)
            used_crit = crit_added.get(crit, 0.0)
            allowed_crit = max(0.0, min(pts, crit_cap - used_crit))
            crit_added[crit] = used_crit + allowed_crit
            cat_cap = self._cat_caps.get(cat, 100.0)
            new_cat = min(cat_cap, prev_cat + allowed_crit)
            marginal = round(new_cat - prev_cat, 6)
            cat_scores[cat] = new_cat
            contributions.append(
                {
                    "activity_id": aid,
                    "category_id": cat,
                    "rule_id": crit,
                    "projected_added": marginal,
                }
            )

        cat_gain = {k: round(cat_scores[k] - base_cats[k], 6) for k in base_cats}
        total_after = min(100.0, round(base_total + sum(cat_gain.values()), 6))
        total_gain = round(total_after - base_total, 6)

        return {
            "contract_version": CONTRACT_VERSION,
            "request_id": request["request_id"],
            "context": dict(request["context"]),
            "evaluation_status": EvaluationStatus.OK.value,
            "selected_activity_ids": list(request["selected_activity_ids"]),
            "result": {
                "category_after": cat_scores,
                "category_gain": cat_gain,
                "total_after": total_after,
                "total_gain": total_gain,
                "contributions": contributions,
            },
            "errors": [],
            "mode": DEMO_MODE,
            "official_award_verified": False,
        }


def _compute_conflict_pairs(candidates: list[dict[str, Any]]) -> list[list[str]]:
    fixed: list[tuple[str, list[tuple[datetime, datetime]]]] = []
    for entry in candidates:
        sched = entry.get("schedule")
        if sched and sched["type"] == "FIXED":
            blocks = [
                (timestamp(b["start"], "s"), timestamp(b["end"], "e"))
                for b in sched["fixed_blocks"]
            ]
            fixed.append((entry["activity"]["activity_id"], blocks))
    pairs: list[list[str]] = []
    for i, (id_a, blocks_a) in enumerate(fixed):
        for id_b, blocks_b in fixed[i + 1:]:
            if any(overlaps(a, b) for a in blocks_a for b in blocks_b):
                pairs.append(sorted([id_a, id_b]))
    pairs.sort()
    return pairs


def make_candidate_entry(
    activity_id: str,
    title: str,
    domain: str,
    mode: str,
    schedule: dict[str, Any],
    *,
    registration_deadline: str | None = None,
    registration: str = "NOT_REGISTERED",
    progress: str = "NOT_STARTED",
) -> dict[str, Any]:
    if schedule["type"] == "FIXED":
        start = schedule["fixed_blocks"][0]["start"]
        end = schedule["fixed_blocks"][-1]["end"]
    else:
        start = schedule["window_start"]
        end = schedule["window_end"]
    return {
        "activity": {
            "activity_id": activity_id,
            "title": title,
            "domain": domain,
            "mode": mode,
            "start": start,
            "end": end,
            "registration_deadline": registration_deadline or iso_at(0, 23),
            "location": "ONLINE" if mode == "online" else "HCMUS Campus",
            "audience": "All HCMUS students",
            "completion_requirements": "Attendance check-in",
            "fee": 0,
            "mandatory": False,
            "points": None,
            "source": "benchmark-fixture",
        },
        "score_binding_ref": f"bind:{activity_id}",
        "schedule": schedule,
        "participation": {
            "registration": registration,
            "progress": progress,
        },
        "feasibility": {
            "status": "FEASIBLE",
            "reason_codes": [],
        },
    }


def make_planner_input(
    *,
    request_id: str,
    candidates: list[dict[str, Any]],
    baseline_scores: dict[str, float],
    total_target: float | None = None,
    category_targets: dict[str, float] | None = None,
    preferred_domains: list[str] | None = None,
    preferred_modes: list[str] | None = None,
    max_activities: int | None = None,
    max_duration_minutes: int | None = None,
    available_intervals: list[dict[str, str]] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    as_of: str | None = None,
    previous_plan: dict[str, Any] | None = None,
    keep_requests: list[dict[str, Any]] | None = None,
    category_caps: dict[str, float] | None = None,
) -> dict[str, Any]:
    w_start = window_start or iso_at(1, 0)
    w_end = window_end or iso_at(60, 23)
    now = as_of or iso_at(0, 8)
    avail = available_intervals or [{"start": iso_at(1, 7), "end": iso_at(60, 22)}]
    base_total = sum(baseline_scores.values())
    caps = dict(category_caps or {"C1": 30.0, "C2": 25.0, "C3": 25.0, "C4": 25.0, "C5": 10.0})
    return {
        "contract_version": CONTRACT_VERSION,
        "request_id": request_id,
        "context": {
            "student_id": "23120001",
            "term_id": "HK1_2026_2027",
            "dataset_version": "opt-bench/1",
            "ruleset_version": "1028/QD-KHTN-CTSV",
            "calendar_version": "cal/1",
            "baseline_ref": "base/1",
            "timezone": "Asia/Ho_Chi_Minh",
            "window_start": w_start,
            "window_end": w_end,
            "as_of": now,
        },
        "baseline": {
            "category_scores": dict(baseline_scores),
            "category_caps": caps,
            "total_score": base_total,
            "max_total_score": 100.0,
            "included_activity_ids": [],
        },
        "goals": {
            "total_target": total_target,
            "category_targets": dict(category_targets or {}),
        },
        "preferences": {
            "preferred_domains": list(preferred_domains or []),
            "preferred_modes": list(preferred_modes or []),
        },
        "limits": {
            "max_activities": max_activities,
            "max_duration_minutes": max_duration_minutes,
        },
        "available_intervals": avail,
        "candidates": candidates,
        "conflict_pairs": _compute_conflict_pairs(candidates),
        "previous_plan": previous_plan,
        "keep_requests": list(keep_requests or []),
    }


@dataclass(frozen=True)
class PlannerScenario:
    id: str
    name: str
    description: str
    planner_input: dict[str, Any]
    scorer_factory: Callable[[], CappedMultiTierScorer]
    personalization_strategy: str = "BALANCED"
    preference_utility: Callable[[tuple[str, ...], Mapping[str, Any]], float] | None = None
    exact_feasible: bool = True


def _build_small_exact_scenario() -> PlannerScenario:
    """N=10 mixed fixed/flexible activities with subadditive caps — exact ground truth."""
    candidates = [
        make_candidate_entry("A01", "AI Research Seminar", "academic", "offline", make_fixed_schedule(iso_at(2, 8), iso_at(2, 11))),
        make_candidate_entry("A02", "Math Olympiad Workshop", "academic", "offline", make_fixed_schedule(iso_at(2, 9), iso_at(2, 11))),  # conflicts A01
        make_candidate_entry("A03", "Online Security Quiz", "academic", "online", make_flexible_schedule(iso_at(2, 8), iso_at(5, 20), 45)),
        make_candidate_entry("A04", "Green Campus Cleanup", "volunteer", "offline", make_fixed_schedule(iso_at(3, 8), iso_at(3, 12))),
        make_candidate_entry("A05", "Blood Donation Drive", "volunteer", "offline", make_fixed_schedule(iso_at(3, 9), iso_at(3, 11))),  # conflicts A04
        make_candidate_entry("A06", "Civic Law Online Test", "other", "online", make_flexible_schedule(iso_at(2, 8), iso_at(6, 20), 60)),
        make_candidate_entry("A07", "Career Talk Tech", "career", "offline", make_fixed_schedule(iso_at(4, 14), iso_at(4, 16))),
        make_candidate_entry("A08", "Student Sports Day", "culture_sports", "offline", make_fixed_schedule(iso_at(5, 7), iso_at(5, 11))),
        make_candidate_entry("A09", "Soft Skills Webinar", "skills", "online", make_flexible_schedule(iso_at(3, 8), iso_at(8, 20), 90)),
        make_candidate_entry("A10", "Community Support Online", "volunteer", "online", make_flexible_schedule(iso_at(4, 8), iso_at(9, 20), 30)),
    ]
    rules = {
        "A01": ("C1", "1.9", 6.0),
        "A02": ("C1", "1.9", 5.0),
        "A03": ("C1", "1.9", 4.0),
        "A04": ("C3", "3.1", 8.0),
        "A05": ("C3", "3.1", 6.0),
        "A06": ("C4", "4.1", 5.0),
        "A07": ("C1", "1.5", 4.0),
        "A08": ("C3", "3.2", 5.0),
        "A09": ("C4", "4.2", 4.0),
        "A10": ("C3", "3.1", 3.0),
    }
    p_input = make_planner_input(
        request_id="bench-small-exact",
        candidates=candidates,
        baseline_scores={"C1": 16.0, "C2": 20.0, "C3": 14.0, "C4": 15.0, "C5": 5.0},
        total_target=84.0,
        category_targets={"C1": 22.0, "C3": 20.0, "C4": 20.0},
        preferred_domains=["academic", "volunteer"],
        preferred_modes=["online"],
    )
    return PlannerScenario(
        id="small_exact",
        name="Small Multi-Category (N=10, Exact Ground Truth)",
        description="10 mixed fixed/flexible activities with criterion caps and pairwise conflicts.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules, criterion_caps={"1.9": 8.0, "3.1": 10.0}),
        exact_feasible=True,
    )


def _build_medium_exact_scenario() -> PlannerScenario:
    """N=14 scenario where Exact Search is still feasible (~1-2s) to measure true Optimality Gap."""
    rng = random.Random(2026)
    domains = ["academic", "volunteer", "skills", "culture_sports", "career"]
    modes = ["offline", "online"]
    cats = ["C1", "C3", "C4"]
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    for i in range(14):
        aid = f"MED-{i:02d}"
        cat = cats[i % len(cats)]
        crit = f"{cat}.{i % 2}"
        pts = float(rng.choice([3, 4, 5, 6, 7]))
        dur = rng.choice([45, 60, 90, 120, 180])
        day = 2 + (i // 3)
        if i % 3 == 0:
            sched = make_flexible_schedule(iso_at(day, 8), iso_at(day + 4, 20), dur)
            mode = "online"
        else:
            start_h = 8 + (i % 3) * 3
            sched = make_fixed_schedule(iso_at(day, start_h), iso_at(day, start_h) if dur == 0 else (BASE_DAY + timedelta(days=day, hours=start_h, minutes=dur)).isoformat())
            mode = modes[i % 2]
        candidates.append(make_candidate_entry(aid, f"Medium Activity {i}", domains[i % len(domains)], mode, sched))
        rules[aid] = (cat, crit, pts)
    p_input = make_planner_input(
        request_id="bench-medium-exact",
        candidates=candidates,
        baseline_scores={"C1": 15.0, "C2": 20.0, "C3": 15.0, "C4": 15.0, "C5": 5.0},
        total_target=86.0,
        category_targets={"C1": 21.0, "C3": 21.0, "C4": 20.0},
        preferred_domains=["academic", "skills"],
        preferred_modes=["online"],
        max_activities=6,
    )
    return PlannerScenario(
        id="medium_exact",
        name="Medium Multi-Category (N=14, Exact Verifiable)",
        description="14 candidates where Exact B&B provides exact ground truth for optimality gap.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules, criterion_caps={"C1.0": 8.0, "C3.0": 8.0}),
        exact_feasible=True,
    )


def _build_multicat_blindspot_scenario() -> PlannerScenario:
    """N=36 scenario designed to expose Beam v1's top-20 singleton blind spot!

    25 C1 activities (high points, preferred domain/mode, short duration) dominate top-20 singletons.
    Only 4 C4 activities exist (longer duration, non-preferred domain) — needed to meet C4 target!
    """
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    for i in range(26):
        aid = f"C1-{i:02d}"
        sched = make_flexible_schedule(iso_at(2, 8), iso_at(20, 20), 30 + (i % 3) * 15)
        candidates.append(make_candidate_entry(aid, f"Tech Seminar {i}", "academic", "online", sched))
        rules[aid] = ("C1", f"1.{i % 4}", 6.0)
    for i in range(6):
        aid = f"C3-{i:02d}"
        sched = make_flexible_schedule(iso_at(2, 8), iso_at(20, 20), 90 + i * 10)
        candidates.append(make_candidate_entry(aid, f"Volunteer Event {i}", "volunteer", "offline", sched))
        rules[aid] = ("C3", "3.1", 5.0)
    for i in range(4):
        aid = f"C4-{i:02d}"
        sched = make_flexible_schedule(iso_at(2, 8), iso_at(20, 20), 150 + i * 15)
        candidates.append(make_candidate_entry(aid, f"Civic Workshop {i}", "other", "offline", sched))
        rules[aid] = ("C4", "4.1", 4.0)

    p_input = make_planner_input(
        request_id="bench-multicat-blindspot",
        candidates=candidates,
        baseline_scores={"C1": 18.0, "C2": 20.0, "C3": 15.0, "C4": 15.0, "C5": 5.0},
        total_target=88.0,
        category_targets={"C1": 24.0, "C3": 20.0, "C4": 23.0},
        preferred_domains=["academic"],
        preferred_modes=["online"],
        max_activities=5,
    )
    return PlannerScenario(
        id="multicat_blindspot",
        name="Multi-Category Blind-Spot Stress (N=36)",
        description="26 high-scoring C1 items flood top-20 singletons; C4 requires 2 longer non-preferred items.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules),
        exact_feasible=False,
    )


def _build_replan_stability_scenario() -> PlannerScenario:
    """N=30 replan scenario where retaining previous activities minimizes set_changes."""
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    for i in range(30):
        aid = f"RP-{i:02d}"
        day = 2 + (i // 2)
        sched = make_flexible_schedule(iso_at(day, 8), iso_at(day + 6, 20), 60 + (i % 4) * 30)
        cat = ["C1", "C3", "C4"][i % 3]
        candidates.append(make_candidate_entry(aid, f"Activity {i}", ["academic", "volunteer", "other"][i % 3], "online", sched))
        rules[aid] = (cat, f"{cat}.1", 5.0 if i < 20 else 6.0)

    # Previous plan selected RP-00 (C1), RP-01 (C3), RP-02 (C4) — all still eligible,
    # while RP-20..29 give slightly more points (6 vs 5) so naive greedy would churn the whole plan!
    prev_selected = [
        {"activity_id": "RP-00", "scheduled_blocks": [{"start": iso_at(2, 8), "end": iso_at(2, 9)}]},
        {"activity_id": "RP-01", "scheduled_blocks": [{"start": iso_at(2, 10), "end": iso_at(2, 11, 30)}]},
        {"activity_id": "RP-02", "scheduled_blocks": [{"start": iso_at(3, 8), "end": iso_at(3, 10)}]},
    ]
    prev_based_on = {
        "dataset_version": "opt-bench/1",
        "ruleset_version": "1028/QD-KHTN-CTSV",
        "calendar_version": "cal/1",
        "baseline_ref": "base/1",
        "previous_plan_version": None,
    }
    prev_plan = {
        "plan_version": plan_version(
            prev_based_on, [(item["activity_id"], item["scheduled_blocks"]) for item in prev_selected]
        ),
        "based_on": prev_based_on,
        "selected_activities": prev_selected,
    }
    p_input = make_planner_input(
        request_id="bench-replan-stability",
        candidates=candidates,
        baseline_scores={"C1": 15.0, "C2": 20.0, "C3": 15.0, "C4": 15.0, "C5": 5.0},
        total_target=85.0,
        category_targets={"C1": 20.0, "C3": 20.0, "C4": 20.0},
        previous_plan=prev_plan,
        keep_requests=[],
    )
    return PlannerScenario(
        id="replan_stability",
        name="Replan Stability (N=30, 3 Retained)",
        description="Previous 3 activities already meet targets with 0 set_changes; tests churn avoidance.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules),
        exact_feasible=False,
    )


def _build_personalization_pref_first_scenario() -> PlannerScenario:
    """N=32 PREFERENCE_FIRST scenario with custom preference_utility."""
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    utility_map: dict[str, float] = {}
    for i in range(32):
        aid = f"PF-{i:02d}"
        sched = make_flexible_schedule(iso_at(2, 8), iso_at(25, 20), 60 + (i % 3) * 30)
        cat = ["C1", "C3"][i % 2]
        domain = "academic" if i >= 24 else "other"
        mode = "online" if i >= 20 else "offline"
        candidates.append(make_candidate_entry(aid, f"Pref Activity {i}", domain, mode, sched))
        rules[aid] = (cat, f"{cat}.1", 4.0 if i >= 24 else 6.0)
        # Higher-index activities have much higher personalized utility!
        utility_map[aid] = 10.0 if i >= 24 else 1.0

    def pref_util(aids: tuple[str, ...], _res: Mapping[str, Any]) -> float:
        return sum(utility_map.get(a, 0.0) for a in aids)

    p_input = make_planner_input(
        request_id="bench-pref-first",
        candidates=candidates,
        baseline_scores={"C1": 18.0, "C2": 20.0, "C3": 18.0, "C4": 15.0, "C5": 5.0},
        total_target=86.0,
        category_targets={"C1": 22.0, "C3": 22.0},
        preferred_domains=["academic"],
        preferred_modes=["online"],
        max_activities=5,
    )
    return PlannerScenario(
        id="pref_first",
        name="Personalization PREFERENCE_FIRST (N=32)",
        description="High-utility preferred activities give slightly fewer points; tests utility maximization.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules),
        personalization_strategy="PREFERENCE_FIRST",
        preference_utility=pref_util,
        exact_feasible=False,
    )


def _build_min_effort_scenario() -> PlannerScenario:
    """N=36 MINIMUM_EFFORT scenario where short-duration activities meet targets with minimal time."""
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    for i in range(36):
        aid = f"ME-{i:02d}"
        # First 24 are long (180-240m) with 6 pts; last 12 are short (30-45m) with 5 pts
        dur = 30 if i >= 24 else 180 + (i % 3) * 30
        pts = 5.0 if i >= 24 else 6.0
        cat = ["C1", "C3", "C4"][i % 3]
        sched = make_flexible_schedule(iso_at(2, 8), iso_at(25, 20), dur)
        candidates.append(make_candidate_entry(aid, f"Effort Activity {i}", "academic", "online", sched))
        rules[aid] = (cat, f"{cat}.1", pts)

    p_input = make_planner_input(
        request_id="bench-min-effort",
        candidates=candidates,
        baseline_scores={"C1": 15.0, "C2": 20.0, "C3": 15.0, "C4": 15.0, "C5": 5.0},
        total_target=85.0,
        category_targets={"C1": 20.0, "C3": 20.0, "C4": 20.0},
        max_activities=4,
    )
    return PlannerScenario(
        id="min_effort",
        name="Personalization MINIMUM_EFFORT (N=36)",
        description="Short 30m activities vs long 180-240m activities; tests duration minimization.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules),
        personalization_strategy="MINIMUM_EFFORT",
        preference_utility=lambda aids, _r: float(len(aids)),
        exact_feasible=False,
    )


def _build_large_scale_scenario(n: int = 80) -> PlannerScenario:
    """Large-scale catalog (N=80) with dense fixed conflicts, flexible windows, and 3-tier caps."""
    rng = random.Random(1028 + n)
    domains = ["academic", "volunteer", "skills", "culture_sports", "career", "other"]
    modes = ["offline", "online"]
    cats = ["C1", "C2", "C3", "C4", "C5"]
    candidates = []
    rules: dict[str, tuple[str, str, float]] = {}
    for i in range(n):
        aid = f"LG-{i:03d}"
        cat = cats[i % len(cats)]
        crit = f"{cat}.{i % 3}"
        pts = float(rng.choice([2, 3, 4, 5, 6, 8]))
        dur = rng.choice([30, 45, 60, 90, 120, 180])
        day = 2 + (i % 25)
        if i % 2 == 0:
            sched = make_flexible_schedule(iso_at(day, 8), iso_at(day + 7, 20), dur)
            mode = "online"
        else:
            start_h = rng.choice([8, 9, 13, 14, 15])
            end_dt = BASE_DAY + timedelta(days=day, hours=start_h, minutes=dur)
            sched = make_fixed_schedule(iso_at(day, start_h), end_dt.isoformat())
            mode = "offline"
        candidates.append(make_candidate_entry(aid, f"Campus Event {i}", domains[i % len(domains)], mode, sched))
        rules[aid] = (cat, crit, pts)

    p_input = make_planner_input(
        request_id=f"bench-large-{n}",
        candidates=candidates,
        baseline_scores={"C1": 14.0, "C2": 18.0, "C3": 12.0, "C4": 14.0, "C5": 4.0},
        total_target=88.0,
        category_targets={"C1": 22.0, "C3": 20.0, "C4": 20.0},
        preferred_domains=["academic", "skills"],
        preferred_modes=["online"],
        max_activities=8,
    )
    return PlannerScenario(
        id=f"large_{n}",
        name=f"Large Scale Catalog (N={n})",
        description=f"{n} mixed fixed/flexible activities across 5 categories with dense conflicts and caps.",
        planner_input=p_input,
        scorer_factory=lambda: CappedMultiTierScorer(rules, criterion_caps={"C1.0": 8.0, "C3.0": 8.0, "C4.0": 8.0}),
        exact_feasible=False,
    )


def get_all_planner_scenarios() -> list[PlannerScenario]:
    return [
        _build_small_exact_scenario(),
        _build_medium_exact_scenario(),
        _build_multicat_blindspot_scenario(),
        _build_replan_stability_scenario(),
        _build_personalization_pref_first_scenario(),
        _build_min_effort_scenario(),
        _build_large_scale_scenario(80),
    ]


def build_tight_scheduler_instance(k: int, *, seed: int = 42, tight: bool = False) -> tuple[dict[str, Any], Any, dict[str, Any]]:
    """Build an inner-scheduler test instance with k flexible activities."""
    rng = random.Random(seed + k)
    w_start = iso_at(1, 8)
    w_end = iso_at(45, 20)
    avail_raw = [{"start": iso_at(d, 8), "end": iso_at(d, 18)} for d in range(1, 45)]
    available = validate_intervals(avail_raw, "available")
    schedules = {}

    if tight:
        # Pack k activities tightly inside a small set of days with staggered deadlines
        # so naive ECT fails when short-slack / early-deadline items are delayed.
        cursor = BASE_DAY + timedelta(days=1, hours=8)
        for i in range(k):
            dur = rng.choice([45, 60, 75, 90])
            # Staggered release before cursor, tight deadline right after
            rel = max(BASE_DAY + timedelta(days=1, hours=8), cursor - timedelta(minutes=rng.choice([0, 30, 60])))
            dl = cursor + timedelta(minutes=dur + rng.choice([0, 15, 30]))
            # Keep within daily 08:00-18:00 window
            if dl.hour >= 18 or (dl.hour == 17 and dl.minute > 45):
                cursor = (cursor + timedelta(days=1)).replace(hour=8, minute=0)
                rel = cursor
                dl = cursor + timedelta(minutes=dur + 15)
            schedules[f"TIGHT-{i:02d}"] = validate_schedule(
                make_flexible_schedule(rel.isoformat(), dl.isoformat(), dur), f"tight[{i}]"
            )
            cursor = cursor + timedelta(minutes=dur)
    else:
        for i in range(k):
            start_day = 1 + (i % 30)
            end_day = min(44, start_day + rng.choice([2, 3, 5, 7]))
            schedules[f"FLEX-{i:02d}"] = validate_schedule(
                make_flexible_schedule(iso_at(start_day, 8), iso_at(end_day, 18), 90), f"flex[{i}]"
            )

    options = {
        "window_start": timestamp(w_start, "ws"),
        "window_end": timestamp(w_end, "we"),
        "as_of": timestamp(iso_at(0, 8), "as_of"),
    }
    return schedules, available, options
