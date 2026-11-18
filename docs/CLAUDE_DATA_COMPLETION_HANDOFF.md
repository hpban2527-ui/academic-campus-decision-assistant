# Claude Code handoff — complete UniLife's operational data pipeline

Prepared on 18 November 2026. This is an implementation assignment, not a request for another proposal or annotation interface.

## 1. Destination and authorization

Finish the data side of University Life Assistant / Academic Campus Decision Assistant so the running application actually consumes a coherent, source-grounded activity dataset through SP1 → SP2 → SP3 → UI.

The user explicitly does **not** want to continue manual extraction, spreadsheet filling, per-post approval, or reviewing all 189 announcements. Their business rules have already been discussed and accepted. Use AI extraction, deterministic validation and conservative routing. If the organizer omitted essential facts, represent the absence and exclude the activity from the affected operation. Do not ask the user to invent those facts.

Make ordinary implementation decisions autonomously. Resolve routine cases from the source and existing contracts. If a case cannot be resolved, emit a specific machine-readable reason and keep it out of the affected operation; a new business-rule decision can be documented without blocking completion of the rest of the dataset. Do not turn this back into a blanket human-review requirement.

Success is a working data pipeline used by the real application, not merely a new ZIP, viewer, JSON file or readiness report. Do not stop after rebuilding the standalone 129-post catalog.

## 2. Working-copy situation — inspect before changing Git state

Repository:

```text
C:\Users\ADMIN\Desktop\CT_University Life Assistant\academic-campus-decision-assistant
```

At handoff preparation:

- Working branch: `Thao_Duyen`, HEAD `01b08644bd0c18df86b1b1aa02c5fcc2305416b6`.
- Locally known integrated main: `origin/main` at `f03bb5af30a3a9fc23a8256a3e64c6181ffd1be6` (`UniLife Final integration`). Verify whether the remote has advanced when network access permits.
- The current branch is older than integrated main and does not contain every integration module. For example, `src/sp3/feasibility.py`, `src/api/sp3_real.py`, human-review helpers and admin rebuild tooling exist on integrated main but are not all present in this checkout.
- Important work is **uncommitted**, including modified `src/sp1/extract_v2.py` and `src/sp1/llm_v2.py`, plus new files listed below. Preserve both tracked changes and untracked files.
- Existing stash: `backup-before-main-update`. Do not pop it blindly.
- Previous Codex sessions could read Git state but could not write `.git/FETCH_HEAD`. If your environment has the same restriction, preserve and implement working-copy changes or prepare a patch; do not bypass permissions or erase work.

First inventory the working tree and relevant artifacts. Choose a safe integration checkout/worktree or otherwise preserve this work before reconciling it with integrated main. Do not overwrite newer main datasets with older branch artifacts, force-reset, clean untracked files, or discard any existing review progress. Do not push or merge main as part of this assignment unless separately instructed.

## 3. Read these files first

Business rules and schemas:

- `docs/ACTIVITY_DATA_ACCEPTANCE_V1.md` — latest user-approved acceptance contract.
- `data/config/activity_acceptance_v1.json` — executable policy configuration.
- `docs/NLP_RULES_CURRENT_20261113.md`, `docs/TEAM_COMPLETION_RULES_20261109.md` and the existing ADRs — earlier background; newer explicit user decisions in this handoff take precedence.
- `schemas/layer_a_record_v2.schema.json`, `schemas/activity_v2.schema.json` and the actual SP2/SP3 contracts in the integrated checkout.
- `docs/labelling_guide_v2.md` and `data/gold/README_v2.md` — preserve the distinction between operational AI-derived data and independent evaluation labels.

New implementation already present in this working tree:

- `src/sp1/acceptance.py` — deterministic data-readiness routing.
- `scripts/activity_acceptance.js` — offline viewer counterpart, parity-tested with Python.
- `scripts/package_ai_review.py` — packages the AI drafts and policy catalog.
- `scripts/review_ai_drafts.html` — now an exception/correction viewer, not a mandatory review gate.
- `scripts/check_acceptance_parity.cjs`.
- `scripts/validate_ai_review_export.py` — validator for genuinely human-reviewed exports; never label automated records as human-reviewed.
- `tests/sp1/test_acceptance.py`, `tests/sp1/test_title_publication_labels.py`, `tests/test_ai_review_packet.py`.
- Modified title cleanup in `src/sp1/extract_v2.py` and `src/sp1/llm_v2.py`.

