# SP1 extractor

SP1 turns one Vietnamese activity announcement (a Facebook post, a notice on a school site) into
**extraction drafts**: the activity fields the post states, plus metadata showing where each value
came from and what still needs a human.

Principle: SP1 only transcribes what the post states. The model (or the regex baseline) only proposes
values and points at evidence. Deterministic code checks every value. When it is unsure it sets null
and adds a flag. Every value it derives instead of reading is recorded in `meta`.

Contract: [`schemas/extraction_draft.schema.json`](../schemas/extraction_draft.schema.json) (1.3.0).
Decisions: [`docs/adr/0001-sp1-extraction-contract.md`](adr/0001-sp1-extraction-contract.md).
Code: `src/sp1/` (`extractor.py` checks and assembles, `regex_baseline.py` regex extraction and the
shared keyword lists, `dates.py` date parsing, `llm_backend.py` prompt and reply parsing, `evaluate.py`
scoring against gold labels).

## Input

The collector's posts file: a JSON array of posts.

| key | required | meaning |
|---|---|---|
| `post_id` | yes | non-empty string |
| `url` | yes | the post URL (http/https), becomes `source.URL_post` |
| `share_url` | no | collector's original sharing link; accepted but not used for extraction, output source or IDs |
| `raw_content` | yes | the post text, at most 20 000 characters |
| `publisher` | yes | page or unit that posted it |
| `platform` | yes | e.g. `facebook` |
| `date_posted` | no | `YYYY-MM-DD` or an ISO datetime (only the date part is used), used only to fill a missing year (see date rules) |

Any other key is an input error. All posts are assumed to contain the real post text.
`extract(text, source)` can also be called directly, with `source = {publisher, platform, URL_post}`.

## Output

`extract()` returns a list of drafts (one per activity found; the regex path always returns one).
`extract_post()` returns `{post_id, drafts}`. `run_posts()` and the CLI turn a bad post into
`{post_id, index, error}` and carry on with the rest.

Each draft is `{record, meta}`:

- `record`: the 15 activity fields. `activity_id` is temporary (`TMP-<8 hex of sha1(URL_post)>-<nn>`).
  `source` holds `publisher`, `platform`, `URL_post` and `URL_registration`.
- `meta` (set by code only):
  - `status`: `valid` (no flags), `partial` (only `needs_review:*` flags) or `failed` (any other flag).
  - `flags`: what went wrong (see the table below).
  - `evidence`: field -> span copied from the post.
  - `time_defaults`: which datetimes got a default time.
  - `year_from_posted`: which datetimes took their year from `date_posted`.
  - `derived`: what the mode/location reconciliation set (`mode`: `venue_physical` | `venue_platform` |
    `meeting_link`; `location`: `cleared_for_online`).
  - `method` (`regex` | `llm`), `model`, `fallback_from` (`llm:parse_error` | `llm:client_error`),
    `draft_schema_version`.

Routing: `valid` drafts go to the deduplicator and then `activities.json`, where the deduplicator
assigns `ACT###`. `partial` and `failed` drafts go to `review_queue.json`.

Flags:

| flag | meaning |
|---|---|
| `needs_review:<field>` | `title` or `mode` is null (always flagged); `completion_requirements` is null for an activity that is online and has `drl_recognized` true (only then, D16) |
| `ungrounded:<field>` | the evidence is missing or not in the post, or it does not state the value |
| `invalid_value:<field>` | wrong type or enum value, unparseable date, or a value that is not a link |
| `out_of_range:<field>` | points not in (0, 100], fee not in [0, 10 000 000], year not in 2020–2035 |
| `end_before_start` | end is not after start |
| `injection_suspected` | the post contains prompt-injection phrases or the prompt delimiter |

## How every value is checked

Every LLM value goes through these steps, and so does every regex value:

1. **Type / enum check.** On failure the value is null and the field gets `invalid_value`.
2. **Grounding.** Each evidence span must occur in the post, after NFC, whitespace folding and
   casefolding. Text fields must also have their value in the post.
   - On failure the field gets `ungrounded`, but the value is kept. The draft becomes `failed`, so a
     person sees it.
3. **Evidence states the value.** This applies to `drl_recognized`, `mandatory`, `fee` and
   `completion_requirements`. The evidence must contain the phrase that states the value.
   - On failure the value is set to null, its evidence is removed, and the field gets `ungrounded`.
4. **Range checks.**
5. **Mode/location reconciliation.**

## Field rules

The regex column describes `regex_baseline.py`. The checks column applies to both paths.

