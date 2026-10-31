# SP1 – Data QA & Dataset Handoff Report
**Project:** Academic Campus Decision Assistant  
**Sub-project:** SP1 (Data Collection, QA & Handoff)  
**Target Semester:** Semester 3, Academic Year 2025–2026 (**2026-05-18 to 2026-08-17**)  

---

## 1. Executive Summary

This report documents the quality assurance (Data QA) performed on the initial 20 activity records and the dataset augmentation executed to prepare data for **SP2** (DRL Rule Engine) and **SP3** (Decision Assistant).

### Key Outcomes:
1. **Initial Audit (20 Activities):** Completed a QA audit across all 20 records in `activities.json`, recording findings in `QA20.json`.
2. **Extractor Discrepancy Tracking:** Identified extraction issues, cataloged with expected vs. actual values to support parser fixes by the extractor developer (Duyen).
3. **Dataset Augmentation for Semester 3:** The initial 20 posts contained only **1** confirmed Semester 3 activity. To ensure downstream feasibility for SP3, 17 new Semester 3 activity announcements were collected, their link were saved to `urls.txt` and their content were save into `source.json`, bringing the total pool of verified Semester 3 activities to **18**.

---

## 2. QA Schema & Assessment Methodology

To evaluate each announcement without overlapping criteria, the QA review schema (`QA20.json`) separates **extraction data quality** from **downstream SP3 scope eligibility**:

### 2.1 Field Definitions

| Field Name | Data Type | Permitted Values | Purpose & Definition |
| :--- | :--- | :--- | :--- |
| **`activity_id`** | `string` | Activities id in activities.json | Identifies the activity record, matching keys across `activities.json` and `source.json`. |
| **`status`** | `string` | `"complete"`, `"incomplete"` | **Data Quality**: Evaluates whether the extractor captured the post's contents correctly and completely. If fields were omitted or misrepresented, it is marked `"incomplete"`. |
| **`category`** | `string` | `"valid"`, `"out_of_scope"`, `"needs_verification"` | **SP3 Eligibility**: Determines if the activity belongs in Semester 3 and is ready for student planning.<br>• `valid`: Confirmed HK3 activity, verified data, ready for SP3.<br>• `out_of_scope`: Not an activity.<br>• `needs_verification`: Borderline timing or unconfirmed eligibility. |
| **`semester`** | `string` | `"In semester 3"`, `"Not in semester 3"`, `"Unknown"` | **Temporal Classification**: Checks if event dates fall within HK3 (**2026-05-18 to 2026-08-17**). `"Unknown"` is assigned when the raw post contains no specific event dates. |
| **`source_mismatch`** | `boolean` | `true`, `false` | Flags discrepancies between raw text (`source.json`) and parsed output (`activities.json`). |
| **`source_details`** | `object` / `null` | `{ "extracted": "...", "original": "..." }` | Provides concrete before/after evidence for discrepancies to guide extractor bug fixes. |
| **`review`** | `array<string>` | List of field names | Highlights specific fields that are missing, erroneous, or require manual verification. |
| **`notes`** | `string` | Contextual text | Rationale behind classification, dates, and administrative observations. |

---

## 3. Audit of the 20 Initial Activities (`activities.json` & `QA20.json`)

Each activity from `activities.json` was audited against its raw post counterpart. Below is the detailed record mapping with exact line locations.

### 3.1 Mapping & Review Table

