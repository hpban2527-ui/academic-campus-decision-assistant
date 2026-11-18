# Operational activity data pipeline (contract, migration notes, runbook)

Status: implemented on branch `feat/operational-data-pipeline-20261118` (2026-11-18). Business rules:
`docs/ACTIVITY_DATA_ACCEPTANCE_V1.md` (agreed with the user on 2026-11-18).
Decision record: `docs/adr/0003-operational-activity-dataset.md`.

## 1. What the application reads

The real-data path of the web app (`?source=real` on `/api/sp3/catalog`, `/api/sp3/demo/plan`,
`/api/sp3/personalized/plan`) reads exactly one file:

```text
data/operational/activity_dataset.json      schema unilife-operational-dataset/1.0
```

`src/api/sp3_real.py` loads it as a whole, caches it by modification time and size, and reloads it when a
build replaces it. Catalog and planning use the same loaded object, and every response carries
`dataset.dataset_version`. The synthetic MVP fixture stays the default source and is unchanged.

`data/handover/*` and `data/activity_store_v2.json` are the legacy SP1 v2 outputs (Qwen-only, the 14-field
v0.2 handover). They are still rebuilt by `scripts/admin_rebuild.py` and tested, but **the application no
longer reads them**.

## 2. Inputs (authoritative, versioned in `data/`)

| Input | Path | Role |
| --- | --- | --- |
| Frozen corpus (189 posts) | `data/raw/source.json` + `data/gold/split_v2.json` | evaluation corpus; never edited for operations; read through the logged final-run reader |
| Operational updates | `data/raw/operational_updates.json` (optional) | new posts (190, 191, ...) and edited texts of existing posts |
| AI-assisted annotations | `data/sp1_annotations/ai_annotations_20261118.json` | 129 non-test posts, 19 stated-fact fields + activity type, evidence spans, uncertainty; label `AI_EXTRACTED_POLICY_CHECKED_NOT_GOLD`; provenance in `data/sp1_annotations/provenance/` |
| Human decisions | `data/review/decisions.csv` | genuine corrections (63 applied), bound to the text fingerprint |
| Recorded model replies | `data/llm_outputs/final/*.jsonl`, `data/llm_outputs/operational/*.jsonl` | Qwen/Qwen3.5-4B replies, replayed only when the prompt digest matches |
| Acceptance policy | `data/config/activity_acceptance_v1.json` + `src/sp1/acceptance.py` | data readiness and schedule (`activity-acceptance/1.1`) |
| Rules | `data/drl_rules.json` | SP2 rule catalog (points come only from here) |

`artifacts/` is a delivery folder and is not read by any build. `scripts/import_ai_annotations.py` copied the
annotation packet from `artifacts/ai_review_20261118/` into `data/sp1_annotations/` once.

## 3. Per-post processing (src/sp1/operational.py)

1. **Extraction source** (first match, each bound to the current text fingerprint):
   AI annotation (non-test only) → recorded model reply whose `input_sha256`
   (SHA-256 of both rendered prompts), model ID and prompt versions match → otherwise
   `EXTRACTION_PENDING` (`model_output_missing` or `model_output_stale`). Test posts use only frozen model
   outputs. A changed text or a changed candidate builder can never replay an old D1/T1 role mapping.
2. **Grounding:** every non-null AI value must have an evidence span found at its offsets in the
   preprocessed text; otherwise the field becomes uncertain (`evidence_not_grounded:<field>`).
3. **Human decisions** are applied last; a decision on another text version is stale and ignored.
4. **Acceptance policy** decides `READY`, `READY_WITH_WARNINGS`, `NOT_SCHEDULABLE` or `NOT_AN_ACTIVITY`, the
   reasons, the warnings and the schedule. Injection-suspected posts are blocked.
5. **Audience** (`src/sp1/audience.py`): all lines are kept; the basis is `NOT_STATED`, `OPEN_TO_STUDENTS`,
   `RESTRICTED_TO_FIT`, `STRUCTURED_SCOPE`, `RESTRICTED_FREE_TEXT` or `UNCLEAR`.
