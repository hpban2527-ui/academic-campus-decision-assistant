# SP1 v2 handover contract check

Audit date: 2026-11-14. Scope: read-only analysis of SP1 v2 output against the available origin/Nhu_Ngoc snapshot. No adapter was implemented.

## 1. Verification boundary and result

**Remote freshness is UNVERIFIED.** The requested command, git fetch origin, failed with:

~~~
error: cannot open '.git/FETCH_HEAD': Permission denied
~~~

All remote-code citations below refer to the locally available remote-tracking snapshot:

- Branch reference: origin/Nhu_Ngoc.
- Commit: 1f3618ad619b4ab84b61c55e8021d4d05b12a80b.
- Commit date: 2026-11-07 10:11:51 +0700.
- Subject: fix(sp2): default-awarded DRL items, rule matcher and user score estimation.
- The local ADR-0002 D13, lines 114-128, describes a later review through a327853 on 2026-11-14. That later implementation is **UNVERIFIED** here.
- src/personalization/, TopicId, CampusId and activity_features references are absent from the inspected snapshot. Their current implementation, enums, loader and missing-value behavior are **UNVERIFIED**. Absence in this cached commit is not evidence of absence on the remote server today.

Local inputs read for this audit:

- data/activity_store_v2.json, schema sp1-activity-store/2.0, 189 records.
- Store SHA-256: af10ce9ac9fb1b6a346a47e2bb8633ee84d72b21a01166824778baa00c985d73.
- schemas/activity_v2.schema.json, SHA-256: 86ae58b5721d68f807304ab8d4934b0e0c9e27c460898c98482c4d8cd6ef4281.
- data/config/semesters.json and the local ADR paragraph cited above.
- No data/raw/source.json or file under data/gold/ was opened, including on remote branches. A tree listing can contain their names; their contents were not read.
- No server module was imported or started. The counting script executed only the inspected, standard-library-only feasibility definitions in memory. It created no source, data, cache or test files.

**Result:** 189/189 activities validate against SP1 v2. None can be passed unchanged to the inspected legacy 14-field activity contract. Under the explicit conservative projection in section 6, 13/189 pass the legacy activity structure checks; only two survive the additional single-session and directly resolvable fixed-schedule checks. Neither has a registration deadline. No record is demonstrated to be fully selectable by SP3 from this store alone: trusted bindings, student participation, eligibility/source review and request context are absent.

These are compatibility counts, not extraction-accuracy scores or a claim that the remaining activities can never be planned.

## 2. Actual data paths in the inspected branch

