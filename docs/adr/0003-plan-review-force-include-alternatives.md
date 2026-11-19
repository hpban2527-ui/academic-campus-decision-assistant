# ADR 0003: Plan review (force-include, alternatives, remove / what-if) and the confirmed plan on a calendar dashboard

- Status: implemented on branch `feat/plan-review-dashboard`; for review by Thao Duyen, integration by Binh An.
- Date: 2026-11-19
- Contract: planner contract `sp3-planner/0.2` gains revision 0.2.1 (additive, see D10). The wire string
  `contract_version` is unchanged.
- Needs agreement: Ngoc (`preview_personalized_swap` and `real` source, see "Open points"), Binh An (merge of
  `web/index.html`, `src/api/server.py`, `src/api/sp3_service.py`).

## Context

Students get a plan option and need to adjust it: swap an activity, remove one, ask "what if I skip this",
and then confirm a plan that appears on the home dashboard as a calendar. The planner could not force an
activity into a plan unless its schedule was FIXED, so `preview_personalized_swap` failed for flexible
replacements ("needs a force-include contract"). There was no way to list valid replacements, no
remove-only preview, and the dashboard showed calculator numbers (0 points, "con 80d") that disagreed with the
planner (baseline 60, target 80).

## Decisions (product decisions 1-9, fixed before implementation)

1. Students review a plan option, can SWAP or REMOVE activities, then CONFIRM. The confirmed plan is shown on
   the home dashboard as a calendar.
2. A replacement is valid only if the plan still reaches the target (`projected_total >= target`). If the base
   plan was already below the target, a replacement must not lower the projected total.
3. Replacement ranking: (a) preference utility from the personalization engine, higher first; (b) total plan
   duration, shorter first; (c) registration deadline, later first (a missing deadline last); (d) `activity_id`.
4. "Neu bo" (preview) = `what_if_skip` with `KEEP_TIME` for every remaining selected activity, so it only adds
   compensating activities and never reshuffles the others. "Bo" (remove) = remove only and re-score, with no
   automatic replacement; it may fall below the target and is then flagged, not rejected.
5. No participation time limit is added anywhere; `limits.max_duration_minutes` stays as the confirmed
   preference sets it. `weekly_participation_hours` is not touched.
6. Activities with missing planning information (no scored criterion or points binding, no start or end, no
   mode, or an offline/hybrid activity without a campus or location) are never offered as replacements.
7. Hard exclusions of the confirmed preference apply to replacements exactly as to the planner (they arrive as
   INFEASIBLE candidates, so a `FORCE_INCLUDE` or `KEEP_TIME` on them is a `NOT_ELIGIBLE` keep conflict).
8. Numbers shown to students come only from SP2/SP3 outputs; the UI computes no score.
9. The confirmed plan is stored locally per account and stays until the student confirms a new one.

## D10. Planner contract revision 0.2.1: `FORCE_INCLUDE`

`keep_requests[]` accepts `{activity_id, mode}` with `mode` in `KEEP_TIME`, `FORCE_INCLUDE`.

| | `KEEP_TIME` | `FORCE_INCLUDE` |
| --- | --- | --- |
| must be in `previous_plan` | yes | no |
| time-frozen | yes, previous blocks | no; the normal scheduler places it |
| conflicts it can raise | `NOT_LISTED`, `NOT_ELIGIBLE`, `FIXED_CHANGED`, `BLOCK_INVALID`, `BLOCK_OVERLAP`, `CONFLICT`, `LIMIT` | `NOT_LISTED`, `NOT_ELIGIBLE`, `BLOCK_OVERLAP`, `CONFLICT`, `NO_TIME`, `LIMIT` |

- One request per activity ID across both modes. The base set of every plan is all required activities
  (`required = keep_time | force_include`). The search only adds activities to that set.
- Placement reuses `sp3.scheduler.schedule_set`; no second scheduler. `KEEP_TIME` activities are passed as the
  scheduler's `keep`, forced ones are ordinary flexible or fixed members of the set, so they fit around the
  kept blocks.
- New keep-conflict code `NO_TIME`: a forced activity that no schedule can place together with the
  conflict-free `KEEP_TIME` blocks; when each fits alone but not all together, every forced activity gets it.
  The planner returns `KEEP_CONFLICT` before scoring; it never drops a forced activity or returns a fake plan.
- `ALREADY_MET` stays the empty plan. A forced base set that meets every target with no previous plan is
  reported as `TARGET_MET` (found while testing the regression below).
- `plan_checker` re-derives the same conflicts independently and flags `FORCE_NOT_HONORED` when a forced
  activity is missing from a plan. Where its brute force cannot decide (more than 6 flexible activities) it
  accepts either answer for a `NO_TIME` entry.
