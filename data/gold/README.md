# Gold labels for SP1

## `source_gold.json`

- Posts: the 20 posts in `data/raw/source.json` (collector file, branch `Minh_Tri`, added in commit 6ad5170).
- Labeller: Minh Tri, `Activities/activities_draft.json`, added in commit eecfe1e (unchanged up to 2086cb6). To confirm with
  Minh Tri: the labels were made without seeing the extractor output.
- Conversion (format only, no value changed): `activity_id` -> `post_id`; `source` reduced to
  `URL_registration`; the `_review` notes dropped. `drl_recognized` is left out because it is not
  labelled yet, so the evaluator does not score it.
- The draft file is used instead of `Activities/activities.json` because the latter fills
  `mandatory = false` and `fee = 0` as defaults where the post says nothing; the draft keeps null,
  which is the agreed meaning (not stated).
- One labeller, no overlap subset yet, so no inter-labeller agreement.
- These 20 posts were read during error analysis (2026-10-26), so they are the development set. A test
  set for the before/after comparison must be labelled and frozen before any fix is written.

Rebuild:

```python
import json
draft = json.load(open("activities_draft.json", encoding="utf-8"))
gold = [{"post_id": a["activity_id"],
         "activities": [{"source": {"URL_registration": a["source"].get("URL_registration")},
                         **{k: v for k, v in a.items() if k not in ("activity_id", "source", "_review")}}]}
        for a in draft]
json.dump(gold, open("source_gold.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
```

Do not edit gold values after seeing extractor output. A disputed label is raised with the labeller
and recorded in `reports/sp1_test_report.md` (categories CONV and GOLD).
