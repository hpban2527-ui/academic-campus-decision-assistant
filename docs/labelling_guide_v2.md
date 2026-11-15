# SP1 labelling guide v2

## 1. What to label

Create one record per post. Record the facts stated in the post (layer A). Use `null` for an unstated
single value and `[]` for an empty list. Use the post's `date_posted` only for the missing-year rule in
section 5. Keep the team's defaults for the normaliser (layer B).

## 2. How to label a post

1. Open the source post that matches the template's `post_id`. Work on one post at a time. Fill in
   your initials, the date you labelled it, and the minutes you spent on that post.
2. Label blind. Read the original post and fill in the fields yourself. Keep the extractor and AI
   tools out of labelling. Never ask an AI to label a test post.
3. If a field is doubtful, put its exact key in `unsure` and give a short reason in `notes`. Use
   `null` or `[]` when you cannot support a value. Distinguish an uncertain field from a clearly
   unstated one by using `unsure` only for uncertainty.
4. The second labeller fills in the overlap template independently. Wait until both have finished
   before discussing any overlap post or comparing files.
5. Record each disagreement and its resolution in `data/gold/adjudication_v2.md`, including the
   post ID, field, both values, final decision, and reason. Settle disagreements before measuring.
   After seeing system output, a change to test gold requires a logged `GOLD` error with the same
   details and the evidence supporting the correction.

Keep phone numbers and personal email addresses out of every field, including `notes` and the
adjudication log. Replace an embedded contact in otherwise relevant text with `[contact removed]`.

## 3. File format

Keep the template as a JSON array and keep every key. Set `minutes_spent` to a number when you
finish. Dates and URLs go in quotes. JSON `true`, `false`, and `null` go without quotes. The example
shows the outer structure with a shortened `record`. The template contains all fields in section 4.

```json
[
  {
    "post_id": "<keep the existing ID>",
    "labeller": "AB",
    "labelled_at": "2026-11-13",
    "minutes_spent": 5,
    "record": {"post_type": "activity"},
    "year_inferred": [],
    "unsure": [],
    "notes_codes": [],
    "notes": ""
  }
]
```

Keep a field set to `null` when its value is unstated. The v1 evaluator skips omitted keys as
unlabelled. A blank v2 template is work to complete, and a filled `labeller` and `labelled_at`
record who completed the row and when.

## 4. Record fields

Examples are from the original posts at dev positions 1–16. A position is the row number in
`data/raw/source.json`, counting from 1.

### 4.1 `post_type`

Choose `activity` when the post offers a way to take part, such as registration or exam sign-up,
a link to join the activity, or an explicit statement that participation is recognised. A written
invitation to register can qualify without a link. Use `info_only` for results, summaries or
administrative reminders. Read the body to decide even when the title says “Thông báo”. Use
`insufficient` when the post is cut off or provides too little information to decide. If a post
states that participation is mandatory and gives neither a way to take part nor a recognition cue,
use `activity` and add `"mandatory_no_participation_cue"` to `notes_codes` for review.

**Dev example, position 5.** “Có mặt đúng thời gian đã đăng ký” reminds already registered students
about their appointments. This update is `"info_only"`.

### 4.2 `title`

Copy the official title as a string, including “THÔNG BÁO” or “MỞ FORM” when part of that title.
Remove decoration and hashtags. Exclude a separate banner such as a media-support label. Use
`null` if the name is absent. Some v1 titles dropped “THÔNG BÁO”. Recheck dev titles under v2.

**Dev example, position 10.** `[HẠT NẮNG ĐÊM - MỞ FORM]` gives `"HẠT NẮNG ĐÊM - MỞ FORM"`.

### 4.3 `domain`

Choose one category for the activity's topic: `academic` for subject learning or research,
`volunteer` for community service, `culture_sports` for arts or sport, `skills` for skill-building,
`career` for career development, or `other` for a clear topic outside those categories. Use `null`
when the topic is unclear and mark a doubtful choice in `unsure`. The final convention is pending
with the personalisation owner.

**Dev example, position 12.** “Olympic AI HCMUS 2026” is `"academic"` because the competition is on AI.