| field | how the regex finds it | checks | null when | flags |
|---|---|---|---|---|
| `URL_registration` | Candidates: a URL on a line with a registration word (đăng ký, form, biểu mẫu, register/registration) or a participation phrase (link tham gia, đường dẫn tham gia, đường dẫn dự thi, link dự thi, link zoom, link meet), or alone on the next line; also any Zoom / Google Meet / Teams link. Facebook links are removed. If nothing is left: the post's only form link (forms.gle, Google Forms, Microsoft Forms). Links that differ only by scheme count as one; the form with the scheme is kept. | LLM value must look like a link and not be a Facebook link; must match exactly one URL in the post (case-insensitive, without scheme). The stored value is copied from the post, `https://` added if missing. | no candidate; two or more distinct candidates; an online post without a link (no flag) | `invalid_value`, `ungrounded` (LLM) |
| `title` | first line without leading emoji and `[TAG]`s | grounding; value in the post | not found | `needs_review:title` |
| `domain` | first keyword list that matches, in order: volunteer, career, skills, culture_sports, academic (never `other`) | enum | no keyword | `invalid_value` |
| `start`, `end` | **1.** The span after a `Thời gian:` / `Thời điểm:` / `Ngày giờ:` label. **2.** Otherwise every dated line, except registration lines (deadline, registration window). A date inside a link, money or a score ratio does not count. One line → that line. Several lines → one activity in rounds (D16), see the date rules. | span grounded; parsed by `dates.py`; year 2020–2035 | no span; parse error | `ungrounded:start`, `invalid_value:start`, `out_of_range`, `end_before_start` |
| `registration_deadline` | **1.** A registration-window line (`Thời gian mở đơn:`, `Thời gian nhận đơn:`, `Thời gian đăng ký:`, `Thời hạn đăng ký:`) with "từ X đến Y" → Y. **2.** Otherwise the text from hạn (chót) đăng ký / thời hạn đăng ký / đăng ký trước / deadline to the end of the line, if it contains a date → the last date/time in it. | as above; 23:59 if no time, traced | no such line | `ungrounded`, `invalid_value`, `out_of_range` |
| `mode` | **1.** the `Hình thức:` line: the hybrid phrase, an online signal or "trực tiếp". **2.** Otherwise the whole post: the hybrid phrase; online signals (trực tuyến, online, "qua <platform>") that are not near a registration word; offline signals (offline, tổ chức / tham gia / tham dự / diễn ra / học trực tiếp). A bare platform name, a venue, a link and "livestream" are not signals. | enum; then reconciliation | no signal, both kinds of signal, or a conflict found by reconciliation | `needs_review:mode` |
| `location` | **1.** A `Địa điểm:`, `Địa điểm tổ chức:`, `Nơi tổ chức:`, `Tại:` or `Địa chỉ:` label at the start of a line. **2.** Otherwise the first "tại <venue>" where the venue starts with a physical-venue word (D15). The venue runs to the end of the line, or to a sentence-ending "." (a dot inside a number such as "1.1" does not end it). Lines with a hashtag or a Facebook link are skipped. | grounding; value in the post; then reconciliation | none found; mode is online | `ungrounded` |
| `points` | number + điểm rèn luyện / RL / ĐRL, not after "tối đa", "đến", "từ" or "x-" | number in (0, 100]; the evidence must contain the number | no exact number (expected null: posts do not state points) | `invalid_value`, `out_of_range`, `ungrounded` (value kept) |
| `drl_recognized` | **Recognition phrase:** (a) "ghi nhận" + only the filler words tham gia / là / vào / cho / thêm / 01 / 1 / một + an object (hoạt động / điểm rèn luyện / rèn luyện / điểm RL / ĐRL); (b) cộng / tính / quy đổi + optional vào / thêm + optional number + optional "điểm" + rèn luyện / RL / ĐRL; (c) tích luỹ / tích lũy / tích luy + hoạt động. **Negative phrase:** "không (được)" + a recognition phrase. A recognition phrase that is not negated → true. Otherwise a negative phrase → false. | true needs a non-negated recognition phrase in the evidence; false needs a negative phrase | no phrase; evidence does not state it | `ungrounded` (value null) |
| `mandatory` | Works per clause (split on `. ; ! ?` and new lines). **True:** a clause with "bắt buộc" not preceded by "không" and a participation word (tham gia, tham dự, hoàn thành, thực hiện, sinh viên). True wins over a negative clause. **Otherwise false:** "không bắt buộc". | true needs "bắt buộc" not preceded by "không" in the evidence; false needs "không bắt buộc" | not stated (no flag, D10) | `ungrounded` (value null) |
| `audience` | `Đối tượng (tham gia / tham dự):` label → a one-item list | grounding; values in the post | no label | `invalid_value`, `ungrounded` |
| `fee` | **0:** miễn phí / không thu phí / không mất phí / free. **Amount:** lệ phí / chi phí / phí + amount (k / nghìn / ngàn × 1000). A range, or both free and paid → null. | in [0, 10 000 000]. 0 needs a "free" phrase in the evidence. > 0 needs the amount written in the evidence (500000, 500.000, 500,000, 500k, 500 nghìn / ngàn). | not stated (no flag, D10); null means unknown, not free | `out_of_range`, `ungrounded` (value null) |
| `completion_requirements` | **Display information for students; SP2 does not parse it (D16).** It takes the first sentence with a completion keyword that also has a recognition phrase, otherwise the first sentence with a completion keyword. "làm bài" alone does not count. Completion keywords:<br>• điểm danh, check-in / check-out, (nộp) minh chứng, quiz, trả lời câu hỏi, tham gia / tham dự đầy đủ, hoàn thành bài thi / khảo sát / form / bài<br>• a score ratio: đạt / trả lời đúng / làm đúng / đúng (+ từ / tối thiểu / ít nhất) N/M câu / câu hỏi / điểm<br>• a percentage: đạt / hoàn thành / đúng (+ từ / tối thiểu / ít nhất / trên) N%<br>• a score: đạt / từ / tối thiểu N điểm (trở lên), only in a sentence with bài thi / câu / trắc nghiệm / điểm thi | grounding; value in the post; the evidence must contain a completion keyword (same list) | no keyword | `needs_review:completion_requirements` only when online and `drl_recognized` true; `ungrounded` (value null) |

