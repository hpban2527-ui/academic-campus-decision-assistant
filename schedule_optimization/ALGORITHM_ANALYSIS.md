# SP3 Schedule Suggestion Optimization — Problem Formulation, Algorithm Design & Complexity Analysis

This document provides the standalone algorithmic specification, mathematical proofs, and time/space complexity analysis for the **SP3 Schedule Suggestion** subsystem ([src/sp3/scheduler.py](../src/sp3/scheduler.py) and [src/sp3/planner.py](../src/sp3/planner.py)).

---

## 1. Two-Level Problem Formulation

**Objective:** Select a feasible, conflict-free subset of extracurricular activities and assign concrete non-overlapping time slots within the student's free calendar so that all DRL score targets (per-category and total) are met—or the remaining gap is minimized—while preserving stability against any previous plan and optimizing effort versus personal preference under the chosen strategy.

**Expected Output:** A contract-validated (`sp3-planner/0.2`) recommendation containing the selected activity subset $S^*$ with concrete scheduled blocks, projected SP2 DRL scores and remaining gaps, replan change labels (`KEPT` / `MOVED` / `ADDED` / `DROPPED`), and explicit search guarantees (`status`, `optimality_proven`, `evaluated_subsets`).

Given a student's baseline DRL state, available free intervals $\mathcal{F}_0$ (disjoint, sorted), eligible candidate activities $C$ ($|C| = N$), declared fixed-time conflicts $E \subseteq \binom{C}{2}$, score goals (total target $T_{\text{tot}}$ and category targets $\{T_c\}$), limits $(L_{\text{count}}, L_{\text{dur}})$, optional previous plan $P$ with `KEEP_TIME` set $K \subseteq P$, and personalization strategy $\sigma \in \{\text{BALANCED}, \text{MINIMUM\_EFFORT}, \text{PREFERENCE\_FIRST}\}$, SP3 decomposes this goal into two nested combinatorial problems:

1. **Inner Problem (Whole-Set Interval Scheduling — `scheduler.py`):**
   Given a candidate subset $S \supseteq K$, partition $S$ into fixed/kept blocks $S_{\text{fix}}$ and flexible activities $S_{\text{flex}}$ ($|S_{\text{flex}}| = k$). Each flexible activity $i \in S_{\text{flex}}$ requires a single contiguous sitting $[s_i, s_i + d_i)$ inside its usable window $[w_i^{\text{start}}, w_i^{\text{end}}]$ and inside a single free interval of $\mathcal{F} = \mathcal{F}_0 \setminus S_{\text{fix}}$, with no pairwise overlaps. During replan, also minimize `time_changes` (number of retained flexible activities moved from their previous blocks).

2. **Outer Problem (Subadditive Subset Selection — `planner.py`):**
   Find a conflict-free, schedulable subset $S \supseteq K$ satisfying $|S| \le L_{\text{count}}$ and $\sum_{a \in S} d_a \le L_{\text{dur}}$ that minimizes the **8-tuple lexicographic rank** (evaluated via the black-box SP2 multi-tier capped whole-set scorer $f_{\text{SP2}}(S)$):
   $$\text{Rank}(S) = \left(\text{cat\_gap}(S),\; \text{total\_gap}(S),\; \text{set\_changes}(S),\; \text{time\_changes}(S),\; \rho_5(S),\; \rho_6(S),\; \rho_7(S),\; \text{IDs}(S)\right)$$
   where $(\rho_5, \rho_6, \rho_7)$ adapts to $\sigma$:
   - `BALANCED`: $(|S|,\; -\text{utility}(S),\; \text{duration}(S))$
   - `MINIMUM_EFFORT`: $(|S|,\; \text{duration}(S),\; -\text{utility}(S))$
   - `PREFERENCE_FIRST`: $(-\text{utility}(S),\; |S|,\; \text{duration}(S))$

> [!IMPORTANT]
> **Why ILP/Additive Knapsack Does Not Directly Apply:** SP2's 3-level cap (criterion cap → category cap → total 100 cap) makes $f_{\text{SP2}}$ **subadditive** ($f(A \cup B) \le f(A) + f(B)$). Every candidate subset $S$ must therefore be evaluated as a whole via `ProjectedScorer` ($T_{\text{SP2}} = \mathcal{O}(|S| \cdot |\text{Rules}|)$ per call).

---

## 2. Inner Problem (`scheduler.py`) — Algorithms & Complexity

Let $m = |\mathcal{F}_0|$ be the number of available free intervals, $f = |S_{\text{fix}}|$ be the number of fixed/kept blocks, $F = |\mathcal{F}| \le m + f$ be the number of remaining free intervals after subtracting fixed/kept blocks, and $k = |S_{\text{flex}}|$ be the number of flexible activities to place.

