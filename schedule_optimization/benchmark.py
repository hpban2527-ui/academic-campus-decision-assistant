"""Reproducible Benchmark Suite for SP3 Schedule Suggestion Optimization.

Compares:
  1. Outer Planner methods: exact (B&B), greedy (baseline), beam_v1 (original guided),
     and guided_v2 (category/replan/personalization-aware + 1-swap local search).
  2. Inner Scheduler methods: exact_dp (Bitmask DP), fast_v1 (Greedy EDF v1),
     and fast_v2 (Available-EDF + O(log|F|) carving + Replan Hold).

Run:
    python schedule_optimization/benchmark.py
Outputs:
    schedule_optimization/results/benchmark_results.json
    schedule_optimization/results/benchmark_report.md
"""
from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import sys
import time
import tracemalloc
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from schedule_optimization.scenarios import (
    PlannerScenario,
    build_tight_scheduler_instance,
    get_all_planner_scenarios,
    iso_at,
    make_flexible_schedule,
)
from sp3.contract import timestamp, validate_schedule
from sp3.plan_checker import check_plan
from sp3.planner import build_plan
from sp3.scheduler import ScheduleStatus, schedule_set

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _total_duration(planner_input: dict[str, Any], selected_ids: list[str]) -> float:
    by_id = {c["activity"]["activity_id"]: c for c in planner_input["candidates"]}
    total = 0.0
    for aid in selected_ids:
        sched = by_id[aid]["schedule"]
        if sched["type"] == "FLEXIBLE_WINDOW":
            total += float(sched["duration_minutes"])
        else:
            for blk in sched["fixed_blocks"]:
                s = timestamp(blk["start"], "s")
                e = timestamp(blk["end"], "e")
                total += (e - s).total_seconds() / 60.0
    return round(total, 1)


def _pref_matches_count(planner_input: dict[str, Any], selected_ids: list[str]) -> int:
    by_id = {c["activity"]["activity_id"]: c["activity"] for c in planner_input["candidates"]}
    pref_domains = set(planner_input["preferences"]["preferred_domains"])
    pref_modes = set(planner_input["preferences"]["preferred_modes"])
    total = 0
    for aid in selected_ids:
        act = by_id[aid]
        if act["domain"] in pref_domains:
            total += 1
        if act["mode"] in pref_modes:
            total += 1
    return total


def _set_changes(planner_input: dict[str, Any], selected_ids: list[str]) -> int:
    prev = planner_input.get("previous_plan")
    if not prev:
        return 0
    retained = {a["activity_id"] for a in prev["selected_activities"]}
    chosen = set(selected_ids)
    return len(retained - chosen) + len(chosen - retained)


def run_planner_benchmarks() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for sc in get_all_planner_scenarios():
        methods = (["exact"] if sc.exact_feasible else []) + ["greedy", "beam_v1", "guided_v2"]
        exact_ref: dict[str, Any] | None = None

        for method in methods:
            scorer = sc.scorer_factory()
            t0 = time.perf_counter()
            out = build_plan(
                sc.planner_input,
                scorer,
                personalization_strategy=sc.personalization_strategy,
                preference_utility=sc.preference_utility,
                search_method=method,
            )
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            violations = check_plan(sc.planner_input, out, sc.scorer_factory())

            sel_ids = sorted(a["activity_id"] for a in out["selected_activities"])
            summary = out["score_summary"] or {}
            rem_cats = summary.get("remaining_by_category") or {}
            cat_gap = round(sum(float(v) for v in rem_cats.values()), 4)
            tot_gap = float(summary.get("remaining_total") or 0.0)
            dur = _total_duration(sc.planner_input, sel_ids)
            pref_cnt = _pref_matches_count(sc.planner_input, sel_ids)
            util = round(float(sc.preference_utility(tuple(sel_ids), {})), 2) if sc.preference_utility else None
            changes = _set_changes(sc.planner_input, sel_ids)

            row = {
                "scenario_id": sc.id,
                "scenario_name": sc.name,
                "catalog_size": len(sc.planner_input["candidates"]),
                "strategy": sc.personalization_strategy,
                "method": method,
                "status": out["status"],
                "projected_total": summary.get("projected_total", 0.0),
                "category_gap": cat_gap,
                "total_gap": tot_gap,
                "selected_count": len(sel_ids),
                "selected_ids": sel_ids,
                "pref_matches": pref_cnt,
                "duration_min": dur,
                "utility": util,
                "set_changes": changes,
                "evaluated_subsets": out["search"]["evaluated_subsets"],
                "optimality_proven": out["search"]["optimality_proven"],
                "latency_ms": round(elapsed_ms, 2),
                "contract_valid": len(violations) == 0,
            }
            if method == "exact":
                exact_ref = row
            if exact_ref is not None:
                row["matches_exact_targets_and_size"] = (
                    row["status"] == exact_ref["status"]
                    and row["category_gap"] == exact_ref["category_gap"]
                    and row["total_gap"] == exact_ref["total_gap"]
                    and row["selected_count"] == exact_ref["selected_count"]
                    and row["duration_min"] <= exact_ref["duration_min"] + 1e-6
                )
            else:
                row["matches_exact_targets_and_size"] = None
            rows.append(row)
    return rows


