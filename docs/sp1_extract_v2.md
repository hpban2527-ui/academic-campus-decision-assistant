# SP1 rule-based layer A v2

The entry point is sp1.extract_v2.extract_v2(post). run_pipeline(post, config) also applies layer B.
Both accept one collector post and return a fresh result. Corpus callers use sp1.devdata to enforce
the frozen test boundary. The extractor reads 19 stated-fact fields and adds a separate activity type.

| Field | Rule | Method | Test |
| --- | --- | --- | --- |
| title | Ranked N1 candidates, banner exclusion and decoration trimming | segment | test_rules, test_title_banner_and_brackets |
| multi_session | Distinct session cues or multiple dated schedules | rule | test_first_round |
| window_open, window_close | First-session selection, date parser, stated precision | rule, segment, fallback_v1 | test_rules, test_first_round, test_year_inferred_and_reversed_window |
| registration_deadline | Registration closing cue, range end or deadline fallback | rule, fallback_v1 | test_rules |
| duration_minutes_stated | Duration cue with minute or hour quantity | rule | test_rules |
| mode | Mode label, first-session cues, venue/link cues, then v1 | segment, rule, fallback_v1 | test_rules, test_empty_defaults_and_conflict_flags |
| location | Nearest place field following first session, then inline venue | segment, fallback_v1 | test_rules |
| audience_text | N1 audience value or audience sentence | segment, rule | test_rules |
| audience_scope | Cohort and programme restrictions, excluding priority wording | rule | test_rules |
| mandatory_stated | Negative or positive cue, including non-attendance deduction | rule | test_rules |
| recognition_stated | Existing positive and negative phrase helpers | rule | test_rules |
| points_stated | Existing numeric conduct-point helper | fallback_v1 | test_rules |
| fee | Stated free or a unique amount with payer unit and deposit | rule | test_rules, test_empty_defaults_and_conflict_flags |
| registration_url, join_url | Separate link roles, reject read-more and source URL | rule, fallback_v1 | test_rules, test_join_and_registration |
| completion_requirements | Stated conditions, thresholds and local deadlines | rule | test_completion, test_completion_year_and_phone_evidence |
| domain | Existing domain keyword helper | fallback_v1 | test_rules |
| post_type | Participation and information cues, truncated-text handling | rule | test_rules |
| activity_type | Priority-ordered closed keyword taxonomy | rule | test_each_type, test_priority |

## Evaluation and reproduction

Use PYTHONPATH=src and run python -m sp1.evaluate_v2, then python scripts/run_sp1_v2.py.
The evaluator uses only the 16 retained dev_gold posts and completed rows of dev_extra gold.
The readiness script runs on 129 non-test posts through devdata.get_post.
Readiness is structural availability under the supplied criteria. Gold correctness is measured
separately on the development samples.

The v1 plannability comparison uses drl_recognized=true as an activity proxy, since v1 has no
post_type. This makes the comparison sensitive to the changed participation definition.
The reports disclose that proxy and use the same semester boundaries for both versions.

## Changes after dev analysis

One development round was used. No new keyword was fitted to an individual post.

| Field | Symptom and position | General change | Dev before / after |
| --- | --- | --- | --- |
| title | Prefix tag lost its opening bracket at 26 and 28, standalone media banner at 16 | Preserve balanced prefix tags, strip only a whole bracket wrapper, skip joined banner candidates | Gold v1 title 8/16 to 9/16, gold v2 title 3/5 to 4/5 |
| audience_text | Multi-line N1 value was reduced to one line | Preserve the full audience value as required by the field rule | Gold v2 audience_text 3/5 to 2/5 |

Gold v1 mapped-field total moved from 126/160 to 127/160. Gold v2 total stayed 77/95.
The cohort spelling fix was caught by the synthetic khóa 2024 case before this analysis.
The full audience-value change exposes N1 continuation boundaries that need separate review.

## Conflicts and interpretations

- Existing layer-A schema evidence accepts strings or arrays of strings. Phase 1 requires offset
  objects. Tests validate the 19-field record against $defs.record and check offset evidence
  independently. The full envelope awaits a schema change.
- The guide requires attendance choice for hybrid mode. A combined-mode phrase alone is flagged
  for review. An explicit hybrid designation or choice cue permits hybrid.
- The guide calls a mandatory post without a participation cue an activity. That case takes
  precedence over the insufficient fallback in section 3.14 of the task.
- The guide requires multiple stated fee amounts to be reviewed. This takes precedence over a
  free phrase elsewhere in the post.
- Registration wording takes precedence over generic participation wording for a form link.
  A meeting/LMS link still takes the join role.
- ADR-0002 D10 retains email, whereas the older labelling guide requests personal-email removal.
  N0 retains email as its contract specifies. Review the guide before further labelling.
- Original evidence offsets and literal original evidence are retained in memory. Export masks
  phones in evidence text while preserving offsets. A redacted export span may differ from the
  original slice. The readiness JSON includes every output field, with this export transformation.

## Limitations and proposed changes

- Update the layer-A envelope schema to accept offset evidence objects.
- Extend N0 phone masking for parenthesised area codes. Export already masks that format.
- Review N1 continuation boundaries, which can attach narrative to an audience or venue.
- Review the three Step 1 tests that load the entire corpus and the legacy source-file SP1 test
  before enabling them in a test-blind development run.
- Gold v2 marks mandatory=false for four posts where rules find no explicit optionality.
  The guide requires null for silence. Keep those mismatches visible for human adjudication.
- On five gold v2 posts, mode is correct for 2/5 and audience_text for 2/5. Domain and recognition
  are each correct for 3/5. These fields merit contextual reading in the later LLM comparison.
- On sixteen gold v1 posts, domain is correct for 8/16 and title for 9/16. Multi-round timing and
  title-prefix conventions differ across gold versions and need interpretation.
- Keywords can miss implicit participation, venue descriptions and eligibility embedded in prose.
- N0 injection screening adds flags. It is a deterministic cue screen and does not establish
  universal semantic invariance under arbitrary injected text.
- Threshold deadlines use the date in the local condition line. Repeated conditions are deduplicated.
- Development sample sizes are small. Total-field Wilson intervals treat field outcomes as trials,
  although errors within one post can be correlated.
