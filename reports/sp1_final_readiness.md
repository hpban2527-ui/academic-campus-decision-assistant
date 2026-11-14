# SP1 final readiness (all posts)

Model: Qwen/Qwen3.5-4B. Posts: 189. Posts without LLM output: 0.
Structural readiness, not gold accuracy: a post is plannable when it is an activity with an opening
date in a configured semester, a known mode and a non-failed status. Intervals are Wilson 95%.
Dev posts were used to choose the model and merge policy; pool and test posts were not.

| Group | Rules plannable | Hybrid plannable |
| --- | --- | --- |
| dev | 22/40 = 55.0% [39.8%, 69.3%] | 22/40 = 55.0% [39.8%, 69.3%] |
| pool | 74/89 = 83.1% [74.0%, 89.5%] | 73/89 = 82.0% [72.8%, 88.6%] |
| test | 40/60 = 66.7% [54.1%, 77.3%] | 39/60 = 65.0% [52.4%, 75.8%] |
| all | 136/189 = 72.0% [65.2%, 77.9%] | 134/189 = 70.9% [64.1%, 76.9%] |

| Rules -> Hybrid | Posts |
| --- | ---: |
| not -> not | 53 |
| plannable -> not | 2 |
| plannable -> plannable | 134 |

| Method | Not-plannable reason | Posts |
| --- | --- | ---: |
| rules | failed_status | 8 |
| rules | mode | 28 |
| rules | post_type | 14 |
| rules | semester | 23 |
| rules | window_open | 13 |
| hybrid | failed_status | 9 |
| hybrid | mode | 28 |
| hybrid | post_type | 14 |
| hybrid | semester | 26 |
| hybrid | window_open | 17 |

## Duplicates

Merged groups: 0. Canonical records: 189/189. Possible-duplicate pairs flagged for review: 1.
Consumers (SP2/SP3) must use records with duplicate_of = null.

| Hybrid value | Posts |
| --- | ---: |
| mode:None | 28 |
| mode:offline | 149 |
| mode:online | 12 |
| post_type:activity | 175 |
| post_type:info_only | 1 |
| post_type:insufficient | 13 |
| status:failed | 9 |
| status:partial | 52 |
| status:valid | 128 |