| Consumer file:line | What it loads or calls | Verified implication |
| --- | --- | --- |
| src/api/server.py:78-82 | data/drl_rules.json, data/student_profile.json, data/activities.json, data/source_posts.json and schemas/activity.schema.json | The server does not load activity_store_v2.json. The old activity schema is enforced in the reviewed scoring path. |
| src/api/server.py:117-125 | Indexes source_posts text for deduplication | Uses post_id/id and raw_content/content/text, not SP1 v2 duplicate_of. Source text contents were not inspected. |
| src/api/sp3_service.py:28-68 | data/activities.json, DataQA/QA20.json and DataQA/source.json | Existing catalog entries are marked REVIEW_REQUIRED and score_binding_verified=False. Extra source posts are re-extracted using the legacy extractor/publication path. |
| src/api/sp3_service.py:21,72-75,159-160 | tests/sp3/fixtures/main_flow_integration.json, with data/drl_rules.json inserted as the ruleset | Planning demo data come from a fixture. Replacing the catalog alone does not feed v2 records into the planner. |
| src/api/sp3_service.py:86-100,121-140 | Availability -> feasibility -> planner -> independent plan checker | The adapter must produce the feasibility request and external trusted evidence, not just a list of activity objects. |
| src/api/server.py:1580-1592 | GET /api/sp3/catalog; POST /api/sp3/demo/plan | The inspected planning endpoint is a synthetic scenario preview, not a general v2-store planning endpoint. |
| src/sp3/projected_scorer.py:127-153 | InMemoryScoringData with activities, bindings, baselines, ruleset and versions | Production store resolution is not supplied by the SP1 file. |
| src/personalization/* | Absent in cached origin/Nhu_Ngoc | Latest models and activity_features.json loader: UNVERIFIED. |

Structural-only sample inspection found:

- data/activities.json is an array of 20 legacy 14-field records. Its nested source has publisher, platform, URL_post and URL_registration. All points are null. Some mode and completion_requirements values are null; a displayed catalog row is therefore not necessarily accepted by strict feasibility.
- DataQA/QA20.json has 20 entries with activity_id, category, notes, review, semester, source_details, source_mismatch and status.
- main_flow_integration.json supplies scoring_data.activities/bindings/baselines and evidence.eligibility_by_activity/schedule_by_activity/source_review_by_activity/term_scope_by_activity/term_verified.
- data/drl_rules.json has 75 rules. Only object keys, value types and counts were inspected; rule descriptions and individual regulation values were not reproduced.

## 3. Activity field mapping

All remote paths and line numbers in this report are anchored to the commit above. "Required key; nullable" means the key must be present even when its value is null.

Statuses: OK = same field name and compatible non-null format; RENAME = move/rename with unchanged value; CONVERT = representation or semantic handling needed; MISSING_IN_SP1 = external data not supplied by the store; UNUSED_BY_CONSUMERS = no read in the inspected consumer snapshot. An OK row may still contain missing values that prevent acceptance.

The feasibility input activity must have **exactly** 14 keys; source must have **exactly** four. Missing and additional keys both raise FeasibilityContractError (src/sp3/feasibility.py:188-194,234-249). The planner also requires the exact 14-key shape (src/sp3/planner.py:488-489), but relies on upstream feasibility for several nested/value checks. A shape match alone is insufficient.

### 3.1 All legacy activity fields and nested source fields

| Consumer file:line | Field | Expected / missing behavior | SP1 v2 source | Status | Conversion / notes |
| --- | --- | --- | --- | --- | --- |
| src/sp3/feasibility.py:44-60,245-249; src/sp3/planner.py:488-489; src/sp3/projected_scorer.py:174-176 | activity object | Required exact 14-key object. Missing/extra keys rejected. | record.activity, 24 keys | CONVERT | Build a new legacy projection. Keep v2-only fields in a separate sidecar; do not pass them through inside the legacy object. |
| src/sp3/feasibility.py:248,360-362; src/sp3/planner.py:490; src/sp3/projected_scorer.py:174-176,407-409; src/sp2/drl_engine.py:665-671 | activity_id | Required non-empty string; duplicate request IDs rejected. Missing trusted scorer record -> MISSING_ACTIVITY. | activity.activity_id | OK | TMP-... is accepted by these readers. If prepare_publication is used, TMP IDs are rewritten to ACT- plus 12 uppercase SHA-256 hex characters of canonical URL (src/api/lead_contract.py:65-68). Pick one identity policy and remap bindings, dedup references, previous plans and ledger consistently. |
| src/sp3/feasibility.py:234-242; src/api/lead_contract.py:112-113 | source | Required exact object with publisher, platform, URL_post, URL_registration. | activity.source plus activity.registration_url | CONVERT | Remove post_id/date_posted from the legacy source object and preserve them in the sidecar. Add URL_registration from the top-level registration_url. |
| src/sp3/feasibility.py:237 | source.publisher | Required non-empty string; missing/blank rejected. | activity.source.publisher | OK | Copy unchanged. |
| src/sp3/feasibility.py:238 | source.platform | Required non-empty string; no closed platform enum in this reader. | activity.source.platform | OK | Copy unchanged. |
| src/sp3/feasibility.py:225-239; src/api/reviewed_pipeline.py:70-71 | source.URL_post | Required absolute HTTP(S) URL with host. Approval source_url must match it. | activity.source.URL_post | OK | Preserve the source identity. Publication optionally canonicalizes tracking parameters (src/api/lead_contract.py:23-34); approval/fingerprint must refer to the final projected record. |
| src/sp3/feasibility.py:240-242; src/api/lead_contract.py:127-132 | source.URL_registration | Required key; null or absolute HTTP(S) URL. Invalid non-null URL rejected/reviewed. | activity.registration_url | RENAME | Move into source.URL_registration. Do not substitute join_url or source.URL_post. Eight store records fail this legacy URL contract under the projection. Protocol/URI repairs need an explicit policy, not an invented destination. |
| src/sp3/feasibility.py:250; src/sp3/planner.py:491,1019-1020; src/sp3/plan_checker.py:357; src/sp2/rule_matcher.py:108 | title | Required non-empty string for SP3. Matcher alone tolerates missing/false-like values as empty text. | activity.title | OK | Copy non-null titles. V2 permits null; null must remain a blocker rather than a generated label. Used for display and rule-match text. |
| src/sp3/feasibility.py:251-252; src/sp3/planner.py:492-493,665-670; src/sp3/plan_checker.py:655; src/sp2/rule_matcher.py:109 | domain | Required key; null or academic, volunteer, culture_sports, skills, career, other. Missing key rejected. | activity.domain | OK | Same six-value enum. Planner uses it for soft preference matching; no translation into scoring criterion or TopicId is implemented here. |
| src/sp3/feasibility.py:253,526-544; src/sp3/planner.py:495-498; src/sp2/rule_matcher.py:65-71 | start | Required key; null or offset-aware ISO datetime. Missing usable bound -> MISSING_SCHEDULE unless authoritative fixed-block evidence provides the schedule. | activity.window.open | RENAME | Copy the timestamp including +07:00. Retain time_defaults/year_inferred separately. A normalization-generated midnight is not evidence of a real midnight session. |
| src/sp3/feasibility.py:254,526-544; src/sp3/planner.py:495-498; src/sp2/rule_matcher.py:65-71 | end | Required key; null or offset-aware ISO datetime. Reversed/equal bounds -> UNSUPPORTED_SCHEDULE in schedule resolution. | activity.window.close | RENAME | Copy actual window close. Do not automatically convert a multi-day participation window into a fixed attendance block. Synthesizing end from duration is a separate, disclosed scenario in section 6. |
| src/sp3/feasibility.py:255-259,617-621; src/sp3/planner.py:522-524 | registration_deadline | Required key; nullable. NOT_REGISTERED with null -> MISSING_DEADLINE; as_of >= deadline -> DEADLINE_PASSED. REGISTERED skips this check. | activity.registration_deadline | OK | Preserve +07:00. Do not substitute event close. Date-only deadline defaults remain traced in meta.time_defaults. 138/189 deadlines are null. |
| src/sp3/feasibility.py:260-265; src/sp3/planner.py:494,665-670; src/sp3/plan_checker.py:655; src/sp2/rule_matcher.py:110; src/api/server.py:976-979 | mode | Required online/offline/hybrid; null rejected. | activity.mode | OK | Enums agree, but v2 allows null and 28 rows are null. Mode alone does not establish an online schedule type. |
| src/sp3/feasibility.py:262-265; schemas/activity.schema.json:173-188 | location | Required key; string or null; online requires null. | activity.location | OK | Copy unchanged. The inspected planner does not calculate travel time from this field. |
| src/sp3/feasibility.py:266; src/api/reviewed_pipeline.py:78-81,150; src/api/server.py:971-972,1010-1011 | points | Required key; finite non-negative number or null. Non-null disagreement with bound regulation points triggers review. | activity.points_announced | RENAME | Keep null for all 189 rows. This is announced points, not projected/awarded points. The scorer obtains authoritative numbers through rules and bindings. |
| src/sp3/feasibility.py:267-268; src/api/lead_contract.py:69-71,86-87 | mandatory | Required bool. Missing or wrong type rejected at feasibility; publication can explicitly default unstated null to false. | activity.mandatory | OK | V2 already applies its default with provenance. The inspected planner does not force mandatory activities into the selected set. Keep requests/participation are separate inputs. |
| src/sp3/feasibility.py:269-272,623-630; src/api/lead_contract.py:94-98 | audience | Required key; array of strings or null. Object rejected. No free-text eligibility inference. | activity.audience.{text,cohorts,programs,all_students} | CONVERT | For legacy display, use [text] when text is non-empty, otherwise null. Preserve structured cohorts/programs/all_students separately for a student-specific eligibility resolver. Empty restrictions must not silently become a trusted ELIGIBLE result. |
| src/sp3/feasibility.py:273-275; src/api/lead_contract.py:72-74,88-89 | fee | Required finite non-negative scalar number, never null. No cost-based ranking/budget check in the inspected planner. | activity.fee | CONVERT | 0 -> 0. For {amount_vnd,per:person,deposit:false}, copy amount_vnd and retain the original object separately. Team, unknown-unit or deposit amounts have no lossless scalar interpretation here; block/review unless Ngoc agrees a representation. Current data: 178 scalar zeros, three person fees, seven unknown-unit fees, one team fee. |
| src/sp3/feasibility.py:276-278; src/api/lead_contract.py:82-83; src/sp2/rule_matcher.py:111; src/api/server.py:976-979,1142 | completion_requirements | Required non-empty string. Missing/null/array rejected by feasibility. Matcher concatenates its string representation; it does not execute completion conditions. | activity.completion_requirements[] | CONVERT | Counting projection serializes a non-empty list as deterministic JSON text, retaining every type/threshold/unit/deadline. Empty [] remains unknown and is blocked. Do not use the literal string "[]" or fabricated attendance text merely to pass validation. A native structured contract would avoid this lossy consumer interface. |

### 3.2 Other activity-backed data and mandatory external inputs

These are separate envelopes or alternate lower-level engine inputs. They are not extra keys that may be inserted into the strict 14-field activity.

| Consumer file:line | Field | Expected / missing behavior | SP1 v2 source | Status | Conversion / notes |
| --- | --- | --- | --- | --- | --- |
| src/sp2/rule_matcher.py:74-79,104-115; src/api/server.py:882-884,946-948 | raw_content argument | Required positional string argument; combined with title/domain/mode/completion text. No activity.raw_content lookup. | Not present in the activity store | MISSING_IN_SP1 | Caller needs an approved sanitized-text source or must explicitly accept title/field-only matching with an empty string. This audit did not access raw posts. Title-only matching is not equivalent to the current full-text call. |
| src/api/dedup_review.py:33-40 | top-level post_id, url, publisher, raw_content on post inputs | Optional aliases; falls back to source.URL_post, activity_id, source.publisher; missing raw_content disables text MinHash comparisons. | activity.source.post_id, activity.source.URL_post, activity.source.publisher; no raw text | CONVERT | This is a legacy post dedup API, not a consumer of the v2 duplicate map. Use the existing v2 canonical identity rather than silently re-deduplicating without text. |
| src/api/reviewed_pipeline.py:60-63 | metadata.status, metadata.flags, metadata.is_duplicate | status must equal valid; any flags or truthy is_duplicate -> NEEDS_REVIEW. Missing status also fails. | activity.meta.status, activity.meta.flags, record.duplicate_of | CONVERT | Move metadata out of activity. Map is_duplicate = (duplicate_of is not null), and skip duplicate records before downstream construction. Do not equate valid with approved source review. |
| src/api/lead_contract.py:59-61,75-77,117-126 | draft.meta.flags, derived, evidence; draft.record.drl_recognized | Optional metadata; publication inspects start/end evidence lists for suspicious date phrases and moves recognition into meta. | activity.meta.flags/derived; activity.drl_recognized; no original extraction evidence in store | CONVERT | Preserve v2 provenance in a separate envelope. Original extraction evidence is MISSING_IN_SP1 for this particular store, so older evidence checks cannot be reproduced faithfully from it. |
| src/api/reviewed_pipeline.py:64-81 | approval.{decision,activity_id,fingerprint,reviewer_id,reviewed_at,source_url,regulation_id,rule_id} | Independently trusted APPROVED record, matching final activity fingerprint/source and verified rule. Missing/mismatch -> NEEDS_REVIEW. | None | MISSING_IN_SP1 | Requires a reviewer/backend record. A model label, valid schema or completion text is not an approval. |
| src/sp3/feasibility.py:363-365,645-646; src/sp3/planner.py:499-501,516 | candidate.score_binding_ref | Required key; null or non-empty string; null prevents FEASIBLE selection. | None | MISSING_IN_SP1 | Backend must create and resolve a trusted binding. A non-null string alone does not create the scorer-side binding. |
| src/sp3/projected_scorer.py:83-106,178-189,410-428 | binding.{activity_id,binding_ref,rule_id,field,operation,value} | Exact binding shape. INCREMENT requires finite positive numeric value; SET a scalar. Rule/condition field/operator/category/baseline fact must agree. Missing -> MISSING_BINDING and NEEDS_REVIEW. | None | MISSING_IN_SP1 | Map activity to regulation facts through a reviewed binding. No automatic binding-to-fact adapter is provided by rule_matcher. category_id comes from the rule, not activity.domain. |
| src/sp3/feasibility.py:282-302,366-369; src/sp3/contract.py:539-550 | candidate.participation.{registration,progress} | Required object: REGISTERED/NOT_REGISTERED and NOT_STARTED/COMPLETED/CANCELLED. Missing fields or bad enums rejected. | None | MISSING_IN_SP1 | Student-specific state from backend. Initial defaults, if adopted, need an explicit backend policy. Do not infer registration/completion from the announcement. |
| src/sp3/feasibility.py:147-155,623-644 | evidence.eligibility_by_activity, source_review_by_activity, term_scope_by_activity / term_verified | Missing eligibility -> MISSING_ELIGIBILITY; source_review must be true; missing/unverified term -> TERM_UNVERIFIED. OUT_OF_SCOPE -> OUTSIDE_WINDOW. | Audience restrictions and semester labels are inputs to resolvers, not trusted evidence | MISSING_IN_SP1 | External student/scope/source verification is required. No automatic pass from store.plannable or activity.meta.status. |
| src/sp3/feasibility.py:471-544 | evidence.schedule_by_activity[id] | Optional authoritative schedule evidence. FIXED: type + fixed_blocks; FLEXIBLE_WINDOW: type + duration_minutes. Without evidence, only same-local-date offline/hybrid with usable start/end gets FIXED fallback. | window, duration_minutes, duration_source, multi_session | CONVERT | These are ingredients, not an explicit schedule type. Full fixed_blocks for a genuinely multi-session activity are MISSING_IN_SP1. Online and multi-day meaning must be resolved before selection. |
| src/sp3/contract.py:521-536; src/sp3/planner.py:503,517-520; src/sp3/scheduler.py:95-124 | candidate.schedule | Normalized FIXED with non-empty sorted non-overlapping blocks; or FLEXIBLE_WINDOW with window_start/window_end and positive integer duration <= window length. Required non-null for FEASIBLE. | No schedule object; partial ingredients above | MISSING_IN_SP1 | Feasibility generates this output. Its flexible evidence input omits bounds, whereas its normalized output includes them: do not confuse the two shapes. |
| src/sp3/feasibility.py:655-660; src/sp3/planner.py:504-526,160-166 | candidate.feasibility.{status,reason_codes} | Required FEASIBLE/INFEASIBLE/NEEDS_REVIEW; FEASIBLE requires empty reasons. Other statuses require reasons. | record.plannable and not_plannable_reasons are different concepts | MISSING_IN_SP1 | Run actual feasibility. Never rename plannable=true to FEASIBLE or SP1 partial to a planner status. |
| src/sp3/contract.py:160-166; src/sp3/feasibility.py:305-346; src/sp3/planner.py:389-405 | request context, availability, baseline, goals/preferences/limits | Exact request contract, student/term/as_of/timezone and version identifiers, intervals, baseline scores/caps/ledger, goals. Missing keys rejected. | None; semester labels only help term resolution | MISSING_IN_SP1 | Not NLP fields. Supply from backend/user state. timezone must be Asia/Ho_Chi_Minh, distinct from the +07:00 timestamp offset. |
| src/sp3/feasibility.py:664-687; src/sp3/planner.py:543-567; src/sp3/scheduler.py:64-154 | conflict_pairs and joint scheduling | All overlapping fixed-schedule pairs must be represented; flexible activities are scheduled together. Missing fixed conflicts rejected. | None | MISSING_IN_SP1 | Derived downstream from resolved schedules and student availability, not from text or mode alone. |
| src/sp2/drl_engine.py:674-703 | activity.benefit_claims[].verification_status, type, drl_criterion / criterion_code, points, claim_id | Optional alternate activity metadata for evaluate_progress. Missing/non-list -> no verified claims. Accepted verification statuses: CONFIRMED, VERIFIED, VERIFIED_BY_REVIEWER. DRL_POINTS/DRL_SCORE claim requires criterion and numeric points. | None | MISSING_IN_SP1 | This lower-level path is separate from the strict 14-key activity path. Never generate verified claims from recognition_stated or points_announced. |
| src/sp2/drl_engine.py:706-719 | activity.benefit_claims[].topic_code, counts_for_topic | Optional TOPIC_CREDIT claim with verified status and counts_for_topic=true. Otherwise no topic credit. | None | MISSING_IN_SP1 | A DRL topic-credit code is not automatically a personalization TopicId. |
| src/sp2/drl_engine.py:689-710,790-824; src/api/reviewed_pipeline.py:118-123 | student record.criterion_code, points, topic_code, status/evidence fields | Confirmed progress uses student participation/award records. Missing/unverified evidence excludes confirmed scoring. | None | MISSING_IN_SP1 | Reviewed adapter constructs criterion_code from rule.category_id and points from rule.points for a clearly marked demonstration. Do not confuse these records with SP1 activities. |

### 3.3 SP1-only fields and wrappers

No corresponding direct reader was found in the inspected SP2/SP3/API sources unless listed below. Unknown keys cannot remain inside the legacy activity because of exact-key validation.

| Consumer file:line | Field | Expected | SP1 v2 source | Status | Conversion / notes |
| --- | --- | --- | --- | --- | --- |
| No direct read; src/sp3/feasibility.py:247 and src/sp3/planner.py:489 reject extra fields | post_type | No legacy activity field | activity.post_type | UNUSED_BY_CONSUMERS | Adapter should retain only activity records for planning; info_only/insufficient must not become activities just because a legacy projection validates. |
| src/api/lead_contract.py:75-76 only at the legacy draft boundary | drl_recognized | Optional draft claim moved to metadata | activity.drl_recognized | CONVERT | Preserve as metadata. Not proof of credited points or reviewer approval. |
| No direct read in inspected consumers | recognition_stated | No legacy field | activity.recognition_stated | UNUSED_BY_CONSUMERS | Preserve as a source claim. Does not produce verified benefit_claims or a rule binding. |
| No direct read of v2 flag; schedule readers src/sp3/feasibility.py:483-501 and src/sp3/contract.py:510-527 | multi_session | Consumers need complete fixed blocks, not this boolean | activity.multi_session | UNUSED_BY_CONSUMERS | Retain as a review gate. A first-session window cannot reconstruct all required sessions. The counting safety screen requires multi_session=false. |
| No direct activity-field read; src/sp3/contract.py:533-535 reads schedule.duration_minutes | duration_minutes, duration_source | Duration is used inside resolved flexible schedule; fixed duration comes from blocks | activity.duration_minutes, duration_source | CONVERT | Copy duration only after schedule type is justified. V2 permits zero/null, but flexible scheduling requires an integer >=1. Preserve stated/default/unsupported origin. |
| No direct read in cached snapshot | campus[] | No campus constraint or preference in this snapshot | activity.campus | UNUSED_BY_CONSUMERS | Prospective personalization conversion is unverified; see section 5. Multiple campuses cannot be collapsed into one without a policy. |
| No direct read; legacy object permits only source.URL_registration | join_url | No separate join-link slot | activity.join_url | UNUSED_BY_CONSUMERS | Preserve separately. Do not overwrite the signup link. |
| No direct read | source.post_id, source.date_posted | Not members of the four-key legacy source | activity.source.post_id/date_posted | UNUSED_BY_CONSUMERS | Preserve in provenance sidecar. date_posted is never an event start substitute. |
| No direct read | semester_by_program; wrapper semester | No automatic mapping to context.term_id or trusted scope | activity.semester_by_program; record.semester | UNUSED_BY_CONSUMERS | Use to propose a scope decision, with the agreed semester bounds; not proof of IN_SCOPE. |
| src/api/reviewed_pipeline.py:60-63 reads separate metadata, not embedded v2 meta | meta.status, flags | Separate metadata consumed by reviewed scoring; absent in planner's activity shape | activity.meta.status/flags | CONVERT | Keep review gates and all diagnostic distinctions. Partial/failed are not planner FEASIBLE statuses. |
| No direct v2 trace reader | meta.derived, unsupported, time_defaults, year_inferred, normalizer_version, config_versions | No equivalent legacy activity fields | activity.meta.* | UNUSED_BY_CONSUMERS | Preserve for audit and adapter decisions. In particular keep date-only and default-duration evidence instead of treating normalized bounds as stated facts. |
| No duplicate_of reader in searched remote sources | duplicate_of | Null or canonical reference in v2 wrapper; unknown to old consumers | record.duplicate_of | UNUSED_BY_CONSUMERS | Mandatory adapter gate: skip every non-null value before matching/scoring/planning. Existing ID-ledger dedup is insufficient for cross-posts with different IDs. Currently all 189 are null. |
| No wrapper reader; src/api/dedup_review.py:60-68 has a different source-candidate representation | sources, possible_duplicates | No legacy wrapper contract | record.sources/possible_duplicates | UNUSED_BY_CONSUMERS | Retain source lineage. Two records have possible_duplicates; do not automatically treat proposals as confirmed duplicate_of. |
| No wrapper reader | position, split, field_methods, llm_available, llm_warnings | No legacy activity fields | record.* | UNUSED_BY_CONSUMERS | Preserve separately for traceability and review; they are not eligibility or source approvals. |
| No wrapper reader | plannable, not_plannable_reasons | SP1 structural/readiness result | record.* | UNUSED_BY_CONSUMERS | Recompute student-specific feasibility using SP3. 134 plannable rows do not imply 134 selectable candidates. |
| No SP1-store loader in inspected API | schema, generated_at, model_id, prompt_versions, merge_policy, llm_file, n_posts, n_without_llm, n_duplicate_groups, n_possible_duplicate_pairs, n_canonical | Store envelope; consumers load an activity array or their own request envelope | Store top level | UNUSED_BY_CONSUMERS | Adapter should retain provenance/version metadata while extracting canonical records. Dataset-version strategy must be agreed with the backend. |

## 4. Scoring and scheduling implications

### Points and criterion come from the regulation path

All 189 SP1 points_announced values are null. That is compatible with the nullable legacy points field and also matches the old 20-record sample's points shape.

1. rule_matcher reads title, domain, mode, completion_requirements and its separate raw_content argument (src/sp2/rule_matcher.py:104-115). It does not read points_announced, campus, activity_type, audience restrictions or a Qwen confidence.
2. It filters the supplied catalog to verified, positive numeric-point rules in C1-C5 and proposes a rule/category/points tuple (rule_matcher.py:42-62,89-96). No match returns rule=None (line 210). A manual override must still name an available filtered rule (lines 98-102).
3. The reviewed adapter obtains approval.rule_id, checks that rule, and constructs the student score record with criterion_code=rule.category_id and points=rule.points (src/api/reviewed_pipeline.py:75-81,118-123). The rule's more specific criterion_id is also returned (line 147); do not map activity.domain into either one.
4. The planner scorer instead resolves a trusted ScoreBinding, changes the rule's condition.field in baseline facts, runs the real engine and returns marginal category gains (src/sp3/projected_scorer.py:404-429,524-560). Engine awards use rule.points and the rule's repeat/count semantics (src/sp2/drl_engine.py:417-451).
5. A matcher suggestion is not the required backend binding: it does not supply reviewed baseline fact changes, student context or verification. The inspected demo obtains bindings from its fixture.

Important duration edge case: rule_matcher uses end-start to distinguish volunteer durations (lines 65-71,144-150). If start/end describe a multi-day online participation window rather than attendance, this can select an inappropriate duration-based rule. Passing duration_minutes silently in place of window bounds is not an established contract. This needs an explicit binding rule.

### Completion, mandatory, duplicates and quality

- completion_requirements is validated as text and used in keyword matching/display, not as an executable completion predicate. Its structured per-condition deadlines/thresholds have no direct planner enforcement.
- mandatory is validated as a bool but does not enter the inspected planner's eligibility or ranking tuple (planner.py:160-166,650-671). A mandatory source announcement is not automatically a KEEP_TIME request.
- No consumer reads duplicate_of. Skip non-null records explicitly before all downstream work, preserving canonical/source links. The engine's ledger dedup works by activity ID and criterion/topic (drl_engine.py:834-856), which will not resolve distinct IDs for the same cross-posted activity.
- SP1 meta.status=partial/failed is not directly consumed by feasibility; it requires separate source-review evidence. The reviewed scoring path does inspect metadata.status and flags and returns NEEDS_REVIEW for any non-valid status or non-empty flags.
- The server's DEMO path has a separate conditional estimate branch for warnings/ambiguity (server.py:974-985,1003-1012). Do not use that demo exception to grant trusted eligibility or actual credit.
- Schema validity, publication approval, participation completion and point verification are separate decisions.

### Time, multiple sessions, scope and registration

- SP1 timestamps already include seconds and +07:00. They are accepted by the old offset-aware parsers; no UTC conversion or removal of the offset is needed. Planner context.timezone must separately equal Asia/Ho_Chi_Minh (feasibility.py:322-323). Schedule intervals are half-open (contract.py:414-416).
- Without schedule evidence, same-local-date offline/hybrid bounds become FIXED. Online and cross-date bounds become MISSING_SCHEDULE_TYPE; missing bounds become MISSING_SCHEDULE (feasibility.py:526-544).
- A fixed activity can have multiple blocks, but SP1 v2 stores only the first session/round window. multi_session=true cannot generate the remaining blocks.
- Date-only normalization supplies bounds, not exact attendance time. The conservative safety count excludes date-only open/close bounds even if the legacy parser accepts them.
- Missing registration deadlines block NOT_REGISTERED candidates. REGISTERED bypasses deadline checks, but it is a student state that cannot be fabricated to raise usability.
- Local semester config uses HK3 2025-2026 = May 17-August 28 and HK1 2026-2027 = August 29-November 15. The inspected sp1_catalog advertises HK3 May 18-August 17 (sp3_service.py:62). This discrepancy needs agreement; a label alone cannot establish identical scope.

## 5. Personalization: explicitly unverified portion

No latest personalisation behavior is asserted from the cached branch. The local ADR records intended integration, not a substitute for reading the actual consumer.

| Consumer file:line | Field | Expected | SP1 v2 source | Status | Conversion / notes |
| --- | --- | --- | --- | --- | --- |
| src/personalization/models.py: UNVERIFIED, absent in cached snapshot; local ADR-0002:119-122 | topics / TopicId | UNVERIFIED implementation. ADR lists mathematics, artificial_intelligence, technology, research, soft_skills, career, volunteer, environment, culture, sports, health, safety, civic_education. | activity.domain; no activity_type field in this activity store | MISSING_IN_SP1 | A six-domain value does not identify a unique topic among thirteen. Exact topic array/scalar shape, null handling and mapping need the later consumer code. |
| src/personalization/models.py: UNVERIFIED; local ADR-0002:123-125 | campus_id / CampusId | UNVERIFIED implementation. Intended codes: NVC, DONG_HOA, ONLINE, OTHER. | activity.campus[] and activity.mode | CONVERT | Intended mapping only: CS1 -> NVC; CS2 -> DONG_HOA; Other -> OTHER; mode online -> ONLINE. Empty/unknown/multiple-campus or hybrid cases remain unresolved. Do not claim the current loader accepts this mapping. |
| Activity feature loader: UNVERIFIED; local ADR-0002:126-128 | activity_features.json envelope, activity_id, topics, campus_id, time_tags | ADR names personalization-features/0.1; exact JSON shape/types/defaults UNVERIFIED. | activity_id, window, campus, domain provide partial ingredients | MISSING_IN_SP1 | Loader lookup path, ID join behavior, missing-file handling, time-tag enum and required/optional rules cannot be established until the newer branch is readable. |

## 6. Reproducible counts and interpretation

The in-memory script in the command appendix uses the remote feasibility._validate_activity and _resolve_schedule functions without importing the API/server. It also validates against both actual schemas. No gold, raw text, source-post sample content or model inference is used.

Projection rules for this count:

1. Select rows with duplicate_of is null. Build exactly the legacy 14 activity keys and four source keys.
2. Copy existing values and rename window.open/close, points_announced and registration_url as in section 3.
3. Project audience to [text] or null, preserving the full structured object outside the proposed legacy projection. This is display conversion, not eligibility approval.
4. Keep scalar fee; flatten only per-person non-deposit objects. Other fee semantics are blocked.
5. Serialize only non-empty completion lists using json.dumps(..., ensure_ascii=False, sort_keys=True). Leave empty lists as null so a missing completion condition is not invented.
6. Do not repair URLs, invent deadlines, infer a schedule type from online mode, promote source status, or create rule bindings.
7. Additional safety stages explicitly require post_type=activity, non-failed status and multi_session=false. These are proposed adapter gates, not hidden existing consumer behavior.
8. Timestamp feasibility relative to a real student/as_of/availability is not evaluated because that context was not supplied.

| Sequential stage | Records | Meaning |
| --- | ---: | --- |
| Store records | 189 | 189 canonical rows; no confirmed duplicate_of in this snapshot. |
| Valid against local SP1 v2 schema | 189 | All activity objects satisfy their own schema. |
| Pass old activity schema unchanged | 0 | Different shape/types. |
| Pass old schema after the explicit projection | 13 | Structural acceptance only. |
| Pass remote feasibility activity validator after projection | 13 | Same 13; no student/evidence assumptions. |
| Above, post_type=activity and status != failed | 10 | Proposed semantic filter. |
| Above, explicitly single session | 8 | Conservative multi-session filter. |
| Above, fixed schedule resolves from existing bounds without new evidence | 2 | Positions 37 and 116, same-date offline/hybrid fallback. |
| Above, neither open nor close is a date-only default | 2 | These two have no date-only boundary issue. |
| Above, registration deadline is present | 0 | Neither can satisfy the NOT_REGISTERED deadline gate from store data. |
| Trusted FEASIBLE candidates established from the store alone | 0 | Bindings, participation and external verification are absent for every row. Actual feasibility after supplying those inputs remains UNVERIFIED. |

Converted structure-pass positions: 6, 37, 40, 47, 68, 72, 79, 81, 100, 116, 151, 154, 156. These positions are audit references, not post-specific rules.

Structural blockers after projection, counted once per record per field; categories overlap:

| Blocking field | Records | Cause |
| --- | ---: | --- |
| completion_requirements | 174 | Empty list has no truthful non-empty legacy completion string. |
| mode | 28 | Null is allowed by v2 but rejected downstream. |
| fee | 8 | Seven unknown-unit fees and one team fee cannot be flattened under the stated policy. |
| source.URL_registration | 8 | Non-null values fail the strict legacy HTTP(S)/URI contract without repair. |

Additional observations:

- Store.plannable is true for 134 rows; 125 of these have empty completion_requirements, 14 have a date-only opening bound and 11 have multi_session=true.
- Overall status: 128 valid, 52 partial, nine failed. 62 rows have non-empty flags.
- Overall post_type: 175 activity, 13 insufficient, one info_only.
- 97 rows have both window bounds. Of the 13 structurally accepted rows, four have MISSING_SCHEDULE and five MISSING_SCHEDULE_TYPE under the existing fallback. One of those 13 has a registration deadline, but it does not survive the conservative fixed/single-session stages.
- Each of score_binding_ref, participation, schedule, eligibility_by_activity, source_review_by_activity and term_scope_by_activity is present in zero store activity/wrapper records.
- A separate sensitivity calculation permits end=start+duration_minutes only for explicitly single-session offline entries with a non-date-only start, missing end, positive integer duration and same-day resulting bounds. It raises the conservative timed fixed-schedule pool from two to five (positions 37, 47, 72, 81, 116). All five still lack a deadline. This is a proposed duration/default policy, not a verified implemented conversion.
- The two possible-duplicate proposals should remain reviewable. There are no non-null duplicate_of rows to exclude in this snapshot; the adapter gate is still necessary for future stores.
- No actual eligibility, current registration or successful scored plan is claimed. For already registered students or additional authoritative schedule/review/binding records, counts could differ.

## 7. Blocking gaps and questions for Ngoc

Blocking gaps:

1. **Fresh consumer code unavailable:** the cached branch predates the personalization work. Current interfaces beyond this commit are UNVERIFIED.
2. **No v2 loader/adapter:** API catalog and demo planning load legacy/sample sources; object and nested source keys differ.
3. **Completion contract mismatch:** 174 truthful empty arrays cannot satisfy a required non-empty string. Also resolve eight non-scalar fee meanings and eight signup URL incompatibilities.
4. **Schedule semantics and deadlines:** first-session-only output, missing bounds, date-only defaults, online schedule type and absent signup deadlines require explicit policies/evidence.
5. **Trusted backend context:** no activity-to-rule bindings, student participation/eligibility, source approvals, baseline facts or actual availability are supplied by SP1.
6. **Scope/identity/version alignment:** semester bounds differ; publication can replace TMP IDs; all downstream references must use the same stable identity and dataset version.

Open questions for Ngoc:

- Which remote commit should be the integration target, and can the current personalization models/loader be made available for this audit?
- Should consumers adopt native activity_v2 or keep the 14-field projection plus a lossless sidecar?
- Can completion_requirements be an empty structured array when the announcement is silent? Which activities must be held for review, and who supplies any verified completion policy?
- How should team/unknown-unit fees and deposit semantics be represented without changing their meaning?
- Who produces and approves ScoreBinding(field, operation, value, rule_id), and should full sanitized source text be retained for rule_matcher?
- Which identity survives publication, deduplication, feature lookup, rule bindings and existing student ledgers?
- How are missing signup deadlines handled for NOT_REGISTERED users? Is there a separately verified "registration not required" representation?
- Which approved evidence determines FIXED versus FLEXIBLE_WINDOW, and is first-session-only extraction sufficient for every planned activity?
- Can a stated or team-default duration supply missing fixed-session end times, and how are date-only bounds handled?
- Which semester bounds are authoritative, and which backend converts semester_by_program and audience restrictions into trusted term/eligibility decisions?
- What are the exact TopicId/CampusId/time_tags enums, missing-feature behavior and multiple-campus policy in the latest personalization implementation?
- Should mandatory influence planner selection, and if so through which explicit contract? The inspected planner only validates its boolean type.

## 8. Command and write audit

Only docs/sp1_handover_contract_check.md was created by this task. No implementation, data or test file was edited. The pre-existing working tree already had many modified/untracked files, so final git status cannot honestly be described as containing only one entry. The relevant assertion is that the status delta from the captured baseline adds only this report.

git fetch origin and git status --short were the explicit step-1/final-output exceptions to the otherwise read-only git show / git ls-tree / git grep restriction. Fetch failed before the requested refresh. No commit, push, merge, checkout, reset, stash or branch switch was used. No tokens or secrets were requested or printed.

The following records the exact shell commands used. File contents retrieved with git show were retained only in tool memory for line-number inspection. Repeated line-window displays from that memory are not additional shell commands.

### Executed shell commands, in order

Command 1:

~~~powershell
git fetch origin
~~~

Result: failed, FETCH_HEAD permission denied; remote freshness UNVERIFIED.

Command 2:

~~~powershell
Get-Content schemas/activity_v2.schema.json -Raw; Get-Item docs/sp1_handover_contract_check.md -ErrorAction SilentlyContinue; Get-Content AGENTS.md -ErrorAction SilentlyContinue; git status --short
~~~

Command 3:

~~~powershell
git ls-tree -r --name-only origin/Nhu_Ngoc src/sp2 src/sp3 src/api src/personalization data schemas tests/personalization tests/sp3 tests/sp2
~~~

Command 4:

~~~powershell
git show -s --format="%H%n%ci%n%s" origin/Nhu_Ngoc; git grep -n -E 'activity|activities|completion_requirements|mandatory|registration_deadline|duplicate_of|activity_features|TopicId|CampusId' origin/Nhu_Ngoc -- src/sp2 src/sp3 src/api src/personalization
~~~

Command 5:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import subprocess,json
branch='origin/Nhu_Ngoc'
paths=subprocess.check_output(['git','ls-tree','-r','--name-only',branch],text=True).splitlines()
selected=[p for p in paths if p.startswith(('src/sp2/','src/sp3/','src/api/','src/personalization/')) and p.endswith('.py')]
selected += [p for p in paths if p in ['schemas/activity.schema.json','data/activities.json','data/drl_rules.json','data/sp2_sp3_output_sample.json','data/docs/sp2_sp3_output_contract.md','docs/SP3_PLANNER_CONTRACT_V0_2.md']]
print(json.dumps({'files':{p:subprocess.check_output(['git','show',branch+':'+p]).decode('utf-8') for p in selected},'paths':paths}))
'@ | .venv\Scripts\python.exe -
~~~

Result handling: output exceeded the tool response budget and the JSON envelope could not be decoded. Source retrieval was repeated per file below; no file was written by this attempt.

Command 6:

~~~powershell
git show origin/Nhu_Ngoc:src/sp2/rule_matcher.py
~~~

Command 7:

~~~powershell
git show origin/Nhu_Ngoc:src/sp2/drl_engine.py
~~~

Command 8:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/contract.py
~~~

Command 9:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/feasibility.py
~~~

Command 10:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/planner.py
~~~

Command 11:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/projected_scorer.py
~~~

Command 12:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/scorer_adapter.py
~~~

Command 13:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/scheduler.py
~~~

Command 14:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/plan_checker.py
~~~

Command 15:

~~~powershell
git show origin/Nhu_Ngoc:src/sp3/availability.py
~~~

Command 16:

~~~powershell
git show origin/Nhu_Ngoc:src/api/sp3_service.py
~~~

Command 17:

~~~powershell
git show origin/Nhu_Ngoc:src/api/lead_contract.py
~~~

Command 18:

~~~powershell
git show origin/Nhu_Ngoc:src/api/reviewed_pipeline.py
~~~

Command 19:

~~~powershell
git show origin/Nhu_Ngoc:src/api/dedup_review.py
~~~

Command 20:

~~~powershell
git show origin/Nhu_Ngoc:src/api/server.py
~~~

Command 21:

~~~powershell
git show origin/Nhu_Ngoc:schemas/activity.schema.json
~~~

Command 22:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import subprocess,json
from collections import Counter
ref='origin/Nhu_Ngoc'
paths=subprocess.check_output(['git','ls-tree','-r','--name-only',ref],text=True).splitlines()
print('Relevant inventory:',json.dumps([p for p in paths if p.startswith(('DataQA/','src/personalization/')) or 'activity_features' in p or p in ['data/activities.json','data/source_posts.json','tests/sp3/fixtures/main_flow_integration.json']]))
def read(p):return json.loads(subprocess.check_output(['git','show',ref+':'+p]))
def fields(rows):
 out={}
 for row in rows:
  if isinstance(row,dict):
   for k,v in row.items():out.setdefault(k,set()).add(type(v).__name__)
 return {k:sorted(v) for k,v in sorted(out.items())}
r=read('data/drl_rules.json')
print('Rule catalog structure:',json.dumps({'top_level':fields([r]),'rule_count':len(r['rules']),'rule_fields':fields(r['rules']),'condition_fields':fields([x.get('condition') for x in r['rules']]),'scoring_model':fields([r['scoring_model']]),'category_cap_fields':fields(r['scoring_model'].get('category_caps',[]))}))
for p in ['data/activities.json','DataQA/QA20.json','tests/sp3/fixtures/main_flow_integration.json']:
 if p not in paths:print(p,'UNVERIFIED absent');continue
 x=read(p)
 print(p,'top_type',type(x).__name__,'length',len(x),'fields',json.dumps(fields(x if isinstance(x,list) else [x])))
 if p=='data/activities.json':print('Activity source fields:',json.dumps(fields([a.get('source') for a in x])))
 if p.endswith('main_flow_integration.json'):
  print('Scoring data structure:',json.dumps(fields([x.get('scoring_data')])));print('Evidence structure:',json.dumps(fields([x.get('evidence')])))
'@ | .venv\Scripts\python.exe -
~~~

Command 23:

~~~powershell
git grep -n -E 'TopicId|CampusId|activity_features|duplicate_of|multi_session|points_announced|semester_by_program' origin/Nhu_Ngoc -- src/sp2 src/sp3 src/api src/personalization
~~~

Command 24:

~~~powershell
git grep -n -E 'mandatory|completion_requirements|benefit_claims|audience|\.points|\["points"\]' origin/Nhu_Ngoc -- src/sp2 src/sp3
~~~

Command 25:

~~~powershell
git grep -n -E 'DATA_DIR|DATA /|QA /|DEMO|_json\(|load_json\(' origin/Nhu_Ngoc -- src/api/sp3_service.py src/api/server.py
~~~

Command 26:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import json,hashlib
from pathlib import Path
from collections import Counter
p=Path('data/activity_store_v2.json'); b=p.read_bytes(); s=json.loads(b); rows=s['records']
print('store_sha256',hashlib.sha256(b).hexdigest())
print('store_meta_keys',list(s)); print('schema',s.get('schema'),'records',len(rows))
print('record_keys',sorted(set().union(*(r.keys() for r in rows))))
print('activity_keys',sorted(set().union(*(r['activity'].keys() for r in rows))))
for field,fn in [('duplicate',lambda r:r.get('duplicate_of') is not None),('plannable',lambda r:r.get('plannable')),('status',lambda r:r['activity']['meta']['status']),('post_type',lambda r:r['activity']['post_type']),('mode',lambda r:r['activity']['mode']),('multi_session',lambda r:r['activity']['multi_session']),('semester',lambda r:r['semester']),('duration_source',lambda r:r['activity']['duration_source']),('completion_count',lambda r:len(r['activity']['completion_requirements'])),('points_null',lambda r:r['activity']['points_announced'] is None),('fee_type',lambda r:type(r['activity']['fee']).__name__)]:
 print(field,json.dumps(dict(Counter(str(fn(r)) for r in rows))))
print('duplicates valid references',all(any(x['activity']['activity_id']==r['duplicate_of'] for x in rows) for r in rows if r.get('duplicate_of') is not None))
print('schema_sha256',hashlib.sha256(Path('schemas/activity_v2.schema.json').read_bytes()).hexdigest())
'@ | .venv\Scripts\python.exe -
~~~

Command 27:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import json, subprocess, sys, types, hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta
from jsonschema import Draft202012Validator, FormatChecker

ref = 'origin/Nhu_Ngoc'
remote_source = subprocess.check_output(['git', 'show', ref + ':src/sp3/feasibility.py']).decode('utf-8')
module = types.ModuleType('handover_feasibility_readonly')
sys.modules[module.__name__] = module
exec(compile(remote_source, ref + ':src/sp3/feasibility.py', 'exec'), module.__dict__)
store_path = Path('data/activity_store_v2.json')
store = json.loads(store_path.read_bytes())
rows = store['records']
old_schema = json.loads(subprocess.check_output(['git', 'show', ref + ':schemas/activity.schema.json']))
old_validator = Draft202012Validator(old_schema, format_checker=FormatChecker())
new_validator = Draft202012Validator(json.loads(Path('schemas/activity_v2.schema.json').read_bytes()))
def project(a):
    fee = a['fee']
    if isinstance(fee, dict):
        # Do not collapse team/deposit/unknown-unit fees into a per-person scalar.
        fee = fee['amount_vnd'] if fee['per'] == 'person' and fee['deposit'] is False else None
    audience = a['audience']
    return {
        'activity_id': a['activity_id'],
        'source': {k: a['source'][k] for k in ('publisher', 'platform', 'URL_post')} |
                  {'URL_registration': a['registration_url']},
        'title': a['title'], 'domain': a['domain'], 'start': a['window']['open'],
        'end': a['window']['close'], 'registration_deadline': a['registration_deadline'],
        'mode': a['mode'], 'location': a['location'], 'points': a['points_announced'],
        'mandatory': a['mandatory'], 'audience': [audience['text']] if audience['text'] else None,
        'fee': fee,
        # Machine-readable JSON string preserves every condition attribute. Empty means unknown.
        'completion_requirements': json.dumps(a['completion_requirements'], ensure_ascii=False, sort_keys=True)
                                   if a['completion_requirements'] else None,
    }
def parse(a):
    return module._validate_activity(a, 'activity')
def scheduled(a):
    aid, start, end, deadline = parse(a)
    entry = {'activity': a, 'score_binding_ref': None,
             'participation': {'registration': 'NOT_REGISTERED', 'progress': 'NOT_STARTED'}}
    parsed = module._ParsedActivity(entry, aid, start, end, deadline,
                                   module.RegistrationStatus.NOT_REGISTERED, module.ProgressStatus.NOT_STARTED)
    result, reasons = module._resolve_schedule(parsed, module.FeasibilityEvidence())
    return result, reasons
canonical = [r for r in rows if r.get('duplicate_of') is None]
converted, valid = {}, []
errors = Counter()
for r in canonical:
    a = project(r['activity']); converted[r['position']] = a
    for error in old_validator.iter_errors(a):
        errors['.'.join(map(str, error.absolute_path))] += 1
    try:
        parse(a)
    except module.FeasibilityContractError:
        continue
    valid.append(r)
base = [r for r in valid if r['activity']['post_type'] == 'activity'
        and r['activity']['meta']['status'] != 'failed']
single = [r for r in base if r['activity']['multi_session'] is False]
fixed = [r for r in single if scheduled(converted[r['position']])[0] is not None]
timed = [r for r in fixed if 'window_open' not in r['activity']['meta']['time_defaults']
         and 'window_close' not in r['activity']['meta']['time_defaults']]
deadline = [r for r in timed if converted[r['position']]['registration_deadline'] is not None]
in_term = [r for r in deadline if r['semester'] in {'HK3_2025_2026','HK1_2026_2027'}]
status_valid = [r for r in in_term if r['activity']['meta']['status'] == 'valid'
                and not r['activity']['meta']['flags']]
stages = {'all_rows': len(rows), 'canonical':len(canonical),
          'sp1_schema_valid':sum(new_validator.is_valid(r['activity']) for r in rows),
          'direct_legacy_schema_valid':sum(old_validator.is_valid(r['activity']) for r in rows),
          'converted_schema_valid':sum(old_validator.is_valid(project(r['activity'])) for r in canonical),
          'converted_feasibility_activity_valid':len(valid), 'activity_nonfailed':len(base),
          'explicit_single_session':len(single), 'fixed_schedule_fallback':len(fixed),
          'no_date_only_bounds':len(timed), 'deadline_present':len(deadline),
          'in_either_configured_semester':len(in_term),
          'valid_status_and_no_flags':len(status_valid),
          'trusted_feasible_from_store_alone':0}
print('STAGES',json.dumps(stages,sort_keys=True))
print('CONVERSION_SCHEMA_BLOCKERS',json.dumps(dict(errors),sort_keys=True))
print('POSITIONS_BY_STAGE',json.dumps({'converted_valid':[r['position'] for r in valid],
     'fixed':[r['position'] for r in fixed], 'timed':[r['position'] for r in timed],
     'deadline':[r['position'] for r in deadline], 'term':[r['position'] for r in in_term],
     'unflagged':[r['position'] for r in status_valid]}))
print('VALID_ROW_SCHEDULE_REASONS',json.dumps(dict(Counter(reason for r in valid
      for reason in scheduled(converted[r['position']])[1])),sort_keys=True))
print('PRESENT_FIELDS',json.dumps({key:sum(key in r or key in r['activity'] for r in rows)
      for key in ['score_binding_ref','participation','schedule','eligibility_by_activity','source_review_by_activity','term_scope_by_activity']}))
print('FEE_CLASSES',json.dumps(dict(Counter(('scalar' if not isinstance(r['activity']['fee'],dict) else
       str(r['activity']['fee']['per']) + ':deposit=' + str(r['activity']['fee']['deposit'])) for r in rows))))
print('TIME_DEFAULT_KEYS',json.dumps(dict(Counter(k for r in rows for k in r['activity']['meta']['time_defaults']))))
# Sensitivity: supply a documented duration only where a same-day single offline end is missing.
derived_valid = []
for r in single:
    a = dict(converted[r['position']]); act=r['activity']
    if (a['mode']=='offline' and a['start'] and a['end'] is None and
        'window_open' not in act['meta']['time_defaults'] and
        type(act['duration_minutes']) is int and act['duration_minutes']>0):
        start=datetime.fromisoformat(a['start']); end=start+timedelta(minutes=act['duration_minutes'])
        if start.date()==end.date():a['end']=end.isoformat(timespec='seconds')
    schedule,reasons=scheduled(a)
    if schedule and 'window_open' not in act['meta']['time_defaults'] and 'window_close' not in act['meta']['time_defaults']:
        derived_valid.append(r)
print('DURATION_DERIVED_FIXED_SENSITIVITY',json.dumps({'count':len(derived_valid),'positions':[r['position'] for r in derived_valid],
        'with_deadline':sum(r['activity']['registration_deadline'] is not None for r in derived_valid)}))
print('USER_CONTEXT','No real student, as_of, availability, baseline, approvals or rule bindings were supplied; no actual planner eligibility is asserted.')

'@ | .venv\Scripts\python.exe -
~~~

Command 28:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import json, subprocess, sys, types, hashlib
from pathlib import Path
from collections import Counter
from datetime import datetime, timedelta
from jsonschema import Draft202012Validator, FormatChecker

ref = 'origin/Nhu_Ngoc'
remote_source = subprocess.check_output(['git', 'show', ref + ':src/sp3/feasibility.py']).decode('utf-8')
module = types.ModuleType('handover_feasibility_readonly')
sys.modules[module.__name__] = module
exec(compile(remote_source, ref + ':src/sp3/feasibility.py', 'exec'), module.__dict__)
store_path = Path('data/activity_store_v2.json')
store = json.loads(store_path.read_bytes())
rows = store['records']
old_schema = json.loads(subprocess.check_output(['git', 'show', ref + ':schemas/activity.schema.json']))
old_validator = Draft202012Validator(old_schema, format_checker=FormatChecker())
new_validator = Draft202012Validator(json.loads(Path('schemas/activity_v2.schema.json').read_bytes()))
def project(a):
    fee = a['fee']
    if isinstance(fee, dict):
        # Do not collapse team/deposit/unknown-unit fees into a per-person scalar.
        fee = fee['amount_vnd'] if fee['per'] == 'person' and fee['deposit'] is False else None
    audience = a['audience']
    return {
        'activity_id': a['activity_id'],
        'source': {k: a['source'][k] for k in ('publisher', 'platform', 'URL_post')} |
                  {'URL_registration': a['registration_url']},
        'title': a['title'], 'domain': a['domain'], 'start': a['window']['open'],
        'end': a['window']['close'], 'registration_deadline': a['registration_deadline'],
        'mode': a['mode'], 'location': a['location'], 'points': a['points_announced'],
        'mandatory': a['mandatory'], 'audience': [audience['text']] if audience['text'] else None,
        'fee': fee,
        # Machine-readable JSON string preserves every condition attribute. Empty means unknown.
        'completion_requirements': json.dumps(a['completion_requirements'], ensure_ascii=False, sort_keys=True)
                                   if a['completion_requirements'] else None,
    }
def parse(a):
    return module._validate_activity(a, 'activity')
def scheduled(a):
    aid, start, end, deadline = parse(a)
    entry = {'activity': a, 'score_binding_ref': None,
             'participation': {'registration': 'NOT_REGISTERED', 'progress': 'NOT_STARTED'}}
    parsed = module._ParsedActivity(entry, aid, start, end, deadline,
                                   module.RegistrationStatus.NOT_REGISTERED, module.ProgressStatus.NOT_STARTED)
    result, reasons = module._resolve_schedule(parsed, module.FeasibilityEvidence())
    return result, reasons
canonical = [r for r in rows if r.get('duplicate_of') is None]
converted, valid = {}, []
errors = Counter()
for r in canonical:
    a = project(r['activity']); converted[r['position']] = a
    errors.update({'.'.join(map(str, error.absolute_path)) for error in old_validator.iter_errors(a)})
    try:
        parse(a)
    except module.FeasibilityContractError:
        continue
    valid.append(r)
base = [r for r in valid if r['activity']['post_type'] == 'activity'
        and r['activity']['meta']['status'] != 'failed']
single = [r for r in base if r['activity']['multi_session'] is False]
fixed = [r for r in single if scheduled(converted[r['position']])[0] is not None]
timed = [r for r in fixed if 'window_open' not in r['activity']['meta']['time_defaults']
         and 'window_close' not in r['activity']['meta']['time_defaults']]
deadline = [r for r in timed if converted[r['position']]['registration_deadline'] is not None]
in_term = [r for r in deadline if r['semester'] in {'HK3_2025_2026','HK1_2026_2027'}]
status_valid = [r for r in in_term if r['activity']['meta']['status'] == 'valid'
                and not r['activity']['meta']['flags']]
stages = {'all_rows': len(rows), 'canonical':len(canonical),
          'sp1_schema_valid':sum(new_validator.is_valid(r['activity']) for r in rows),
          'direct_legacy_schema_valid':sum(old_validator.is_valid(r['activity']) for r in rows),
          'converted_schema_valid':sum(old_validator.is_valid(project(r['activity'])) for r in canonical),
          'converted_feasibility_activity_valid':len(valid), 'activity_nonfailed':len(base),
          'explicit_single_session':len(single), 'fixed_schedule_fallback':len(fixed),
          'no_date_only_bounds':len(timed), 'deadline_present':len(deadline),
          'in_either_configured_semester':len(in_term),
          'valid_status_and_no_flags':len(status_valid),
          'trusted_feasible_from_store_alone':0}
print('STAGES',json.dumps(stages,sort_keys=True))
print('CONVERSION_SCHEMA_BLOCKERS',json.dumps(dict(errors),sort_keys=True))
print('POSITIONS_BY_STAGE',json.dumps({'converted_valid':[r['position'] for r in valid],
     'fixed':[r['position'] for r in fixed], 'timed':[r['position'] for r in timed],
     'deadline':[r['position'] for r in deadline], 'term':[r['position'] for r in in_term],
     'unflagged':[r['position'] for r in status_valid]}))
print('VALID_ROW_SCHEDULE_REASONS',json.dumps(dict(Counter(reason for r in valid
      for reason in scheduled(converted[r['position']])[1])),sort_keys=True))
print('PRESENT_FIELDS',json.dumps({key:sum(key in r or key in r['activity'] for r in rows)
      for key in ['score_binding_ref','participation','schedule','eligibility_by_activity','source_review_by_activity','term_scope_by_activity']}))
print('FEE_CLASSES',json.dumps(dict(Counter(('scalar' if not isinstance(r['activity']['fee'],dict) else
       str(r['activity']['fee']['per']) + ':deposit=' + str(r['activity']['fee']['deposit'])) for r in rows))))
print('TIME_DEFAULT_KEYS',json.dumps(dict(Counter(k for r in rows for k in r['activity']['meta']['time_defaults']))))
# Sensitivity: supply a documented duration only where a same-day single offline end is missing.
derived_valid = []
for r in single:
    a = dict(converted[r['position']]); act=r['activity']
    if (a['mode']=='offline' and a['start'] and a['end'] is None and
        'window_open' not in act['meta']['time_defaults'] and
        type(act['duration_minutes']) is int and act['duration_minutes']>0):
        start=datetime.fromisoformat(a['start']); end=start+timedelta(minutes=act['duration_minutes'])
        if start.date()==end.date():a['end']=end.isoformat(timespec='seconds')
    schedule,reasons=scheduled(a)
    if schedule and 'window_open' not in act['meta']['time_defaults'] and 'window_close' not in act['meta']['time_defaults']:
        derived_valid.append(r)
print('DURATION_DERIVED_FIXED_SENSITIVITY',json.dumps({'count':len(derived_valid),'positions':[r['position'] for r in derived_valid],
        'with_deadline':sum(r['activity']['registration_deadline'] is not None for r in derived_valid)}))
print('USER_CONTEXT','No real student, as_of, availability, baseline, approvals or rule bindings were supplied; no actual planner eligibility is asserted.')

print('OTHER_COUNTS',json.dumps({
 'deadline_missing':sum(r['activity']['registration_deadline'] is None for r in canonical),
 'empty_completion_and_plannable':sum(not r['activity']['completion_requirements'] and r['plannable'] for r in canonical),
 'date_only_open_and_plannable':sum('window_open' in r['activity']['meta']['time_defaults'] and r['plannable'] for r in canonical),
 'multi_true_and_plannable':sum(r['activity']['multi_session'] is True and r['plannable'] for r in canonical),
 'missing_mode':sum(r['activity']['mode'] is None for r in canonical),
 'both_bounds':sum(bool(r['activity']['window']['open'] and r['activity']['window']['close']) for r in canonical),
 'safe_fee':sum(project(r['activity'])['fee'] is not None for r in canonical),
 'flags_nonempty':sum(bool(r['activity']['meta']['flags']) for r in canonical),
 'possible_duplicates_nonempty':sum(bool(r['possible_duplicates']) for r in canonical),
 'deadline_in_converted_valid':sum(r['activity']['registration_deadline'] is not None for r in valid)
},sort_keys=True))

'@ | .venv\Scripts\python.exe -
~~~

Command 29:

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
from pathlib import Path
p=Path('docs/adr/0002-sp1-stated-facts-team-defaults-schema-v2.md')
lines=p.read_text(encoding='utf-8').splitlines()
for i,line in enumerate(lines,1):
 if '**D13.' in line:
  print('\n'.join(f'{n}: {lines[n-1]}' for n in range(i,min(i+15,len(lines)+1))))
'@ | .venv\Scripts\python.exe -
~~~

Command 30:

~~~powershell
git status --short
~~~

Command 31:

~~~powershell
Get-Content data/config/semesters.json -Raw
~~~

### Captured working-tree baseline

~~~text
 M docs/adr/0002-sp1-stated-facts-team-defaults-schema-v2.md
 M src/sp1/dates.py
 M tests/sp1/test_dates.py
 M tests/sp1/test_extractor.py
?? data/activity_store_v2.json
?? data/config/
?? data/gold/final_run_access_log.jsonl
?? data/llm_inputs/
?? data/llm_outputs/
?? data/redteam/
?? docs/SP3_PLANNER_CONTRACT_DRAFT.md
?? docs/sp1_extract_v2.md
?? docs/sp1_llm_v2.md
?? docs/sp1_normalizer.md
?? notebooks/
?? prompts/sp1_classify_v2.txt
?? prompts/sp1_roles_v2.txt
?? reports/sp1_dedup_eval.md
?? reports/sp1_final_readiness.md
?? reports/sp1_llm_dev_compare.md
?? reports/sp1_manual_check_after.csv
?? reports/sp1_manual_check_before.csv
?? reports/sp1_redteam_eval.md
?? reports/sp1_segmentation_dev.md
?? reports/sp1_v2_dev_eval.md
?? reports/sp1_v2_non_test_output.json
?? reports/sp1_v2_readiness_non_test.md
?? schemas/activity_v2.schema.json
?? schemas/examples/sp3/
?? schemas/layer_a_record_v2.schema.json
?? schemas/sp3/
?? scripts/build_activity_store.py
?? scripts/check_sp3_contract.py
?? scripts/compare_llm_dev.py
?? scripts/eval_dedup_synthetic.py
?? scripts/eval_redteam.py
?? scripts/export_llm_inputs.py
?? scripts/report_segmentation_dev.py
?? scripts/run_sp1_v2.py
?? src/sp1/activity_type.py
?? src/sp1/candidates.py
?? src/sp1/dedup_v2.py
?? src/sp1/devdata.py
?? src/sp1/evaluate_v2.py
?? src/sp1/extract_v2.py
?? src/sp1/hybrid.py
?? src/sp1/llm_v2.py
?? src/sp1/normalize.py
?? src/sp1/preprocess.py
?? src/sp1/segment.py
?? tests/sp1/fixtures/llm_v2/
?? tests/sp1/test_activity_type.py
?? tests/sp1/test_candidates.py
?? tests/sp1/test_compare_llm_dev.py
?? tests/sp1/test_dedup_v2.py
?? tests/sp1/test_devdata.py
?? tests/sp1/test_evaluate_v2.py
?? tests/sp1/test_export_llm_inputs.py
?? tests/sp1/test_extract_v2.py
?? tests/sp1/test_hybrid.py
?? tests/sp1/test_llm_v2.py
?? tests/sp1/test_llm_v2_lenient.py
?? tests/sp1/test_normalize.py
?? tests/sp1/test_preprocess.py
?? tests/sp1/test_segment.py
~~~

### Final verification command

The following command verifies the one-file status delta and prints the full final status. It also checks that the report contains all required mapping statuses.

~~~powershell
$env:PYTHONDONTWRITEBYTECODE='1'; @'
import json, subprocess
from pathlib import Path
baseline = set(json.loads(r'''[" M docs/adr/0002-sp1-stated-facts-team-defaults-schema-v2.md"," M src/sp1/dates.py"," M tests/sp1/test_dates.py"," M tests/sp1/test_extractor.py","?? data/activity_store_v2.json","?? data/config/","?? data/gold/final_run_access_log.jsonl","?? data/llm_inputs/","?? data/llm_outputs/","?? data/redteam/","?? docs/SP3_PLANNER_CONTRACT_DRAFT.md","?? docs/sp1_extract_v2.md","?? docs/sp1_llm_v2.md","?? docs/sp1_normalizer.md","?? notebooks/","?? prompts/sp1_classify_v2.txt","?? prompts/sp1_roles_v2.txt","?? reports/sp1_dedup_eval.md","?? reports/sp1_final_readiness.md","?? reports/sp1_llm_dev_compare.md","?? reports/sp1_manual_check_after.csv","?? reports/sp1_manual_check_before.csv","?? reports/sp1_redteam_eval.md","?? reports/sp1_segmentation_dev.md","?? reports/sp1_v2_dev_eval.md","?? reports/sp1_v2_non_test_output.json","?? reports/sp1_v2_readiness_non_test.md","?? schemas/activity_v2.schema.json","?? schemas/examples/sp3/","?? schemas/layer_a_record_v2.schema.json","?? schemas/sp3/","?? scripts/build_activity_store.py","?? scripts/check_sp3_contract.py","?? scripts/compare_llm_dev.py","?? scripts/eval_dedup_synthetic.py","?? scripts/eval_redteam.py","?? scripts/export_llm_inputs.py","?? scripts/report_segmentation_dev.py","?? scripts/run_sp1_v2.py","?? src/sp1/activity_type.py","?? src/sp1/candidates.py","?? src/sp1/dedup_v2.py","?? src/sp1/devdata.py","?? src/sp1/evaluate_v2.py","?? src/sp1/extract_v2.py","?? src/sp1/hybrid.py","?? src/sp1/llm_v2.py","?? src/sp1/normalize.py","?? src/sp1/preprocess.py","?? src/sp1/segment.py","?? tests/sp1/fixtures/llm_v2/","?? tests/sp1/test_activity_type.py","?? tests/sp1/test_candidates.py","?? tests/sp1/test_compare_llm_dev.py","?? tests/sp1/test_dedup_v2.py","?? tests/sp1/test_devdata.py","?? tests/sp1/test_evaluate_v2.py","?? tests/sp1/test_export_llm_inputs.py","?? tests/sp1/test_extract_v2.py","?? tests/sp1/test_hybrid.py","?? tests/sp1/test_llm_v2.py","?? tests/sp1/test_llm_v2_lenient.py","?? tests/sp1/test_normalize.py","?? tests/sp1/test_preprocess.py","?? tests/sp1/test_segment.py"]'''))
current_text = subprocess.check_output(['git', 'status', '--short']).decode('utf-8')
current = set(current_text.splitlines())
expected = '?? docs/sp1_handover_contract_check.md'
assert current - baseline == {expected}, sorted(current - baseline)
assert baseline - current == set(), sorted(baseline - current)
report = Path('docs/sp1_handover_contract_check.md').read_text(encoding='utf-8')
assert report.startswith('# SP1 v2 handover contract check')
assert 'UNVERIFIED' in report and '189' in report
assert all(status in report for status in ['OK', 'RENAME', 'CONVERT', 'MISSING_IN_SP1', 'UNUSED_BY_CONSUMERS'])
print('Status delta verified: only docs/sp1_handover_contract_check.md added.')
print('Report lines:',len(report.splitlines()))
print('git status --short:')
print(current_text, end='')

'@ | .venv\Scripts\python.exe -
~~~

