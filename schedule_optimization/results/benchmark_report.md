# SP3 Schedule Suggestion Optimization — Benchmark Report

Generated: `2026-11-19 12:46:36`

## 1. Outer Planner Comparison (Exact vs Greedy vs Beam v1 vs Guided v2)

| Scenario | Method | Status | Score | Cat Gap | Activities | Pref | Duration (m) | Utility | Set Changes | Evals | Latency (ms) | Contract |
| :--- | :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| small_exact (N=10) | `exact` | `TARGET_MET` | 87.0 | 0.0 | 3 | 3 | 360 | — | — | 158 | 14.59 | PASS |
| small_exact (N=10) | `greedy` | `TARGET_MET` | 89.0 | 0.0 | 3 | 3 | 480 | — | — | 13 | 1.75 | PASS |
| small_exact (N=10) | `beam_v1` | `TARGET_MET` | 87.0 | 0.0 | 3 | 3 | 360 | — | — | 116 | 12.45 | PASS |
| small_exact (N=10) | `guided_v2` | `TARGET_MET` | 87.0 | 0.0 | 3 | 3 | 360 | — | — | 125 | 12.00 | PASS |
| medium_exact (N=14) | `exact` | `TARGET_MET` | 89.0 | 0.0 | 3 | 6 | 330 | — | — | 470 | 50.43 | PASS |
| medium_exact (N=14) | `greedy` | `TARGET_MET` | 91.0 | 0.0 | 3 | 4 | 540 | — | — | 17 | 2.44 | PASS |
| medium_exact (N=14) | `beam_v1` | `TARGET_MET` | 89.0 | 0.0 | 3 | 6 | 330 | — | — | 223 | 21.10 | PASS |
| medium_exact (N=14) | `guided_v2` | `TARGET_MET` | 89.0 | 0.0 | 3 | 6 | 330 | — | — | 237 | 24.50 | PASS |
| multicat_blindspot (N=36) | `greedy` | `TARGET_MET` | 92.0 | 0.0 | 4 | 2 | 435 | — | — | 40 | 8.25 | PASS |
| multicat_blindspot (N=36) | `beam_v1` | `TARGET_MET` | 92.0 | 0.0 | 4 | 2 | 435 | — | — | 260 | 32.64 | PASS |
| multicat_blindspot (N=36) | `guided_v2` | `TARGET_MET` | 92.0 | 0.0 | 4 | 2 | 435 | — | — | 400 | 49.94 | PASS |
| replan_stability (N=30) | `greedy` | `TARGET_MET` | 88.0 | 0.0 | 3 | 0 | 180 | — | 6 | 33 | 5.76 | PASS |
| replan_stability (N=30) | `beam_v1` | `TARGET_MET` | 87.0 | 0.0 | 3 | 0 | 180 | — | 4 | 260 | 28.36 | PASS |
| replan_stability (N=30) | `guided_v2` | `TARGET_MET` | 85.0 | 0.0 | 3 | 0 | 270 | — | 0 | 400 | 55.63 | PASS |
| pref_first (N=32) | `greedy` | `TARGET_MET` | 95.0 | 0.0 | 5 | 0 | 300 | 5.0 | — | 37 | 8.26 | PASS |
| pref_first (N=32) | `beam_v1` | `TARGET_MET` | 95.0 | 0.0 | 5 | 0 | 300 | 5.0 | — | 260 | 28.72 | PASS |
| pref_first (N=32) | `guided_v2` | `TARGET_MET` | 95.0 | 0.0 | 5 | 10 | 360 | 50.0 | — | 400 | 54.49 | PASS |
| min_effort (N=36) | `greedy` | `TARGET_MET` | 88.0 | 0.0 | 3 | 0 | 630 | 3.0 | — | 39 | 5.79 | PASS |
| min_effort (N=36) | `beam_v1` | `TARGET_MET` | 88.0 | 0.0 | 3 | 0 | 630 | 3.0 | — | 260 | 25.05 | PASS |
| min_effort (N=36) | `guided_v2` | `TARGET_MET` | 85.0 | 0.0 | 3 | 0 | 90 | 3.0 | — | 387 | 37.90 | PASS |
| large_80 (N=80) | `greedy` | `TARGET_MET` | 89.0 | 0.0 | 4 | 6 | 165 | — | — | 44 | 8.76 | PASS |
| large_80 (N=80) | `beam_v1` | `TARGET_MET` | 89.0 | 0.0 | 4 | 7 | 165 | — | — | 260 | 30.46 | PASS |
| large_80 (N=80) | `guided_v2` | `TARGET_MET` | 89.0 | 0.0 | 4 | 8 | 225 | — | — | 400 | 44.51 | PASS |

## 2. Inner Scheduler Comparison (Exact Bitmask DP vs Fast v1 vs Fast v2)

### 2.1 Scalability ($k = 4 \dots 64$ flexible activities)

| $k$ | DP States ($2^k$) | Exact DP (ms) | Exact DP Mem (KB) | Fast v1 (ms) | Fast v2 (ms) | Status (v2) |
| :---: | :---: | :---: | :---: | :---: | :---: | :--- |
| 4 | 16 | 1.120 | 7.0 | 0.152 | 0.140 | `SCHEDULED` |
| 8 | 256 | 5.055 | 19.9 | 0.198 | 0.532 | `SCHEDULED` |
| 12 | 4,096 | 107.918 | 220.0 | 0.316 | 0.227 | `SCHEDULED` |
| 14 | 16,384 | 482.519 | 856.5 | 0.214 | 0.196 | `SCHEDULED` |
| 16 | 65,536 | 2319.076 | 3400.9 | 0.273 | 0.213 | `SCHEDULED` |
| 24 | Capped (>16) | — | — | 0.327 | 0.355 | `SCHEDULED` |
| 32 | Capped (>16) | — | — | 0.732 | 0.604 | `SCHEDULED` |
| 48 | Capped (>16) | — | — | 1.267 | 3.207 | `SCHEDULED` |
| 64 | Capped (>16) | — | — | 2.298 | 2.697 | `SCHEDULED` |

### 2.2 Tight-Window Feasibility Rate (20 instances at $k = 14$)

- **Exact Bitmask DP**: `20/20` scheduled
- **Fast v1 (Greedy EDF v1)**: `20/20` scheduled
- **Fast v2 (Available-EDF + Fast Carving)**: `20/20` scheduled

### 2.3 Replan Stability Above Cap ($k = 24$: 22 retained + 2 new)

- **Fast v1**: `time_changes = 1` (0.535 ms)
- **Fast v2 (Replan Hold)**: `time_changes = 0` (0.397 ms)
