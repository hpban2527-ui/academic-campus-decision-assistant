# SP1 extractor: test on the collector's 20 posts

- Owner: Thao Duyen (SP1). Requested by Binh An (integration), 2026-10-26.
- Status: **draft for team review**. Results are measured; the error causes (section 5) and the fix
  proposals (sections 6–7) are one person's analysis and have not been checked by a second person.
- Code: branch `Thao_Duyen`, regex extractor (`method = "regex"`), draft schema 1.3.0. No extractor
  logic was changed for this test. The only code change is that posts may now carry `share_url`.
- Raw evaluator output: [`sp1_evaluation.md`](sp1_evaluation.md). Full extractor output:
  [`sp1_output.json`](sp1_output.json). Sample: [`sp1_sample.json`](sp1_sample.json).
  How to run and integrate: [`docs/sp1_run_guide.md`](../docs/sp1_run_guide.md).

## 1. Summary

1. **Input (task 1): done.** The extractor reads Minh Tri's `source.json` as it is (20 posts, 7 keys
   including `share_url` and `date_posted` with a time). Result: 20 posts, 20 drafts, 0 input errors.
   `share_url` is accepted and ignored; `url` stays the source link and the ID input.
2. **Output by status (n = 20):** 7 `valid`, 10 `partial` (all `needs_review:mode`), 3 `failed`
   (all `invalid_value:start`). Every post gives exactly one draft.
3. **Accuracy against Minh Tri's labels (n = 20, strict match):** between 0.35 (title) and 0.95 (fee)
   on the fields that have values. With n = 20 the 95% intervals are about ±0.2 wide, so the numbers
   show where the extractor is weak, not a precise level. Section 4.
4. **Overall (20 posts × 13 scored fields = 260 values):** 184 match (71%), 76 do not. Fields that
   are null on both sides count as matches, so the stricter figure is: where the post states a value,
   the extractor gets it right in 75/142 (53%). Of the 76 non-matching values, 61 are extractor errors
   (49 rule gaps, 12 from one date bug), 9 are label-convention differences and 6 are doubtful gold
   labels. Most extractor errors leave a field null (42 of the 76 values are `missed`, 9
   `fabricated`), which sends the draft to review instead of passing a wrong value on.
5. **`valid` does not mean correct.** 5 of the 7 `valid` drafts have at least one extractor error.
   One (P08) has wrong `start`/`end` (from a cited earlier notice) and a wrong registration link, with
   no flag. Until the date fix is in, a person should check `valid` drafts before they enter
   `activities.json`. Section 6.
6. **Biggest gaps:** `registration_deadline` (found in 2 of the 12 posts that state one), `mode` and
   `location` for offline events (venue labels the rules do not know), `title` (tag handling),
   `audience`. All have specific, testable fixes (section 7). None is implemented, as agreed.
7. **Data findings for the collector:** 8/20 posts contain shortened links (`https://…/.../…`); all 20
   `url` values carry a `?rdid=` tracking parameter that changes between collections; only 4/20 posts
   state conduct-score recognition. Section 8.

## 2. What was run

| Item | Value |
|---|---|
| Posts | `data/raw/source.json`, byte-identical to `Collecting_Data/source.json` on branch `Minh_Tri` (added in 6ad5170, unchanged up to 2086cb6); 20 Facebook posts, posted 2026-02-23 to 2026-10-24 |
| Gold | `data/gold/source_gold.json` = Minh Tri's `Activities/activities_draft.json` (added in eecfe1e, unchanged up to 2086cb6), converted to the gold format only; no value changed. See `data/gold/README.md` |
| Command | `python -m sp1.extractor --input data/raw/source.json --output reports/sp1_output.json` then `python -m sp1.evaluate --posts data/raw/source.json --gold data/gold/source_gold.json --out reports/sp1_evaluation.md` |
| Unit tests | `python -m pytest -q tests/sp1`: 208 passed |
| Scoring | first draft vs first gold activity per post; text compared after Unicode NFC, whitespace collapse and case folding; datetimes compared exactly; a value counts as `correct`, `wrong`, `fabricated` (gold null, prediction not) or `missed` (gold has a value, prediction null) |

Why Minh Tri's `activities_draft.json` and not `activities.json`: the `activities.json` file fills
`mandatory = false` and `fee = 0` as defaults where the post says nothing (his `_review` notes list
them). The draft file keeps those as null, which matches the agreed rule (null = not stated). The two
files differ only in those defaults and in one `mode` (P06).

## 3. Task 1: reading `source.json` directly

