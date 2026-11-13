# ADR 0002: SP1 stated facts vs team defaults, post type, and draft schema 2.0.0

- Status: accepted by Thao Duyen (owner of all language-processing decisions, confirmed 2026-11-13).
  The schema change is not implemented yet.
- Date: 2026-11-13
- Supersedes: part of ADR 0001 (see "Relation to ADR 0001").
- Contract: `schemas/extraction_draft.schema.json` 1.3.0 -> 2.0.0 (breaking), `schemas/activity.schema.json`
  to be updated to match.
- Notified, not approval required: Binh An (integration, server), Nhu Ngoc and Ngoc Tuyen (SP2 input),
  Minh Tien (UI fields and flags), Minh Tri (collector, dedup).
- Source of the business rules: "Bo quy tac xu ly thong tin hoat dong, tong hop den 13/11/2026"
  (team rule set; items still marked open there stay open here).

## Context

The team rule set of 2026-11-13 changes what SP1 must deliver:

- Collected posts now include several semesters, pure information posts and incomplete posts, so
  "every post earns conduct points" no longer holds and `drl_recognized` is kept.
- One post is one activity; for several sessions or rounds, the first one is used.
- The team sets defaults where a post is silent (no fee stated -> free; no mandatory cue -> not
  mandatory; no audience -> all students; offline without an end time -> 2 hours; quiz without a
  duration -> 30 minutes).
- Location needs a campus code (CS1, CS2, Other) next to the detailed address.

The defaults conflict with ADR 0001 D10 and with the gold labels, which keep `null` for "not stated".
If SP1 wrote defaults directly, a silent post and an explicit "mien phi" would look the same, gold
accuracy would rise only because of the defaults, and a later change of convention would require
re-extraction.

Signal counts on the 189 posts in `data/raw/source.json` (keyword matches, not labels; they say which
rules occur often, not which values are correct): "dang ky" 161 (85%), result/summary words 25 (13%),
Nguyen Van Cu / Cho Quan 100 (53%), Linh Trung / Dong Hoa / CS2 47 (25%), cohort codes 21 (11%),
online 16 (8%), "bat buoc" 4 (2%), quiz thresholds 6 (3%).

## Decisions

**D1. Stated facts and team defaults are separated.**
SP1 (layer A) records only what the post states; not stated -> `null` (single value) or `[]` (list).
A deterministic normalizer (layer B) then applies the team defaults and records each one in
`meta.derived` as `{field: rule_id}`, e.g. `{"fee": "team_default:fee_not_stated_free"}`.
Layer C (validator) sets `status` and `flags` as before. Gold labels describe layer A only.

**D2. Post type is classified; `drl_recognized` is derived from it.**
New field `post_type`: `activity | info_only | insufficient`.
- `activity`: the post offers participation in this activity (registration or exam sign-up, a Zoom/Meet
  or quiz link for the activity, or an explicit statement that it is recognised), even without a URL.
- `info_only`: results, summaries, administrative reminders. Decided from the content, never from the
  word "thong bao" in the title alone.
- `insufficient`: the post is cut or lacks the information to decide.
Fixed mapping: `activity -> true`, `info_only -> false`, `insufficient -> null`. `info_only` posts are kept
as sources but not offered as activities. `true` is the team's classification, not a confirmation that
the school granted points.

**D3. Mandatory post without registration or recognition cue (rule set open item 6).**
Until the team settles it: `drl_recognized = null`, flag `needs_review:drl_recognized`, and the post is
always kept, because it carries a mandatory item or a deduction.

**D4. Campus is separate from the detailed location.**
`campus: [ "CS1" | "CS2" | "Other" ]` (list), set by a dictionary in layer B (Nguyen Van Cu -> CS1,
Linh Trung -> CS2, outside the university -> Other; "one of the two campuses, announced later" ->
`["CS1","CS2"]`, meaning possible places, not both). `location` keeps the room, hall or address as written.
Online -> `location = null`, `campus = []`.