6. **Duplicates:** same stated opening and near-identical text or title. The canonical record keeps the
   members as `aliases`; members become `DUPLICATE` and carry no SP3 activity, binding or features.
7. **SP2 binding** and **personalization features** for data-ready canonical activities only.
8. **SP3 activity** (contract `sp3-activity/0.3`, below) and schedule evidence for data-ready activities.

### Status and dimensions

| Status | Meaning | In the planner |
| --- | --- | --- |
| READY / READY_WITH_WARNINGS | source supports a schedule; warnings list non-blocking unknowns | candidate |
| NOT_SCHEDULABLE | essential fact missing, uncertain or contradictory (reasons listed) | no |
| NOT_AN_ACTIVITY | information only | no |
| DUPLICATE | another post is the canonical record (`duplicate_of`) | no |
| EXTRACTION_PENDING | no valid extraction for the current text yet | no |

Separate dimensions on every record: `data_ready_for_scheduling`, `score_binding_supported`,
`student_eligibility_basis`, `human_reviewed`, `official_award_verified` (always false).

## 4. Business rules as implemented

* Missing organizer facts stay `null`/`[]`. Unknown fee is `null` (never 0); unknown domain is `null`;
  no registration deadline is invented (the old "deadline = start" convention is not used).
* Fixed offline events, live online sessions and hybrid events need a stated date **and** start time. A
  date-only start is excluded with `missing_fixed_start_time`.
* Missing end with a real start: team default 120 min offline, 30 min online/hybrid, labelled
  `team_default` in the schedule and in `sp3_derived`; a stated duration wins.
* Online quizzes with a stated window are `FLEXIBLE_WINDOW`; date-only bounds become 00:00/23:59 window
  bounds, duration stated or the 30-minute quiz default. A webinar/Zoom/Meet/Teams session is never a
  flexible quiz. The quiz/live regexes were audited on all 15 online records of the corpus: no live
  session is routed as flexible; posts that only mention a fanpage remain quizzes. No change was needed.
* First session only; multi-session sources keep `multiple_sessions` as a warning.
* A mandatory activity that cannot be scheduled keeps `mandatory_unscheduled` and stays visible.
* Unbound activities stay visible (`score_binding_unsupported`) but are `MISSING_SCORE_BINDING` in SP3 and
  never count toward the target.
* A free-text audience restriction (another faculty, a class, a team, ...) is `NEEDS_REVIEW` eligibility
  in SP3 (`MISSING_ELIGIBILITY`): not planned automatically, not a task for the student.
* A hard budget (`max_fee`) excludes an activity whose cost is unknown (`fee:unknown`).

## 5. Contract and schema migration notes

| Item | Before | Now | Owner to inform |
| --- | --- | --- | --- |
| SP3 activity `fee` | number required (`sp3-activity/0.2`) | number or `null` = unknown (`sp3-activity/0.3`), `src/sp3/feasibility.py` | SP3 (Minh Trí, Bình An) |
| Unstated deadline | `MISSING_DEADLINE` → NEEDS_REVIEW | new optional evidence `deadline_unstated_by_activity`; when true, no gate. Without it, v0.2 behaviour is unchanged | SP3 |
| Planner input check | FEASIBLE + NOT_REGISTERED required a deadline | a stated deadline must still be open; an unstated one is accepted (feasibility decides) — `src/sp3/planner.py` | SP3 |
| Personalization budget | unknown fee passed a hard budget | `fee:unknown` hard exclusion — `src/personalization/scoring.py` | Như Ngọc |
| Recorded replies | replayed by post ID | replayed only on matching `input_sha256` (legacy store too: `llm_output_stale`) | SP1 |
| `export_llm_inputs.py --only-missing` | skipped any post with a record | skips only posts with a record for the current prompts | SP1 |
| Runtime real data | `data/handover/*` | `data/operational/activity_dataset.json` | Bình An, Minh Tiến (UI) |
| Web UI (real source) | showed "Chưa rõ điểm", "Chờ rà soát" | shows rule-based points as estimates, unknown cost/domain as unknown, data warnings, automatic exclusions with reasons | Minh Tiến |

