# SP3 Planning & Recommendation — Working Contract v0.2

Status: **proposal**. It becomes the working contract once it is reviewed and
merged through the normal pull-request process.

v0.2 extends `sp3-planner/0.1` with flexible scheduling, multi-session fixed
activities, participation state and replan. Everything in v0.1 that is not
changed here still applies (data conventions, baseline rules, SP2 scoring
envelope, search budget, failure handling, consistency checks).

## 1. What changes from v0.1

| Area | v0.1 | v0.2 |
| --- | --- | --- |
| Version string | `sp3-planner/0.1` | `sp3-planner/0.2` for every SP3 envelope; defined once in `src/sp3/contract.py` |
| Activity schedule | One fixed interval taken from `activity.start/end` | Normalized `schedule`: `FIXED` (one or more blocks) or `FLEXIBLE_WINDOW` (one sitting inside a window) |
| Availability | Free intervals | Same, plus ad-hoc busy intervals; never subtracts SP3 activities |
| Candidate entry | activity, binding, feasibility | adds `schedule` and `participation` |
| Planner output | Selected activity IDs with start/end | Selected activities with concrete `scheduled_blocks` |
| Replan | Not supported | `previous_plan` + `keep_requests`; output reports kept, moved, added and dropped activities |
| Scoring | Attribution by activity start | Attribution by the planned order (`attribution_order`) |
| Versioning | Context versions only | Output carries `plan_version` and `based_on`; apply only on matching versions |

The 14-field SP1 activity object is unchanged. All new information lives
outside it.

## 2. Module boundaries

| Module | Responsibility in v0.2 |
| --- | --- |
| Availability (`src/sp3/availability.py`) | Expand the weekly pattern, apply day exceptions and ad-hoc busy intervals, return merged free intervals and `calendar_version` |
| Feasibility (`src/sp3/feasibility.py`) | Normalize each activity's schedule; check each activity **on its own** (time, registration, eligibility, term, source, binding); report fixed-time conflicts |
| Planner (`src/sp3/planner.py` and its scheduler) | Choose the activity set **and** schedule it as a whole: keep fixed blocks, place flexible sittings, prevent overlaps, apply limits and keep requests, call SP2 for the whole set, explain the result, compute replan changes |
| Plan checker (`src/sp3/plan_checker.py`) | Re-verify every planner output independently of the planner's decision logic |
| SP2 projected scoring | Score the whole selected set from trusted activity-to-rule bindings and baseline facts |
| Backend integration | Trusted schedule evidence and participation state, plan storage, version check on apply, `/api/sp3/plan` |
| UI | Inputs for availability, busy intervals, participation and keep requests; display of scheduled blocks and plan changes |

`FEASIBLE` from feasibility means **feasible on its own**. It does not mean the
activity fits together with every other selected activity.

## 3. Conventions added in v0.2

- Intervals are half-open `[start, end)`. A block ending at 15:00 and another
  starting at 15:00 do not overlap.
- Durations are positive integers in minutes.
- A `FLEXIBLE_WINDOW` activity is done in **one contiguous sitting** of
  `duration_minutes`. It has no partial progress and no make-up.
- `available_intervals` is the student's free time after the weekly pattern,
  day exceptions and ad-hoc busy intervals. It **never** subtracts the time of
  any SP3 activity (proposed, registered or kept). The planner owns all SP3
  activity time.
- Transition and travel time are not modeled. Every planner output carries
  the `TRAVEL_NOT_MODELED` warning.
- The schedule type is never inferred from the mode label `online`.

## 4. Shared types

### 4.1 `interval`

`{"start": timestamp, "end": timestamp}` with `start < end`.

### 4.2 `schedule` (normalized, produced by feasibility)

Exactly one of:

```json
{"type": "FIXED", "fixed_blocks": [{"start": "...", "end": "..."}]}
```

- `fixed_blocks` is non-empty, sorted by `start` and non-overlapping.
- A multi-session activity lists every required session.