| Check | Result |
|---|---|
| Keys in the file | `post_id, url, raw_content, publisher, platform, date_posted, share_url` |
| `share_url` | optional input key; not used for extraction, `source` or IDs (test: `test_share_url_does_not_change_extraction_or_source`) |
| `date_posted` with a time (`2026-10-24T21:57:41`) | accepted; only the date part is used, to fill a year the text leaves out |
| Whole file through the CLI | 20 posts extracted, 20 drafts, 0 input errors (test: `test_tri_source_file_is_accepted_without_preprocessing`) |
| Unknown keys | still rejected, so a typo in a key name is reported rather than ignored |

## 4. Results

### 4.1 Draft status

| status | posts | meaning for integration |
|---|---|---|
| valid | 7 | no check failed; goes on to dedup and `activities.json` (but see section 6) |
| partial | 10 | only `needs_review:mode`; review queue |
| failed | 3 | `invalid_value:start`: a date was found but could not be parsed; review queue |

`needs_review:mode` on 12/20 posts measures the risk named in ADR 0001 (D2): many drafts wait for a
reviewer because `mode` is not read. In 6 of these 12 the post does state an offline venue that the
rules miss (P02, P11, P12, P13, P14, P17); the other 6 give no place at all, and Minh Tri also labels
their `mode` null.

### 4.2 Field accuracy (n = 20 posts)

Category columns count the non-matching values by cause (section 5). "Gold states a value" shows how
often the extractor found a value that the post does state; it is not inflated by fields that are null
on both sides.

| field | n | correct | accuracy (95% Wilson CI) | gold states a value: found correctly | extractor (EXT) | date bug (DATE) | label convention (CONV) | gold doubtful (GOLD) |
|---|---|---|---|---|---|---|---|---|
| URL_registration | 20 | 16 | 0.80 (0.58–0.92) | 14/16 | 3 | 0 | 1 | 0 |
| title | 20 | 7 | 0.35 (0.18–0.57) | 7/20 | 9 | 0 | 4 | 0 |
| domain | 20 | 10 | 0.50 (0.30–0.70) | 10/20 | 9 | 0 | 1 | 0 |
| start | 20 | 13 | 0.65 (0.43–0.82) | 10/15 | 0 | 6 | 0 | 1 |
| end | 20 | 14 | 0.70 (0.48–0.85) | 8/11 | 0 | 6 | 0 | 0 |
| registration_deadline | 20 | 10 | 0.50 (0.30–0.70) | 2/12 | 10 | 0 | 0 | 0 |
| mode | 20 | 13 | 0.65 (0.43–0.82) | 7/14 | 6 | 0 | 0 | 1 |
| location | 20 | 14 | 0.70 (0.48–0.85) | 6/12 | 4 | 0 | 1 | 1 |
| points | 20 | 20 | 1.00 (0.84–1.00) | – (gold null in all 20) | 0 | 0 | 0 | 0 |
| drl_recognized | 0 | – | not labelled | – | – | – | – | – |
| mandatory | 20 | 20 | 1.00 (0.84–1.00) | – (gold null in all 20) | 0 | 0 | 0 | 0 |
| audience | 20 | 10 | 0.50 (0.30–0.70) | 6/14 | 7 | 0 | 0 | 3 |
| fee | 20 | 19 | 0.95 (0.76–0.99) | 5/6 | 1 | 0 | 0 | 0 |
| completion_requirements | 20 | 18 | 0.90 (0.70–0.97) | 0/2 | 0 | 0 | 2 | 0 |
| **all errors** | | | | | **49** | **12** | **9** | **6** |

How to read this table:

- `points` and `mandatory` score 1.00 only because no post states them and the extractor returns null.
  This shows no invention, not extraction skill.
- `drl_recognized` is not in Minh Tri's labels, so it is not scored. The extractor marks 4 posts
  `true` (P01, P09, P10, P19), each with the sentence "được ghi nhận tham gia hoạt động" as
  evidence, and 16 null. These 4 need Minh Tri's label before any accuracy is claimed.
- `completion_requirements`: both non-null gold values (P09, P19) differ from the prediction only
  in length (full sentence vs short phrase, CONV). The 18 nulls match.
- With one labeller there is no inter-labeller agreement figure yet.

## 5. Why values do not match

Every one of the 76 non-matching values was read against the post text and given one cause:

| Category | Meaning | Count |
|---|---|---|
| EXT | extractor rule gap: the post states the value in a way the rules do not read, or a rule reads the wrong text | 49 |
| DATE | the date-gathering bug in section 6 | 12 |
| CONV | both values are defensible; the team has not fixed a labelling convention yet | 9 |
| GOLD | the gold value is not supported by the collected text or adds an inference | 6 |

The causes, grouped (EXT and DATE only):

