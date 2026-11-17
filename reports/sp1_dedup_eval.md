# SP1 duplicate grouping evaluation (synthetic reposts)

Rules-only extraction on non-test posts. Seed 20261114. Intervals are Wilson 95%.
Synthetic positives use 20 sampled posts with a stated opening time; each gets 4 reposts.

| Repost kind | Grouped with original |
| --- | --- |
| exact | 20/20 [84%, 100%] |
| shared | 20/20 [84%, 100%] |
| edited | 20/20 [84%, 100%] |
| summary | 20/20 [84%, 100%] |

Real non-test corpus: 129 posts, 8256 pairs. Merges: 0 (expected 0: the corpus was compiled with one post per activity; not independently labelled). Possible-duplicate flags: 1.

Limitation: reposts are generated from the original text, so they share wording. A repost rewritten
in other words with a different title is not grouped; at most it is flagged when titles overlap.