```json
{"type": "FLEXIBLE_WINDOW", "window_start": "...", "window_end": "...", "duration_minutes": 45}
```

- `window_start < window_end`.
- `1 <= duration_minutes <= window length in minutes`.

`schedule` is `null` only when the candidate is `NEEDS_REVIEW` or
`INFEASIBLE` because the schedule could not be normalized.

### 4.3 `participation`

```json
{"registration": "NOT_REGISTERED", "progress": "NOT_STARTED"}
```

| Field | Values | Meaning |
| --- | --- | --- |
| `registration` | `REGISTERED`, `NOT_REGISTERED` | `REGISTERED` skips the registration-deadline check. Being selected by the planner never means registered |
| `progress` | `NOT_STARTED`, `COMPLETED`, `CANCELLED` | `COMPLETED`: done, never scheduled again. `CANCELLED`: the student will not do it (includes a missed online sitting), never selected again in this replan |

The default for an activity the student has not interacted with is
`NOT_REGISTERED` / `NOT_STARTED`. Participation is supplied by the backend from
the student's stored state; it is not inferred from elapsed time.

### 4.4 `planned_activity`

`{"activity_id": string, "scheduled_blocks": [interval, ...]}`

`scheduled_blocks` is non-empty, sorted and non-overlapping. For `FIXED` it
equals `fixed_blocks`; for `FLEXIBLE_WINDOW` it is exactly one block of
`duration_minutes`.

## 5. Availability

The availability payload moves to `sp3-availability/0.2`. Its new field is
`busy_intervals`: an array of `interval` subtracted after weekly expansion and
day exceptions. A busy interval affects only the time it covers.

The output is unchanged in shape: merged, sorted `available_intervals` and a
deterministic `calendar_version` that changes whenever any input changes.

## 6. Feasibility

### 6.1 `feasibility_request`

Fields are the same as v0.1 (`contract_version`, `request_id`, `context`,
`available_intervals`, `activities`), with `contract_version = "sp3-planner/0.2"`.

Each `activities[]` entry is now:

```json
{"activity": {"...14 fields...": "..."}, "score_binding_ref": "string or null", "participation": {"registration": "...", "progress": "..."}}
```

Trusted evidence stays outside the request (`FeasibilityEvidence`). The only
changed evidence field is `schedule_by_activity`, keyed by activity ID:

```json
{"type": "FIXED", "fixed_blocks": [{"start": "...", "end": "..."}]}
{"type": "FLEXIBLE_WINDOW", "duration_minutes": 45}
```

For `FLEXIBLE_WINDOW`, the window is taken from `activity.start` and
`activity.end`. `ASYNCHRONOUS` and `required_duration_minutes` are removed.

### 6.2 Schedule normalization (deterministic, in this order)

1. Evidence present: use it. `FIXED` blocks must be valid (section 4.2).
   `FLEXIBLE_WINDOW` needs non-null `activity.start` and `activity.end`
   (otherwise `MISSING_SCHEDULE`), and the duration must fit the window
   (otherwise `UNSUPPORTED_SCHEDULE`).
2. No evidence, `activity.start` and `activity.end` present, `mode` is
   `offline` or `hybrid`, and both fall on the same local date: `FIXED` with
   one block `[start, end)`.
3. Otherwise: `schedule = null` with `MISSING_SCHEDULE` (start/end missing)
   or `MISSING_SCHEDULE_TYPE` (anything else, including every online activity
   without evidence and multi-day offline windows).

### 6.3 Individual checks

Progress:

- `COMPLETED` adds `ALREADY_COMPLETED`.
- `CANCELLED` adds `CANCELLED`.

`FIXED`:

- Every block lies inside the planning window; otherwise `OUTSIDE_WINDOW`.
- The first block starts at or after `as_of`; otherwise `ALREADY_STARTED`.
- Every block lies inside a single merged available interval; otherwise
  `OUTSIDE_AVAILABILITY`.

`FLEXIBLE_WINDOW`:

- The usable window is
  `[max(window_start, context.window_start, as_of), min(window_end, context.window_end))`.
- If the usable window is empty, add `WINDOW_ENDED` when `window_end <= as_of`,
  otherwise `OUTSIDE_WINDOW`.
- Otherwise, at least one merged available interval must overlap the usable
  window by `>= duration_minutes` **contiguously**; otherwise
  `OUTSIDE_AVAILABILITY`. (This replaces v0.1's sum of free fragments.)

Registration:

- `NOT_REGISTERED`:
  - missing deadline adds `MISSING_DEADLINE`;
  - `as_of >= registration_deadline` adds `DEADLINE_PASSED`.
- `REGISTERED`: no deadline check.

Eligibility, term scope, source review and score binding are unchanged from
v0.1. All applicable reasons are collected.

### 6.4 Status and reason codes

| Class | Codes |
| --- | --- |
| Certain failure → `INFEASIBLE` | `OUTSIDE_WINDOW`, `OUTSIDE_AVAILABILITY`, `WINDOW_ENDED`, `ALREADY_STARTED`, `DEADLINE_PASSED`, `INELIGIBLE`, `ALREADY_COMPLETED`, `CANCELLED` |
| Missing or unverified data → `NEEDS_REVIEW` | `MISSING_SCHEDULE`, `MISSING_SCHEDULE_TYPE`, `UNSUPPORTED_SCHEDULE`, `MISSING_DEADLINE`, `MISSING_ELIGIBILITY`, `NEEDS_SOURCE_REVIEW`, `TERM_UNVERIFIED`, `MISSING_SCORE_BINDING` |

- Any certain failure gives `INFEASIBLE`.
- Otherwise, any review reason gives `NEEDS_REVIEW`.
- Otherwise the status is `FEASIBLE`, with empty `reason_codes`.

Reason codes keep a fixed documented order.

### 6.5 `feasibility_response`

`candidates[]` entries:

```json
{"activity": {}, "score_binding_ref": "...", "participation": {}, "schedule": {}, "feasibility": {"status": "...", "reason_codes": []}}
```

`conflict_pairs` contains every pair of candidates that both have `FIXED`
schedules (any status) and any overlapping blocks. Pairs are sorted and
unique. Feasibility does not report pairs that involve `FLEXIBLE_WINDOW`
activities; the planner resolves those while scheduling.

## 7. `planner_input` (v0.2)

The fields from v0.1 (`contract_version`, `request_id`, `context`, `baseline`,
`goals`, `preferences`, `limits`, `candidates`, `conflict_pairs`), plus:

| Field | Meaning |
| --- | --- |
| `available_intervals` | Exactly the intervals used for feasibility; `context.calendar_version` identifies them |
| `previous_plan` | `null`, or `{plan_version, based_on, selected_activities: [planned_activity]}` — the plan currently in use |
| `keep_requests` | Array of `{activity_id, mode: "KEEP_TIME"}`; each ID must be in `previous_plan.selected_activities`; unique |

`candidates` and `conflict_pairs` are copied unchanged from the matching
`feasibility_response`.

`KEEP_TIME` keeps the activity and its previous blocks exactly. Activities
without a keep request may be kept, moved or replaced. Registration is not a
keep request.

## 8. Scheduling a candidate set (planner)

For a set `S` of eligible candidates:

1. Fixed blocks of `S` must not overlap each other. This is already implied by
   `conflict_pairs`; the planner re-checks it.
2. Free time is `available_intervals` minus the fixed blocks of `S`.
3. Each `FLEXIBLE_WINDOW` activity in `S` receives exactly one block of
   `duration_minutes` inside its usable window and inside free time. Blocks of
   different activities never overlap.
4. `KEEP_TIME` activities use their previous blocks unchanged. A kept block
   must still be valid (section 10.4).

**Placement is deterministic and exact.**

- A single placement order is not enough: with free time 07:00–13:00, A
  (window 09:00–12:00, 120 min) placed first leaves no gap for B (window
  07:00–13:00, 180 min), yet B 07:00–10:00 then A 10:00–12:00 is valid.
- Left-shift lemma: ordering the flexible blocks of any valid schedule by
  start and moving each to its earliest feasible start at or after the
  previous block's end keeps the schedule valid; no block ends later.
- `earliest_fit(a, t)` (earliest feasible start `>= t` inside one free
  interval and the usable window) has an end that is non-decreasing in `t`, so
  `dp[T]`, the minimal completion time of a sequence placing exactly the
  flexible subset `T`, is exact:
  `dp[T] = min over a in T of end(earliest_fit(a, dp[T - {a}]))`. The set is
  schedulable if and only if `dp[all]` is finite. Ties on completion time
  place the smaller `activity_id` last.
- Cost is `O(2^k · k)` earliest-fit calls for `k` flexible activities. Above
  16 flexible activities in one set the result is undetermined, never
  unschedulable: the subset is not scored or extended, and the planner
  reports `search.complete = false`, `optimality_proven = false`,
  `limit_reason = SCHEDULING_LIMIT` and `SEARCH_INCOMPLETE`.
- Replan placement minimizes time changes (section 9, item 4), then prefers
  left-shifted blocks. A retained flexible activity can stay only if its
  previous block is still valid. Subsets of those activities are held at
  their previous blocks, largest first (ties: smallest sorted ID list), while
  the DP places the rest; the first success is minimal. This enumeration may
  spend at most the work of one DP at the cap; if it stops early, minimality
  is not claimed (same search flags as above).

Schedulability is monotone: every subset of a schedulable set is schedulable.
The planner therefore uses it as a pruning constraint while it enumerates
subsets, in the same way as conflicts and limits. Unschedulable subsets are
not scored.

`max_duration_minutes` counts fixed block minutes plus flexible
`duration_minutes`.

## 9. Ranking (replaces v0.1 section 6 tuple)

The planner prefers the lowest tuple:

1. Sum of remaining category-target gaps.
2. Remaining total-target gap (0 when no total target).
3. **Activity-set changes**: `|P \ S| + |S \ P|`.
4. **Time changes**: the number of activities in `P ∩ S` whose
   `scheduled_blocks` differ from the previous plan.
5. Number of selected activities.
6. Negative preference-match score.
7. Total planned duration in minutes.
8. Sorted activity ID list.

`P` is the set of `previous_plan` activities whose progress is not
`COMPLETED`. Without a previous plan, items 3 and 4 are always 0.
`P` also excludes activities in `baseline.included_activity_ids`;
already-counted activities are not changes.

Pruning:

- **No previous plan:** the v0.1 size-dominance pruning remains valid.
- **Previous plan present:** size-dominance pruning is disabled. The
  4,096-evaluation budget, `SEARCH_INCOMPLETE` and the proof rules of v0.1
  are unchanged.

## 10. Outputs

### 10.1 `score_request` / `score_response`

`score_request` adds `attribution_order`: a permutation of
`selected_activity_ids`, ordered by `(first scheduled block start, activity_id)`.
The scorer attributes contributions in this order.

Category and total results do not depend on the order. Per-category
contributions still sum to the category gain. `score_response` is unchanged
apart from the version string.

### 10.2 `planner_output` additions

`selected_activities[]` entries become:

```json
{"activity_id": "...", "title": "...", "schedule_type": "FIXED", "scheduled_blocks": [], "registration": "REGISTERED", "change": "KEPT", "reasons": []}
```

- `change` is one of `KEPT`, `MOVED`, `ADDED`. Without a previous plan, it is
  always `ADDED`.
- v0.1 `start` and `end` are replaced by `scheduled_blocks`.

New top-level fields:

| Field | Meaning |
| --- | --- |
| `dropped_activities` | Activities in `P` that are not selected: `{activity_id, registered, code, message}`. Codes: `CANCELLED`, `NO_LONGER_FEASIBLE`, `NO_TIME`, `LOWER_PRIORITY`, `NOT_LISTED` |
| `pending_confirmation` | IDs with progress `COMPLETED` that are not in `baseline.included_activity_ids`. They are never selected or scored |
| `keep_conflicts` | Empty unless status is `KEEP_CONFLICT`: `{activity_id, code, message}` |
| `score_comparison` | `null` without a previous plan; otherwise SP2's projection for the still-usable part of the previous plan (`P` ∩ eligible, uncounted candidates) next to the new projection |
| `based_on` | `{calendar_version, dataset_version, ruleset_version, baseline_ref, previous_plan_version}` |
| `plan_version` | `"sp3plan-"` + the first 16 hex characters of SHA-256 over the canonical JSON of `based_on` and the selected `planned_activity` list |

`score_comparison`, when a previous plan exists:

```json
{"basis": "PREVIOUS_ACTIVITY_SET_RESCORED", "previous_activity_ids": [], "previous_projected_by_category": {}, "previous_projected_total": 0, "new_projected_total": 0}
```

- `previous_activity_ids`: sorted IDs of `P` ∩ eligible candidates.
- `previous_projected_by_category` and `previous_projected_total`: one extra
  `score_plan` call for that set (outside the search budget), attributed in
  previous-block order. It is the hypothetical score of that activity set
  only; it never implies that the old schedule is still usable.
- `new_projected_total`: `score_summary.projected_total` of the new plan.

### 10.3 Exclusion codes

The exclusion codes, in order, are: `NEEDS_REVIEW`, `NOT_FEASIBLE`,
`ALREADY_COUNTED`, `CONFLICT`, **`NO_TIME`**, `LIMIT`, `LOWER_PRIORITY`.

`NO_TIME` means that adding the candidate to the selected set leaves no valid
schedule.

Every candidate still appears exactly once in `selected_activities` or
`excluded_candidates`.

### 10.4 New status `KEEP_CONFLICT`

The planner returns `KEEP_CONFLICT` when any of these holds:

- a `KEEP_TIME` activity is not `FEASIBLE`;
- a kept block is outside the usable window or outside available time;
- kept blocks overlap each other or a fixed block of another kept activity;
- a kept `FIXED` activity's blocks no longer equal its current `fixed_blocks`.

With `KEEP_CONFLICT`:

- `selected_activities = []`, `score_summary = null`, `proof = null`;
- `feasibility_conclusion = UNDETERMINED`;
- `limit_reason = KEEP_CONFLICT`;
- `keep_conflicts` lists every conflict.

The planner never silently releases a keep request. The student decides.

### 10.5 Warnings added

- `DROPS_REGISTERED`: a dropped activity is registered. Replan never cancels
  a registration.
- `PENDING_CONFIRMATION`: completed activities await score confirmation.

## 11. Apply and `what_if_skip` (backend)

- The planner is pure. It reads its whole input and writes nothing.
- A planner output is a **preview**. The backend applies it only when:
  - every `based_on` value equals the current value; and
  - `previous_plan_version` equals the student's active plan version.

  Otherwise the backend rejects the apply with `STALE_PLAN`. A plan built from
  old data never overwrites a newer plan.
- `what_if_skip(X)` calls the planner on a copy, with the active plan as
  `previous_plan` and `participation.progress = CANCELLED` for `X`. It returns
  the resulting changes and `score_comparison`. Nothing is applied.

## 12. Shared acceptance cases

Cases F1–F6 live in `tests/sp3/fixtures/v0_2_feasibility_cases.json` and cases
P1–P9 in `tests/sp3/fixtures/v0_2_planner_cases.json`. Separate files let the
modules be developed on separate branches without merge conflicts. Each case
has a name, the module under test, the input and the expected projection.
Planner cases use feasibility outputs written in the section 6.5 shape, so the
planner can be tested without importing the feasibility module.

| ID | Module | Case | Expected |
| --- | --- | --- | --- |
| F1 | Availability | Ad-hoc busy interval on one day | Only that day's free time changes; `calendar_version` changes |
| F2 | Feasibility | Flexible 60 min with two separate 30-min free fragments | `INFEASIBLE`, `OUTSIDE_AVAILABILITY` |
| F3 | Feasibility | `REGISTERED`, deadline passed | No `DEADLINE_PASSED` |
| F4 | Feasibility | `COMPLETED` / `CANCELLED` | `INFEASIBLE` with `ALREADY_COMPLETED` / `CANCELLED` |
| F5 | Feasibility | Online without evidence; multi-day offline without evidence | `NEEDS_REVIEW`, `MISSING_SCHEDULE_TYPE`, `schedule = null` |
| F6 | Feasibility | Multi-session fixed with one session outside free time; overlap on any session | `OUTSIDE_AVAILABILITY`; pair in `conflict_pairs` |
| P1 | Planner | Two flexible activities, each feasible alone, one shared slot | One selected, the other `NO_TIME` |
| P2 | Planner | Flexible placed around a selected fixed block | Blocks do not overlap |
| P3 | Planner | Blocks `[..,15:00)` and `[15:00,..)` | Both selected |
| P4 | Planner | `KEEP_TIME` block now covered by a busy interval | `KEEP_CONFLICT`, no plan |
| P5 | Planner | Previous plan still valid; an equal-score alternative exists | All `KEPT`, no swap |
| P6 | Planner | Previous flexible block no longer free | `MOVED` to a new block, same score |
| P7 | Planner | Completed activity not in baseline | In `pending_confirmation`; not selected or scored |
| P8 | Planner | Dropping a registered activity | `DROPS_REGISTERED` warning |
| P9 | Planner + scorer | Attribution order | Follows scheduled blocks, not window opening |
| E1 | End to end | Full chain availability → feasibility → planner → scorer | The planner accepts the feasibility output unchanged |
| E2 | Backend | Apply with changed `calendar_version` | `STALE_PLAN` |

The v0.1 examples are kept as regression cases, converted to v0.2 shape.

## 13. Migration checklist

- Both `src/sp3/contract.py` and `src/sp3/feasibility.py` declare
  `CONTRACT_VERSION = "sp3-planner/0.2"`, each with a test asserting that exact
  string, until both modules are integrated on one branch. After integration,
  `feasibility.py` imports the constant from `sp3.contract` and the duplicate
  is removed. `availability.py` keeps its own `sp3-availability/0.2`.
- Package files that already exist on one branch (`src/sp3/__init__.py`,
  `tests/sp3/conftest.py`) are not created on another branch.
- Availability: section 5, case F1.
- Feasibility: section 6, cases F2–F6.
- Planner and scorer: sections 7–10, cases P1–P9; the plan checker covers
  sections 8 and 10.
- End to end: case E1 after availability, feasibility and planner are
  integrated on one branch.
- Backend: schedule evidence and participation sources, plan storage and the
  apply rule in section 11, case E2.

## 14. Planner v0.2 implementation handoff

This handoff implements the planner side of `sp3-planner/0.2`: whole-set
scheduling, participation state, keep requests, replan, attribution in
scheduled order, and the matching scorer and checker changes. It does not
import the availability or feasibility modules. All scoring remains
`DEMO_ONLY` and unverified.

### 14.1 Modules and entry points

| Module | Entry points |
| --- | --- |
| `src/sp3/contract.py` | `CONTRACT_VERSION`; validators for intervals, schedules, participation, previous plans and keep requests; the status and code enums (keep-conflict, change, dropped, warning codes, limit reasons); `plan_version` |
| `src/sp3/scheduler.py` | `schedule_set(...)` returning `SCHEDULED`, `UNSCHEDULABLE` or `UNDETERMINED` with blocks; `MAX_FLEXIBLE_PER_SET = 16` |
| `src/sp3/planner.py` | `build_plan(planner_input, score_plan)`; `what_if_skip(planner_input, activity_id, score_plan)` |
| `src/sp3/scorer_adapter.py` | `ScorerAdapter(backend).score_plan` |
| `src/sp3/projected_scorer.py` | `ProjectedScorer(InMemoryScoringData(payload))`, the SP2-backed backend |
| `src/sp3/plan_checker.py` | `check_plan(planner_input, planner_output, score_plan)` |

### 14.2 Required test modules

| Test module under `tests/sp3` | Coverage | Scores from |
| --- | --- | --- |
| `test_planner_contract.py` | Version string, schedule, participation, previous-plan and keep validators, `plan_version` | None |
| `test_scheduler.py` | Placement, clipping, adjacency, kept blocks, replan, cap, determinism | None |
| `test_scheduler_properties.py` | 200 seeded grid instances against an independent brute force, including minimal time changes | None |
| `test_scorer_adapter.py` | Request validation including `attribution_order`, delegation, isolation | Static doubles |
| `test_projected_scorer.py` | Trusted data, bindings, caps, attribution order | Fake engine |
| `test_projected_scorer_integration.py` | Full planner run and attribution by schedule | Real SP2 engine and `data/drl_rules.json` on synthetic data |
| `test_main_flow_integration.py` | Main flow on stored availability/feasibility v0.2 output: first plan, replan after new busy time, `what_if_skip`, keep conflicts; upstream drift check after integration | Real SP2 engine and `data/drl_rules.json` on synthetic data |
| `test_planner.py` | v0.1 examples as fixed-schedule regressions, ranking, limits, failures, invalid input | Static tables, toy model |
| `test_planner_cases.py` | Cases P1–P9 from section 12 | Static tables |
| `test_planner_replan.py` | Replan, keep conflicts, scheduling limit, `what_if_skip`, determinism | Static tables, toy model |
| `test_planner_properties.py` | 130 fixed-schedule and 100 replan instances against brute-force oracles | Toy model |
| `test_plan_checker.py` | Detection of inconsistent plans, schedules, changes, scores and search claims | Static tables, toy model |

Keep `tests/sp3/planner_doubles.py` and the fixtures `contract_examples.json`,
`synthetic_scoring_data.json`, `v0_2_planner_cases.json` and
`main_flow_integration.json` with these tests.
The P1–P9 candidates are unchanged feasibility output; the fixture records the
feasibility commit in `derived_from`. `main_flow_integration.json` stores the
real availability and feasibility outputs for its inputs, with the producing
commit in `upstream.commit`; its drift check re-runs those modules and is
skipped until they are on the same branch. Only the two integration modules
use the real engine; no test uses real student records.

### 14.3 Reproduce the checks

From the repository root, with Python 3.12 and `requirements.txt` installed:

```text
python -m pytest -q tests/sp3/test_planner_contract.py tests/sp3/test_scheduler.py tests/sp3/test_scheduler_properties.py tests/sp3/test_scorer_adapter.py tests/sp3/test_projected_scorer.py tests/sp3/test_projected_scorer_integration.py tests/sp3/test_main_flow_integration.py tests/sp3/test_planner.py tests/sp3/test_planner_cases.py tests/sp3/test_planner_replan.py tests/sp3/test_planner_properties.py tests/sp3/test_plan_checker.py
python -m pytest -q tests/sp3
```

The first command names every required module, so a missing file fails
collection. Tests set up the `src` imports; CI also sets `PYTHONPATH=src`.

### 14.4 Waiting for integration

- Case E1 live on one branch with availability and feasibility v0.2: the drift
  check in `test_main_flow_integration.py` then runs instead of being skipped;
  feasibility imports `CONTRACT_VERSION` from `sp3.contract` (section 13).
- Backend: `/api/sp3/plan`, plan storage, apply with the `STALE_PLAN` check
  (case E2), and a `what_if_skip` endpoint.
- UI for availability, participation, keep requests and plan changes.
- Trusted schedule evidence, bindings and baseline facts for real students.
