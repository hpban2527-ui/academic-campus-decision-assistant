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
            page.evaluate("window.__h4_xss = 0")
            page.evaluate("loadActivitiesFromApi()")
            page.wait_for_function(
                "document.querySelector('#validActivitiesList').textContent.includes('H4 UNSAFE')",
                timeout=12000,
            )
            assert page.evaluate("window.__h4_xss") == 0, "XSS executed from activity title"
            assert page.locator("#validActivitiesList img").count() == 0, "Untrusted HTML parsed as an image"
            assert page.locator("#reviewQueueList img").count() == 0, "Untrusted review title parsed as HTML"
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
            assert not errors, f"Browser JavaScript errors: {errors}"
            browser.close()
        output["browser_errors"] = errors
        (OUT / "evidence.json").write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print("H4_REAL_BROWSER_E2E: 5/5 verified; XSS probes: 2/2; browser errors: 0")
        print(json.dumps(output, ensure_ascii=False))
    finally:
        server.terminate()
        try:
            server.wait(timeout=8)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