**D5. Time is stored as window, duration and its source.**
`window: {open, close}` (ISO 8601, `+07:00`) as stated, for the first session or round;
`duration_minutes`; `duration_source: stated | default_offline_2h | default_quiz_30m | unsupported`.
The slot a student is actually scheduled in belongs to SP3, not SP1. Date-only bounds keep the
ADR 0001 D4 traces (`date_only_0000`, `date_only_2359`); they are normalisation bounds, not event times.
Conflicting dates -> `needs_review`.

**D6. Audience is kept as written, with structured scope.**
`audience_scope: {cohorts: [], programs: []}` (e.g. `{"cohorts": ["K25"], "programs": ["CLC"]}`), plus the
original text. Both cohort and program are kept when the post states both. "Uu tien" is not a
restriction. Empty scope -> all students (layer B default, traced).

**D7. Registration and joining links are separate.**
`registration_url` and `join_url` (Zoom, Meet, quiz). Both optional, both must occur in the post text
(ADR 0001 D9 grounding). The post's own URL stays in `source` and is never used as either.

**D8. Who extracts what.**
- LLM (with evidence span): `post_type`, `title` (official name, prefixes kept), the first session or
  round schedule when the post lists several dates, `domain`.
- Regex or dictionary: campus, cohort and program codes, mandatory cues ("bat buoc", "khong ... bi tru
  diem"), quiz thresholds, fee and deposit amounts (team fee kept as a team fee), URLs.
- Code only: ISO dates, year from posting date, durations, campus codes, all defaults, semester.
The model never computes dates, points, criteria or durations.

**D9. Open rule-set items outside language processing get no new default.**
Items 1, 2, 5, 7, 8 of the rule set (online first-round duration, missing registration deadline,
SP2 mapping, mandatory schedule clash, online completion timing): layer B writes `unsupported` (or
leaves the field null with a flag) and never invents a rule. Item 9 (semester dates) is resolved by D11.

**D10. Contact details (2026-11-14).**
Phone numbers are masked (`[phone removed]`) before text is sent to a model and before it is stored in
the activity store. Email addresses are kept so students can contact the organiser. Measured on the
189 posts: emails appear in 66 posts (26 with `gmail.com`, which may be personal; 26 with `hcmus.edu.vn`).
This is a deliberate choice and is stated in the report under R7.

**D11. Semester assignment (2026-11-14).**
Semesters in v1 (same dates for `standard` and `high_quality` programs), stored in
`data/config/semesters.json`, bounds inclusive, `+07:00`:
- HK3 2025-2026: 2026-05-17 to 2026-08-28 (replaces "HK2 2025-2026" in the rule set)
- HK1 2026-2027: 2026-08-29 to 2026-11-15
An activity is assigned by its own dates (`window_open`), never by the posting date. An activity outside
both semesters gets `out_of_scope_semester`; no date -> `insufficient_data`. 13 of the 189 posts were
posted before 2026-05-17, so some activities are expected to fall outside scope.

**D12. Domain preference (2026-11-14).**
An activity has exactly one `domain` from the 6-value enum (D6 of ADR 0001). A student's preference is
0 to 6 domains and is soft: it only ranks, never excludes. Later, students may type preferences as free
text; an NLP parser maps the text to the enum (out of v1 scope until built).

## Relation to ADR 0001

- D10 (mandatory, fee nullable) still holds for layer A; the team defaults now live in layer B.
- The 9 Nov plan to drop `drl_recognized` is reversed by D2.
- The "several activities per post" part of D1 (one draft per activity) is replaced: one post -> one draft.
- D4, D8, D9, D11 unchanged.

## Consequences

- Breaking change for SP2 and the UI: new fields `post_type`, `campus`, `window`, `duration_*`,
  `audience_scope`, `registration_url`, `join_url`, `meta.derived`. SP2 must read defaults from the
  final record and may show their origin from `meta.derived`.
- The labelling guide must be updated (v2): label stated facts, `post_type`, and the first
  session/round. Existing 20-post gold remains valid for unchanged fields.
- Evaluation reports layer A against gold; layer B is tested with hand-written unit cases, one per rule.
- Risk: rare rules (mandatory, quiz threshold, multi-round) appear in few posts; the test sample must
  include them on purpose or they are not measured.

## Changelog

- 2026-11-14: added D10 (contacts), D11 (semesters, `out_of_scope_semester`), D12 (domain preference).
- 2026-11-13: created.
