# Updating activity data (admin runbook)

Students never submit announcements. The admin (a developer on the team) adds new announcements in an
offline batch, and the change reaches the app through a reviewed pull request:

```
add posts -> export LLM inputs (new posts only) -> run the notebook on Kaggle -> admin_rebuild
          -> human review (decisions.csv) -> admin_rebuild again -> tests -> PR on a data/ branch
```

**The app never calls a model.** The server only reads the committed files in `data/` (the store, the
handover, the bindings, the features and the review queue). The only model run is the Kaggle notebook in
step 3, started by hand. `scripts/admin_rebuild.py` makes no network calls and no model calls; it replays
the recorded model replies from the `.jsonl` files. `scripts/ingest_post.py` and `src/sp1/live_ingest.py`
are developer tools only, and the API has no ingestion endpoint.

All commands run from the repository root. On PowerShell:

```powershell
$env:PYTHONPATH = "src"
git switch -c data/batch-20261201        # one branch per batch; use the batch date
```

(Git Bash: `export PYTHONPATH=src`.) In the examples, `20261201` stands for the batch date.

## 1. Add the posts

Append each new announcement to the end of `data/raw/source.json`, one JSON object per post:

```json
{
  "post_id": "pfbid0...",
  "url": "https://www.facebook.com/<page>/posts/pfbid0...",
  "share_url": "https://www.facebook.com/share/p/...",
  "publisher": "Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên",
  "platform": "Facebook",
  "date_posted": "2026-11-28T08:00:00",
  "raw_content": "<the announcement text, verbatim>"
}
```

- Required metadata: `url`, `publisher`, `platform`, `date_posted` (local time, `YYYY-MM-DDTHH:MM:SS`).
  `post_id` must be unique; for Facebook posts use the `pfbid...` id from the URL.
- Paste `raw_content` exactly as published. Do not edit it. Review decisions are tied to a fingerprint of
  this text, so any later edit makes them stale.
- Contact details: the store writer masks phone numbers and bank account numbers in every text field of the
  outputs (`[phone removed]`, `[account removed]`). E-mail addresses are kept. Like the existing 189 posts,
  `data/raw/source.json` keeps the original text.
- Never add real student data.

The corpus order is frozen by `data/gold/split_v2.json`: the post ids in `source.json` must appear in the
same order as in its `posts` list, otherwise every build stops with "Source post IDs or order differ from the
frozen split". For each new post, append an entry to `posts` in `data/gold/split_v2.json`:

```json
{"position": 190, "post_id": "pfbid0...", "split": "pool", "stratum": "other", "group": "G184", "in_overlap": false}
```

`position` and `group` continue the last entry. The proposed split is `pool` (posts never used to choose
the model or the merge policy). This still needs the team's agreement. Update `counts.pool` to match.
Nothing checks `source_sha256` in that file, and it will no longer match.

`data/raw/source.json` is in the team source lock (`docs/TEAM_SOURCE_LOCK_20261029.json`), so
`scripts/check_team_source_integrity.py` reports it as changed. Per the lock's own rule, the hash update goes
in the same PR and needs the lead's review. Do not edit the hash list on your own.

## 2. Export the LLM inputs for the new posts only

```powershell
python scripts/export_llm_inputs.py --split all --final-run-include-test --only-missing `
    --reason "batch 20261201: export new posts for the Kaggle run" `
    --out data/llm_inputs/batch_20261201.jsonl
```

`--only-missing` leaves out every post that already has a record in the existing outputs (by default
`data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl`; after several batches, pass each file with `--llm`). The
script prints the positions and ids it exported. If it prints "Nothing to export", every post already has
output. The reading of the corpus is logged in `data/gold/final_run_access_log.jsonl`; commit that file.
Do not commit `data/llm_inputs/` (it holds prompts built from the held-out test posts as well).

## 3. Run the notebook on Kaggle

1. Upload `data/llm_inputs/batch_20261201.jsonl` as a private Kaggle dataset.
2. Open `notebooks/sp1_llm_v2_kaggle.ipynb` and set, in the first cell:
   `MODELS = ["Qwen/Qwen3.5-4B"]` (the policy model, `_model_id` in `data/config/merge_policy.json`),
   `INPUT_FILE = "/kaggle/input/<dataset>/batch_20261201.jsonl"`, `DRY_RUN = False`.
3. Run it on a GPU (the final run used 2x T4). Do not change the prompts or token limits.
4. Download `/kaggle/working/llm_outputs/Qwen__Qwen3.5-4B.jsonl` and `run_info.json`.
5. **Rename** the output before copying it. The notebook names it after the model, the same name as the
   original run, so copying it unchanged would overwrite the original run:
   `data/llm_outputs/final/Qwen__Qwen3.5-4B_batch_20261201.jsonl`.
6. Append the new entry of `run_info.json` to the `runs` list of `data/llm_outputs/final/run_info.json`
   (do not replace the file).

## 4. Rebuild

```powershell
python scripts/admin_rebuild.py --reason "batch 20261201: rebuild with 6 new posts" `
    --llm data/llm_outputs/final/Qwen__Qwen3.5-4B.jsonl `
    --llm data/llm_outputs/final/Qwen__Qwen3.5-4B_batch_20261201.jsonl
```

Pass every output file with `--llm`, oldest first. The command runs `build_activity_store`,
`build_handover`, `build_bindings`, `build_features` and `export_review_queue`, in that order, and stops at the
first failing step with exit code 1 and a line such as `FAILED at step 1/5 (build_activity_store): ...`.
The steps before it have already written their outputs, so fix the cause and run the command again (or
restore with `git checkout -- data/ reports/`). Common failures:

| Message | Cause and fix |
| --- | --- |
| `N posts have no LLM output: position 190 (pfbid...)` | A post has no model reply. Export it (step 2), run the notebook and add the file with another `--llm`. `--allow-partial` exists for dry runs into another `--out-dir` only. |
| `Post ... has different LLM output in A and B` | The same post was run twice with different replies. Keep one file's record and delete the other. Different run timings alone are not a conflict. |
| `Unknown post at file:line` | The post is missing from `data/gold/split_v2.json` (step 1). |
| `Prompt version mismatch` / `Model ... is not the policy model` | The notebook ran with other prompts or another model. Rerun it as in step 3. |
| `Source post IDs or order differ from the frozen split` | `source.json` and `split_v2.json` disagree (step 1). |

### Reading the summary and the diff

The summary at the end is read from the files that were just written:

```
=== Summary (read from the output files) ===
  posts in store:            195
  posts without LLM output:  0
  plannable after review:    164
  handed over to SP3:        179
  blocked (not handed over): 16
  score bindings:            166 (INCREMENT 151, SET 15)
  review queue rows:         63
  review decisions:          63 applied, 0 stale, 0 rejected rows
```

(Example values.) `handed over + blocked = posts in store`. Then comes the diff against the handover that was
in the directory before the run:

```
=== Handover diff against the previous build ===
posts in store: 189 -> 195
added 5, removed 0, changed 1
  + position 190 pfbid0...
  ~ position 57 pfbid0...: end, title
```

- `+` an activity is new in `data/handover/activities_sp3.json`, usually a new post.
- `-` an activity is no longer handed over: the post became blocked or a duplicate, or was removed.
- `~` a handed-over record changed; the changed fields are listed. In a batch that only adds posts, a
  change to an old post is unexpected: find out why (for example a new duplicate group or a review decision)
  before you commit.

## 5. Review

Open `data/review/queue.csv` in Excel (UTF-8). Each row is a record that is not fully usable, with
`reasons`, `how_to_fix` and the current values. To record a decision, copy the row's `post_id` and
`text_sha256` into a new row of `data/review/decisions.csv` (keep its header, one row per post) and fill in:

- `reviewer` (your name as it should appear; if the review was AI-assisted, say so, as in the existing rows),
  `reviewed_at` (`YYYY-MM-DD`);
- any of `set_post_type` (`activity`, `info_only`, `insufficient`), `set_title`, `set_mode` (`online`,
  `offline`, `hybrid`), `set_location`, `set_window_open`, `set_window_close`, `set_registration_deadline`
  (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM`), `set_activity_type`, `set_rule_id` (a verified rule in
  `data/drl_rules.json`);
- `approve` = `yes` when the record is correct as it is; `note` with your evidence.

Check every new post against its announcement, not only the queued ones.

## 6. Rebuild again

Run the step 4 command again. In the summary, `rejected rows` must be 0. Rejected rows and their reasons
are listed under `decision_problems` in `data/activity_store_v2.json`. A `stale` decision means the post
text changed after the review; review that post again. A reviewed record leaves the queue once none of
its reasons remain; otherwise it stays, with `already_reviewed_by` filled in.

## 7. Run the tests

```powershell
python -m pytest -q tests/sp1 tests/sp2 tests/sp3 tests/integration
python -m pytest -q tests/test_e2e_pipeline.py tests/test_session_flow.py tests/personalization
python scripts/check_sp2_cases.py
python scripts/check_team_source_integrity.py
```

Expected after adding posts: `tests/integration/test_sp3_flow.py` pins the size of `data/raw/source.json`
(189 posts, 173 unstructured) through `GET /api/sp3/catalog`, and `check_team_source_integrity.py` reports
`data/raw/source.json` as changed. Both are lead-owned; update them in the same PR with the lead's agreement.
Any other failure blocks the PR. Restart the server (`python run_server.py`) to load the new files, then
check "Kho bài thật" in the web page.

## 8. Commit and open a PR

```powershell
git add data/raw/source.json data/gold/split_v2.json data/gold/final_run_access_log.jsonl `
    data/llm_outputs/final/ data/activity_store_v2.json data/handover/ data/review/ `
    reports/sp1_final_readiness.md reports/sp1_handover_readiness.md reports/sp2_binding_readiness.md
git commit -m "data: batch 20261201, 6 new announcements"
git push -u origin data/batch-20261201
```

Open the PR against `main`. Paste the summary and the diff from step 6 into the description, list the
reviewer of the decisions, and name the posts that stay blocked or unbound.

## What blocks a post

A post can stop at four points. Each one is visible in a file:

1. **Not handed over to SP3** (`data/handover/blocked.json`): `duplicate` (another record of the same
   activity is canonical), `not_an_activity`, `failed_status`, `missing_title`, `missing_mode`,
   `invalid_source_url`, `fee_not_per_person`, or `contract:...` (the 14-field SP3 activity contract
   refused it). Fix `missing_mode`, `failed_status` and `not_an_activity` with a review decision.
2. **Not plannable** (`plannable: false` and `not_plannable_reasons` in the store): no opening date, no
   mode, not an activity, a failed status, or an opening date outside a configured semester
   (`data/config/semesters.json`).
3. **No score binding** (`data/handover/bindings.json`, `explanations`): the SP1 activity type and the SP2
   rule matcher did not name the same rule. The catalog shows the activity as `REVIEW_REQUIRED`; fix it with
   `set_rule_id` in a decision.
4. **Not selectable by the planner**: the demo planner (`src/api/sp3_real.py`) only plans the rest of term
   HK1 2026-2027 from 2026-10-01. A handed-over activity outside that window, or one that the rule-based
   evidence marks out of term or ineligible, is excluded as infeasible.
