# ADR 0001: SP1 extraction contract

- Status: accepted
- Date: 2026-10-25
- Contract: `schemas/extraction_draft.schema.json` 1.3.0
- Details of every field rule: [`docs/sp1_extractor.md`](../sp1_extractor.md)

## Context

SP1 reads Vietnamese activity announcements and produces activity records for the store that the
student assistant answers from. Wrong data costs students time: a wrong place, a missed deadline, a
believed conduct-score credit that does not exist. Posts are informal and inconsistent, and a small
LLM can invent values. So the contract is built for traceability: every value is copied from the
post, checked by code, or explicitly derived and recorded.

## Decisions

- **D1 Output shape.** The extractor returns a list of drafts `{record, meta}`, one per activity.
  `meta` (status, flags, evidence, traces, method) is set by deterministic code only, never by the
  model.
- **D2 Review.** `needs_review` is raised only for `title` and `mode` (always), and for
  `completion_requirements` in the one case given in D16. Status `valid` = no flags. `partial` = only `needs_review` flags. `failed` = any other flag.
  Partial and failed drafts both go to the review queue. Valid drafts go to the deduplicator.
- **D3 Conduct score.** `drl_recognized` is true, false or null.
  - The school confirmed that "ghi nhận (tham gia) hoạt động" means the activity counts for the
    conduct score.
  - Posts never state a number of points. `points` stays in the record and is expected to be null.
- **D4 Date-only times.** A date without a time: start 00:00, end and registration deadline 23:59,
  recorded in `meta.time_defaults`.
- **D5 IDs.** Temporary ID `TMP-<first 8 hex of sha1(URL_post)>-<nn>`. The deduplicator assigns the
  final `ACT###`.
- **D6 Domain.** Enum `academic`, `volunteer`, `culture_sports`, `skills`, `career`, `other`, or null.
- **D7 Demo.** Batch LLM extraction fills the activity store. The regex extractor serves the live
  input box.
- **D8 Datetimes.** ISO 8601 with `+07:00`.
- **D9 Registration link.** SP1 extracts `URL_registration` from the text (it is not input).
  - It is the registration link (offline) or the participation link (online: Zoom/Meet/Teams, online
    test).
  - Noise links are filtered out: read-more, official notice, class lists, hashtags, Facebook.
  - A post has at most one such link. Two distinct candidates → null.
- **D10 Mandatory and fee.** Both are nullable, without flags.
  - `mandatory` is only what the post states. SP2 decides which items are mandatory from the student
    handbook.
  - A null fee means unknown, not free.
- **D11 Posts file and missing year.** SP1 reads the collector's posts file directly.
  - A missing year is taken from `date_posted`: the posted year, or the next year if the date would
    fall more than 60 days before the post. This is recorded in `meta.year_from_posted`.
- **D12 Scope of v1.** Thematic seminars (chuyên đề A/B) are out of v1. Mandatory items in v1 are
  the required surveys from the handbook (team to confirm).
- **D13 Mode and location.** `location` is a physical venue only, and only for offline or hybrid
  activities.
  - A physical venue means in person. An online platform as the venue, or a lone meeting link, means
    online.
  - A stated mode that contradicts the venue → mode null for review.
  - Invariant: online ⇒ location null.
  - Derivations are recorded in `meta.derived`.
  - The full table is in `docs/sp1_extractor.md`.
- **D14 One phrase list per meaning.** `drl_recognized` uses one shared phrase list in the regex
  extractor and in the LLM evidence check.
  - A positive phrase wins over a negated clause ("về sớm sẽ không được ghi nhận" is a completion
    condition).
  - LLM evidence must itself state the recognition, otherwise the value is null.
  - The same pattern applies to `mandatory`, `fee` and `completion_requirements`.
- **D15 Reading real posts: time line, deadline, venue.**
  - Money ("3.000.000 đồng", "500,000", "30k") and score ratios ("20/40 câu", "đạt 8/10") are never
    dates. They are never chosen as the time line, and `dates.py` ignores them.
  - A registration-window line ("Thời gian mở đơn / nhận đơn / đăng ký", "Thời hạn đăng ký" with
    "từ X đến Y") gives the registration deadline Y. It is never the activity time.
  - Without a location label, the first "tại <venue>" whose venue starts with a physical-venue word is
    the location. Hashtag and Facebook-link lines are skipped. The D13 reconciliation then applies.
- **D16 Display-only completion; multi-round events.**
  - `completion_requirements` is display information for students, and SP2 does not parse it.
    `needs_review:completion_requirements` is raised only when mode is online, `drl_recognized` is
    true and the value is null. Online recognised activities always state how to be recognised, so
    there the extractor missed it. Elsewhere a null value gets no flag.
  - A multi-round event is one activity. Without a labelled time line, several dated lines are its
    rounds:
    - start from the chronologically first line alone;
    - end from the last line alone;
    - evidence = all the lines;
    - times are never merged across lines.

## Consequences

- Drafts carry enough evidence for a reviewer to accept or fix a value without rereading the post.
- Being strict costs recall: unusual wording gives null and a review item, never a guess. Review
  volume should be measured in the evaluation.
- The regex baseline returns one activity per post. Multi-activity posts need the LLM path, which
  has not been evaluated yet.
- `record` must stay in sync with `activity.schema.json`, which another team member owns.

## Open questions (for the schema owner)

- Final `activity.schema.json` v1.2.0: 15 fields, `mandatory` and `fee` nullable, online ⇒
  location null.
- The date-only trace (`meta.time_defaults`) is not carried into `activities.json`. Should it be?
- When the same activity is posted twice, the deduplicator keeps only one `source`. Should it keep all?

## Changelog

- **D15, D16 (2026-10-25), no schema shape change, still 1.3.0**
  - Money and score ratios are not dates.
  - The registration window gives the deadline.
  - Inline venue.
  - `needs_review:completion_requirements` is raised only for online recognised activities.
  - Multi-round events.
  - The evaluation script `sp1.evaluate`.
- **1.3.0 (2026-10-25)**
  - Added `meta.derived` and the online ⇒ location null invariant (D13).
  - The registration link now includes participation links, and noise links are filtered (D9).
  - The evidence for `drl_recognized`, `mandatory`, `fee` and `completion_requirements` must state
    the value (D14).
  - New Year ranges ("30/12 đến 02/01/2027").
  - This ADR replaces `docs/adr/0001-sp1-schema-v1-1-and-extraction-draft.md`, which earlier code
    referred to but which is not in this repository.
- **1.2.0 and earlier:** `URL_registration` extracted from the text instead of being input; the
  collector posts file read directly.
