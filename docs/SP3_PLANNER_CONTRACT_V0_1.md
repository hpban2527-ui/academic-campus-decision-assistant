# SP3 Planning & Recommendation — Working Contract v0.1

## 1. Purpose and scope

The planner receives feasibility-assessed activities and recommends a schedule
based on DRL (student conduct/training score) targets, availability, and
preferences. It explains its selections, obtains projected scores from SP2,
and reports any remaining target gap.

Version 0.1 covers fixed-time activities, category and total score targets,
activity-count/time limits, duplicate avoidance, and unmet-target handling.
Multi-session scheduling, travel time, financial budgets, enrollment, and
saving plans are outside this version's scope.

Planning is read-only. It must not award points, update the baseline, register
the student, or change the review queue. All results remain
`mode="DEMO_ONLY"` and `official_award_verified=false`.

## 2. Responsibilities and integration flow

| Member | Responsibility relevant to this contract | Handoff |
| --- | --- | --- |
| Minh Trí | Activity data QA, stable IDs, term scope, source and schedule completeness | Activity records and QA findings |
| Như Ngọc | Individual feasibility and activity conflicts | `feasibility_request → feasibility_response` |
| Ngọc Tuyền, with the SP2 engine owner | Score snapshots, rule mappings, caps, and scoring requirements | Baseline and SP2 bridge data |
| Thảo Duyên | Plan selection, ranking, explanations, and unmet-target handling | `planner_input → planner_output` |
| Minh Tiến | Goal/preferences form and plan presentation | `plan_request` and `planner_output` |
| Bình An | Backend orchestration, interface review, and integration | API and assignment of the SP2 adapter implementation |

The SP2 adapter implementer still needs confirmation by Bình An. Until the
adapter is ready, Duyên can use the static scoring expectations in Section 9.

```text
UI plan_request
  → backend resolves activity data, baseline, rule mappings, and versions
  → feasibility_request → feasibility_response
  → planner_input → planner ↔ SP2 score_request / score_response
  → planner_output → UI
```

Proposed internal interfaces:

- `assess_feasibility(request) -> feasibility_response`
- `build_plan(request, score_plan) -> planner_output`
- `score_plan(request) -> score_response`

Proposed endpoint: **POST /api/sp3/plan**. It is not implemented by this
document. The existing `/api/sp2/evaluate` evaluates a snapshot and must not
be assumed to accept an entire future plan.

The backend resolves trusted baselines, rule mappings, and assessment data.
A client-provided score, approval, or FEASIBLE label is not authoritative.
The public student identifier supports the demo flow; it is not authentication.

## 3. Data conventions

These conventions apply to all interfaces below.

| Item | Version 0.1 convention |
| --- | --- |
| Required fields | All listed fields are required unless explicitly described as nullable |
| Version | `contract_version` must equal `sp3-planner/0.1`; reject unknown versions |
| IDs and versions | Non-empty strings; activity IDs remain stable across modules |
| Dates | ISO 8601 timestamps with an explicit offset; compare actual instants |
| Timezone | `Asia/Ho_Chi_Minh`; use the supplied `as_of`, not the machine clock |
| Scores | Finite, non-negative numbers; do not interpret missing values as zero |
| Goals | Desired final scores, not additional points to earn |
| Empty preferences | No preference for that dimension |
| Null limits | No limit; zero is a real limit, not an omitted value |
| Intervals | Half-open `[start, end)`; adjoining intervals do not overlap |
| Activity schedule | One fixed interval; do not move an activity to fit a plan |
| Travel time | Not modeled; include `TRAVEL_NOT_MODELED` in output warnings |
| Baseline | Confirmed scores in the selected demo snapshot; exclude previously projected points |
| Unknown fields | Reject unexpected fields in interface objects to detect contract drift |

The actual dates of HK3 2025–2026 and the applicable ruleset require owner
verification. The examples below use `SYNTHETIC-DEMO`; their dates and scores
must not be presented as university-verified information.

## 4. Input interfaces

### 4.1 Public `plan_request`

| Field | Type and meaning |
| --- | --- |
| `contract_version`, `request_id` | Version and non-empty request identifier |
| `scope` | Object containing `student_id`, `term_id`, `window_start`, `window_end`, `as_of`, `timezone` |
| `available_intervals` | Array of `{start, end}`; an empty array means no availability |
| `goals` | `{total_target: number or null, category_targets: {category_id: number}}` |
| `preferences` | `{preferred_domains: string[], preferred_modes: string[]}` |
| `limits` | `{max_activities: integer or null, max_duration_minutes: number or null}` |