AI annotation work and generated data:

```text
artifacts/ai_review_20261118/source_manifest.json
artifacts/ai_review_20261118/packets/batch_01.json ... batch_06.json
artifacts/ai_review_20261118/annotations/batch_01.json ... batch_06.json
artifacts/ai_review_20261118/annotations/audit_01.json ... audit_06.json
artifacts/ai_review_20261118/ai_crosscheck_log.json
artifacts/ai_review_20261118/deliverables/unilife_ai_drafts_129.json
artifacts/ai_review_20261118/deliverables/unilife_policy_catalog_129.json
artifacts/ai_review_20261118/deliverables/summary.json
artifacts/ai_review_20261118/deliverables/unilife_review_129.html
artifacts/ai_review_20261118/unilife_review_129.zip
```

The ZIP is a delivery artifact, not the runtime source of truth. If local artifacts are unavailable, report exactly what is missing and recover from the existing project files where possible; do not invent annotations or claim you inspected missing files.

## 4. What has actually been completed

- Corpus: 189 original announcements. Frozen split: 40 dev, 89 pool, 60 test.
- AI-assisted draft extraction covers all **129 non-test posts**, with 19 stated-fact fields plus activity type, exact-source evidence, uncertainty notes and source fingerprints.
- A second AI pass produced 17 draft corrections. This is AI cross-checking, not independent human gold.
- Current policy classification of those 129 posts:

| Status | Count |
| --- | ---: |
| READY | 1 |
| READY_WITH_WARNINGS | 93 |
| NOT_SCHEDULABLE | 34 |
| NOT_AN_ACTIVITY | 1 |

Thus 94 have data sufficient to construct a schedule under the current policy. This is **not** a measured NLP accuracy, a promise that 94 are currently available, or a claim that all 94 have verified score bindings or student eligibility.

- The standalone viewer exports policy-processed records without requiring per-post human approval. Old review progress can be imported using the same packet ID, post IDs and source fingerprints; real user edits must be preserved.
- Previously run checks: 591 tests passed for `tests/sp1` plus `tests/test_ai_review_packet.py`; Python/JavaScript policy parity passed for all 129 records. This does **not** establish that the new data has passed the integrated app's complete SP2/SP3/browser flow.
- The catalog has **not yet been connected to application runtime**. This is the main remaining task.

## 5. Accepted business behavior

### Missing facts versus defaults

Separate stated facts, explicit team defaults, unresolved source information and genuine human corrections. Preserve `null`/`[]` when the source is silent. Do not fill a field just to satisfy an old schema. Keep evidence and provenance after normalization, merging, corrections and handover.

### Scheduling

- Fixed offline events, live online sessions and hybrid attendance need a source-supported date and start time. A date-only `00:00` normalization boundary is not a real event start.
- Missing essential timing means retain the source, emit a reason, and exclude from automatic scheduling. Do not create a mandatory user task to supply an organizer's missing time.
- Existing team defaults when a real start time exists but the end/duration is missing: 120 minutes offline; 30 minutes live online/hybrid. An explicit stated duration wins. Mark these as assumptions in the schedule, never as extracted statements.
- Online quizzes with a supported participation window can be flexible. Date-only bounds become window boundaries, not mandatory attendance hours. Use the stated duration, otherwise the agreed 30-minute quiz default.
- Do not turn every online event into a flexible quiz. A live webinar containing a quiz is still a live event. Audit the existing regex-based quiz/live distinction and improve it conservatively if necessary.
- Do not shrink a stated duration to make a plan fit.
- Current team scope uses the first session/round. Keep later-session and whole-course obligations in metadata; do not claim that attending one session satisfies a source requirement to attend several.
- Mandatory activities with missing schedules must remain visible as unscheduled obligations, not silently disappear.

### Optional or contextual fields