- Versioning: `CONTRACT_VERSION` stays `"sp3-planner/0.2"` because feasibility, fixtures and the demo wiring
  compare that string; `contract.CONTRACT_REVISION = "0.2.1"` records the change. Inputs that use only
  `KEEP_TIME` behave exactly as before.
- API of the validators: `parse_keep_requests` returns `KeepRequests(keep_time, force_include)`;
  `validate_keep_requests` keeps returning the `KEEP_TIME` IDs.

## D11. Review endpoints (synthetic and real sources after Phase 1-2 integration)

All request bodies set `confirmed_profile: true` and carry `preference` and `base_result` (one engine result,
as for swap-preview). Every response is stateless; nothing is stored or applied.

- `POST /api/sp3/personalized/swap-preview`: `add_activity_id` is now required but nullable. A string keeps
  Ngoc's behaviour (FIXED replacement unchanged; flexible replacement uses `FORCE_INCLUDE`). `null` removes the
  activity only and returns `{status: "PREVIEW", kind: "REMOVE", target_total, projected_total,
  remaining_total, remaining_by_category, target_met, warnings: ["BELOW_TARGET"] | [], before, after,
  dropped_activity_ids, added_activity_ids: [], result}`. The count cap that stops SP3 from adding activities
  is `max_activities = number of remaining activities` (an internal mechanism, not a time limit).
- `POST /api/sp3/personalized/alternatives`: `{..., remove_activity_id, limit = 3 (1..10)}` returns
  `{status: "ALTERNATIVES", target_total, base_projected_total, required_projected_total, target_rule:
  "REACH_TARGET" | "NO_REGRESSION", total_valid, limit, items[], filtered_out[]}`. Each item has
  `activity_id, title, schedule_type, scheduled_blocks, criterion, effective_gain, projected_total,
  remaining_total, target_met, duration_minutes, plan_duration_minutes, mode, campus, location,
  registration_deadline, preference {utility, matches[]}, added_activity_ids, dropped_activity_ids,
  extra_added_activity_ids, preview_id, preview`. `preview` is the full swap-preview payload; the client
  confirms `preview.result`. `preview_id` is a stateless hash of the swap and the plan. `filtered_out` explains
  every rejected candidate with `HARD_EXCLUDED`, `NOT_FEASIBLE`, `INCOMPLETE_INFO`, `SWAP_REJECTED` (conflict or
  keep conflict) or `BELOW_TARGET`. Each candidate goes through `preview_personalized_swap`, so the checker has
  0 violations and there are no keep conflicts for every item.
- `POST /api/sp3/personalized/what-if-skip`: `{..., remove_activity_id}` runs `what_if_skip` with `KEEP_TIME`
  for all remaining selected activities and returns the same preview shape with `kind: "WHAT_IF_SKIP"`; the
  other activities' blocks are verified unchanged.

## D12. `confirmed_plan` (per-account local data, `unilife_data_<mssv>`)

Keys added next to the existing ones; the keys owned by others (`profile`, `canonical_availability`,
`confirmed_preference`, `planner`) are only read.

```json
{
  "confirmed_plan": {
    "plan_version": "sp3plan-0123456789abcdef",
    "based_on": {"calendar_version": "...", "dataset_version": "...", "ruleset_version": "...",
                 "baseline_ref": "...", "previous_plan_version": null},
    "confirmed_at": "2026-11-19T09:30:00.000Z",
    "source": "SYNTHETIC-DEMO",
    "option_label": "Can bang",
    "target_total": 80,
    "as_of": "2026-11-08T20:00:00+07:00",
    "score_summary": {"baseline_total": 60, "gain_total": 20, "projected_total": 80, "remaining_total": 0, "...": "..."},
    "activities": [{
      "activity_id": "SEM-A", "title": "...", "criterion": "C1", "effective_gain": 5, "mode": "offline",
      "campus": null, "location": "Synthetic hall", "registration_deadline": "2026-11-08T23:00:00+07:00",
      "completion_requirements": "...", "scheduled_blocks": [{"start": "...", "end": "..."}], "source_url": "..."
    }]
  },
  "pending_plan_notice": false,
  "invalidated": {"value": false, "reason": null},
  "confirmed_plan_basis": {"availability": "<fingerprint>", "preference": "<fingerprint>"}
}
```

`as_of` and `confirmed_plan_basis` are additions to the agreed field list: `as_of` is the planner's demo clock
(`plan.context.as_of`, 2026-11-08 for the synthetic fixture, 2026-10-01 for the real store), used as "today" so
the UI never reads the system date; `confirmed_plan_basis` holds fingerprints of `canonical_availability`
(without `weekly_participation_hours`, which the planner never receives) and `confirmed_preference`.