### 2.1 Preprocessing & Interval Primitives
- **Subtracting fixed/kept blocks (`_subtract`):** $\mathcal{O}(m \cdot f + f \log f)$ (small in practice since $f \le L_{\text{count}}$).
- **Earliest fit lookup (`_earliest_fit`):** Binary search (`bisect_left`) over sorted endpoints of $\mathcal{F}$:
  $$\text{Time} = \mathcal{O}(\log F + \delta)$$
  where $\delta$ is the number of too-short intervals skipped before finding one of length $\ge d_i$ (worst-case $\mathcal{O}(F)$, typical $\mathcal{O}(\log F)$).
- **In-place interval carving (`_carve_interval`, added in Fast v2):** Binary search to locate the containing interval and update/split in place:
  $$\text{Time} = \mathcal{O}(\log F + F_{\text{shift}})$$
  avoiding the $\mathcal{O}(F)$ full list reconstruction of `_subtract` on every item in Fast v1.

### 2.2 Method 1: Exact Bitmask Dynamic Programming (`_place`, $k \le 16$)
- **Recurrence:**
  $$\text{finish}[\text{mask}] = \min_{i \in \text{mask}} \left( \text{earliest\_fit}(i,\; \text{finish}[\text{mask} \setminus \{i\}],\; \mathcal{F}) + d_i \right)$$
- **Correctness (Left-Shift Property):** Any valid schedule can be left-shifted inductively without reducing remaining free space, so `reachable[(1 << k) - 1] == 1` iff a valid non-overlapping placement exists.
- **Complexity:**
  - **Time:** $\mathcal{O}(k \cdot 2^k \cdot \log F)$
  - **Space:** $\mathcal{O}(2^k)$ (3 arrays: `finish`, `last`, `reachable` — verified empirically as $4\times$ memory per $+2$ increase in $k$, reaching $3.4\text{ MB}$ at $k = 16$).
- **Exact Replan Stability (`_keep_most`):** Enumerates subsets of `keepable` previous blocks from largest to smallest within a work budget of $K_{\max} \cdot 2^{K_{\max}}$ ($K_{\max} = 16$), guaranteeing minimum `time_changes` whenever budget is not exceeded.

### 2.3 Method 2: Fast v1 Multi-Rule Greedy (`_place_greedy_edf_v1`, $k > 16$)
- Runs 4 rules sequentially until one succeeds: (1) Dynamic Left-Shifted ECT, (2) Static EDF carving, (3) Static LSF carving, (4) Static ERT carving.
- **Complexity:**
  - Rule 1 (Dynamic ECT): $\mathcal{O}(k^2 \log F)$
  - Rules 2–4 (Static Carving with `_subtract`): $\mathcal{O}(k \log k + k^2 F)$
  - **Space:** $\mathcal{O}(k + F)$
- **Limitation:** Ignores `previous_blocks` during replan (`held = ()`, causing avoidable `time_changes`), and lacks a dynamic deadline rule for tight-window traps.

