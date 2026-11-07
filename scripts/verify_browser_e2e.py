"""H4 browser acceptance on a real Chromium page against a real local FastAPI server.

Run from repository root:
  pip install -r requirements.txt playwright
  python -m playwright install chromium
  python scripts/verify_browser_e2e.py

This does not make HCMUS awards official. UI must label demo scores as synthetic.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "h4_browser"
OUT.mkdir(parents=True, exist_ok=True)
PORT = 8765
BASE = f"http://127.0.0.1:{PORT}"


def check_health() -> None:
    for _ in range(90):
        try:
            with urlopen(BASE + "/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("FastAPI server did not become healthy")


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", str(PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    output = {"url": BASE, "cases": [], "security": [], "backend": "REAL_LOCAL_FASTAPI"}
    try:
        check_health()
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#backendStatusText').textContent.includes('API')", timeout=15000)
            page.evaluate("document.body.classList.add('dev-mode')")
            page.locator("#tabBtnTestSuites").click()
            page.locator("[onclick='runBatchAllTests()']").click()
            page.wait_for_function(
                "document.querySelector('#batchLogRows').textContent.includes('Ca 5')",
                timeout=45000,
            )
            logs = page.locator("#batchLogRows").inner_text()
            badge = page.locator("#batchSummaryBadge").inner_text()
            for idx in range(1, 6):
                expected = f"[Ca {idx}"
                assert expected in logs, f"missing result for case {idx}: {logs}"
                case_line = next((line for line in logs.splitlines() if expected in line), "")
                assert "PASS" in case_line, f"case {idx} is not PASS: {case_line}"
                output["cases"].append({"id": idx, "ui": "PASS"})
            assert badge.strip() == "5/5 PASS", f"actual UI badge: {badge!r}"
            page.screenshot(path=str(OUT / "01_five_cases_pass.png"), full_page=True)

            # Open one real preset through its normal browser UI.
            page.locator("#testSuitesGrid button").first.click()
            page.wait_for_function(
                "document.querySelector('#resDecisionBadge').textContent.toLocaleLowerCase('vi').includes('dự kiến')",
                timeout=25000,
            )
            output["single_preset"] = {
                "decision": page.locator("#resDecisionBadge").inner_text(),
                "category": page.locator("#resCatBeforeAfter").inner_text(),
                "explanation": page.locator("#resExplanation").inner_text()[:400],
            }
            page.screenshot(path=str(OUT / "02_single_post_pipeline.png"), full_page=True)

            # XSS probe: an attacker-controlled post title in the activity API
            # must be displayed as text, without executing onerror JavaScript.
            payload = '<img src=x onerror="window.__h4_xss=1">H4 UNSAFE'
            page.route(
                "**/api/activities",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "activities": [{
                            "activity_id": "probe", "title": payload, "source": {"publisher": payload},
                            "location": payload, "mode": "offline", "points": None,
                        }],
                        "review_queue": [{"activity_id": "review", "title": payload, "flags": [payload]}],
                    }),
                ),
            )
            page.route(
                "**/api/sp3/catalog",
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/json",
                    body=json.dumps({
                        "activities": [{
                            "activity": {
                                "activity_id": "probe", "title": payload,
                                "source": {"publisher": payload},
                                "location": payload, "mode": "offline", "points": None,
                            },
                            "data_qa": {"activity_id": "probe", "status": "needs_review", "notes": payload},
                            "publication_status": "REVIEW_REQUIRED",
                            "score_binding_verified": False,
                        }],
                        "new_post_drafts": [{
                            "activity": {"activity_id": "draft", "title": payload},
                            "publication_status": "REVIEW_REQUIRED",
                            "review_flags": [payload],
                            "score_binding_verified": False,
                        }],
                        "activity_count": 1,
                        "unstructured_new_posts": 1,
                    }),
                ),
            )
            page.evaluate("window.__h4_xss = 0")
            page.evaluate("loadActivitiesFromApi()")
            page.wait_for_function(
                "document.querySelector('#validActivitiesList').textContent.includes('H4 UNSAFE')",
                timeout=12000,
            )
            assert page.evaluate("window.__h4_xss") == 0, "XSS executed from activity title"
            assert page.locator("#validActivitiesList img").count() == 0, "Untrusted HTML parsed as an image"
            assert page.locator("#reviewQueueList img").count() == 0, "Untrusted review title parsed as HTML"
            assert page.locator("#sp3NewDraftsList img").count() == 0, "Untrusted SP3 draft parsed as HTML"
            output["security"].append("activity/review HTML escaped")
            page.screenshot(path=str(OUT / "03_xss_safe_rendering.png"), full_page=True)

            # Inspector evidence from raw post is another HTML injection surface.
            page.evaluate(
                """() => {
                  const p = '<img src=x onerror="window.__h4_xss=2">H4 INSPECTOR';
                  const rec = {title:p, source:{publisher:p}};
                  populateInspectorTable(rec,{status:'valid',evidence:{title:p},flags:[]},{is_duplicate:false});
                }"""
            )
            assert page.evaluate("window.__h4_xss") == 0, "XSS executed from SP1 evidence"
            assert page.locator("#inspectorTableBody img").count() == 0, "Untrusted SP1 evidence parsed as HTML"
            output["security"].append("inspector evidence HTML escaped")

            # Run the SP3 journey through the real FastAPI server, not mock responses.
            sp3 = browser.new_page(viewport={"width": 1440, "height": 940})
            sp3_errors = []
            sp3.on("pageerror", lambda error: sp3_errors.append(str(error)))
            sp3.goto(BASE, wait_until="domcontentloaded")

            def is_sp3_response(response):
                return "/api/sp3/demo/plan" in response.url and response.request.method == "POST"

            with sp3.expect_response(is_sp3_response, timeout=60000) as initial_call:
                sp3.locator("#tabBtnPlan").click()
            initial = initial_call.value.json()
            sp3.locator("#plannerActiveResult").wait_for(state="visible", timeout=60000)
            assert initial["mode"] == "DEMO_ONLY"
            assert initial["official_award_verified"] is False
            assert initial["plan"]["status"] == "TARGET_MET"
            assert initial["plan"]["score_summary"]["projected_total"] == 80
            assert len(initial["plan"]["selected_activities"]) == 3
            assert sp3.locator("#planDisclosure").is_visible(), "Demo disclaimer hidden in user mode"
            assert "chưa phải điểm rèn luyện" in sp3.locator("#planDisclosure").inner_text()
            assert "60 → 80" in sp3.locator("#planScoreOverview").inner_text()
            assert sp3.locator("#planPanelSelected .candidate-card").count() == 3
            sp3.screenshot(path=str(OUT / "04_sp3_first_plan.png"), full_page=True)

            with sp3.expect_response(is_sp3_response, timeout=60000) as replan_call:
                sp3.locator("#planStepper button").nth(1).click()
            replanned = replan_call.value.json()
            assert replanned["scenario"] == "replan"
            assert replanned["official_award_verified"] is False
            assert "Tình huống mẫu" in sp3.locator("#planChangeCard").inner_text()
            sp3.screenshot(path=str(OUT / "05_sp3_replan.png"), full_page=True)

            with sp3.expect_response(is_sp3_response, timeout=60000) as skip_call:
                sp3.locator("#planStepper button").nth(2).click()
            skipped = skip_call.value.json()
            assert skipped["scenario"] == "what_if_skip"
            assert skipped["plan"]["status"] == "PARTIAL"
            assert "QUIZ-L" not in {a["activity_id"] for a in skipped["plan"]["selected_activities"]}
            sp3.screenshot(path=str(OUT / "06_sp3_what_if.png"), full_page=True)

            sp3.locator("#planStepper button").first.click()
            sp3.locator("#inputPlanTarget").fill("90")
            sp3.locator("#btnToggleBusySlots").click()
            sp3.locator("#busySlot2").check()
            sp3.locator("#btnToggleBusySlots").click()
            assert sp3.locator("#planStaleNotice").is_visible(), "Changed inputs did not mark plan stale"
            with sp3.expect_response(is_sp3_response, timeout=60000) as adjusted_call:
                sp3.locator("#btnRunPlanner").click()
            adjusted = adjusted_call.value.json()
            assert adjusted["requested_total_target"] == 90
            assert adjusted["official_award_verified"] is False
            assert adjusted["availability"]["available_intervals"] != initial["availability"]["available_intervals"]
            assert "90đ" in sp3.locator("#planTargetScoreText").inner_text()
            assert not sp3.locator("#planStaleNotice").is_visible()

            sp3.locator("#tabBtnActivities").click()
            sp3.wait_for_function(
                "document.querySelector('#validActivitiesList').textContent.includes('Chưa rõ điểm')",
                timeout=45000,
            )
            assert "Hoạt động nguồn" in sp3.locator("#viewActivities").inner_text()
            assert "đã công nhận" not in sp3.locator("#viewActivities h3").first.inner_text().lower()
            sp3.screenshot(path=str(OUT / "07_sp3_source_catalog.png"), full_page=True)

            sp3.locator("#tabBtnPlan").click()
            sp3.evaluate("""() => {
                window.__sp3_xss = 0;
                const payload = '<img src=x onerror="window.__sp3_xss=1">SP3 UNSAFE';
                planStages.first.plan.selected_activities[0].title = payload;
                planStages.first.feasibility.candidates[0].activity.title = payload;
                currentPlanStage = 'first';
                renderSp3PlanResult();
            }""")
            assert sp3.evaluate("window.__sp3_xss") == 0, "Untrusted SP3 activity title executed JavaScript"
            assert sp3.locator("#planPanelSelected img").count() == 0, "Untrusted SP3 title parsed as HTML"
            assert not sp3_errors, f"SP3 desktop errors: {sp3_errors}"
            sp3.close()

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile_errors = []
            mobile.on("pageerror", lambda error: mobile_errors.append(str(error)))
            mobile.goto(BASE, wait_until="domcontentloaded")
            mobile.locator("#btnMobileMenuToggle").click()
            with mobile.expect_response(is_sp3_response, timeout=60000) as mobile_call:
                mobile.locator("#tabBtnPlan").click()
            mobile.locator("#plannerActiveResult").wait_for(state="visible", timeout=60000)
            assert mobile_call.value.json()["plan"]["status"] == "TARGET_MET"
            assert mobile.locator("#planDisclosure").is_visible()
            assert not mobile_errors, f"SP3 mobile errors: {mobile_errors}"
            mobile.screenshot(path=str(OUT / "08_sp3_mobile.png"), full_page=True)
            mobile.close()

            output["sp3"] = {
                "first_plan": "PASS", "replan": "PASS", "what_if_skip": "PASS",
                "goal_and_busy_constraints": "PASS", "source_review_labels": "PASS",
                "desktop": "PASS", "mobile": "PASS", "xss": "PASS",
            }
            output["security"].append("SP3 activity title HTML escaped")
            assert not errors, f"Browser JavaScript errors: {errors}"
            browser.close()
        output["browser_errors"] = errors
        (OUT / "evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print("MVP_BROWSER_E2E: 5/5 H4; SP3 desktop/mobile, constraints, replan, what-if and XSS; errors: 0")
        print(json.dumps(output, ensure_ascii=False))
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