- `confirmConfirmedPlan(result)` writes `confirmed_plan` from an engine result only (it checks the plan version
  format, the scored status, `context.as_of` and the target) and clears both notices.
- Re-running the planner never touches `confirmed_plan`; it sets `pending_plan_notice`.
- `persistCurrentUserData` recomputes the fingerprints; a changed availability or confirmed preference sets
  `invalidated` with a reason (a missing preference is ignored: it is also what the page holds while loading).
- The dashboard (`#confirmedPlanDashboard`) reads only `confirmed_plan`: Hom nay agenda (default), Tuan and
  Thang views, the busy schedule as a faded background in the week view, both banners, an empty state and a
  progress block from `score_summary`. The four older overview cards and the semester-progress block stay in
  the page but are hidden, because their numbers come from the calculator and can contradict the planner.

## D13. Student availability in review calls (added 2026-11-19)

`preview_personalized_swap` used to rebuild the plan from the default synthetic availability, so swaps and
alternatives could place an activity in time the student marked busy. The three review endpoints
(`swap-preview`, `alternatives`, `what-if-skip`) now accept an optional `availability` object with the same
field name and schema as `PersonalizedPlanRequest.availability` (canonical `sp3-availability/0.2`: weekly
blocks, exceptions, busy intervals). It is passed as `availability_request` to `personalized_demo_plan`, which
is what `/personalized/plan` does. Omitted = the fixture default (previous behaviour). Because the plan is
rebuilt with the student's availability, an activity in busy time is INFEASIBLE there, so it is filtered from
alternatives and a swap to it is rejected even if the client's `base_result` still lists it as feasible.

The only edits in Ngoc's code are marked `REVIEW-DASH: availability pass-through (needs Ngoc review)`: the new
`availability_request` parameter of `preview_personalized_swap` and its forwarding to `personalized_demo_plan`,
and the `availability` field plus forwarding in `SmartSwapRequest` / the swap-preview handler.

Review results carry `checker_violations` (always 0: a plan that fails the independent check raises instead of
being returned). Results from other endpoints do not have the field; the UI treats a missing value as 0 for the
same reason.

## D14. Review screen contract (`openPlanReview`)

`openPlanReview(result, optionLabel)` opens the review screen (`#planReviewScreen`) on a private draft.

- `result`: one engine result, as returned in `options[i].result` of `/personalized/options`, by
  `/personalized/plan`, or as the `result` of a swap / remove / what-if preview. It must be a scored plan with a
  `plan_version`, `plan.context.as_of` and `requested_total_target` (`cpdIsEngineResult`); otherwise the call
  returns `false`. The object is copied; the caller's data is never changed.
- `optionLabel`: Vietnamese label kept as `confirmed_plan.option_label` (` - da chinh` is appended when the
  student edited the plan).
- Ngoc's option cards call the same function. The planner screen's "Review ke hoach" button calls
  `openPlanReviewFromUi()`, which passes the plan on screen.
- Layout (kieu A): activity list on the left, one panel on the right: summary, alternatives or activity detail;
  below the `lg` breakpoint the panel stacks under the list. Rows have Doi / Neu bo / Bo.
  - Doi: `/alternatives` (limit 10), top 3 with "Xem them (n)" for the rest, one reason chip (the strongest
    preference match). Choosing adopts the engine's `preview.result` for the whole plan and marks the row
    "Da doi" with "Hoan tac".
  - Neu bo: `/what-if-skip`, shown under the row, never applied.
  - Bo: `/swap-preview` with `add_activity_id: null`, shown under the row; "Xac nhan bo" applies it. A plan below
    target shows "Chua dat muc tieu" and a warning text; the confirm button stays enabled.
  - Summary: baseline -> projected vs target, per-criterion bars scaled by the criterion cap
    (`DEFAULT_SCORES_TEMPLATE`, a display scale), checker violations, mandatory activities not scheduled,
    "Xac nhan ke hoach" (disabled only when `checker_violations > 0`) and "Khoi phuc phuong an goc".
- Undo: every applied change is a step holding the previous result; "Hoan tac" restores the state before that
  step and drops the steps after it.
- States: loading, API error (the last valid draft is kept; "Thu lai"), no alternatives. Edit buttons are disabled
  until a preference is confirmed (the review endpoints need one); confirming still works.
- Confirm calls `confirmConfirmedPlan` and opens the dashboard. The draft lives in memory only; it is not persisted.
- All requests send `plannerAvailabilityPayload()` (D13) and use `sp3Query()`; Phase 1-2 enables real-source review.

## D15. Confirming over an existing confirmed plan (added 2026-11-19)