### 4.4 `multi_session`

Use `true` for several stated activity sessions or rounds and `false` for a clearly single session
or round. Use `null` when the schedule is too incomplete to decide. Signup, shortlisting and result
announcements are separate milestones. An online window can be one round even if it spans days.

**Dev example, position 2.** “Vòng Sơ khảo” and “Vòng Chung kết” give `true`. The preliminary round
supplies the schedule and venue fields.

### 4.5 `window_open`

Use the start of the first activity session or round. Enter `YYYY-MM-DDTHH:MM+07:00` if the time is
stated, `YYYY-MM-DD` if only the date is stated, and `null` if the start is unstated. Keep registration
dates in their own field. Apply section 5 if the year is missing.

**Dev example, position 2.** “Vòng Sơ khảo: 01/11/2026” gives `"2026-11-01"`.

### 4.6 `window_close`

Use the stated end of the first session or round, including the close of an online participation
window. Use the same date or datetime format as `window_open`. An “end of day” phrase without a
clock time stays date-only. Use `null` when the first session's end is unstated.

**Dev example, position 6.** “đến hết ngày 23/10/2026” gives `"2026-10-23"`.

### 4.7 `duration_minutes_stated`

Enter the stated duration in minutes as an integer. Convert an explicitly stated number of hours
to minutes where applicable. Use `null` if duration is unstated, even if both start and end exist.

**Dev example, position 6.** “40 phút làm bài” gives `40`.

### 4.8 `registration_deadline`

Record the stated last time or date for registering. For a registration window, use its closing
bound. Use the date or datetime format from section 4.5. If the post gives only the event end,
registration start or a capacity cutoff, use `null` for this field.

**Dev example, position 8.** “Thời hạn đóng form: 23h59 ngày 24/09/2026” gives
`"2026-09-24T23:59+07:00"`.

### 4.9 `mode`

Enter `online` or `offline` based on how the first session or round is attended. A stated physical
venue or online participation platform can establish the mode. Use `hybrid` if the student can
choose between the two for that same session. If the mode is unclear or cues conflict, use `null`
and mark conflicting cues in `unsure`.

**Dev example, position 15.** “Trực tuyến trên nền tảng MyAloha” gives `"online"`.

### 4.10 `location`

Copy the physical room, hall or address of the first session or round as a string. Keep the
location wording and put campus coding aside for the normaliser. Use `null` for online sessions
and when no physical venue is stated.

**Dev example, position 2.** “tại cơ sở phường Chợ Quán” gives `"cơ sở phường Chợ Quán"`.

### 4.11 `audience_text`

Copy the eligibility or audience sentence as written in a string, omitting any preceding field
label such as “Đối tượng:”. Use `null` if there is no such sentence.

**Dev example, position 1.** `"Tất cả sinh viên Trường Đại học Khoa học tự nhiên."`

### 4.12 `audience_scope`

Use `{"cohorts": [], "programs": []}` with any stated eligibility restrictions filled in. Write a
cohort as `K24`, `K25`, and so on, including when the post writes “khóa 2025” or “K2025”. Use
`standard` for the standard programme (Chuẩn or đại trà) and `high_quality` for CLC. Keep both
cohort and programme when both restrict participation. “Ưu tiên” is a preference. Leave that
scope list empty if there is no restriction. Use the codes here for the gold template. ADR-0002
illustrates the draft with `CLC`.

**Dev example, position 16.** “Các bạn Tân sinh viên K26 khoa Công nghệ thông tin” gives
`{"cohorts": ["K26"], "programs": []}`. The faculty wording stays in `audience_text`.

### 4.13 `mandatory_stated`

Use `true` when the post says the activity is mandatory or missing it results in a deduction.
Use `false` only for an explicit statement that it is optional, such as “không bắt buộc”. Use
`null` when the post is silent on whether the activity is mandatory.

**Dev example, position 12.** The post invites teams to sign up and gives no obligation or
deduction for missing the activity. Use `null`.

### 4.14 `recognition_stated`

Use `true` only when the post explicitly says that completing the activity counts for recognition
or conduct credit. Use `null` otherwise. Recognition can be conditional. Record the stated
condition in `completion_requirements`.