- Unknown domain: keep the activity with a warning; do not invent a topic or reward an unverified preference match.
- Unknown/ambiguous fee: preserve `null`, not zero. Unknown, team-based, deposit-dependent or otherwise non-comparable costs cannot certify compliance with a hard per-person budget.
- No registration URL alone is not a reason to discard an event: written instructions, walk-in attendance and other registration channels may exist. Preserve participation instructions and source URLs.
- Missing registration deadline stays unknown. Do not invent a deadline equal to event start. Update downstream feasibility behavior consistently; an old `MISSING_DEADLINE` gate must not accidentally reintroduce blanket human approval or erase the new policy. Preserve uncertainty about whether registration is open when that cannot be established.
- Unknown venue/campus cannot establish a campus preference or travel feasibility. Unknown activity type cannot establish a scoring rule.
- Unresolved audience, obligation, completion or core schedule conflicts must not be treated as verified. Route conservatively with precise reasons rather than inventing a resolution or requiring the user to annotate the whole corpus.

### Titles and publication banners

- Leading `[HTTT]`, `[HTTT}`, and `[Hỗ trợ truyền thông]` are publication/support labels in this project, not event titles.
- Skip leading bracketed campaign-context banners such as `[HƯỞNG ỨNG ...]` when identifying the concrete event below.
- Preserve real event prefixes and names such as `[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ` and distinct tags such as `[HTTN26]`.
- Never globally remove all bracketed text or every occurrence of HTTT inside a genuine name.
- Keep original text and grounded evidence. The recent fix deliberately preserves candidate IDs because recorded LLM outputs refer to those IDs.

## 6. Required implementation

### A. Establish one authoritative operational dataset

Inventory the whole 189-post corpus and all existing stores, cached model outputs, manual decisions, handover files, bindings and feature files. Reconcile them on the integrated branch. The 129-post catalog is an enriched operational input, not a replacement for the entire corpus and not a reason to ignore the other 60 posts.

Preserve valid existing human corrections bound to the current source fingerprint. Do not overwrite them silently with older branch data or new AI drafts. Resolve source-supported conflicts automatically where possible; otherwise keep a documented unresolved state and exclude only the affected operation.

Keep 60 held-out posts separate for evaluation. Do not create AI gold labels, use test examples to tune prompts/policy, or claim held-out accuracy from them. Existing frozen inference outputs may be used for operational processing under the repository's final-run access/reason log, without turning outputs into gold. Account for every source post as usable, informational, duplicate, excluded or explicitly unresolved; a blocked post still counts as accounted for.

Move any authoritative dependency out of disposable `artifacts/` paths into a clearly named versioned project data location. Keep AI provenance, source hashes and optional genuine human decisions. Do not make routine runtime or rebuild depend on a user opening the offline HTML viewer.

### B. Finish the real SP1 → SP2 → SP3 adapters

Connect extraction/accepted facts to normalization, deduplication, scoring bindings, personalization features, scheduling readiness and the catalog actually loaded by the API.

Known integration traps to fix rather than conceal:

1. Old normalizers use `fee=0` for missing fees. The new policy requires unknown cost to remain unknown through the operational pipeline and UI.
2. Old SP3 14-field contracts require numeric fees. Migrate/version the relevant contracts and all real consumers together, or design an explicit unknown-cost-aware adapter. A hidden zero placeholder does not satisfy the task.
3. Old code substitutes event start for an unstated signup deadline. Do not let that invented deadline survive through another adapter.
4. Old readiness checks admit date-only starts or merely warn about missing clock times. The actual planner candidate input must enforce the accepted fixed/flexible distinction.
5. Some handover code takes only the first line of `audience_text`. Do not lose exclusions or scoped requirements kept on subsequent lines.
6. Data readiness, student eligibility, score eligibility, human approval and official award verification are distinct dimensions. Do not mark all of them true just because an activity passes the data policy.
7. Preserve stable post/activity identity across stores, bindings and features. Keep old temporary IDs only as traceable aliases if needed.
8. Do not keep two independent implementations that disagree. Use one backend policy and test any frontend mirror against it.

SP2 points must come from supported verified rules and bindings. Never use invented points, treat unknown points as a known zero, or count an activity toward a target merely because its schedule is available. Leave activities without a supported binding visible with the appropriate warning, but do not claim their unverified credit satisfies a point target. Preserve `DEMO_ONLY`/official-verification limits.

### C. Finish API/UI consumption

The real activity catalog and planning endpoints must read the same generated version. Expose usable activities, excluded records with clear reasons, and unknown-field warnings in the normal application.

Show unknown cost/domain as unknown. Do not require per-post approval. Missing source timing is an automatic exclusion, not a task for the user to fill in. Keep optional correction controls for genuine extraction errors; preserve older user progress/exports and source hashes.