Both confirm paths (the "Xac nhan ke hoach" button on the plan result and the review screen) go through
`cpdRequestConfirm(result, label, done)`. With no confirmed plan it confirms at once. Otherwise it opens
`#planDiffModal` first: activities added, removed, moved (same activity, different blocks) and unchanged, and the
projected total before -> after; both totals are engine outputs (`confirmed_plan.score_summary` and the new
`plan.score_summary`). "Xac nhan ke hoach moi" calls `confirmConfirmedPlan`, which clears `pending_plan_notice`
and `invalidated` and refreshes the dashboard; "Giu ke hoach cu" leaves everything unchanged. Steps 2 and 3 of the
planner journey are demo scenarios and offer neither button.

The dashboard's "today" is `confirmed_plan.as_of`, the demo clock of the plan's source: 2026-11-08 for the
synthetic fixture and 2026-10-01 for the real store (`api.sp3_real.AS_OF`). For the synthetic demo student nothing is
planned on 2026-11-08 itself; the agenda shows the registration deadlines due that evening and the activities of
09-12 Nov. For the real store the first planned activity is 2026-10-25, so "Hom nay" shows "next activity on ...".

Browser flow (register, plan, review, swap, remove, confirm, busy change, replan, diff, confirm, real-store clock):
`scripts/verify_review_dashboard_e2e.py`.

## Consequences

- Flexible replacements work in swap-preview, alternatives and what-if.
- Replacement previews keep every other planned activity at its time (`KEEP_TIME`), so an alternative that
  needs a slot the kept blocks occupy is rejected (`SWAP_REJECTED`) instead of reshuffling the plan.
- A replacement may pull in compensating activities (`extra_added_activity_ids`); the UI should show them.

## Open points

- Browser acceptance on desktop/mobile is still pending. This execution environment rejects localhost
  connections with Windows socket error 10013; controller tests do not replace browser acceptance.
- Phase 3 (opening the planner after onboarding) is not wired; it requires a separate product decision.
- Ngoc must review the availability parameter on her preview wrappers, the shared remove-only path,
  FORCE_INCLUDE handling and the marked controller hooks before final integration by An.

## Phase 1-2 integration with Nhu_Ngoc ee14c95 (2026-11-19, uncommitted)

- Ngoc's `_preview_personalized_change` is the only swap/add implementation. Flexible replacements use the
  existing FORCE_INCLUDE revision 0.2.1; the wire string remains `sp3-planner/0.2`.
- Swap/remove/alternatives/what-if accept current request availability and support `source=real`. They do not
  reuse availability from an older result. Both removal routes delegate to `remove_planned_activity` and never
  add compensation; what-if is the separate compensating preview.
- Preference explanations are refreshed by the preference engine after every edit. Points and feasibility
  remain SP2/SP3 outputs.
- One full-screen review dialog and shared detail renderer serve both planner entry points. The old alternatives
  and activity-detail entry points redirect into this flow; their compatibility bodies remain inactive.
- `UniLifePlanReviewContract.confirmPlan` resolves only after persistence or explicit cancellation of the diff.
  Confirmation stores the edited result, updates the planner state, and opens the home dashboard.
- `REVIEW_ALLOW_ADD = false` removes free-slot add entry points while retaining their implementation. The
  optional participation-hours editor is hidden and UI planner requests always set the duration cap to null.
- All local HTML/controller changes relative to Ngoc's integration base are inside REVIEW-DASH markers.
  Her busy-calendar profile callback and busy deletion already save through `persistCurrentUserData`; onboarding
  draft writes remain local drafts and were not rewritten.

## Verification

- `tests/sp3/test_planner_force_include.py`, `tests/personalization/test_plan_review.py`,
  `tests/test_review_dashboard_ui.py`.
- Browser: `python scripts/verify_review_dashboard_e2e.py` (Edge/Chrome through the DevTools protocol, standard
  library only), or the manual checklist below.

### Manual checklist (if no browser can be driven)

1. New account, no plan: the home page shows one sentence and a button "Den Lap lich"; no banner.
2. Lap lich, build a plan, press "Xac nhan ke hoach" next to the result: the page switches to the home dashboard.
3. Header shows "Hom nay" with the planner's date (not today's system date); the agenda lists the activities with
   time, place, "+Xd . Muc N" and the registration deadline.
4. Progress block shows the baseline, the planned gain and the target from the plan (60 -> 80 / target 80), never
   0 or "con 80d" from the calculator.
5. Tuan: the first week with activities opens; a busy interval you added shows as a faded hatched block; Thang
   shows the month with the activities and a flag on deadline days.
6. Click an activity: a detail panel opens with time, place, deadline, points and completion evidence.
7. Change the busy schedule: banner "Ke hoach bi anh huong" with the reason.
8. Run the planner again: banner "Co ke hoach moi chua chot"; the calendar still shows the old plan.
9. Confirm again: both banners disappear. A second account has its own empty dashboard.