At least one target is required: a non-null total_target or a non-empty
category_targets map. Target category IDs must exist in the selected baseline.
A target above a cap is allowed; do not silently lower it.

Allowed domains: `academic`, `volunteer`, `culture_sports`, `skills`,
`career`, `other`. Allowed modes: `online`, `offline`, `hybrid`.
Preference arrays contain unique values.

### 4.2 Internal `context` and `baseline`

The backend creates `context` by extending scope with `baseline_ref`,
`dataset_version`, `ruleset_version`, and `calendar_version`.
These refer to immutable snapshots for one planning request.

The `baseline` object contains:

| Field | Meaning |
| --- | --- |
| `category_scores` | Map of category ID to current confirmed score |
| `category_caps` | Map of the same category IDs to their score caps |
| `total_score` | Current total after the overall cap |
| `max_total_score` | Overall score cap |
| `included_activity_ids` | Unique IDs of activities already counted in this baseline |

Require `category_scores[c] <= category_caps[c]` and
`total_score = min(sum(category_scores.values()), max_total_score)`.
Missing baseline data or an unavailable counted-activity ledger produces
`NEEDS_DATA`; an empty ledger is valid only when known to be empty.

All assessments and scorer responses must match the context of the request.
Changed data requires reassessment, not mixing responses from different versions.

### 4.3 `feasibility_request → feasibility_response`

Both envelopes include `contract_version`, `request_id`, and `context`.

The request adds `available_intervals` and `activities`. Each activity entry
has `activity` and `score_binding_ref` (a string or null). The backend resolves
QA, eligibility, and rule-mapping evidence by context and activity ID.

The existing activity object retains these 14 fields:

`activity_id`, `source`, `title`, `domain`, `start`, `end`,
`registration_deadline`, `mode`, `location`, `points`, `mandatory`,
`audience`, `fee`, `completion_requirements`.

The source object contains `publisher`, `platform`, `URL_post`, and
`URL_registration`. Preserve the existing SP1 activity contract; do not add
planner fields inside it or fabricate missing source data. Malformed source
records remain in upstream QA rather than being forced into candidates.

The response adds:

- `candidates`: activity entries with
  `feasibility={status, reason_codes}`.
- `conflict_pairs`: arrays of two distinct activity IDs, each pair sorted
  lexicographically, with no repeated pairs.

Feasibility statuses:

| Status | Meaning |
| --- | --- |
| `FEASIBLE` | Required checks passed; reason_codes is empty |
| `INFEASIBLE` | A known constraint fails; at least one reason code |
| `NEEDS_REVIEW` | Essential data or verification is missing; at least one reason code |

Standard reason codes: `OUTSIDE_WINDOW`, `OUTSIDE_AVAILABILITY`,
`DEADLINE_PASSED`, `ALREADY_STARTED`, `INELIGIBLE`, `MISSING_SCHEDULE`,
`MISSING_DEADLINE`, `MISSING_ELIGIBILITY`, `NEEDS_SOURCE_REVIEW`,
`TERM_UNVERIFIED`, `MISSING_SCORE_BINDING`, `UNSUPPORTED_SCHEDULE`.

A FEASIBLE activity must have a non-null score_binding_ref and complete schedule,
satisfy `start < end`, start at or after as_of, and fit inside the planning
window and the union of available intervals. Registration requires
`as_of < registration_deadline`; a missing deadline requires review in v0.1.
Merge overlapping/adjoining availability intervals before checking coverage.

Như Ngọc supplies all time-overlap conflicts. The planner checks for missing
overlap pairs as an input-consistency check, rather than implementing a second
eligibility engine. Unknown eligibility or multi-session details require review.

### 4.4 `planner_input`

Required fields:

```text
contract_version, request_id, context, baseline,
goals, preferences, limits, candidates, conflict_pairs
```

The backend copies goals/preferences/limits from the public request and candidates/
conflict_pairs from the matching feasibility response. Only FEASIBLE activities
not already in included_activity_ids may be selected.

The source field `mandatory` does not automatically require selection.
The source field `points` is an announced amount, not guaranteed earned credit.

## 5. SP2 scoring interface

### 5.1 `score_request`

Required fields: `contract_version`, `request_id`, `context`, `baseline`,
and `selected_activity_ids` (unique, lexicographically sorted IDs).

The adapter resolves the selected records and trusted rule mappings using the
context. The planner does not supply invented award amounts or approval flags.

### 5.2 `score_response`

Required fields: the same version/request/context and selected_activity_ids,
plus `evaluation_status`, `result`, `errors`, `mode="DEMO_ONLY"`,
and `official_award_verified=false`.

