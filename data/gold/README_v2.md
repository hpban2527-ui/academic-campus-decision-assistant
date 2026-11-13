# SP1 evaluation data v2

The evaluation split was frozen on 2026-11-13 before changes to the SP1 extractor. `dev_gold` has
retained v1 labels and `dev_extra` is reserved for additional development labelling. `pool` holds
unlabelled posts available for error analysis. All source posts remain available to UniLife.

## Files and labellers

| File | Purpose |
| --- | --- |
| `source_gold.json` | Existing v1 labels. Sixteen of the twenty IDs are still in the source and are fixed as `dev_gold`. Recheck the retained dev labels against v2 before reusing them. |
| `split_v2.json` | Frozen manifest of all 189 source positions, post IDs, splits, stratum signals, group IDs, and overlap membership. |
| `test_gold_v2_template.json` | Labeller 1 independently labels all 60 test posts. |
| `overlap_gold_v2_template.json` | Labeller 2 independently labels the 20 selected posts from the same test set. |
| `dev_extra_gold_v2_template.json` | Labeller 1 labels 24 additional development posts, bringing the dev total to 40 once the retained v1 entries have been rechecked. |
| `adjudication_v2.md` | Both labellers record disagreements and resolutions after independent labelling. |

Follow [the v2 labelling guide](../../docs/labelling_guide_v2.md). Test posts are for the human
labellers and the final measurements. Keep them out of extractor development, debugging, examples,
and AI labelling. Measure the test set twice only, once before the extractor changes and once after.
Keep test gold fixed after seeing system output, except for a `GOLD` error logged in adjudication.

## How the split was made

- Positions 1–16 are fixed dev. A related group stays in the same split, and a group touching
  fixed dev is kept with it. Groups are connected components of the three collector series and
  all pairs at exact Jaccard similarity at least 0.60 over character 5-shingles of NFC-normalised,
  lowercased text with whitespace collapsed. The three collector series were the only groups
  with multiple members.
- Each post receives its first matching keyword stratum in this order: `mandatory`,
  `quiz_threshold`, `info_candidate`, `multi_date`, `online`, `other`. These are rough keyword
  signals for coverage. Human labellers decide the gold labels independently. Allocation uses
  the highest-priority member stratum for the whole group. The manifest records each post's own
  primary stratum, which is also used for overlap coverage.
- For test, rare allocation strata with at most 10 eligible posts receive a target of half their
  eligible posts rounded up. Other quotas use proportional largest remainders, with ties broken
  by stratum order. The sampler sorts groups by their member IDs and shuffles them using
  `random.Random(20261113)`. It selects whole groups to reach 60 posts while minimising deviation
  from quotas, prioritising rare strata when quotas cannot all be met. The five-member group in
  `mandatory` made that stratum's target of four unattainable. The split put five posts from that
  allocation stratum in test and reduced the `info_candidate` allocation from six to five.
- The overlap takes one post from each primary stratum present in test, then samples the remaining
  slots from all other test IDs with seed `20261114`. `dev_extra` uses the same group stratification
  on the remaining eligible groups with seed `20261115`. The other 89 posts are `pool`.

## Reproducing the split

Run `python scripts/make_split_v2.py` from the repository root. It checks both inputs before
producing output. The script writes the manifest and three blank templates when absent, and
preserves identical existing outputs. Use `--output-dir` with an existing empty directory to
reproduce the outputs after labelling has started.

| Hash | SHA-256 |
| --- | --- |
| `data/raw/source.json` | `c6bca5873981bd1c70a7b2f82e2a258fdfaec5471313df35cf2250c4b754dd0e` |
| `data/gold/source_gold.json` | `a5d88aee2ef2635fac1392e6c6593d218a9cc95a7fa0f510cd86ee906121644d` |
| Test IDs | `4974c1af6ee0105a32d08b8b96617c31f6325246db64439d1b76ab838ebd1ded` |

Both input hashes use file bytes with CRLF converted to LF. The test ID hash uses sorted IDs
joined by LF with no trailing newline, encoded as UTF-8.
