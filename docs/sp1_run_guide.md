# SP1 extractor: run and integrate

Short guide for integration. Details: `docs/sp1_extractor.md`. Test results: `reports/sp1_test_report.md`.

## 1. Setup

From the repository root (tested with Python 3.13):

```bash
pip install -r requirements.txt          # jsonschema, pytest
python -m pytest -q tests/sp1            # expect: 208 passed
```

## 2. Batch: collector posts file -> drafts

Input is the collector's file as it is (`data/raw/source.json`): a JSON array of posts with
`post_id, url, raw_content, publisher, platform`, and optionally `date_posted` and `share_url`.

```bash
PYTHONPATH=src python -m sp1.extractor --input data/raw/source.json --output reports/sp1_output.json
```

PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m sp1.extractor --input data/raw/source.json --output reports/sp1_output.json
```

The command prints `20 posts extracted (20 drafts), 0 input errors`. A malformed post does not stop
the batch; it becomes `{"post_id", "index", "error"}` in the output.

## 3. In code

```python
import sys; sys.path.insert(0, "src")      # or set PYTHONPATH=src
from sp1.extractor import extract, extract_post, run_posts, InputError

# Batch (list of posts) -> [{post_id, drafts} | {post_id, index, error}]
results = run_posts(posts)

# One post from the collector file -> {post_id, drafts}; raises InputError if malformed
result = extract_post(post)

# Live text box in the web app -> list of drafts; raises InputError on bad input
drafts = extract(text, {"publisher": "...", "platform": "facebook", "URL_post": "https://..."},
                 posted_date="2026-10-26")   # optional; fills a year the text leaves out
```

## 4. Output

Each draft is `{record, meta}`. `record` is the 15-field activity record (the 14 agreed fields plus
`drl_recognized`). `meta` explains it and is never shown as data to SP2:

| `meta` key | use |
|---|---|
| `status` | `valid` / `partial` / `failed`: routing, below |
| `flags` | e.g. `needs_review:mode`, `invalid_value:start`: what a reviewer must check |
| `evidence` | the text span each value came from: show it as the source of a value |
| `time_defaults` | `start: date_only_0000`, `end`/`registration_deadline: date_only_2359` when the post gives a date without a time |
| `derived` | values set by a rule, e.g. `mode: venue_physical` |

Example with one draft of each status: `reports/sp1_sample.json`.

## 5. Routing

```python
valid, review = [], []
for r in results:
    for d in r.get("drafts", []):
        (valid if d["meta"]["status"] == "valid" else review).append({"post_id": r["post_id"], **d})
activities = [d["record"] for d in valid]      # -> dedup (assigns ACT###) -> activities.json
```

- `valid`: no check failed. **For now a person should check these too**: on the 20 test posts one
  `valid` draft had wrong dates (`reports/sp1_test_report.md`, section 6).
- `partial` / `failed`: review queue. Show `flags` and `evidence`.
- `activity_id` is temporary (`TMP-<hash of url>-01`); dedup assigns the final ID.
- `null` means "the post does not say". SP2 and the UI must not read a null `fee` as free or a null
  `mandatory` as not mandatory.

## 6. Limits to know before integrating

- Regex path only: one activity per post; weak on deadlines, offline venues and titles
  (`reports/sp1_test_report.md`, sections 5 and 7).
- `drl_recognized` is not yet checked against labels.
- The LLM path (`method="llm"`) has not been run.
