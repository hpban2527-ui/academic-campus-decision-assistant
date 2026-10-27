# Project E — Lead & Integration Handoff (27/10/2026)

Owner: Bình An (Group 6). Scope: **contract, repository integration, backend API, data QA and system acceptance**. Frontend design and UI workflows remain **Lưu Minh Tiến's** responsibility. No automatic merge to \`main\`.

## 1. What is wired

| Source | Authoritative module/file | Integration action |
| --- | --- | --- |
| SP1 Code | \`src/sp1/extractor.py\` — Thảo Duyên | Synced updated parser; accepts Trí's \`share_url\` |
| SP1 Data | \`Collecting_Data/source.json\` — Minh Trí | Original 20-post dataset retained; stable URL identity and QA audit |
| SP2 Data | \`data/drl_rules.json\` — Ngọc Tuyền | Synced 75 real rules; 10 corrected expected cases |
| SP2 Code | \`src/sp2/drl_engine.py\` — Như Ngọc | Synced \`evaluate_rules_progress\` bridge and matching test |
| Backend | \`src/api/server.py\` — Lead | Safe extraction and SP2 snapshot API |
| Publication contract | \`src/api/lead_contract.py\`, \`schemas/activity.schema.json\` — Lead | Strict 14-field published shape + reviewer gate |
| Frontend | \`web/index.html\` — Minh Tiến | **Preserved byte-for-byte**; API compatibility to be aligned by frontend owner |

The **SP1 extractor draft** has 15 fields, including \`drl_recognized\`, plus \`meta\` with raw text spans. This is intentional and is *not* the published activity object.

The **published 14-field activity** is constructed by \`prepare_publication\`. \`drl_recognized\` becomes a metadata claim. The agreed group defaults apply **only at this boundary**: omitted \`mandatory → false\`, \`fee → 0\`, with \`meta.derived\` recording their provenance. Unknown \`mode\` or missing \`completion_requirements\` must be reviewed. Tracking URL parameters (e.g. \`rdid\`) do not change stable activity identity. \`start/end\` date ordering and ISO offsets are checked.

**IMPORTANT:** The current SP1 regex evaluator reported 5 erroneous draft values among 7 nominally \`valid\` examples and a false date for P08. Hence **every candidate requires reviewer approval** before publication, not only partial or failed extraction. The review queue is real; a finished human review workflow is not present yet.

## 2. Backend contracts

### \`GET /api/health\`
Runtime inventory, not a release certification.

### \`POST /api/evaluate\` — SP1 intake + safe classification

Input (compatible with Tiến's request payload):
\`\`\`json
{
  "post_id": "unique-post-id",
  "publisher": "Cơ quan thông báo",
  "platform": "facebook",
  "date_posted": "2026-10-27",
  "url": "https://example.org/post",
  "raw_content": "Nội dung thông báo...",
  "has_evidence": false,
  "rule_override": "auto"
}
\`\`\`

Response:
- \`sp1.record\`: **exactly 14 fields**, candidate only, NOT automatically published;
- \`sp1.meta\`: evidence/flags, \`drl_recognized\`, \`publication_status="REVIEW_REQUIRED"\`, \`routed_to\`;
- \`sp2.decision\`: \`REJECTED_DUPLICATE\`, \`NEEDS_REVIEW\` or \`PENDING_REVIEW\`;
- \`sp2.projected_added=0\`, \`sp2.confirmed_added=0\` until eligibility/recognition are actually verified;
- \`sp2.rule\` may contain a user-selected **suggestion**, not an award or proof;
- \`dedup\`: duplicate boolean, match ID and similarity.

**Do not display "confirmed" just because \`has_evidence=true\`. This checkbox is user-declared, not checked university evidence.**

### \`POST /api/sp2/evaluate\` — actual rules engine as an explicitly labeled DEMO

\`\`\`json
{
  "student_profile": {"university": "HCMUS"},
  "student_snapshot": {
    "record_id": "sample-1",
    "status": "CONFIRMED",
    "evidence_status": "VERIFIED",
    "values": {"semester_gpa": 8.5, "academic_exam_violations": 0}
  },
  "scope": {"universities": ["HCMUS"]},
  "personal_targets": {"C1": 30},
  "demo": true
}
\`\`\`

Expected from rules: \`R11=15\`, \`R1203=10\`, C1 \`confirmed_total=25\`, \`remaining=5\`, \`official_award_verified=false\`, \`mode="DEMO_ONLY"\`. A real/official claim (\`demo=false\`) is rejected because there is no trusted school proof service. Client-supplied \`evidence_status\` is **not** itself external verification.

### Error behavior

Malformed SP1 data or unsafe scoring requests return HTTP 422 with a reason. No fabricated success, fallback rule or automatic official points.

## 3. Work still required / blockers

**Lead/backend/data-owned:**
- Verify and resolve official regulation ambiguity: \`R22\` and \`R23\` use identical conditions despite different descriptions; \`R4302\` contains \`"one_week"\` as a non-numeric range endpoint. Current engine flags/skips and does not silently invent a numeric threshold.
- Rectify extractor's unflagged date error (P08), improve the review/approval workflow, and re-evaluate on a held-out labeled sample. Until then keep the fail-closed review gate.
- Dedup: Trí documented that Link 21 cross-post was kept while Link 22 was the organiser's original. A future reviewer must preserve both source URLs and prefer official attribution.
- Existing 20 records have 5 unknown \`mode\`, 18 missing \`completion_requirements\`, and should be treated as imported unreviewed reference data rather than fully accepted activities.

**Frontend owner — Lưu Minh Tiến (no UI edits made by Lead):**
- **P0**: Remove the client-side \`runClientFallback\` synthetic scoring when API is offline/fails; display an error instead.
- **P0**: Do not update per-student \`localStorage\` scores from an unreviewed event or \`PENDING_REVIEW\`.
- **P0**: Handle nullable \`sp2.rule\`, \`category_before\`, \`category_after\`, \`category_missing\` and \`rule_points\` without showing \`R19\`, \`+5\` or \`nullđ\` by default.
- **P0**: Replace hardcoded sample score/profile values with an explicit **DEMO** label; distinguish verified awards from demo simulation.
- **P1**: The five former demo E2E tests expecting auto-confirmation no longer define safe business behavior. Update tests to reflect API review decisions, plus \`/api/sp2/evaluate\` demo behavior.
- **P1**: Batch-run "PASS" must compare actual vs expected assertions; HTTP 200 alone is insufficient.

Do not merge until contract, frontend alignment, CI and integration acceptance are all reviewed.

## 4. Reproducible verification

\`\`\`bash
python -m pip install -r requirements.txt
PYTHONPATH=src python -m pytest -q tests/sp1 tests/sp2 tests/integration
PYTHONPATH=src python scripts/check_sp2_cases.py
PYTHONPATH=src python -m compileall -q src tests scripts run_server.py
python run_server.py
\`\`\`

Legacy tests from Tiến (\`tests/test_e2e_pipeline.py\`) must be run separately and are **expected to need updating** after fail-closed behavior changed. Do not misreport an HTTP success as E2E acceptance.

## 5. Evidence and limitations

- Source commits imported from independent contributor branches; no contributor branch modified.
- Integration branch is **not a merge into \`main\`**.
- Tests are committed, but their PASS state must be verified from a real runtime/CI report; text assertions here are not substitute evidence.
- All educational/demo rule evaluations are labeled explicitly and are **not official ĐRL awards**.