When evaluation_status is `OK`, errors is empty and result contains:

| Field | Meaning |
| --- | --- |
| `category_after` | Projected scores for every baseline category |
| `category_gain` | category_after minus baseline.category_scores |
| `total_after` | Projected total after the overall cap |
| `total_gain` | total_after minus baseline.total_score |
| `contributions` | Entries with activity_id, category_id, rule_id, projected_added |

SP2 evaluates the **whole selected set**, including caps, duplicates, repetition
limits, and rule interactions. Do not sum independent single-activity scores
computed against the same baseline.

Version 0.1 supports non-negative contributions and one rule/category per
activity. Unsupported rules or missing verification produce `NEEDS_REVIEW`.
Each selected ID appears once in contributions, including zero-gain entries.
Allocate contributions deterministically in start-time/ID order; contributions
per category must sum to category_gain. The overall cap may make total_gain
smaller than the sum of category gains.

Scoring the empty set returns the baseline with zero gains and no contributions.
Do not label future attendance CONFIRMED/VERIFIED to bypass evidence checks;
the adapter must keep hypothetical scoring separate from confirmed records.

For `NEEDS_REVIEW` or `ERROR`, result is null and errors has at least one
`{code, message, activity_id}` entry; activity_id may be null.
Never replace an error with zero points or reuse a response for another set.

## 6. Selection policy

For each valid subset, obtain its SP2 result. Prefer the lowest lexicographic
ranking tuple:

1. Sum of remaining gaps for the specified category targets.
2. Remaining gap for the total target, or zero when no total target is set.
3. Number of selected activities.
4. Negative preference-match score.
5. Total activity duration in minutes.
6. Sorted activity ID list.

For each target, `gap = max(0, target - projected_score)`.
Each selected activity earns one preference point for a matching domain and
one for a matching mode. Fewer activities rank before preferences so that
unnecessary activities are not added just to increase preference points.
Present the final schedule in start-time/ID order.

Prioritizing category targets before the total target is a provisional v0.1
choice. Changes to this order require a contract version update.

The default budget is 4,096 unique subset evaluations, including the empty set.
Do not silently truncate candidates. Search order must be deterministic.
If the budget is exhausted with unexplored subsets, report
`search.complete=false` and `limit_reason="EVALUATION_LIMIT"`.
Do not claim optimality or impossibility based only on an incomplete search.

If the baseline already meets all targets, the empty plan is optimal under
this policy. It may return `ALREADY_MET` immediately, with complete=false,
optimality_proven=true, evaluated_subsets=1, and limit_reason=ALREADY_MET.

## 7. Output and failure handling

### 7.1 `planner_output`

| Field | Type and meaning |
| --- | --- |
| `contract_version`, `request_id`, `context` | Match the request |
| `status` | One of the statuses below |
| `selected_activities` | Entries with activity_id, title, start, end, reasons |
| `excluded_candidates` | Entries with activity_id, code, message |
| `score_summary` | Score fields below, or null when evaluation is unavailable |
| `search` | complete and optimality_proven are booleans; evaluated_subsets is a non-negative integer; limit_reason is null, EVALUATION_LIMIT, ALREADY_MET, SP2_FAILURE, or INVALID_INPUT |
| `feasibility_conclusion` | REACHABLE, PROVEN_UNREACHABLE, or UNDETERMINED |
| `proof` | Null or {kind: EXHAUSTIVE_SEARCH, evaluated_subsets: integer} |
| `warnings` | Array of {code, message} |
| `errors` | Array of {code, message, activity_id}; nullable activity_id |
| `mode`, `official_award_verified` | DEMO_ONLY and false |

`score_summary` contains baseline_by_category, projected_by_category,
gain_by_category, baseline_total, projected_total, gain_total,
remaining_by_category, and remaining_total.
The remaining_by_category map contains exactly the specified category targets.
remaining_total is null when no total target is set. A gap is to the user's
target, not automatically to the category cap.

Each reason has code, message, category_id, and projected_added.
Use `GOAL_CONTRIBUTION` for SP2-backed contributions and `PREFERENCE_MATCH`
for actual preference matches; the last two fields are null for preference-only
reasons. Message wording may vary without changing decision semantics.