Keep data readiness independent of dates being current: many source events are historical. Runtime must still apply actual semester, as-of and expiration rules. Test historical examples with an explicit labelled historical/demo clock; do not rewrite dates to make the planner nonempty or bypass expiry in production.

### D. Make future updates reproducible and automatic

Provide one documented command or existing admin entry point that can process additions/edits and rebuild all derived data without manual JSON/CSV annotation.

Required behavior:

- New post 190 receives stable identity, extraction, policy status, evidence, binding decision and catalog exposure/exclusion.
- Use the existing authorized model/backend or cached outputs; model execution belongs to an admin/background batch, not each student page request.
- Reuse unchanged outputs. Validate **input/prompt content hashes as well as model and prompt versions** before replaying cached roles. Inserting a date into an edited post must not reinterpret an old D1 role as a new date.
- Hash changes invalidate stale model replies and stale human decisions. Missing backend/output produces an explicit processing state and conservative exclusion, never fabricated results or false success. Do not invent credentials or silently use a paid external service.
- Handle duplicates without duplicating activity IDs or credit; retain source aliases.
- Rebuild coherently/idempotently. Stage and validate outputs before exposing a new dataset version; do not leave the API reading a mixture of old store, new bindings and stale features after a failed rebuild.
- Respect frozen split/access guards. Evolve the operational ingestion/index path rather than using the held-out manifest as a reason to require manual intervention for every new post.

## 7. Verification and acceptance criteria

Run checks appropriate to the final integrated tree, not only the small current-branch subset. Start with existing tests and add focused regression coverage for actual failure modes.

Previously used commands (PowerShell; adapt after integration):

```powershell
$env:PYTHONPATH = 'src'
python -m pytest -q tests/sp1 tests/test_ai_review_packet.py
node scripts/check_acceptance_parity.cjs artifacts/ai_review_20261118/deliverables/unilife_ai_drafts_129.json
python scripts/check_sp2_cases.py
python scripts/check_team_source_integrity.py
```

Then run the applicable SP2/SP3/integration/personalization/API suites and actual browser verification on the integrated implementation. A prior broad test run stopped making progress after >90%; it was interrupted and must not be reported as a complete pass. Diagnose any repeated stall with a bounded timeout and a useful trace.

Demonstrate at least these end-to-end behaviors:

1. Fixed event with a date but no clock time is retained with a reason and absent from scheduled output.
2. A valid quiz window can schedule a full sitting; a live webinar cannot be moved arbitrarily inside a broad date range.
3. Unknown fee/domain do not create a blanket review gate or become free/preference-matched. A hard budget is not certified when cost is unknown.
4. Missing signup URL does not by itself discard a valid walk-in/otherwise supported event. A missing deadline is not invented.
5. An unbound/unsupported scoring activity does not inflate target attainment.
6. Leading HTTT/publication banners are not titles; real official prefixes survive.
7. New post 190 is processed through the real update path; an edited existing post cannot reuse stale candidate-role mappings.
8. Repeating the rebuild is semantically idempotent; duplicates do not double-count; a failed rebuild does not publish mixed versions.
9. Original source text is preserved; evidence still supports the effective values. AI automation is never relabelled as human review, independent gold or official DRL recognition.
10. Every original post is accounted for, with stable IDs and explicit status. Counts are derived from output files, not hard-coded to the previous 94/34/1 snapshot.

Source locks: inspect the manifest and do not silently reset hashes to hide changes. If a necessary authorized schema/consumer update affects a locked file, document the intended change and handle its manifest/test implications transparently. Do not weaken checks merely to make them green.

## 8. Deliverables and completion report

Deliver a working implementation with:

- An integrated authoritative dataset and traceable excluded/unknown records.
- Consistent SP1/SP2/SP3/API/UI adapters for the accepted policy.
- A runnable update command for new and edited posts.
- The final business/data contract, schema-version/migration notes and a short runbook.
- Reproducible automated checks, observed counts and remaining technical limitations.

Your final report should state what the application actually reads now, how all 189 posts were accounted for, which activities can schedule versus contribute supported points, exact checks run and their results, and how to add post 190. Mention concrete technical blockers honestly if any remain. Do not ask the user to review the whole corpus or provide facts the organizer omitted. Do not present a standalone packet or a passing schema check as completion of runtime integration.

Do not prioritize fine-tuning, a new model survey, or another manual labelling workflow. Finish the operational data pipeline first.