| Cause | Errors | Posts |
|---|---|---|
| Dates taken from citation lines, registration lines, head-counts or addresses (DATE) | 12 | P04, P06, P08, P13, P17, P19 |
| Deadline phrasings not read: "đóng form", "Thời gian đăng ký từ … đến hết", "đến hết ngày" without "từ", "A - B" ranges, "Đăng ký tham dự: đến …", round lines | 10 | P01, P04, P05, P11, P12, P13, P14, P15, P17, P20 |
| Title: a leading `[tag]` is cut and leaves "- …"; a tag-only first line is dropped and body text is taken; a section header taken as title | 9 | P02, P04, P05, P07, P11, P13, P15, P18, P20 |
| Domain: keyword rules (no keyword, wrong keyword, never `other`) | 9 | P01, P02, P03, P05, P06, P08, P14, P18, P19 |
| Mode/location: venue labels not known ("Địa điểm tập trung / sân bóng / phát / nấu"), venues not in the keyword list ("Lớp học tình thương", "Trường Tiểu học"), "thi trực tiếp" | 10 | P02, P11, P12, P13, P14, P17 |
| Audience: head-count taken as audience ("40 sinh viên"); labels "Đối tượng đăng ký / dự thi"; unlabelled audience sentences | 7 | P07, P09, P11, P13, P14, P17, P19 |
| Registration link: a "check your registered time here" link taken as registration; links without a registration word missed | 3 | P08, P15, P20 |
| Fee: "Lệ phí thi đấu: 500.000đ/đội" not read | 1 | P14 |

CONV items (to settle in the labelling guide, section 10): title subtitle / "THÔNG BÁO" prefix /
quote characters (P03, P10, P14, P19); verbatim sentence vs short phrase for
`completion_requirements` (P09, P19); multi-round location (P03); "Link tham gia" as registration link
(P19, team rule says yes, gold says null); domain `skills` vs `other` (P09).

GOLD items (for Minh Tri to confirm): P07 `mode`/`location` rely on a sentence that is cut off in the
collected text ("Top 10 …"); P16 `start` 12:00 from "Trưa" (the contract sets 00:00 with a trace for
a date without a time); P18 `audience` inferred from "tân binh"; P04/P05 `audience` paraphrased
instead of copied.

Every value is listed in Appendix B.

## 6. Known bug: dates gathered from the wrong lines (not fixed)

As agreed, the extractor was not changed. This section records the bug and the proposed fix.