def run_scheduler_benchmarks() -> dict[str, Any]:
    # 1. Scalability benchmark: k = 4..64
    scale_rows: list[dict[str, Any]] = []
    for k in (4, 8, 12, 14, 16, 24, 32, 48, 64):
        schedules, available, options = build_tight_scheduler_instance(k, seed=42, tight=False)
        entry: dict[str, Any] = {"k": k, "dp_states": (1 << k) if k <= 16 else None}

        if k <= 16:
            tracemalloc.start()
            t0 = time.perf_counter()
            dp_res = schedule_set(schedules, available, max_flexible_per_set=16, fast_flexible=False, **options)
            dp_ms = (time.perf_counter() - t0) * 1000.0
            _, dp_peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            entry["exact_dp_ms"] = round(dp_ms, 3)
            entry["exact_dp_kb"] = round(dp_peak / 1024.0, 1)
            entry["exact_dp_status"] = dp_res.status.value
        else:
            entry["exact_dp_ms"] = None
            entry["exact_dp_kb"] = None
            entry["exact_dp_status"] = "CAPPED (>16)"

        for mode in ("v1", "v2"):
            t0 = time.perf_counter()
            res = schedule_set(schedules, available, max_flexible_per_set=0, fast_flexible=True, fast_mode=mode, **options)
            ms = (time.perf_counter() - t0) * 1000.0
            entry[f"fast_{mode}_ms"] = round(ms, 3)
            entry[f"fast_{mode}_status"] = res.status.value

        scale_rows.append(entry)

    # 2. Tight-window feasibility benchmark (20 instances at k=14)
    tight_exact_ok = 0
    tight_v1_ok = 0
    tight_v2_ok = 0
    for seed in range(1, 21):
        schedules, available, options = build_tight_scheduler_instance(14, seed=seed * 13, tight=True)
        e_res = schedule_set(schedules, available, max_flexible_per_set=16, fast_flexible=False, **options)
        v1_res = schedule_set(schedules, available, max_flexible_per_set=0, fast_flexible=True, fast_mode="v1", **options)
        v2_res = schedule_set(schedules, available, max_flexible_per_set=0, fast_flexible=True, fast_mode="v2", **options)
        if e_res.status is ScheduleStatus.SCHEDULED:
            tight_exact_ok += 1
        if v1_res.status is ScheduleStatus.SCHEDULED:
            tight_v1_ok += 1
        if v2_res.status is ScheduleStatus.SCHEDULED:
            tight_v2_ok += 1

    # 3. Replan stability benchmark at k=24 (22 retained + 2 urgent early-window additions)
    schedules_22, available, options = build_tight_scheduler_instance(22, seed=11, tight=False)
    init = schedule_set(schedules_22, available, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    replan_scheds = dict(schedules_22)
    for idx in range(2):
        replan_scheds[f"URGENT-{idx:02d}"] = validate_schedule(
            make_flexible_schedule(iso_at(1, 8), iso_at(3, 18), 60), f"urgent[{idx}]"
        )
    t0 = time.perf_counter()
    rep_v1 = schedule_set(replan_scheds, available, previous_blocks=init.blocks, max_flexible_per_set=16, fast_flexible=True, fast_mode="v1", **options)
    rep_v1_ms = (time.perf_counter() - t0) * 1000.0
    t0 = time.perf_counter()
    rep_v2 = schedule_set(replan_scheds, available, previous_blocks=init.blocks, max_flexible_per_set=16, fast_flexible=True, fast_mode="v2", **options)
    rep_v2_ms = (time.perf_counter() - t0) * 1000.0

    return {
        "scalability": scale_rows,
        "tight_windows_k14": {
            "total_instances": 20,
            "exact_dp_scheduled": tight_exact_ok,
            "fast_v1_scheduled": tight_v1_ok,
            "fast_v2_scheduled": tight_v2_ok,
        },
        "replan_k24": {
            "fast_v1_time_changes": rep_v1.time_changes,
            "fast_v1_ms": round(rep_v1_ms, 3),
            "fast_v2_time_changes": rep_v2.time_changes,
            "fast_v2_ms": round(rep_v2_ms, 3),
        },
    }


def render_markdown_report(planner_rows: list[dict[str, Any]], sched_data: dict[str, Any]) -> str:
    lines = [
        "# SP3 Schedule Suggestion Optimization — Benchmark Report",
        "",
        f"Generated: `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`",
        "",
        "## 1. Outer Planner Comparison (Exact vs Greedy vs Beam v1 vs Guided v2)",
        "",
        "| Scenario | Method | Status | Score | Cat Gap | Activities | Pref | Duration (m) | Utility | Set Changes | Evals | Latency (ms) | Contract |",
        "| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |",
    ]
    for r in planner_rows:
        util_s = "—" if r["utility"] is None else f"{r['utility']:.1f}"
        chg_s = str(r["set_changes"]) if r["scenario_id"] == "replan_stability" else "—"
        valid_s = "PASS" if r["contract_valid"] else "FAIL"
        lines.append(
            f"| {r['scenario_id']} (N={r['catalog_size']}) | `{r['method']}` | `{r['status']}` "
            f"| {r['projected_total']:.1f} | {r['category_gap']:.1f} | {r['selected_count']} "
            f"| {r['pref_matches']} | {r['duration_min']:.0f} | {util_s} | {chg_s} | {r['evaluated_subsets']} "
            f"| {r['latency_ms']:.2f} | {valid_s} |"
        )

    lines.extend([
        "",
        "## 2. Inner Scheduler Comparison (Exact Bitmask DP vs Fast v1 vs Fast v2)",
        "",
        "### 2.1 Scalability ($k = 4 \\dots 64$ flexible activities)",
        "",
        "| $k$ | DP States ($2^k$) | Exact DP (ms) | Exact DP Mem (KB) | Fast v1 (ms) | Fast v2 (ms) | Status (v2) |",
        "| :---: | :---: | :---: | :---: | :---: | :---: | :--- |",
    ])
    for s in sched_data["scalability"]:
        states = f"{s['dp_states']:,}" if s["dp_states"] is not None else "Capped (>16)"
        dp_ms = f"{s['exact_dp_ms']:.3f}" if s["exact_dp_ms"] is not None else "—"
        dp_kb = f"{s['exact_dp_kb']:.1f}" if s["exact_dp_kb"] is not None else "—"
        lines.append(
            f"| {s['k']} | {states} | {dp_ms} | {dp_kb} | {s['fast_v1_ms']:.3f} | {s['fast_v2_ms']:.3f} | `{s['fast_v2_status']}` |"
        )

    tw = sched_data["tight_windows_k14"]
    rp = sched_data["replan_k24"]
    lines.extend([
        "",
        "### 2.2 Tight-Window Feasibility Rate (20 instances at $k = 14$)",
        "",
        f"- **Exact Bitmask DP**: `{tw['exact_dp_scheduled']}/{tw['total_instances']}` scheduled",
        f"- **Fast v1 (Greedy EDF v1)**: `{tw['fast_v1_scheduled']}/{tw['total_instances']}` scheduled",
        f"- **Fast v2 (Available-EDF + Fast Carving)**: `{tw['fast_v2_scheduled']}/{tw['total_instances']}` scheduled",
        "",
        "### 2.3 Replan Stability Above Cap ($k = 24$: 22 retained + 2 new)",
        "",
        f"- **Fast v1**: `time_changes = {rp['fast_v1_time_changes']}` ({rp['fast_v1_ms']:.3f} ms)",
        f"- **Fast v2 (Replan Hold)**: `time_changes = {rp['fast_v2_time_changes']}` ({rp['fast_v2_ms']:.3f} ms)",
        "",
    ])
    return "\n".join(lines)


def main() -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    planner_rows = run_planner_benchmarks()
    sched_data = run_scheduler_benchmarks()

    payload = {
        "generated_at": datetime.now().isoformat(),
        "planner": planner_rows,
        "scheduler": sched_data,
    }
    json_path = RESULTS_DIR / "benchmark_results.json"
    md_path = RESULTS_DIR / "benchmark_report.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_text = render_markdown_report(planner_rows, sched_data)
    md_path.write_text(md_text, encoding="utf-8")
    print(md_text)
    print(f"\nSaved JSON -> {json_path}")
    print(f"Saved Report -> {md_path}")


if __name__ == "__main__":
    main()