Test changes: `tests/sp3/test_planner.py` (the null-deadline case is now accepted; a passed stated deadline
is still rejected), `tests/sp1/test_incremental_llm.py` (stale replies), data-source names in the real-source
tests. The 5 posts whose recorded replies no longer match their prompts (positions 41, 45, 66, 135, 164;
the date parser changed after the Kaggle run) are no longer replayed: 41/45/66/164 use their AI annotation,
test post 135 is `EXTRACTION_PENDING` until it is re-run.

Source lock: `scripts/check_team_source_integrity.py` reports 53/53 unchanged; `data/raw/source.json` is
never edited (updates go to `data/raw/operational_updates.json`).

## 6. Runbook: new or edited announcements (post 190 and later)

1. Add the announcement to `data/raw/operational_updates.json` (create the file if needed):

   ```json
   {"schema": "unilife-operational-posts/1.0",
    "posts": [{"post_id": "pfbid0...", "url": "https://www.facebook.com/<page>/posts/pfbid0...",
               "share_url": null, "publisher": "Phòng Công tác Sinh viên - Trường ĐH KHTN",
               "platform": "Facebook", "date_posted": "2026-11-28T08:00:00",
               "raw_content": "<announcement text, verbatim>"}]}
   ```

   A new `post_id` gets the next position (190, ...). To record an organizer's edit of an existing post,
   add an entry with the **same** `post_id` and the new text.

2. Run the one update command (PowerShell, repository root, project venv):

   ```powershell
   $env:PYTHONPATH = "src"
   .venv\Scripts\python.exe scripts/update_activity_data.py --reason "batch 2026-11-28: post 190"
   ```

   With a served Qwen backend (`SP1_LLM_BASE_URL`, optional `SP1_LLM_MODEL`/`SP1_LLM_API_KEY`), add
   `--call-model`: the replies are recorded in `data/llm_outputs/operational/` with their input digest.
   Without a backend, the post is published as `EXTRACTION_PENDING` and its prompts are written to
   `data/llm_inputs/pending_operational.jsonl`. Run `notebooks/sp1_llm_v2_kaggle.ipynb` on that file, copy
   the output `.jsonl` to `data/llm_outputs/operational/`, and run the command again.

3. Read `reports/operational_dataset_report.md` (counts and the change against the previous version).
   Restart the server (or just reload: the API notices the new file).
4. Checks: `python -m pytest -q tests` and, for the browser path, `python scripts/verify_operational_browser.py`.
5. Commit `data/raw/operational_updates.json`, `data/llm_outputs/operational/`, `data/operational/`,
   `reports/operational_dataset_report.md` on a `data/` branch and open a PR.

Optional correction of a genuine extraction error: add a row to `data/review/decisions.csv` (the only
correction mechanism) and run the update command. It is not required to publish a dataset.

The build is deterministic: rebuilding the same inputs gives the same `dataset_version`. A failed build or
validation leaves the previous `activity_dataset.json` in place (staged write + validation + atomic replace).

## 7. Limitations

* Counts are data readiness, not extraction accuracy. No held-out accuracy is claimed; the 60 test posts
  were processed operationally from frozen model outputs under the access log, not evaluated.
* The AI annotations and the cross-check are AI work, not human review or gold.
* Audience classification is rule-based and conservative: some open activities with a mixed audience
  sentence are kept out of automatic plans (`MISSING_ELIGIBILITY`).
* Duplicate detection needs a stated opening time; reposts without a time are not merged.
* `MISSING_SCORE_BINDING` activities (unsupported rule operators such as `less_than`, unbound types) are
  visible but never planned for points; the R31402/R31404 SET conflict remains on the rules side.
* The planner clock is the labelled historical demo clock 2026-10-01; announcements are not re-dated.
* The legacy `/api/evaluate` single-post demo (`src/api/lead_contract.py`) still uses its own
  group-default `fee = 0`; it is not part of the operational dataset.