| Status | Meaning | Conclusion |
| --- | --- | --- |
| `ALREADY_MET` | Baseline already meets every target; empty plan | REACHABLE |
| `TARGET_MET` | Selected plan is projected to meet every target | REACHABLE |
| `PARTIAL` | A scored plan or baseline leaves a gap | UNDETERMINED or PROVEN_UNREACHABLE |
| `NO_FEASIBLE_CANDIDATES` | Baseline is insufficient and no eligible, uncounted candidate remains | PROVEN_UNREACHABLE after the empty set is evaluated |
| `NEEDS_DATA` | Baseline/context unavailable, or scorer needs review | UNDETERMINED |
| `ERROR` | Invalid internal input or scorer failure | UNDETERMINED |

Evaluate in this order: validate input/context, score the empty baseline, return
ALREADY_MET if appropriate, filter candidates, then search valid subsets.

If any scorer call returns NEEDS_REVIEW or ERROR, return NEEDS_DATA or ERROR
respectively, with selected_activities=[], score_summary=null, proof=null,
search.complete=false, and optimality_proven=false. Retain the evaluation count,
set limit_reason=SP2_FAILURE, and provide an error reason. For invalid internal
input use limit_reason=INVALID_INPUT. When context cannot be resolved at all,
return the API error envelope below rather than fabricating a complete context.

PROVEN_UNREACHABLE requires successful evaluation of every valid subset, with
none meeting the targets. Its proof count includes the empty set. The conclusion
applies only to eligible candidates and constraints in this context; reviewed or
new activities can change it. A partial search that finds a successful plan may
report TARGET_MET/REACHABLE, but not proven optimality.

For completed scoring, every candidate appears exactly once in either selected
or excluded activities. Apply exclusion reasons in this order:
NEEDS_REVIEW, NOT_FEASIBLE, ALREADY_COUNTED, CONFLICT, LIMIT, LOWER_PRIORITY.
CONFLICT must refer to a conflict with a selected activity. LIMIT means adding
the candidate would violate a stated limit. A global error may leave both
lists empty.

Warnings always include DEMO_ONLY and TRAVEL_NOT_MODELED. Add PENDING_CANDIDATES
when review is outstanding and SEARCH_INCOMPLETE when search stops early
except for ALREADY_MET. Successful scoring has errors=[].

### 7.2 Proposed HTTP behavior

| Situation | HTTP status and body |
| --- | --- |
| Scored outcomes, including partial or no candidates | 200; planner_output |
| Missing data or review required | 409; planner_output if context is complete, otherwise api_error |
| Invalid public request | 422; api_error |
| SP2 adapter failure | 502; planner_output |
| Invalid internal contract | 500; planner_output if context is complete, otherwise api_error |

`api_error` contains contract_version, request_id (nullable if unreadable),
code, message, and details=[{path, message}].
These are proposed endpoint behaviors, not changes to existing APIs.

## 8. Required consistency checks

- Activity IDs are unique; conflict pairs reference existing, distinct IDs.
- window_start < window_end, as_of <= window_end, and all timestamps have offsets.
- FEASIBLE candidates satisfy the schedule, deadline, and binding requirements.
- Baseline, feasibility, scorer, and output use identical snapshot contexts.
- Category sets, caps, totals, gains, and remaining gaps are arithmetically consistent.
- Selected IDs are eligible, uncounted, conflict-free, and within both limits.
- Scorer responses match the requested ID set; reasons use actual contributions.
- Complete search/proof counts reflect all evaluated valid subsets without duplicates.
- NEEDS_DATA/ERROR never contain fabricated scores or an impossibility proof.
- Planning leaves all inputs and persistent application state unchanged.

## 9. Inline examples and expected results

All examples are synthetic contract specifications, not executed planner tests
or real SP2 results. Only C1 is modeled in these examples. A real baseline must
include all categories defined by its ruleset.

### 9.1 Example 1 — complete planner input

Activity A contributes a projected 5 points in the mock SP2 evaluation.