**What happens.** When a post has no line labelled exactly "Thời gian:" (or "Thời gian tổ chức /
diễn ra / thực hiện / bắt đầu:"), the regex treats every other line containing a date as one round of
a multi-round activity and takes the first date as `start` and the last as `end`.

| Post | Lines gathered | Result | Status |
|---|---|---|---|
| P06 | "Căn cứ Nghị quyết … ngày 09 tháng 9 năm 2025", "Căn cứ Kế hoạch … ngày 04/9/2026" | start 2025-09-09, end 2026-09-04 (gold: null) | partial (flag is for `mode` only) |
| P08 | "(theo thông báo ngày 24/9/2026) … ngày 26/10/2026" | start 2026-09-24, end 2026-10-26 (gold: null) | **valid, no flag** |
| P17 | "Đăng ký tham dự: đến 23g59, Chủ nhật 04/10/2026" … contest day | start = registration deadline, end = contest day (gold: start = contest day) | partial (flag is for `mode` only) |
| P04 | "nhiệm kì 2025 - 2026", "dài từ 2-8 trang" | could not parse | failed (`invalid_value:start`) |
| P13 | "30 - 35 sinh viên", address "14/1 Ngô Quyền" (label "Thời gian hoạt động" not known) | could not parse | failed |
| P19 | anniversaries "19/5/1890 – 19/5/2026" (label "Thời gian tham gia" not known) | could not parse | failed |

The three `failed` cases are safe: they go to review. The three others pass wrong dates on, and P08 is
marked `valid`.

**Proposed fix** (to implement and test after this report, as a separate pull request):

1. Accept more time labels: "Thời gian hoạt động / tham gia / thi đấu / thi / tập trung:". Exclude
   labels that are not the activity time: "Thời gian đăng ký / mở đơn / đóng form / làm bài / nộp".
2. Without a time label, gather only lines that start with a round word (Vòng, Đợt, Sơ khảo,
   Bán kết, Chung kết, Tuần). Never gather lines that start with "Căn cứ", contain "theo thông báo
   ngày" or "(Nghị quyết | Kế hoạch | Quyết định | Thông báo) số", or are registration lines
   ("Đăng ký … đến …", "đóng form", "nộp").
3. Before looking for dates, mask number patterns that are not dates: head-counts
   ("30 - 35 sinh viên / đội / người"), school-year and term ranges ("2025 - 2026"), house numbers
   after an address label ("14/1 Ngô Quyền").
4. Safety net: if `start` or `end` comes from unlabelled lines, add `needs_review:start`, so such a
   draft can never be `valid`. Also flag a draft whose `end` is before the posting date (P06).

Each of the 6 posts becomes a regression test (expected values from the gold). Rule 4 alone would
have kept P08 out of `valid`.

## 7. Other proposed fixes (not implemented)

Ordered by the number of errors on these 20 posts they address. These counts are what the fixes are
aimed at, not a measured improvement: a fix is only counted once it is re-measured (section 11).

| # | Fix | Errors aimed at | Needs team agreement? |
|---|---|---|---|
| F1 | Date gathering (section 6) | 12 | no |
| F2 | Deadline phrasings: "đóng form/đơn", "Thời gian đăng ký (từ …) đến (hết) …" with or without a colon, "đến hết ngày …", "A - B" ranges, "Đăng ký …: đến …" | 8 (+2 on round lines, which need a decision) | no |
| F3 | Title: keep the text of a tag-only first line; never start a title with "- " after cutting a tag; skip short all-caps header lines such as "HỖ TRỢ TRUYỀN THÔNG" | 9 | title convention (Q1) |
| F4 | Venue labels "Địa điểm <word>:" and the phrase "thi trực tiếp"; decide whether any labelled place that is a street address means offline | 10 | yes, the offline rule (Q7) |
| F5 | Audience labels "Đối tượng đăng ký / dự thi"; reject a value that is only a head-count | 4 (3 more need unlabelled-sentence handling) | no |
| F6 | Registration link: ignore links in sentences about checking an existing registration ("đã đăng ký … tại đây") | 1 | no |
| F7 | Fee label "Lệ phí thi đấu" | 1 | fee per team (Q5) |
| — | Domain: keyword rules stay weak; leave to the LLM path | 9 | domain guide (Q8) |

## 8. Data findings for the collector (Minh Tri)

| # | Finding | Effect | Suggestion |
|---|---|---|---|
| D1 | 8/20 posts contain shortened links as shown by Facebook (`https://ctsv.hcmus.edu.vn/.../...`); P01, P04, P05, P06, P08, P09, P16, P17 | a shortened link is not usable; one reached the output (P08 `URL_registration`) | collect the link target (`href`), not the visible text |
| D2 | P07 text stops mid-sentence ("Chương trình diễn ra online. Top 10 …") | gold used information not in the collected text | check the "See more" expansion for this post |
| D3 | all 20 `url` values end in `?rdid=…` | the temporary activity ID is a hash of `url`, so it changes if the same post is collected again | remove tracking parameters when collecting (or agree that SP1 removes them) |
| D4 | duplicates: P04/P05 (same recruitment), P15/P20 (mirror post; deadline 24/09 vs 25/09, fee stated only in P20) | needs dedup; the two sources disagree | dedup step (Minh Tri) keeps both sources and flags the conflict |
| D5 | only 4/20 posts state conduct-score recognition; no post states "bắt buộc"; P06/P08 are health-check notices, P04 is mostly a CV-tips post | few records will help the conduct-score planner (SP2/SP3) | collect mainly from units that post recognised activities (e.g. the student affairs office); agree whether non-activity posts are kept |
| D6 | P04 includes a student's name and self-introduction | personal data in the stored text | check against the privacy rule for collected text |
| D7 | 9/20 `date_posted` values are exactly `T00:00:00` | the time is probably not real; only the date is used, so no effect on SP1 | note in the data description |

## 9. Integration notes

- **Use the output by status.** `valid` drafts go to dedup, `partial` and `failed` to the review queue.
  Because of P08, a person should check `valid` drafts before they enter `activities.json` until F1
  is merged and re-measured. `docs/sp1_run_guide.md` has the code.
- **Record format is 15 fields.** Drafts carry `drl_recognized` (agreed 2026-10-24). Minh Tri's
  `activities.json` has 14 fields, so `schemas/activity.schema.json` (Binh An) and the labels
  (Minh Tri) need `drl_recognized`; SP2 must read null `mandatory` and `fee` as "not stated".
- **One code source.** Branch `Minh_Tien` has a copy of `src/sp1` from before `share_url` support;
  after merge, `src/api/server.py` should import SP1 from the main branch instead of a copy.
- **IDs are temporary.** `activity_id` is `TMP-<hash of url>-01`; the final `ACT###` comes from dedup.
  See D3 for why the hash is not yet stable.

## 10. Open questions (who decides)

| # | Question | Who |
|---|---|---|
| Q1 | Title: keep a leading `[tag]`? keep a second-line subtitle? keep "THÔNG BÁO"? copy quote characters as written? | Thao Duyen + Minh Tri (labelling guide) |
| Q2 | `completion_requirements`: verbatim sentence (current) or short phrase? Gold should be a span of the text so the grounding check applies | Thao Duyen + Minh Tri |
| Q3 | Multi-round post: one location (first round) or all rounds joined? | Thao Duyen + Minh Tri; SP3 owner for what the planner needs |
| Q4 | "Link tham gia" counts as `URL_registration` (current team rule): Minh Tri's labels should follow it | Minh Tri |
| Q5 | Fee stated per team ("500.000đ/đội"): record as is, divide, or add a unit field? | Binh An (schema), Nhu Ngoc (rules) |
| Q6 | Date with "Trưa / sáng / tối" and no clock time: keep 00:00 + trace (D4) or map to a fixed hour? | team |
| Q7 | Does a labelled street address or named place mean `mode = offline`? | team (extends rule R-mode) |
| Q8 | Domain guide, including when to use `other` | team |
| Q9 | `drl_recognized` labels for these 20 posts | Minh Tri |
| Q10 | Keep or drop posts that announce no activity (P06, P08, P04)? | team |

## 11. Limitations

- n = 20 posts from 7 publishers, one labeller, regex path only. The intervals are wide; no claim
  beyond these posts.
- Only the first activity per post is compared; the regex returns one activity per post.
- The error causes were assigned by Thao Duyen with AI assistance after reading each post; a second
  person has not checked them.
- These 20 posts have now been read while analysing errors, so they become the **development set**.
  For the before/after improvement cycle (R8), the fixes must be measured on a new set of posts
  labelled and frozen before the fixes are written.
- The LLM path has not been run on these posts.

## 12. Reproduce

```bash
pip install -r requirements.txt
python -m pytest -q tests/sp1
PYTHONPATH=src python -m sp1.extractor --input data/raw/source.json --output reports/sp1_output.json
PYTHONPATH=src python -m sp1.evaluate --posts data/raw/source.json --gold data/gold/source_gold.json --out reports/sp1_evaluation.md
```

PowerShell: run `$env:PYTHONPATH = "src"` once, then the same commands without the prefix.

## Appendix A. Posts

Post numbers P01–P20 follow the order in `source.json`. Errors are counted as EXT/DATE/CONV/GOLD.

| post | post_id | publisher | status | flags | errors (EXT/DATE/CONV/GOLD) |
|---|---|---|---|---|---|
| P01 | `pfbid02buJY8Rrn2…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | valid | – | 2/0/0/0 |
| P02 | `pfbid02EJmkk2oaZ…` | Đoàn khoa - Liên chi Hội CNTT KHTN | partial | needs_review:mode | 4/0/0/0 |
| P03 | `pfbid0ouxPwhrPNL…` | SAB in HCMUS | valid | – | 1/0/2/0 |
| P04 | `pfbid0dmRU1XavPQ…` | Google Developer Group on Campus - HCMUS | failed | invalid_value:start, needs_review:mode | 2/2/0/1 |
| P05 | `pfbid02o8CK5Ziex…` | Google Developer Group on Campus - HCMUS | partial | needs_review:mode | 3/0/0/1 |
| P06 | `pfbid02kVX7vEbj6…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | partial | needs_review:mode | 1/2/0/0 |
| P07 | `pfbid0p8jUJBWv9d…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | valid | – | 2/0/0/2 |
| P08 | `pfbid02fsjfr4MEt…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | valid | – | 2/2/0/0 |
| P09 | `pfbid0DeYsfZBiuF…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | valid | – | 1/0/2/0 |
| P10 | `pfbid033dzDjjDUp…` | Phòng Công tác Sinh viên - Trường Đại học Khoa học Tự nhiên | valid | – | 0/0/1/0 |
| P11 | `pfbid0yi4qHyyzkS…` | Đội Sinh Viên Tình Nguyện - Khoa Toán Tin Học | partial | needs_review:mode | 4/0/0/0 |
| P12 | `pfbid02gENqCMzeM…` | Đội Sinh Viên Tình Nguyện - Khoa Toán Tin Học | partial | needs_review:mode | 2/0/0/0 |
| P13 | `pfbid0FhhUJfbqkR…` | Đội Sinh Viên Tình Nguyện - Khoa Toán Tin Học | failed | invalid_value:start, needs_review:mode | 5/2/0/0 |
| P14 | `pfbid02YD2tW2i4Q…` | SAB in HCMUS | partial | needs_review:mode | 6/0/1/0 |
| P15 | `pfbid026SJmz8cRX…` | FIT HCMUS Kênh Hoạt động | partial | needs_review:mode | 3/0/0/0 |
| P16 | `pfbid034Pftro7LA…` | FIT HCMUS Kênh Hoạt động | valid | – | 0/0/0/1 |
| P17 | `pfbid0KfFuXSR1Ly…` | FIT HCMUS Kênh Hoạt động | partial | needs_review:mode | 4/2/0/0 |
| P18 | `pfbid02buju6UWya…` | Đoàn khoa - Liên chi Hội CNTT KHTN | partial | needs_review:mode | 2/0/0/1 |
| P19 | `pfbid0XY9yh6vTLi…` | Đoàn khoa - Liên chi Hội CNTT KHTN | failed | invalid_value:start | 2/2/3/0 |
| P20 | `pfbid02ATDhaQW22…` | Design ITUS | partial | needs_review:mode | 3/0/0/0 |

## Appendix B. Every non-matching value

Long values are shortened with "…"; the full values are in `sp1_evaluation.md`.

| post | field | outcome | category | cause | predicted | gold |
|---|---|---|---|---|---|---|
| P01 | domain | wrong | EXT | keyword "thực tập" (fire drill) read as career | "career" | "skills" |
| P01 | registration_deadline | missed | EXT | "Thời gian đăng ký từ … đến hết ngày 28/10/2026" (no colon) not read | null | "2026-10-28T23:59:00+07:00" |
| P02 | title | wrong | EXT | leading [tag] stripped, leaves "- …" | "- KEY ƠI, ĐỪNG QUÊN CÓ HẸN VỚI VÒNG 4 - ALT!" | "[BẢN LĨNH IT 2026] - KEY ƠI, ĐỪNG QUÊN CÓ HẸN VỚI VÒNG 4 - ALT!" |
| P02 | domain | missed | EXT | no domain keyword | null | "skills" |
| P02 | mode | missed | EXT | label "Địa điểm tập trung" / venue "Vườn điều" not recognised | null | "offline" |
| P02 | location | missed | EXT | label "Địa điểm tập trung" not recognised | null | "Vườn điều, Cơ sở phường Đông Hòa, Trường Đại học Khoa học tự nhiên…" |
| P03 | title | wrong | CONV | subtitle on the second line: keep or drop | "LET IT SHINE 2026" | "LET IT SHINE 2026 - KHÚC KHẢI HOÀN MÙA ĐÔNG" |
| P03 | domain | missed | EXT | no domain keyword (music contest) | null | "culture_sports" |
| P03 | location | wrong | CONV | multi-round post: first venue vs all rounds joined | "cơ sở phường Chợ Quán" | "Vòng Sơ khảo: cơ sở phường Chợ Quán; Vòng Chung kết: Giảng đường 1…" |
| P04 | title | wrong | EXT | tag-only first line dropped; first body sentence taken | "Nhà G có gì hot? TIPS & Tricks đã trở lại với những nội dung bất b…" | "[GDGoC-HCMUS TIPS & TRICKS]" |
| P04 | start | missed | DATE | no "Thời gian:" label; fallback gathered "2025 - 2026", "2-8 trang" → invalid_value | null | "2026-10-03T00:00:00+07:00" |
| P04 | end | missed | DATE | same as start | null | "2026-10-25T23:59:00+07:00" |
| P04 | registration_deadline | missed | EXT | round line "Application (từ 3/10 đến 10/10)" not read as deadline | null | "2026-10-10T23:59:00+07:00" |
| P04 | audience | wrong | GOLD | gold paraphrases the line; prediction copies it verbatim | ["TẤT CẢ SINH VIÊN của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, …" | ["Tất cả sinh viên của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, …" |
| P05 | title | wrong | EXT | tag-only first line dropped; first body sentence taken | "Mỗi mảnh ghép đều mang một màu sắc và dấu ấn riêng, cùng nhau tạo …" | "[GDGoC-HCMUS RECRUITMENT 2026]" |
| P05 | domain | missed | EXT | no domain keyword (recruitment) | null | "career" |
| P05 | registration_deadline | missed | EXT | round line "Application (từ 3/10 đến 10/10)" not read as deadline | null | "2026-10-10T23:59:00+07:00" |
| P05 | audience | wrong | GOLD | gold paraphrases the line; prediction copies it verbatim | ["TẤT CẢ SINH VIÊN của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, …" | ["Tất cả sinh viên của trường Đại học Khoa học tự nhiên, ĐHQG-HCM, …" |
| P06 | domain | missed | EXT | regex never returns "other" | null | "other" |
| P06 | start | fabricated | DATE | citation "Căn cứ Nghị quyết … ngày 09 tháng 9 năm 2025" taken as activity time | "2025-09-09T00:00:00+07:00" | null |
| P06 | end | fabricated | DATE | citation "Kế hoạch … ngày 04/9/2026" taken as activity time | "2026-09-04T23:59:00+07:00" | null |
| P07 | title | wrong | EXT | first line is a section header ("HỖ TRỢ TRUYỀN THÔNG") | "HỖ TRỢ TRUYỀN THÔNG" | "Avalanche Team1 UniHack HCMC 2026" |
| P07 | mode | wrong | GOLD | text says "Địa điểm: Online"; the "pitching trực tiếp" part is cut off in the collected text | "online" | "hybrid" |
| P07 | location | missed | GOLD | same: in-person part is not in the collected text | null | "Online; Vòng Pitching trực tiếp tại TP.HCM" |
| P07 | audience | missed | EXT | unlabelled "dành cho sinh viên trên toàn quốc" | null | ["Sinh viên trên toàn quốc"] |
| P08 | URL_registration | fabricated | EXT | "kiểm tra … đã đăng ký tại đây" link (schedule lookup) taken as registration | "https://datastudio.google.com/.../e586d666.../page/cRFBG" | null |
| P08 | domain | missed | EXT | regex never returns "other" | null | "other" |
| P08 | start | fabricated | DATE | citation "theo thông báo ngày 24/9/2026" taken as activity time; draft is VALID with no flag | "2026-09-24T00:00:00+07:00" | null |
| P08 | end | fabricated | DATE | same: dates from citation lines; draft is VALID with no flag | "2026-10-26T23:59:00+07:00" | null |
| P09 | domain | wrong | CONV | skills vs other: no domain guideline yet | "skills" | "other" |
| P09 | audience | missed | EXT | unlabelled "phát động toàn thể sinh viên" | null | ["Toàn thể sinh viên Trường Đại học Khoa học tự nhiên"] |
| P09 | completion_requirements | wrong | CONV | full sentence copied vs short phrase | "Sinh viên hoàn thành 70% bài thi: được ghi nhận tham gia hoạt động…" | "Hoàn thành 70% bài thi" |
| P10 | title | wrong | CONV | "THÔNG BÁO" prefix kept; gold uses straight quotes not in the text | "THÔNG BÁO Chuyên đề “Sinh viên với kỹ năng tham gia giao thông và …" | "Chuyên đề \"Sinh viên với kỹ năng tham gia giao thông và đảm bảo t…" |
| P11 | title | wrong | EXT | tag-only first line dropped; first body paragraph taken | "Ánh trăng rằm tháng Tám không chỉ mang theo hương vị ngọt ngào của…" | "VƯƠN BƯỚC ĐÊM RẰM - MỞ ĐƠN ĐĂNG KÝ" |
| P11 | registration_deadline | missed | EXT | "Thời hạn đóng form" not a deadline label | null | "2026-09-24T23:59:00+07:00" |
| P11 | mode | missed | EXT | venue "Lớp học tình thương (…)" not in venue keywords | null | "offline" |
| P11 | audience | fabricated | EXT | headcount "40 sinh viên" taken as audience | ["40 sinh viên"] | null |
| P12 | registration_deadline | missed | EXT | "Thời gian đóng form" not a deadline label | null | "2026-05-12T20:00:00+07:00" |
| P12 | mode | missed | EXT | venue "Trường Tiểu học …" not in venue keywords | null | "offline" |
| P13 | title | wrong | EXT | tag-only first line dropped; verse line taken | "Tháng tư lại về … Xuân chưa nỡ rời xa" | "HẠT NẮNG ĐÊM - MỞ FORM" |
| P13 | start | missed | DATE | "Thời gian hoạt động" not a time label; fallback gathered "30 - 35 sinh viên", address "14/1" → invalid_value | null | "2026-04-12T15:00:00+07:00" |
| P13 | end | missed | DATE | same as start | null | "2026-04-12T21:00:00+07:00" |
| P13 | registration_deadline | missed | EXT | "Thời gian đóng form" not a deadline label | null | "2026-04-10T23:00:00+07:00" |
| P13 | mode | missed | EXT | labels "Địa điểm phát / nấu" not recognised | null | "offline" |
| P13 | location | missed | EXT | labels "Địa điểm phát / nấu" not recognised | null | "Địa điểm phát: Các tuyến đường tại Quận 10; Địa điểm nấu: 14/1 Ngô…" |
| P13 | audience | fabricated | EXT | headcount "30 - 35 sinh viên" taken as audience | ["30 - 35 sinh viên"] | null |
| P14 | title | wrong | CONV | subtitle on the second line: keep or drop | "FIT SUPER LEAGUE 2026" | "FIT SUPER LEAGUE 2026 - CHÍNH THỨC MỞ ĐƠN" |
| P14 | domain | wrong | EXT | keyword "kĩ năng" in a football post read as skills | "skills" | "culture_sports" |
| P14 | registration_deadline | missed | EXT | "Thời gian mở đơn: A - B" (dash, no "từ … đến") not read | null | "2026-03-08T23:59:00+07:00" |
| P14 | mode | missed | EXT | label "Địa điểm sân bóng" not recognised | null | "offline" |
| P14 | location | missed | EXT | label "Địa điểm sân bóng" not recognised | null | "Sân bóng đá Phạm Hùng, Hẻm C7D/17e24, Đ. Phạm Hùng, Bình Hưng, Bìn…" |
| P14 | audience | missed | EXT | unlabelled "dành riêng cho các bạn sinh viên khoa CNTT" | null | ["Sinh viên khoa Công nghệ Thông tin"] |
| P14 | fee | missed | EXT | "Lệ phí thi đấu: 500.000đ/đội" not read (also per-team, see open questions) | null | 500000 |
| P15 | URL_registration | missed | EXT | link line has no registration word and the host is not a form host | null | "https://bit.ly/BLIT2026_DangKy" |
| P15 | title | wrong | EXT | leading [tag] stripped, leaves "- …" | "- MỞ FORM ĐĂNG KÝ" | "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ" |
| P15 | registration_deadline | missed | EXT | "Thời gian đăng ký: đến hết ngày …" (no "từ") not read | null | "2026-09-24T23:59:00+07:00" |
| P16 | start | wrong | GOLD | gold sets 12:00 from "Trưa"; contract (D4) is date only → 00:00 with a trace | "2026-10-11T00:00:00+07:00" | "2026-10-11T12:00:00+07:00" |
| P17 | start | wrong | DATE | registration line "Đăng ký tham dự: đến 23g59 … 04/10" gathered as first round | "2026-10-04T23:59:00+07:00" | "2026-10-25T07:30:00+07:00" |
| P17 | end | fabricated | DATE | end taken from the last gathered line (the contest day) | "2026-10-25T07:30:00+07:00" | null |
| P17 | registration_deadline | missed | EXT | "Đăng ký tham dự: đến …" not a deadline label | null | "2026-10-04T23:59:00+07:00" |
| P17 | mode | missed | EXT | "thi trực tiếp tại" not an offline phrase | null | "offline" |
| P17 | location | missed | EXT | unlabelled "tại một trong hai cơ sở"; gold also adds words not in the text | null | "Một trong hai cơ sở của Trường Đại học Khoa học tự nhiên, ĐHQG-HCM…" |
| P17 | audience | missed | EXT | label "Đối tượng đăng ký" not recognised | null | ["Sinh viên Trường Đại học Khoa học tự nhiên, ĐHQG-HCM"] |
| P18 | title | wrong | EXT | leading [tag] stripped, leaves "- …" | "- “+1 MÁY” LÊN KÈO, VÈO VÈO CHẠY TRẠM" | "[ITogether] - \"+1 MÁY\" LÊN KÈO, VÈO VÈO CHẠY TRẠM" |
| P18 | domain | wrong | EXT | keyword "Tình nguyện" from a list of club stations | "volunteer" | "skills" |
| P18 | audience | missed | GOLD | gold infers "Tân sinh viên khoa CNTT" from "tân binh"; not stated | null | ["Tân sinh viên khoa Công nghệ thông tin"] |
| P19 | URL_registration | fabricated | CONV | team rule: "Link tham gia" counts as registration link; gold says null | "https://bit.ly/TheoDauChanNguoi2026" | null |
| P19 | title | wrong | CONV | gold uses straight quotes not in the text | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN “THEO DẤU CHÂN NGƯỜI”" | "CUỘC THI TRẮC NGHIỆM TRỰC TUYẾN \"THEO DẤU CHÂN NGƯỜI\"" |
| P19 | domain | missed | EXT | regex never returns "other" | null | "other" |
| P19 | start | missed | DATE | "Thời gian tham gia" not a time label; fallback gathered 1890/1911/1976 anniversaries → invalid_value | null | "2026-06-05T20:00:00+07:00" |
| P19 | end | missed | DATE | same as start | null | "2026-06-12T23:59:00+07:00" |
| P19 | audience | missed | EXT | label "Đối tượng dự thi" not recognised | null | ["Toàn thể sinh viên Trường Đại học Khoa học tự nhiên, ĐHQG-HCM"] |
| P19 | completion_requirements | wrong | CONV | full sentence (with "Ghi nhận tham gia:" label) vs short phrase | "Ghi nhận tham gia: Sinh viên đạt từ 23/30 câu đúng trở lên được gh…" | "Đạt từ 23/30 câu đúng trở lên" |
| P20 | URL_registration | missed | EXT | link line has no registration word and the host is not a form host | null | "https://bit.ly/BLIT2026_DangKy" |
| P20 | title | wrong | EXT | leading [tag] stripped, leaves "- …" | "- MỞ FORM ĐĂNG KÝ" | "[BẢN LĨNH IT 2026] - MỞ FORM ĐĂNG KÝ" |
| P20 | registration_deadline | missed | EXT | "Thời gian đăng ký: đến hết ngày …" (no "từ") not read | null | "2026-09-25T23:59:00+07:00" |
