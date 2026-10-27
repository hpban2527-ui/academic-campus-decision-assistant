# Project E — Lead Integration CI Evidence (2026-10-27)

**Branch:** `integration/lead-sp1-sp2-20261027`  
**Draft PR:** https://github.com/hpban2527-ui/academic-campus-decision-assistant/pull/3  
**Workflow:** https://github.com/hpban2527-ui/academic-campus-decision-assistant/actions/runs/40455164432  
**Verified run HEAD:** `bcc6ed07a710272bcd6d55b0703ed115d5fb9f6b`

## Independent GitHub Actions results

- **Backend contract gates: SUCCESS.** Python 3.12 / Ubuntu Actions runner.
- `python -m pytest -q tests/sp1 tests/sp2 tests/integration`: **252 passed, 1 warning (1.23 seconds)**.
- `python scripts/check_sp2_cases.py`: **10/10 cases PASS** using Tuyền's rules and corrected test cases.
- `python -m compileall -q src tests scripts run_server.py`: PASS.
- **Frontend legacy E2E job: FAIL**, with **13 passed / 1 failed / 1 warning**.
  - Fail: `tests/test_e2e_pipeline.py::test_frontend_cannot_fallback_to_fake_credit`.
  - Cause: `web/index.html` still calls `runClientFallback(reqBody)` when API is unavailable, generating simulated values. This is owned by Tiến, not a backend-engine failure.
  - The frontend HTML remains identical to the author's `Minh_Tien` branch as requested by group leader.

## Acceptance decision

- **Backend contracts / SP1 / SP2:** Independently tested successfully on CI.
- **Frontend compatibility:** BLOCKED, handoff to Tiến.
- **Official university ĐRL validation:** NOT ESTABLISHED; demo engine / student snapshot only.
- **Automatic publication of regex-extracted draft:** DISABLED pending reviewer approval because the 20-post field accuracy audit found undetected date mistakes.
- **Overall release acceptance / merging into main:** **NOT READY**.

Two unresolved rule-data issues are documented separately: `R22` vs `R23` overlapping conditions and `R4302` with a nonnumeric upper bound. Engine audits/guards them, but they should not be declared verified by automation.