**Dev example, position 6.** “được ghi nhận tham gia hoạt động” gives `true`.

### 4.15 `points_stated`

Enter a number only when the post says how many conduct points the activity earns. Quiz marks,
recognition without a numeric award, and prize amounts leave this field `null`.

**Dev example, position 15.** “23/30 câu đúng” is a quiz threshold. Use `null` for conduct points.

### 4.16 `fee`

Enter `0` only when the post explicitly says the activity is free. Use `null` if it is silent.
Otherwise enter `{"amount_vnd": 40000, "per": "person", "deposit": false}` with the stated
amount and unit. Choose `person`, `team`, or `unknown` for `per`. Set `deposit` to `true` for a
deposit. Keep a team fee in VND per team. When several amounts are stated, use `null`, copy the
amounts and their purposes into `notes`, and add `"fee"` to `unsure` pending a team decision.

**Dev example, position 10.** “Lệ phí: 40.000 VNĐ/sinh viên” gives
`{"amount_vnd": 40000, "per": "person", "deposit": false}`.

### 4.17 `registration_url`

Copy the URL that the post gives for signing up, as a string. Preserve the link text itself
including its query string. Keep surrounding sentence punctuation outside the URL. A post's own
URL, a read-more link, or the link to take the quiz goes elsewhere. Use `null` if no sign-up URL
is stated. Mark the field in `unsure` when distinct links have the same registration role and the
post gives no way to choose.

**Dev example, position 8.** “Link đăng ký” supplies `"https://forms.gle/8fTaa1qxYzU2BCR47"`.

### 4.18 `join_url`

Copy the URL the student uses to enter the online session or take the quiz. Keep it exactly as
written, without adding a protocol. Use `null` if the post provides only a platform name, a sign-up
link or no join link.

**Dev example, position 6.** “Đường dẫn dự thi” supplies
`"https://courses.hcmus.edu.vn/course/view.php?id=25541"`.

### 4.19 `completion_requirements`

Write one object per stated condition for completing the activity or receiving recognition. Each
object has `type`, `threshold`, `unit` and `deadline`. Choose `check_in`, `check_out`, `quiz`,
`form`, `proof_upload`, `min_duration`, or `other` for `type`. Use a numeric `threshold` and a
string `unit` only when stated (such as `70` and `"percent"`, or `20` and `"of 40 questions"`).
Use the date or datetime format in section 4.5 for an explicit condition deadline. Use `null` for
unstated parts of an object. An event's window and mode alone provide no completion condition.
Use `[]` when the post gives no requirements.

**Dev example, position 6.** “hoàn thành 70% bài thi” gives
`[{"type": "quiz", "threshold": 70, "unit": "percent", "deadline": null}]`.

## 5. Dates and earlier notices

If a date has no year, start with the year of `date_posted`. If that date falls more than 60 days
before the posting date, use the next year. Add the field key to `year_inferred`, for example
`["window_open"]` for position 6, where “08g00 ngày 19/10” gives `"2026-10-19T08:00+07:00"`.
For a deadline inside a completion item, use its path, for example
`"completion_requirements[0].deadline"`. Preserve stated clock times and keep date-only fields
date-only. Flag conflicting dates in `unsure` and explain the conflict in `notes`.

A reference to an earlier announcement, an administrative document, or another event cannot
supply the current activity's date. In position 5, “theo thông báo ngày 24/9/2026” refers to an
earlier notice.

## 6. Fields set by code

Leave `campus`, `drl_recognized`, semester, activity IDs, status and flags to the pipeline. Layer B
also applies team defaults for fee, mandatory status, audience and duration. The gold file keeps
only the layer A fields from section 4 and the labelling metadata from section 3.

## 7. Open questions

- Final domain convention with the personalisation owner.
- Representation of fees when several amounts are stated.
- How hybrid attendance affects completion requirements.
- Final handling of a mandatory post without a participation cue. Use the `notes_codes` procedure
  in section 4.1 until the team settles this. ADR-0002 routes the case to review with
  `drl_recognized = null`.