### 2.4 Method 3: Fast v2 Scheduler (`_place_greedy_edf` + `_place_fast_v2_with_replan`, $k > 16$)
- **Rule 1 — Dynamic Available-EDF (Jackson's Rule with Release Times & Gaps):** At each step, computes earliest feasible start $b_i$ and finish $e_i$ for all remaining items, lets $e_{\min} = \min_i e_i$, and selects the item with tightest deadline $w_i^{\text{end}}$ among all items with $b_i \le e_{\min}$, then carves $[b_i, e_i)$ in place via `_carve_interval`. Solves ECT traps where a short wide-deadline task would otherwise block a tight-deadline task.
- **Rules 2–5:** Dynamic ECT + Static EDF/LSF/ERT using `_carve_interval`.
- **Replan Block Hold (`_place_fast_v2_with_replan`):** Greedily selects a maximal non-overlapping subset of `keepable` previous blocks (earliest-end first, $\mathcal{O}(k \log k)$), tries holding all of them (then first/second half if blocked), and schedules only the remaining items.
- **Complexity:**
  - **Time:** $\mathcal{O}(k^2 \log F + k \cdot F)$ (bounded by at most 3 replan hold attempts + 5 dispatch rules).
  - **Space:** $\mathcal{O}(k + F)$
- **Soundness Invariant:** If Fast v2 fails to find a placement, it returns `UNDETERMINED` (never `UNSCHEDULABLE`) and always sets `time_changes_minimal = False`.

### 2.5 Inner Scheduler Complexity Summary

| Method | Condition | Time Complexity | Space Complexity | Exact Feasibility | Replan Stability |
| :--- | :---: | :--- | :--- | :---: | :--- |
| **Exact Bitmask DP** (`_place`) | $k \le 16$ | $\mathcal{O}(k \cdot 2^k \cdot \log F)$ | $\mathcal{O}(2^k)$ | **Yes (Proven)** | Optimal (`_keep_most`) |
| **Fast v1** (`_place_greedy_edf_v1`) | $k > 16$ | $\mathcal{O}(k^2 \log F + k^2 F)$ | $\mathcal{O}(k + F)$ | Heuristic (`UNDETERMINED` on fail) | None (`held = ()`) |
| **Fast v2** (`_place_fast_v2_with_replan`) | $k > 16$ | $\mathcal{O}(k^2 \log F + k F)$ | $\mathcal{O}(k + F)$ | Heuristic (Available-EDF + 4 rules) | Greedy Hold (`time_changes` $\approx 0$) |

---

## 3. Outer Problem (`planner.py`) — Algorithms & Complexity

Let $N = |C_{\text{extra}}|$ be the number of eligible non-kept candidates, $B$ be the evaluation budget (`max_evaluations`, capped at $400$ by default for Guided v2 and $260$ for Beam v1), $P_{\text{pool}} \le 60$ be the working pool size, $T_{\text{sched}}$ be the cost of one `schedule_set` call (cached per subset in `_Scheduling`), and $T_{\text{SP2}}$ be the cost of one whole-set SP2 evaluation.

### 3.1 Method 1: Exact Branch-and-Bound (`_search`, default for $N \le 12$)
- Generates subsets by increasing cardinality $s = 1, 2, \dots, L_{\text{count}}$ via backtracking (`_valid_subsets`).
- **Pruning 1 (Monotonicity):** Any subset failing conflict, duration, or scheduling checks prunes its entire superset subtree immediately.
- **Pruning 2 (Cardinality Dominance):** When `previous_plan is None` and $\sigma \neq \text{PREFERENCE\_FIRST}$, once size $k^*$ yields a target-meeting subset, all subsets of size $> k^*$ are strictly dominated and skipped with `optimality_proven = True`.
- **Complexity:**
  - **Worst-case Time:** $\mathcal{O}\!\left(\min\!\left(B,\; \sum_{s=1}^{k^*} \binom{N}{s}\right) \cdot (T_{\text{sched}} + T_{\text{SP2}})\right)$ — exponential $\mathcal{O}(2^N)$ in the worst case, practical and exact for $N \le 12$ (and verifiable up to $N \approx 15$).
  - **Space:** $\mathcal{O}\!\left(\min(B, 2^N)\right)$ for the scheduling cache `_Scheduling._cache`.

### 3.2 Method 2: Pure Greedy Baseline (`_greedy_search`)
- Scores up to 40 singletons, picks the top-ranked singleton, then iteratively adds the first improving candidate among top-5 priority-ranked additions until targets are met or no improvement exists.
- **Complexity:**
  - **Time:** $\mathcal{O}\!\left((P_{\text{pool}} + L_{\text{count}} \cdot 5) \cdot (T_{\text{sched}} + T_{\text{SP2}})\right)$ — typically $13\text{–}44$ evaluations ($2\text{–}12\text{ ms}$).
  - **Space:** $\mathcal{O}(P_{\text{pool}})$
- **Trade-off:** Fastest baseline, but myopic — suffers from suboptimal duration, poor personalization utility, and high replan churn (`set_changes`).

### 3.3 Method 3: Beam v1 (`_guided_search`, original)
- 4 phases under budget $B_1 = \min(B, 260)$: Stratified Pool ($P = 40$) → Singleton Pass ($40$ evals) → Greedy Rollouts from top 10 singles → Beam Search (width $W = 12$, branching $20$ from top-20 singletons).
- **Complexity:**
  - **Time:** $\mathcal{O}\!\left(B_1 \cdot (T_{\text{sched}} + T_{\text{SP2}}) + N \log N\right)$
  - **Space:** $\mathcal{O}(B_1)$
- **Identified Gaps Fixed in v2:** Blind to `plan.retained` and `personalization_strategy` in rollouts; top-20 singleton cutoff can starve secondary categories; no local search refinement.

### 3.4 Method 4: Guided v2 + Local Search (`_guided_search_v2`, default for $N > 12$)
- 5 deterministic phases under budget $B_2 = 400$ (or explicit `max_evaluations`):
  1. **Strategy- & Replan-Aware Stratified Pool ($P \le 60$):** $\mathcal{O}(N \log N)$. Prioritizes `plan.retained` first, then round-robin across `(domain, mode)` sorted by strategy key.
  2. **Singleton Pass + Multi-Category / Strategy Indexing:** $\mathcal{O}(P \cdot (T_{\text{sched}} + T_{\text{SP2}}) + P \log P)$. Builds `expansion_pool` ($E \le 40$) combining: all `plan.retained`, top-5 per target category, top shortest per category (`MINIMUM_EFFORT`), top highest-utility (`PREFERENCE_FIRST`), and top-24 overall.
  3. **Replan- & Strategy-Aware Greedy Rollouts (up to 10 diverse seeds):** Immediately tests the full eligible `retained` set on replan; evaluates top-4 next candidates per step and chooses the **best** improving move.
  4. **Category-Diverse Beam Search (width $W = 12$, up to $85\%$ of budget):** Expands each parent by dynamically sorting `expansion_pool` against the parent's *remaining* uncovered category gaps (up to 16 expansions/parent).
  5. **Deterministic Local Search Refinement (remaining $\ge 15\%$ of budget, up to 2 passes):**
     - **1-Prune:** Tests removing each non-kept activity ($\mathcal{O}(|S^*|)$ evals).
     - **1-Swap:** Tests swapping each non-kept activity with top-20 unused candidates in `expansion_pool` ($\mathcal{O}(|S^*| \cdot 20)$ evals).
     - **1-Add:** Tests adding high-priority candidates when targets are unmet, during replan, or under `PREFERENCE_FIRST`.
- **Complexity:**
  - **Time:** $\mathcal{O}\!\left(N \log N + B_2 \cdot (T_{\text{sched}} + T_{\text{SP2}})\right)$ where $B_2 \le 400$ is strictly bounded (empirical latency: **$12\text{–}56\text{ ms}$** for $N = 10 \dots 80$).
  - **Space:** $\mathcal{O}(N + B_2)$ for candidate pool, `seen` evaluation table, and `_Scheduling._cache`.
- **Soundness & Determinism:** Always returns `optimality_proven = False` (never overclaims optimality), uses strictly deterministic tie-breaking, and passes `sp3.plan_checker.check_plan` with 0 violations across all tested scenarios.

### 3.5 Outer Planner Complexity & Empirical Trade-off Summary

| Method | Worst-Case Evals | Time Complexity | Space Complexity | Optimality Guarantee | Typical Latency ($N \le 80$) |
| :--- | :---: | :--- | :--- | :--- | :---: |
| **Exact B&B** (`exact`) | $\min(B, 2^N)$ | $\mathcal{O}(\min(B, 2^N)(T_{\text{sched}} + T_{\text{SP2}}))$ | $\mathcal{O}(\min(B, 2^N))$ | **Global Optimum Proven** ($N \le 12$) | $15\text{–}50\text{ ms}$ ($N \le 14$) |
| **Pure Greedy** (`greedy`) | $\le P + 5 L_{\text{count}}$ | $\mathcal{O}(N \log N + (P + L_{\text{count}})(T_{\text{sched}} + T_{\text{SP2}}))$ | $\mathcal{O}(N + P)$ | None (myopic) | $2\text{–}9\text{ ms}$ |
| **Beam v1** (`beam_v1`) | $\le 260$ | $\mathcal{O}(N \log N + 260(T_{\text{sched}} + T_{\text{SP2}}))$ | $\mathcal{O}(N + 260)$ | Heuristic | $12\text{–}33\text{ ms}$ |
| **Guided v2 + Local Search** (`guided_v2`) | $\le 400$ | $\mathcal{O}(N \log N + 400(T_{\text{sched}} + T_{\text{SP2}}))$ | $\mathcal{O}(N + 400)$ | Heuristic (**0% gap vs Exact** on $N \le 14$; optimal replan & personalization) | $12\text{–}56\text{ ms}$ |

---

## 4. Empirical Verification

Full reproducible benchmark numbers comparing all 4 outer methods and 3 inner methods are maintained in [results/benchmark_report.md](results/benchmark_report.md) (generated by `python schedule_optimization/benchmark.py`). Key empirical findings:
- **0% Optimality Gap vs. Exact B&B** on `small_exact` ($N=10$) and `medium_exact` ($N=14$), while running **$2.1\times$ faster** than Exact at $N=14$.
- **Replan Stability:** Reduces `set_changes` from `6` (`greedy`) and `4` (`beam_v1`) down to **`0`** (`guided_v2`); reduces inner flexible `time_changes` at $k=24$ from `1` (`fast_v1`) to **`0`** (`fast_v2`).
- **Personalization:** Improves `PREFERENCE_FIRST` utility **$10\times$** (`5.0` → `50.0`) and reduces `MINIMUM_EFFORT` total duration by **$85.7\%$** (`630 min` → `90 min`).
- **Inner Scalability:** Exact DP scales as $\mathcal{O}(k \cdot 2^k)$ ($2.3\text{ s}$ and $3.4\text{ MB}$ at $k=16$), whereas Fast v2 stays under **$2.7\text{ ms}$** up to $k=64$ while matching Exact DP's $20/20$ feasibility rate on tight windows at $k=14$.