| # | Activity ID & File Location | Status | Category | Semester | Key Findings & Notes |
|---|---|:---:|:---:|:---:|---|
| **1** | `activities: pfbid02buJY8Rrn2XezSWbCNxpUnfSHX4yDYWi5EgXbngmL1FKiEE47XQarhqVqb4WjERECl` `[3;23]` | `complete` | `out_of_scope` | `Not in semester 3` | Fire prevention training (PCCC) on **2026-10-30** (Semester 1, 2026–2027). Extracted accurately, but outside HK3. |
| **2** | `activities: pfbid02EJmkk2oaZJuBw5VqRhEUeSUNqVW6dav9qSV4AZsK661vLikur7U4PPBqJcPDBYHzl` `[26;44]` | `incomplete` | `out_of_scope` | `Not in semester 3` | *Bản Lĩnh IT (Round 4)* on **2026-10-17**. Extractor missed target audience `K26`. Outside HK3. |
| **3** | `activities: pfbid0ouxPwhrPNLVJkqySBkTXowuqDC2wkabJwYYuqsGe2qVP3o836nNvFAHHTMW7KJv5l` `[47;67]` | `complete` | `out_of_scope` | `Not in semester 3` | *Let IT Shine 2026* music contest (Nov 2026). Correct extraction, outside HK3. |
| **4** | `activities: pfbid0dmRU1XavPQ3rzXsGMSTaL69GEcdsmKnXeVaWA4LYybFFgsJDfg3qtMetBGfn7zKkl` `[70;90]` | `incomplete` | `out_of_scope` | `Not in semester 3` | Knowledge-sharing blog post (CV/Resume tips) and internal club recruitment. Missing core activity fields; outside HK3. |
| **5** | `activities: pfbid02o8CK5Ziex6z2ZjnEhnv49RyHkZwMxEcLkpF49QmVymQp3N2hghbSAcrvzFram89Pl` `[93;113]` | `complete` | `out_of_scope` | `Not in semester 3` | GDGoC internal club recruitment (Oct 2026). Accurately extracted based on available text; outside HK3. |
| **6** | `activities: pfbid02kVX7vEbj6FuQSGiHs7NqQMz9CszBXfbmt9RjRcpJfU17z7CnhkjUVEee7vVirgnWl` `[116;134]` | `complete` | `out_of_scope` | `Unknown` | Health check registration round 2 announcement. Post only provides external link; dates omitted in text. |
| **7** | `activities: pfbid0p8jUJBWv9dCfTj4L9hr7QD8CycCVugW71gPzrRh4BgpB6WWCZWA5urLB783sTwc4l` `[137;157]` | `complete` | `out_of_scope` | `Not in semester 3` | *Avalanche UniHack 2026* hackathon (02/11–30/11/2026). External activity posted for media support; outside HK3. |
| **8** | `activities: pfbid02fsjfr4MEtTjN9TpVw3DvfWumQm7Wx2GGE56n7J51Y8sh4brg3p4k1uwhX41h26FFl` `[160;178]` | `incomplete` | `out_of_scope` | `Not in semester 3` | Health check round 1 recap. Extractor set `start: null`, missing explicit makeup date **2026-10-26** in post text. |
| **9** | `activities: pfbid0DeYsfZBiuFn3oyYi6JE2vjfzPWHirxKMfBAzUk284M4guunLjVQxPTs8oodLfWiJl` `[181;201]` | `complete` | `out_of_scope` | `Not in semester 3` | *KHTN ZERO+ 2026* contest (19/10–23/10/2026). Explicitly credited to Semester 1, 2026–2027. |
| **10** | `activities: pfbid033dzDjjDUpdog6s9h3NWATwuoNp5UumRmNNYnZVyKMxFzyLktCc6xsxstaZP4fPjLl` `[204;224]` | `complete` | `out_of_scope` | `Not in semester 3` | Traffic Safety Seminar on **2026-10-17**. Extracted properly; outside HK3. |
| **11** | `activities: pfbid0yi4qHyyzkSe4NWeBqXBMo5aifh7TaV4rEj4ZcYvhKM5DmdA8K6z9G1FUCt5TC7mzl` `[227;245]` | `incomplete` | `out_of_scope` | `Not in semester 3` | *Vươn Bước Đêm Rằm* volunteer campaign on **2026-09-27**. Extractor missed audience `40 sinh viên`. |
| **12** | `activities: pfbid02gENqCMzeMBYaWH3zsqfExUZ5coUdTv7jS37xfTeJijUPRfYs6utzCZGZ3H6o9mYQl` `[248;266]` | `complete` | `needs_verification` | `Not in semester 3` | *Hoa Mùa Hè* volunteer campaign on **16/05–17/05/2026**. Ended 1 day before HK3 start (18/05). Needs confirmation whether credited to HK2 or HK3. |
| **13** | `activities: pfbid0FhhUJfbqkRd3tXeqHd7paVvzojeGnfd4TVFn2NCZASxeUKAXKxK3hPgsoPCPxz5Hl` `[269;287]` | `incomplete` | `out_of_scope` | `Not in semester 3` | *Hạt Nắng Đêm* volunteer event on **2026-04-12** (Semester 2). Extractor missed audience `30 - 35 sinh viên`. |
| **14** | `activities: pfbid02YD2tW2i4Qf1NXyRniCfqRAThQH76uVHCGu8DQwNHupwCUyu4YVAniRHZdvRSngJ4l` `[290;310]` | `complete` | `out_of_scope` | `Not in semester 3` | *FIT Super League 2026* soccer tournament (March–April 2026, Semester 2). |
| **15** | `activities: pfbid026SJmz8cRXUkDwHvJrZyZv4bsikCC1t4pdDBt46gTuwxaTkBKtSHvCPvwJH1KJ47l` `[313;333]` | `complete` | `out_of_scope` | `Unknown` | *Bản Lĩnh IT* registration opening. Post mentions registration deadline (24/09/2026) but no event date. |
| **16** | `activities: pfbid034Pftro7LAxEMRbiQpWNcxtzw7B8ji6B9DWEvMq6nvmbqHR6RP3fLymeJrd5WJytTl` `[336;356]` | `complete` | `out_of_scope` | `Not in semester 3` | *Olympic AI HCMUS 2026* exam on **2026-10-11** (Semester 1, 2026–2027). |
| **17** | `activities: pfbid0KfFuXSR1LyKtz1MQvsRR2civySNdRQuKrD8ouyX5gDcH5kGpZdYcwPpWNqVoqhQzl` `[359;379]` | `complete` | `out_of_scope` | `Not in semester 3` | *Olympic Informatics 2026* on **2026-10-25** (Semester 1, 2026–2027). |
| **18** | `activities: pfbid02buju6UWyad8k9Z4xH1tR5eNwpWsuaZtnwfesY2o8UQzdFh3p7cHemVx24dkaHSdFl` `[382;402]` | `complete` | `out_of_scope` | `Unknown` | *ITogether* station introduction for K26 freshmen. No specific event date in post. |
| **19** | `activities: pfbid0XY9yh6vTLib4ADSzim4hNzw5xh5FK2XMUmhezcWy99AaXxjTBau8qFhxihzANbrUl` `[405;425]` | `incomplete` | `needs_verification` | `In semester 3` | **"Theo dấu chân Người"** contest (**2026-06-05 to 2026-06-12**). Confirmed for HK3 (Advanced program). Extractor omitted registration link `bit.ly/TheoDauChanNguoi2026`. |
| **20** | `activities: pfbid02ATDhaQW22WUMoQuQ4Ef5tbLZS2RCUTLa7VxhpSxRwYiEcThL3pGfrsDf8refWW9Al` `[428;448]` | `complete` | `out_of_scope` | `Unknown` | Media support post by Design ITUS for *Bản Lĩnh IT* (duplicate of #15). |

---

## 4. Extractor Issue Tracking (Actionable Feedback for Extractor Development)

A total of **6 extraction defects** were logged in `QA20.json` with clear before/after context:

1. **Activity #2 (`...PDBYHzl`):**
   * *Extracted:* `"audience": null`
   * *Raw Post:* Explicitly mentions `"ALT đang chờ đón K26 với những thử thách mới"` (Contestants / K26 freshmen).
2. **Activity #4 (`...BGfn7zKkl`):**
   * *Extracted:* Set `start`/`end` from internal club recruitment timeline onto a general skills blog post.
3. **Activity #8 (`...h26FFl`):**
   * *Extracted:* `"start": null, "end": null`
   * *Raw Post:* States makeup health check on `"26/10/2026"` (morning 07:30–11:00, afternoon 13:00–16:00).
4. **Activity #11 (`...TC7mzl`):**
   * *Extracted:* `"audience": null`
   * *Raw Post:* Explicitly states `"Đối tượng tham gia: 40 sinh viên"`.
5. **Activity #13 (`...Pxz5Hl`):**
   * *Extracted:* `"audience": null`
   * *Raw Post:* Explicitly states `"Đối tượng tham gia: 30 - 35 sinh viên"`.
6. **Activity #19 (`...ANbrUl`):**
   * *Extracted:* `"URL_registration": null`
   * *Raw Post:* Contains `"Link tham gia: bit.ly/TheoDauChanNguoi2026."`.

---

## 5. Dataset Augmentation for Semester 3

### 5.1 Rationale
The audit revealed that among the initial 20 announcements, only **1 record** (Activity #19: *"Theo dấu chân Người"*) fell within the verified dates of Semester 3 (May 18, 2026 – August 17, 2026), with Activity #12 on the borderline. This was insufficient for SP3 downstream planning.

### 5.2 Data Collection & Extraction
To solve the data shortage:
* Processed raw URLs listed in `urls.txt`.
* Collected raw post content and parsed records into `source.json` (bringing total records to 38).
* Identified and added **17 new activity announcements strictly occurring in Semester 3**.
* Total verified Semester 3 activities increased from **1 to 18**.

### 5.3 Complete Portfolio of 18 Semester 3 Activities

| # | Activity ID | Event Date | Activity Title / Topic | Publisher / Organizer | Source Post URL |
|:---:|---|:---:|---|---|---|
| **1** | `...ANbrUl` | 05/06 – 12/06/2026 | Cuộc thi trực tuyến "Theo dấu chân Người" | Đoàn - Hội CNTT KHTN | [Facebook Share](https://www.facebook.com/share/p/1LTPMqmzdz/) |
| **2** | `...MYLil` | 22/05/2026 | Workshop "Build On Stellar: From Zero to Web3 App" | GDGoC - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1JuDUvt9Go/) |
| **3** | `...2A8UCl` | 24/05/2026 | Chiến dịch "Trạm An Yên" – Chuỗi Vòng tay nhân ái | Đội SVTN Khoa CNTT | [Facebook Share](https://www.facebook.com/share/p/1FYSHfXhnT/) |
| **4** | `...XjBbDl` | 23/05 – 24/05/2026 | Chiến dịch tình nguyện "Bước Chân Yêu Thương" | SAB in HCMUS | [Facebook Share](https://www.facebook.com/share/p/1DtRojcgtN/) |
| **5** | `...EBGd78xwl`| 30/05/2026 | Workshop "AI thực chiến: Kỹ năng sử dụng AI an toàn" | Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/19wdyDzNQt/) |
| **6** | `...WebgBHl` | 31/05/2026 | Chiến dịch "Ươm Mầm" – Chuỗi Vòng tay nhân ái | Đội SVTN Khoa CNTT | [Facebook Share](https://www.facebook.com/share/p/1JMUVrCkHL/) |
| **7** | `...HJX4Uxl` | 06/06/2026 | Workshop "Bảo vệ dữ liệu cá nhân trong kỷ nguyên số" | Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1DvjWPYtN6/) |
| **8** | `...X3Pfl` | 07/06/2026 | Tọa đàm "Sống khỏe - Sống có trách nhiệm" (Phòng chống ma túy)| Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1F5Am99z1f/) |
| **9** | `...ZXMEGl` | 07/06/2026 | Workshop "Debug Your Eyes – Nâng cấp hệ thị giác" | Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1CBSrsM5uE/) |
| **10**| `...oYAXjEl` | 14/06/2026 | Workshop "Từ kỹ năng số đến công dân toàn cầu" | Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1CdvWyB4Qc/) |
| **11**| `...ruE9Lwl` | 14/06/2026 | Workshop "Hội chứng Dunning – Kruger: Nhận thức bản thân" | Phòng CTSV - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1ApVTpR8M4/) |
| **12**| `...RraAfl` | 20/06 – 21/06/2026 | Cuộc thi [HTTN26] Chặng 1: Tìm hiểu văn hóa khối APEC | Đoàn - Hội CNTT KHTN | [Facebook Share](https://www.facebook.com/share/p/1C8o1Bi3ds/) |
| **13**| `...mr8zJGl` | 08/07/2026 | Seminar Bộ môn CNTT lần 1: "Nhận dạng Đồ tượng chí Phật giáo"| FIT HCMUS Kênh Hoạt động | [Facebook Share](https://www.facebook.com/share/p/1E2xMyYTh4/) |
| **14**| `...Vkrw8l` | 24/07/2026 | Seminar "Human-AI Hybrid System in Algorithmic Trading" | FIT HCMUS Kênh Hoạt động | [Facebook Share](https://www.facebook.com/share/p/19u8MUPo1m/) |
| **15**| `...25aJAXl` | 25/07/2026 | Session CS101: "Product Engineering - How to Engineer a Product"| GDGoC - HCMUS | [Facebook Share](https://www.facebook.com/share/p/1J9qHfGhf3/) |
| **16**| `...GBPU8l` | 05/08/2026 | Seminar Bộ môn CNTT lần 2: "Ước lượng số lượng phức hợp..." | FIT HCMUS Kênh Hoạt động | [Facebook Share](https://www.facebook.com/share/p/16NxLU39foE/) |
| **17**| `...pSZEWl` | 08/08/2026 | Talkshow "Innovate Your Future" | FIT HCMUS Kênh Hoạt động | [Facebook Share](https://www.facebook.com/share/p/1C89BcmcUe/) |
| **18**| `...o9mYQl` | 16/05 – 17/05/2026 | Chiến dịch tình nguyện hè "Hoa Mùa Hè 2026" *(borderline)* | Đội SVTN Khoa Toán - Tin | [Facebook Share](https://www.facebook.com/share/p/19waFLjyKB/) |

---
