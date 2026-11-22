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


def enter_workspace(page) -> None:
    page.evaluate("showWorkspace()")
    page.evaluate("setAuthMode('register')")
    page.locator("#registerName").fill("Sinh viên kiểm thử")
    page.locator("#registerMssv").fill("TEST2026")
    page.locator("#registerPassword").fill("TestPass2026!")
    page.locator("#registerPasswordConfirm").fill("TestPass2026!")
    page.locator("#btnSubmitRegister").click()
    page.locator("#onboardingModal").wait_for(state="visible", timeout=20000)
    page.locator("#onboardingNextButton").click()
    page.locator("#onboardingNextButton").click()
    page.evaluate("""() => {
      selectOnboardingTargetPreset(80);
      selectOnboardingCategoryChoice('ANY');
      selectOnboardingModeChoice('any');
      selectOnboardingCampusChoice('any');
      finishOnboardingTopics(true);
      renderOnboardingStep();
    }""")
    page.locator("#onboardingNextButton").click()
    page.locator("#planOptionsScreen").wait_for(state="visible", timeout=60000)
    page.locator('[data-pos-card] [data-pos-action="review"]').first.click()
    page.locator("#planReviewScreen").wait_for(state="visible", timeout=30000)
    page.locator("#onboardingNextButton").click()
    page.locator("#workspaceApp").wait_for(state="visible", timeout=30000)


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
            browser = playwright.chromium.launch(headless=True, channel="msedge" if os.name == "nt" else None)
            page = browser.new_page(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#backendStatusText').textContent.includes('API')", timeout=15000)
            page.evaluate("document.body.classList.add('dev-mode')")
            enter_workspace(page)
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

            sp3 = browser.new_page(viewport={"width": 1440, "height": 940})
            sp3_errors = []
            sp3.on("pageerror", lambda error: sp3_errors.append(str(error)))
            sp3.goto(BASE, wait_until="domcontentloaded")
            enter_workspace(sp3)

            # Build personalized options from the current five-step profile.
            sp3.locator("#tabBtnPlan").click()
            def is_options_response(response):
                return "/api/sp3/personalized/options" in response.url and response.request.method == "POST"

            with sp3.expect_response(is_options_response, timeout=60000) as options_call:
                sp3.evaluate("runSp3Planner()")
            options = options_call.value.json()
            assert options_call.value.status == 200
            assert isinstance(options.get("options"), list) and options["options"]
            assert any(item.get("status") == "READY" and item.get("result") for item in options["options"])
            sp3.locator("#planOptionsScreen").wait_for(state="visible", timeout=30000)
            assert sp3.locator('[data-pos-card] [data-pos-action="review"]').count() >= 1
            assert sp3.evaluate("!!planStages.first && !planStages.first.official_award_verified")
            sp3.screenshot(path=str(OUT / "04_personalized_options.png"), full_page=True)

            sp3.locator('[data-pos-card] [data-pos-action="review"]').first.click()
            sp3.locator("#planReviewScreen").wait_for(state="visible", timeout=15000)
            assert sp3.evaluate("!!prvDraft && !!prvDraft.result")
            sp3.screenshot(path=str(OUT / "05_plan_review.png"), full_page=True)
            sp3.evaluate("reviewDashBackToPlanOptions()")

            # The scenario API still provides a real replan and what-if result.
            def is_plan_response(response):
                return "/api/sp3/personalized/plan" in response.url and response.request.method == "POST"

            with sp3.expect_response(is_plan_response, timeout=60000) as replan_call:
                sp3.evaluate("gotoPlanStage('replan')")
            replanned = replan_call.value.json()
            assert replan_call.value.status == 200
            assert replanned["scenario"] == "personalized_replan"
            sp3.wait_for_function("!!planStages.replan", timeout=30000)
            assert replanned["official_award_verified"] is False

            with sp3.expect_response(is_plan_response, timeout=60000) as skip_call:
                sp3.evaluate("gotoPlanStage('whatif')")
            skipped = skip_call.value.json()
            assert skip_call.value.status == 200
            assert skipped["scenario"] == "personalized_what_if_skip"
            sp3.wait_for_function("!!planStages.whatif", timeout=30000)
            assert skipped["official_award_verified"] is False
            sp3.screenshot(path=str(OUT / "06_replan_whatif.png"), full_page=True)

            # Updating the target must fetch fresh options rather than reuse old results.
            sp3.evaluate("""() => {
              document.getElementById('inputPlanTarget').value = '90';
              reviewDashClosePlanOptions(true);
            }""")
            with sp3.expect_response(is_options_response, timeout=60000) as adjusted_call:
                sp3.evaluate("runSp3Planner()")
            assert adjusted_call.value.status == 200
            sp3.wait_for_function("!!planStages.first && planStages.first.requested_total_target === 90", timeout=30000)

            # Both halves of the activity repository must remain accessible.
            sp3.evaluate("reviewDashClosePlanOptions(true); switchTab('activities'); setActivitiesSubView('timeline')")
            assert sp3.locator("#timelineDateCardsContainer > *").count() == 5
            sp3.evaluate("setActivitiesSubView('qa')")
            assert not sp3.locator("#activitiesQaSection").evaluate("(el) => el.classList.contains('hidden')")
            sp3.wait_for_function("document.querySelector('#validActivitiesList').textContent.length > 0", timeout=20000)
            sp3.screenshot(path=str(OUT / "07_activity_catalog.png"), full_page=True)

            # Render a hostile plan title as text, not an executable element.
            sp3.evaluate("""() => {
              window.__sp3_xss = 0;
              const activity = planStages.first.plan?.selected_activities?.[0];
              if (!activity) throw new Error('No selected activity for XSS probe');
              activity.title = '<img src=x onerror="window.__sp3_xss=1">SP3 UNSAFE';
              currentPlanStage = 'first';
              renderSp3PlanResult();
            }""")
            assert sp3.evaluate("window.__sp3_xss") == 0
            assert sp3.locator("#planPanelSelected img").count() == 0
            assert not sp3_errors, f"SP3 desktop errors: {sp3_errors}"
            sp3.close()

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile_errors = []
            mobile.on("pageerror", lambda error: mobile_errors.append(str(error)))
            mobile.goto(BASE, wait_until="domcontentloaded")
            enter_workspace(mobile)
            assert mobile.evaluate("!!readLocalUserData(currentStudent.student_id).confirmed_plan")
            mobile.locator("#btnMobileMenuToggle").click()
            mobile.evaluate("switchTab('dashboard')")
            assert mobile.locator("#viewDashboard").is_visible()
            assert not mobile_errors, f"SP3 mobile errors: {mobile_errors}"
            mobile.screenshot(path=str(OUT / "08_mobile_dashboard.png"), full_page=True)
            mobile.close()

            output["sp3"] = {
                "personalized_options": "PASS", "review": "PASS",
                "replan": "PASS", "what_if_skip": "PASS",
                "target_refresh": "PASS", "catalog_timeline": "PASS",
                "desktop": "PASS", "mobile": "PASS", "xss": "PASS",
            }
            output["security"].append("SP3 activity title HTML escaped")
            assert not errors, f"Browser JavaScript errors: {errors}"
            browser.close()
        output["browser_errors"] = errors
        (OUT / "evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print("MVP_BROWSER_E2E: 5/5 H4; personalized options, review, replan, what-if, desktop/mobile and XSS")
        print(json.dumps(output, ensure_ascii=True))
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