```json
{
  "contract_version": "sp3-planner/0.1",
  "request_id": "demo-01",
  "context": {
    "student_id": "synthetic-student",
    "term_id": "SYNTHETIC-DEMO",
    "window_start": "2026-11-01T00:00:00+07:00",
    "window_end": "2026-11-04T00:00:00+07:00",
    "as_of": "2026-11-01T08:00:00+07:00",
    "timezone": "Asia/Ho_Chi_Minh",
    "baseline_ref": "mock-baseline-01",
    "dataset_version": "mock-data-01",
    "ruleset_version": "mock-rules-01",
    "calendar_version": "mock-calendar-01"
  },
  "baseline": {
    "category_scores": {"C1": 20},
    "category_caps": {"C1": 30},
    "total_score": 20,
    "max_total_score": 100,
    "included_activity_ids": []
  },
  "goals": {"total_target": null, "category_targets": {"C1": 25}},
  "preferences": {"preferred_domains": [], "preferred_modes": []},
  "limits": {"max_activities": null, "max_duration_minutes": null},
  "candidates": [{
    "activity": {
      "activity_id": "A",
      "source": {
        "publisher": "Synthetic fixture",
        "platform": "fixture",
        "URL_post": "https://example.invalid/activity/A",
        "URL_registration": null
      },
      "title": "Sample activity A",
      "domain": "academic",
      "start": "2026-11-02T09:00:00+07:00",
      "end": "2026-11-02T10:00:00+07:00",
      "registration_deadline": "2026-11-01T18:00:00+07:00",
      "mode": "online",
      "location": null,
      "points": 5,
      "mandatory": false,
      "audience": ["Synthetic students"],
      "fee": 0,
      "completion_requirements": "Complete the session and satisfy the mock evidence check."
    },
    "score_binding_ref": "mock-binding-A",
    "feasibility": {"status": "FEASIBLE", "reason_codes": []}
  }],
  "conflict_pairs": []
}
```

For the upstream public request, use the scope fields from this context,
available_intervals=[{start: window_start, end: window_end}], and the same
goals/preferences/limits. A FEASIBLE assessment here represents explicit mock
eligibility evidence, not an assumption about a real student.

Expected output below is a **field projection**, not a complete API payload.
A complete response also echoes context/version/request_id, copies the selected
activity's title/schedule, and includes reasons, warnings, errors, and demo flags
as specified in Section 7.

```json
{
  "status": "TARGET_MET",
  "selected_activities": [{"activity_id": "A"}],
  "score_summary": {
    "projected_by_category": {"C1": 25},
    "gain_by_category": {"C1": 5},
    "remaining_by_category": {"C1": 0}
  },
  "feasibility_conclusion": "REACHABLE",
  "search": {
    "complete": true,
    "optimality_proven": true,
    "evaluated_subsets": 2,
    "limit_reason": null
  },
  "proof": null
}
```

### 9.2 Examples 2 and 3 — variations on Example 1

Use distinct request IDs and baseline/dataset/ruleset version identifiers for
each example. All candidates are explicitly mock-FEASIBLE, online, uncounted,
and registered before the same deadline. Other fields follow Example 1.

| Detail | Example 2: conflict and preference | Example 3: unreachable target and cap |
| --- | --- | --- |
| Current C1 / cap / target | 20 / 30 / 25 | 22 / 25 / 30 |
| Activity A | Academic; 2 Nov, 09:00–10:00; mock nominal +5 | Academic; 2 Nov, 09:00–10:00; mock nominal +5 |
| Activity B | Skills; 2 Nov, 09:00–10:00; mock nominal +5 | Skills; 3 Nov, 09:00–10:30; mock nominal +5 |
| Preferences | preferred_domains=["skills"] | Empty |
| conflict_pairs | [["A", "B"]] | [] |
| Selected IDs | ["B"] | ["A"] |
| Projected C1 / gain / gap | 25 / 5 / 0 | 25 / 3 / 5 |
| Excluded activity | A: CONFLICT | B: LOWER_PRIORITY |
| Status / conclusion | TARGET_MET / REACHABLE | PARTIAL / PROVEN_UNREACHABLE |
| Complete evaluations | 3 | 4 |
| Proof | null | {kind: EXHAUSTIVE_SEARCH, evaluated_subsets: 4} |
| Selection reason | Same score and activity count; B matches the preferred domain | Same capped gain; A takes 60 minutes instead of 90 |

Static SP2 expectations for every valid subset:

| Example | Selected set | C1 after | C1 gain | Contributions |
| --- | --- | --- | --- | --- |
| 1 | [] | 20 | 0 | [] |
| 1 | [A] | 25 | 5 | A: 5 |
| 2 | [] | 20 | 0 | [] |
| 2 | [A] | 25 | 5 | A: 5 |
| 2 | [B] | 25 | 5 | B: 5 |
| 3 | [] | 22 | 0 | [] |
| 3 | [A] | 25 | 3 | A: 3 |
| 3 | [B] | 25 | 3 | B: 3 |
| 3 | [A, B] | 25 | 3 | A: 3, B: 0 |

Example 2's [A, B] subset is invalid because of the conflict. In these examples,
total_after equals C1 after, total_gain equals C1 gain, and remaining_total is
null. All listed evaluations return OK. The mock may use rule_id=MOCK_R_A or
MOCK_R_B for the corresponding contribution. A mock scorer must fail on an
unspecified set rather than invent a result.

\