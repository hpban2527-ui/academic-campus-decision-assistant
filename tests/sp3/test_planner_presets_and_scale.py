"""Tests for SP3 multi-objective presets, multi-criteria filters, multi-plan recommendations, and large-scale performance."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from pathlib import Path
import sys
import time
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from api.sp3_service import demo_plan
from planner_doubles import (
    CappedAdditiveScorer,
    at,
    flexible_schedule,
    make_activity,
    make_candidate,
    make_planner_input,
)
from sp3.plan_checker import check_plan
from sp3.planner import (
    AVAILABLE_PRESETS,
    PlanFilters,
    PresetMode,
    SpeedMode,
    build_plan,
    recommend_plans,
)


def _make_rich_candidate(
    activity_id: str,
    points: float,
    start: str | None,
    end: str | None,
    *,
    category: str = "C1",
    domain: str = "academic",
    mode: str = "online",
    location: str | None = "Zoom",
    fee: float = 0,
    mandatory: bool = False,
    schedule: dict[str, Any] | None = None,
    status: str = "FEASIBLE",
) -> tuple[dict[str, Any], tuple[str, float]]:
    act = make_activity(activity_id, start, end, domain=domain, mode=mode)
    act["location"] = location
    act["points"] = points
    act["fee"] = fee
    act["mandatory"] = mandatory
    cand = make_candidate(
        act,
        status=status,
        binding=category,
        schedule=schedule if schedule is not None else make_candidate(act)["schedule"],
    )
    return cand, (category, points)


def _build_multi_criteria_fixture() -> tuple[dict[str, Any], CappedAdditiveScorer]:
    """Construct a fixture where different presets pick demonstrably different optimal schedules.

    Baseline: C1=20 (cap 30), C3=10 (cap 25), total=30.
    Target: total_target=40 (need +10 points), category_targets={"C1": 25} (need +5 in C1).
    Preferences: preferred_domains=["academic"], preferred_modes=["in_person"].
    """
    specs = [
        # Option 1 (MIN_TIME): Two short 30-min activities (total 60 mins) giving +5 C1, +5 C3 = +10
        _make_rich_candidate("FAST_C1", 5, at(2, 8, 0), at(2, 8, 30), category="C1", domain="academic", mode="online", location="Zoom"),
        _make_rich_candidate("FAST_C3", 5, at(2, 8, 30), at(2, 9, 0), category="C3", domain="culture_sports", mode="online", location="Zoom"),
        # Option 2 (MIN_ACTIVITIES): Single 180-min activity giving +10 C1 = +10 in 1 activity
        _make_rich_candidate("ONE_BIG_C1", 10, at(2, 10, 0), at(2, 13, 0), category="C1", domain="skills", mode="hybrid", location="Hall A, CS1"),
        # Option 3 (PREFERENCE_FIRST): Matches both preferred domain="academic" & mode="offline" at CS2 Thu Duc (120 mins)
        _make_rich_candidate("PREF_MATCH", 10, at(3, 9, 0), at(3, 11, 0), category="C1", domain="academic", mode="offline", location="Room E201, CS2 Thu Duc", mandatory=True),
        # Option 4 (EXTRA_POINTS for MAX_SCORE): Adds +15 in C3 (120 mins)
        _make_rich_candidate("HIGH_C3", 15, at(4, 9, 0), at(4, 11, 0), category="C3", domain="volunteer", mode="offline", location="CS1 Nguyen Van Cu", fee=50000),
    ]
    candidates = [item[0] for item in specs]
    model = {item[0]["activity"]["activity_id"]: item[1] for item in specs}
    planner_input = make_planner_input(
        candidates,
        scores={"C1": 20, "C3": 10},
        caps={"C1": 30, "C3": 25},
        category_targets={"C1": 25},
        total_target=40,
        preferred_domains=["academic"],
        preferred_modes=["offline"],
        max_activities=3,
        max_duration_minutes=360,
    )
    return planner_input, CappedAdditiveScorer(model)


# 1. Preset Differentiated Selection & Contract Validity -------------------

def test_all_presets_produce_valid_distinct_priorities():
    planner_input, scorer = _build_multi_criteria_fixture()

    by_preset: dict[str, dict[str, Any]] = {}
    for preset in PresetMode:
        out = build_plan(planner_input, scorer, preset=preset)
        assert out["status"] == "TARGET_MET"
        assert check_plan(planner_input, out, scorer, input_snapshot=deepcopy(planner_input)) == []
        by_preset[preset.value] = out

    # MIN_ACTIVITIES picks a 1-activity plan ("ONE_BIG_C1" or "PREF_MATCH")
    min_act_ids = [a["activity_id"] for a in by_preset["min_activities"]["selected_activities"]]
    assert len(min_act_ids) == 1
    assert min_act_ids == ["ONE_BIG_C1"] or min_act_ids == ["PREF_MATCH"]

    # MIN_TIME picks the 60-minute total duration pair ["FAST_C1", "FAST_C3"]
    min_time_ids = [a["activity_id"] for a in by_preset["min_time"]["selected_activities"]]
    assert set(min_time_ids) == {"FAST_C1", "FAST_C3"}

    # MAX_SCORE achieves the maximum possible score (20+10 + 10+15 = 55 total points)
    max_score_summary = by_preset["max_score"]["score_summary"]
    assert max_score_summary["projected_total"] == 55
    assert "HIGH_C3" in {a["activity_id"] for a in by_preset["max_score"]["selected_activities"]}

    # ONLINE_FIRST selects 100% online activities (FAST_C1 + FAST_C3)
    online_ids = [a["activity_id"] for a in by_preset["online_first"]["selected_activities"]]
    assert set(online_ids) == {"FAST_C1", "FAST_C3"}

    # PREFERENCE_FIRST picks PREF_MATCH (matches both academic + in_person + mandatory)
    pref_ids = [a["activity_id"] for a in by_preset["preference_first"]["selected_activities"]]
    assert pref_ids == ["PREF_MATCH"]


# 2. Multi-Criteria Filters (Location, Domain, Mode, Fee, Mandatory, Hours) -

def test_multi_criteria_filters_location_fee_and_mandatory():
    planner_input, scorer = _build_multi_criteria_fixture()

    # Filter 1: Only activities at CS2 Thu Duc
    out_cs2 = build_plan(
        planner_input,
        scorer,
        preset="balanced",
        filters={"location_keywords": ["CS2", "Thu Duc"]},
    )
    assert check_plan(planner_input, out_cs2, scorer) == []
    assert [a["activity_id"] for a in out_cs2["selected_activities"]] == ["PREF_MATCH"]

    # Filter 2: Mandatory only
    out_mandatory = build_plan(
        planner_input,
        scorer,
        preset="balanced",
        filters=PlanFilters(mandatory_only=True),
    )
    assert check_plan(planner_input, out_mandatory, scorer) == []
    assert [a["activity_id"] for a in out_mandatory["selected_activities"]] == ["PREF_MATCH"]

    # Filter 3: Max fee = 0 with MAX_SCORE preset excludes HIGH_C3 (fee=50000)
    out_free_max = build_plan(
        planner_input,
        scorer,
        preset="max_score",
        filters={"max_fee": 0},
    )
    assert check_plan(planner_input, out_free_max, scorer) == []
    selected_free = {a["activity_id"] for a in out_free_max["selected_activities"]}
    assert "HIGH_C3" not in selected_free
    assert out_free_max["score_summary"]["projected_total"] == 45

    # Filter 4: Allowed modes = ["online"] only
    out_online_only = build_plan(
        planner_input,
        scorer,
        preset="max_score",
        filters={"allowed_modes": ["online"]},
    )
    assert check_plan(planner_input, out_online_only, scorer) == []
    assert {a["activity_id"] for a in out_online_only["selected_activities"]} == {"FAST_C1", "FAST_C3"}


# 3. Dynamic Multi-Plan Recommendation (0, 1, or Many Plans) ---------------

def test_recommend_plans_dynamic_count_zero_one_and_many():
    # Case A: 0 plans when no feasible candidate matches filter or none exist
    planner_input, scorer = _build_multi_criteria_fixture()
    rec_zero = recommend_plans(
        planner_input,
        scorer,
        filters={"location_keywords": ["NonExistentCampus"]},
    )
    assert rec_zero["plans"] == []
    assert rec_zero["plan_summaries"] == []
    assert rec_zero["primary_plan"]["status"] == "PARTIAL"
    assert check_plan(planner_input, rec_zero["primary_plan"], scorer) == []

    # Case B1: 1 plan when baseline already meets targets (ALREADY_MET)
    already_input, already_scorer = _build_multi_criteria_fixture()
    already_input["goals"] = {"total_target": 25, "category_targets": {"C1": 15}}
    rec_already = recommend_plans(already_input, already_scorer, preset="balanced")
    assert len(rec_already["plans"]) == 1
    assert rec_already["primary_plan"]["status"] == "ALREADY_MET"
    assert rec_already["plan_summaries"][0]["activity_count"] == 0

    # Case B2: 1 plan when only a single candidate exists
    single_cand, single_model = _make_rich_candidate("ONLY_ONE", 10, at(2, 9), at(2, 11), category="C1")
    single_input = make_planner_input(
        [single_cand],
        scores={"C1": 20},
        caps={"C1": 30},
        category_targets={"C1": 25},
        total_target=30,
    )
    rec_one = recommend_plans(single_input, CappedAdditiveScorer({"ONLY_ONE": single_model}), max_plans=5)
    assert len(rec_one["plans"]) == 1
    assert rec_one["plan_summaries"][0]["activity_ids"] == ["ONLY_ONE"]
    assert check_plan(single_input, rec_one["plans"][0], CappedAdditiveScorer({"ONLY_ONE": single_model})) == []

    # Case C: Multiple diverse plans when several distinct valid schedules exist
    rec_many = recommend_plans(
        planner_input,
        scorer,
        preset="balanced",
        max_plans=5,
        min_jaccard_distance=0.2,
    )
    assert 3 <= len(rec_many["plans"]) <= 5
    seen_versions: set[str] = set()
    seen_sets: set[tuple[str, ...]] = set()
    for p, summary in zip(rec_many["plans"], rec_many["plan_summaries"]):
        assert check_plan(planner_input, p, scorer) == []
        assert p["plan_version"] not in seen_versions
        seen_versions.add(p["plan_version"])
        act_tuple = tuple(summary["activity_ids"])
        assert act_tuple not in seen_sets
        seen_sets.add(act_tuple)
        assert summary["meets_targets"] is True

    # Ensure the diverse plans cover distinct strategies (1-activity, fast 2-activity, high-score 3-activity)
    assert ("PREF_MATCH",) in seen_sets or ("ONE_BIG_C1",) in seen_sets
    assert ("FAST_C1", "FAST_C3") in seen_sets
    assert any("HIGH_C3" in s for s in seen_sets)


# 4. Large-Scale Performance & Quality-Speed Trade-off (N = 100, 250, 500) -

def _generate_large_scale_input(n_candidates: int, *, include_flexible: int = 20) -> tuple[dict[str, Any], CappedAdditiveScorer]:
    """Generate a realistic large-scale planner_input with ``n_candidates`` activities across 7 days."""
    base_start = datetime.fromisoformat("2026-11-02T08:00:00+07:00")
    domains = ["academic", "skills", "culture_sports", "volunteer", "career", "other"]
    modes = ["online", "offline", "hybrid"]
    locations = ["CS1 Nguyen Van Cu", "CS2 Thu Duc", "Zoom Online", "Hall I CS1"]
    categories = ["C1", "C3", "C4", "C5"]

    candidates: list[dict[str, Any]] = []
    model: dict[str, tuple[str, float]] = {}
    fixed_intervals: list[tuple[str, datetime, datetime]] = []

    for i in range(n_candidates):
        aid = f"ACT-{i:04d}"
        cat = categories[i % len(categories)]
        dom = domains[i % len(domains)]
        mode = modes[i % len(modes)]
        loc = locations[i % len(locations)]
        pts = float(2 + (i % 5) * 2)  # 2, 4, 6, 8, 10 points
        day_offset = i % 5  # Nov 2 .. Nov 6 (strictly after as_of = Nov 1 08:00)
        slot_in_day = (i // 5) % 8  # 8 slots per day
        duration_mins = 45 + (i % 3) * 30  # 45, 75, 105 mins

        if i < include_flexible:
            # Flexible window activity
            w_start = (base_start + timedelta(days=day_offset)).isoformat()
            w_end = (base_start + timedelta(days=day_offset, hours=12)).isoformat()
            sched = flexible_schedule(w_start, w_end, duration_mins)
            cand, entry = _make_rich_candidate(
                aid, pts, None, None, category=cat, domain=dom, mode=mode, location=loc, schedule=sched
            )
        else:
            st_dt = base_start + timedelta(days=day_offset, minutes=slot_in_day * 60)
            en_dt = st_dt + timedelta(minutes=duration_mins)
            fixed_intervals.append((aid, st_dt, en_dt))
            cand, entry = _make_rich_candidate(
                aid, pts, st_dt.isoformat(), en_dt.isoformat(), category=cat, domain=dom, mode=mode, location=loc
            )
        candidates.append(cand)
        model[aid] = entry

    # Build exact conflict pairs for overlapping FIXED schedules
    conflict_pairs: list[list[str]] = []
    for idx_a, (id_a, sa, ea) in enumerate(fixed_intervals):
        for id_b, sb, eb in fixed_intervals[idx_a + 1 :]:
            if max(sa, sb) < min(ea, eb):
                pair = sorted((id_a, id_b))
                conflict_pairs.append(pair)
    conflict_pairs.sort()

    avail = [
        (
            (base_start + timedelta(days=d)).isoformat(),
            (base_start + timedelta(days=d, hours=13)).isoformat(),
        )
        for d in range(6)
    ]

    planner_input = make_planner_input(
        candidates,
        scores={"C1": 10, "C3": 5, "C4": 5, "C5": 0},
        caps={"C1": 30, "C3": 25, "C4": 25, "C5": 10},
        category_targets={"C1": 24, "C3": 17, "C4": 15},
        total_target=62,
        preferred_domains=["academic", "volunteer"],
        preferred_modes=["online"],
        max_activities=8,
        max_duration_minutes=600,
        available=avail,
        conflict_pairs=conflict_pairs,
    )
    return planner_input, CappedAdditiveScorer(model)


@pytest.mark.parametrize("n_candidates", [100, 250, 500])
def test_large_scale_candidates_speed_and_validity(n_candidates: int):
    planner_input, scorer = _generate_large_scale_input(n_candidates, include_flexible=25)

    for mode in (SpeedMode.FAST, SpeedMode.BALANCED):
        t0 = time.perf_counter()
        rec = recommend_plans(
            planner_input,
            scorer,
            preset=PresetMode.BALANCED,
            speed_mode=mode,
            max_plans=4,
        )
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        assert rec["primary_plan"]["status"] == "TARGET_MET"
        assert len(rec["plans"]) >= 2
        # Verify contract compliance via independent check_plan
        assert check_plan(planner_input, rec["primary_plan"], scorer) == []
        # Even at N=500, fast & balanced modes complete well under 1.5 seconds
        assert elapsed_ms < 1500.0, f"N={n_candidates} in {mode.value} took {elapsed_ms:.1f}ms"


def test_speed_mode_quality_vs_evaluation_tradeoff():
    planner_input, _ = _generate_large_scale_input(200, include_flexible=15)

    results = {}
    for mode in (SpeedMode.FAST, SpeedMode.BALANCED, SpeedMode.OPTIMAL):
        _, mode_scorer = _generate_large_scale_input(200, include_flexible=15)
        rec = recommend_plans(
            planner_input,
            mode_scorer,
            preset=PresetMode.MAX_SCORE,
            speed_mode=mode,
            max_plans=3,
        )
        results[mode] = rec

    assert (
        results[SpeedMode.FAST]["candidate_stats"]["evaluated_subsets"]
        <= results[SpeedMode.BALANCED]["candidate_stats"]["evaluated_subsets"]
        <= results[SpeedMode.OPTIMAL]["candidate_stats"]["evaluated_subsets"]
    )
    assert (
        results[SpeedMode.FAST]["primary_plan"]["score_summary"]["projected_total"]
        <= results[SpeedMode.OPTIMAL]["primary_plan"]["score_summary"]["projected_total"]
    )


def test_sp3_service_demo_plan_supports_presets_and_multi_plan():
    res = demo_plan("first_plan", preset="max_score", speed_mode="balanced", max_plans=4)
    assert res["mode"] == "DEMO_ONLY"
    assert res["preset"] == "max_score"
    assert "recommended_plans" in res
    assert len(res["recommended_plans"]) >= 1
    assert set(res["available_presets"].keys()) == set(AVAILABLE_PRESETS.keys())


def test_fast_flexible_edf_handles_more_than_sixteen_flexible_activities():
    """Verify that fast_flexible schedules >16 flexible activities in milliseconds without hitting UNDETERMINED."""
    from sp3.scheduler import ScheduleStatus, schedule_set
    from sp3.contract import validate_intervals, validate_schedule, timestamp

    w_start_str = "2026-11-02T08:00:00+07:00"
    w_end_str = "2026-11-06T20:00:00+07:00"
    as_of_str = "2026-11-01T08:00:00+07:00"
    avail = validate_intervals([{"start": w_start_str, "end": w_end_str}], "avail")

    # 20 flexible activities (exceeds MAX_FLEXIBLE_PER_SET = 16)
    activities = {
        f"FLEX-{i:02d}": validate_schedule(
            flexible_schedule(w_start_str, w_end_str, 60),
            f"flex[{i}]",
        )
        for i in range(20)
    }
    w_start = timestamp(w_start_str, "ws")
    w_end = timestamp(w_end_str, "we")
    as_of = timestamp(as_of_str, "ao")

    # Standard exact mode returns UNDETERMINED when > 16 flexible activities
    exact_res = schedule_set(activities, avail, window_start=w_start, window_end=w_end, as_of=as_of, fast_flexible=False)
    assert exact_res.status is ScheduleStatus.UNDETERMINED

    # Fast flexible mode places all 20 activities in O(k^2) time (< 25ms)
    t0 = time.perf_counter()
    fast_res = schedule_set(activities, avail, window_start=w_start, window_end=w_end, as_of=as_of, fast_flexible=True)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    assert fast_res.status is ScheduleStatus.SCHEDULED
    assert len(fast_res.blocks) == 20
    assert elapsed_ms < 25.0


def test_preferred_hours_and_keep_conflict_handling():
    planner_input, scorer = _build_multi_criteria_fixture()
    # Prefer morning hours 8:00 - 10:00
    rec = recommend_plans(
        planner_input,
        scorer,
        preset="preference_first",
        filters={"preferred_hours": [(8, 10)], "preferred_locations": ["CS2"]},
    )
    assert rec["primary_plan"]["status"] == "TARGET_MET"
    assert len(rec["plans"]) >= 1
    assert check_plan(planner_input, rec["primary_plan"], scorer) == []

