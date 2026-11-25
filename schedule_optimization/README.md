# SP3 Schedule Suggestion Optimization Module

Self-contained workspace for testing, benchmarking, and visually verifying the **SP3 Schedule Suggestion Optimization** algorithms without touching teammate API/UI files (`src/api/*`, `web/index.html`).

## Directory Layout

- Core algorithm upgrades (backwards-compatible with `sp3-planner/0.2`):
  - `src/sp3/scheduler.py`: Exact Bitmask DP ($k \le 16$) + Fast v2 Scheduler ($k > 16$: Dynamic Available-EDF, $\mathcal{O}(\log |\mathcal{F}|)$ interval carving, and Replan Block Hold).
  - `src/sp3/planner.py`: Exact Branch-and-Bound ($N \le 12$) + Guided Search v2 ($N > 12$: Category/Replan/Personalization-aware pool, rollouts, beam search, and deterministic 1-Prune / 1-Swap / 1-Add local search), plus `search_method` parameter (`auto`, `exact`, `greedy`, `beam_v1`, `guided_v2`).
- Dedicated test suite:
  - `tests/sp3_optimization/test_scheduler_opt.py`
  - `tests/sp3_optimization/test_planner_opt.py`
- Benchmark, Analysis & Mock UI lab (`schedule_optimization/`):
  - `ALGORITHM_ANALYSIS.md` — Formal 2-level formulation, algorithm design, proofs, and time/space complexity analysis (Inner & Outer).
  - `scenarios.py` — 7 standardized planner scenarios + inner-scheduler stress generators.
  - `benchmark.py` — Reproducible CLI benchmark comparing Outer (`exact`, `greedy`, `beam_v1`, `guided_v2`) and Inner (`exact_dp`, `fast_v1`, `fast_v2`).
  - `mock_ui_server.py` & `mock_ui.html` — Zero-dependency local Mock UI for live algorithm comparison, schedule inspection, what-if skip, and benchmark execution.
  - `results/benchmark_report.md` & `results/benchmark_results.json` — Generated empirical results.

## Quick Commands

```bash
# 1. Run dedicated optimization tests
python -m pytest tests/sp3_optimization -v

# 2. Verify full SP3 regression suite (1005 existing + 33 new)
python -m pytest tests/sp3 tests/sp3_optimization -q

# 3. Run reproducible benchmark & regenerate report
python schedule_optimization/benchmark.py

# 4. Launch standalone Mock UI (http://127.0.0.1:8765)
python schedule_optimization/mock_ui_server.py --port 8765
```
