# ADR-0003: One operational activity dataset for SP1 -> SP2 -> SP3 -> API

Date: 2026-11-18. Status: proposed by the SP1 owner (Thảo Duyên), implemented on
`feat/operational-data-pipeline-20261118`. Needs agreement of the SP3 owners (contract 0.3), the
personalization owner (budget exclusion) and the UI owner.

## Context

The application's real-data path read `data/handover/*`, a Qwen-only projection that defaulted a missing
fee to 0, set a missing registration deadline to the activity start, admitted date-only starts and
replayed recorded model replies by post ID even after the prompts had changed. A richer AI-assisted
annotation of the 129 non-test posts and an agreed acceptance policy existed only as a delivery packet.

## Decision

1. The runtime reads one generated file, `data/operational/activity_dataset.json`
   (`unilife-operational-dataset/1.0`), built by `scripts/update_activity_data.py` from versioned inputs
   in `data/`. Every post of the operational corpus has one record and an explicit status.
2. Extraction source order: AI annotation (non-test), recorded model reply with a
   matching prompt digest, otherwise `EXTRACTION_PENDING`. Human decisions apply last. Every source is
   bound to the text fingerprint.
3. Data readiness follows `activity-acceptance/1.1`. Missing organizer facts stay unknown and exclude the
   activity only from the operation that needs them.
4. SP3 activity contract `sp3-activity/0.3`: nullable fee; unstated deadline signalled by evidence
   (`deadline_unstated_by_activity`) instead of a `MISSING_DEADLINE` gate; planner accepts it.
5. New and edited announcements go to `data/raw/operational_updates.json`; the frozen evaluation corpus and
   its split stay untouched.
6. Data readiness, eligibility, score binding, human review and official verification stay separate.

## Consequences

* 189/189 posts accounted for; the counts are read from the dataset (`reports/operational_dataset_report.md`).
* The legacy store/handover and their build scripts were removed (2026-11-18); nothing reads them at runtime.
* A post with stale or missing model output is visible as pending until the next offline run.
* SP3, personalization and UI owners must review the listed contract changes before merging.