### Mode / location reconciliation (D13)

This runs on both paths, after every field is checked. `kind` is the kind of venue in the accepted
location:
- `physical`: phòng, giảng đường, hội trường, cơ sở, sảnh, sân, nhà thi đấu, thư viện, tòa nhà,
  khu, nhà văn hoá.
- `platform`: zoom, google meet, meet, ms teams, microsoft teams, moodle.
- `both` or none.

A location that failed grounding counts as none.

| accepted mode | kind / signal | mode | location | meta.derived |
|---|---|---|---|---|
| null | physical | `offline` | kept | `mode: venue_physical` |
| null | platform | `online` | null | `mode: venue_platform`, `location: cleared_for_online` |
| null | no location, a Zoom/Meet/Teams link in the post | `online` | null | `mode: meeting_link` |
| null | both | null (`needs_review:mode`) | kept | |
| `online` | physical or both | null (`needs_review:mode`) | kept | |
| `online` | anything else | `online` | null | `location: cleared_for_online` if there was one |
| `offline` | platform | null (`needs_review:mode`) | kept | |
| `hybrid` | platform | `hybrid` | null | `location: cleared_for_online` |
| other | | unchanged | unchanged | |

When the mode is derived, its evidence is the location evidence or the meeting URL. On a conflict
the mode evidence is removed. Afterwards the code asserts: mode `online` ⇒ location null. The schema
checks the same rule.

## Date and time rules (`dates.py`)

- **Formats:** `dd/mm[/yyyy]`, `dd-mm[-yyyy]`, `dd.mm.yyyy` (only with a year), "ngày 27 tháng 10
  (năm 2026)". Times: 14h00, 14h, 14:00, 8g30, "2 giờ (30 phút)", with sáng / trưa / chiều / tối.
- **Timezone:** every datetime is ISO 8601 with `+07:00`.
- **Date without a time:** start gets 00:00 and end / registration deadline get 23:59, recorded in
  `meta.time_defaults`.
- **End:** set only when the span states a range (two dates or two times). With two dates and one
  time, the time belongs to the start.
- **Missing year, same span:** it is copied from another date in the same span
  ("từ 28/10 đến 30/10/2026"). If it comes from a later date and would put the earlier date after
  it, the earlier date gets the previous year ("từ 30/12 đến 02/01/2027" → 30/12/2026).
- **No year anywhere in the span:** the year comes from `date_posted`. It is the posted year, or the
  next year if the date would fall more than 60 days before the post. This is recorded in
  `meta.year_from_posted`. Without `date_posted` the field gets `invalid_value`.
- **Not dates (D15):** some number groups look like dates but are not, and are ignored when choosing
  the time line and when parsing:
  - money: thousand separators ("3.000.000", "500,000"), or a number followed by đồng / đ / VNĐ /
    VND / k / nghìn / ngàn;
  - score ratios: N/M followed by câu / câu hỏi / điểm, or preceded by đúng / đạt (optionally + từ /
    tối thiểu / ít nhất). "câu lạc bộ" and "điểm danh" after a date are not scores.
- **Rounds (D16):** a multi-round event is one activity. When there is no labelled time line and
  several dated lines remain (regex path), each line is parsed on its own:
  - start = the chronologically first line;
  - end = the last line: its end time if it states a range, else its time, else its date at 23:59
    (traced);
  - evidence = all those lines.

  Times are never merged across lines, and if any line fails to parse, start gets `invalid_value`.
  On the LLM path a list of time spans is still joined, because the model splits one statement into
  pieces.
- **Registration window (D15):** the end of "từ X đến Y" on a registration-window line is the
  registration deadline. Such a line is never the activity time.

## Running

Tests (they need `pytest` and `jsonschema`):

```
python -m pytest -q tests/sp1
```

CLI (regex path) over a posts file:

```
PYTHONPATH=src python -m sp1.extractor --input data/raw/source.json --output reports/sp1_output.json
```

In PowerShell, set `$env:PYTHONPATH = "src"` first.

LLM path, from a notebook with a GPU (e.g. Kaggle):

```python
from sp1 import llm_backend
from sp1.extractor import extract
client = llm_backend.make_hf_client("<model id>")
drafts = extract(text, source, method="llm", llm_client=client, model_name="<model id>")
```

If the reply is not valid JSON, or the client raises an error, that post falls back to the regex
path. `meta.fallback_from` records this.

## Evaluation

```
PYTHONPATH=src python -m sp1.evaluate --posts data/raw/source.json --gold data/gold/source_gold.json --out reports/sp1_evaluation.md
```

The evaluator runs the regex extractor on the posts file and compares the result with the gold file.
It writes a markdown report and prints the summary. The deliverable needs at least 20 labelled posts;
`schemas/examples/gold_example.json` has 2 (the two posts in `tests/sp1/fixtures/`).
`data/gold/source_gold.json` has the collector's 20 posts labelled by Minh Tri (provenance in
`data/gold/README.md`); results and error analysis: `reports/sp1_test_report.md`.

Gold format: a JSON array, one entry per labelled post.

```json
[{"post_id": "lis-2026", "activities": [{
   "source": {"URL_registration": "https://go.sabies.vn/lis26_dangky"},
   "title": "...", "start": "2026-11-01T00:00:00+07:00", "end": "...", "registration_deadline": "...",
   "mode": "offline", "location": "...", "points": null, "drl_recognized": null, "mandatory": null,
   "audience": ["..."], "fee": null, "completion_requirements": null}]}]
```

- An activity has the record fields except `activity_id`. `source` holds only `URL_registration`.
- `null` = the post does not state it. A field left out = not labelled, and it is not scored (the
  example leaves out `domain`).
- `post_id` must match the posts file. `activities: []` means the post has no activity, so every
  predicted value counts as fabricated.
- Only the first gold activity and the first predicted draft of a post are compared. The report
  counts posts with more than one.

Each labelled field gets one of four outcomes:
- **correct**: equal, or both null;
- **wrong**: both non-null and different;
- **fabricated**: predicted non-null, gold null;
- **missed**: predicted null, gold non-null.

How values are compared:
- datetimes exactly;
- strings after NFC, whitespace collapsing and casefolding (URLs too);
- lists as sets of normalised strings;
- numbers by value; booleans only equal booleans.

The report contains:
- per field: n, the four counts, accuracy (correct / n) and a 95% Wilson interval;
- the status of the first draft of each post;
- every value that is not correct, with its post_id, the predicted value and the gold value.

## Known limitations

- **One activity per post on the regex path.** Posts with several activities are merged or partly
  missed; a multi-round event is one activity by design (D16). The LLM path can return several.
- **The LLM path has not been evaluated yet.** `make_hf_client` has not been run in this repository.
- **Seminar credit is not extracted.** "tích luỹ hoạt động chuyên đề A/B" only sets
  `drl_recognized`; which seminar it counts for is not stored (D12).
- **No campus normalisation.** The location is stored as written ("cơ sở Nguyễn Văn Cừ", "CS1"...).
- **Keyword-based regex.** Wording outside the lists gives null, and the field goes to review.
