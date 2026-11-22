"""Browser check of the real-data path: the web app shows the operational dataset end to end.

  python scripts/verify_operational_browser.py

Starts the FastAPI app on 127.0.0.1:8766, opens it in headless Chromium, switches the data source to the
real store, and checks that the activity catalog, the automatic exclusions and a generated plan come
from data/operational/activity_dataset.json (same dataset version as the file). Screenshots and a JSON
summary go to artifacts/operational_browser/ (not tracked).
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
OUT = ROOT / "artifacts" / "operational_browser"
PORT = 8766
BASE = f"http://127.0.0.1:{PORT}"


def wait_healthy() -> None:
    for _ in range(120):
        try:
            with urlopen(BASE + "/api/health", timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError("FastAPI server did not become healthy")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    dataset = json.loads((ROOT / "data/operational/activity_dataset.json").read_text(encoding="utf-8"))
    summary = dataset["summary"]
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    server = subprocess.Popen([sys.executable, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1",
                               "--port", str(PORT)], cwd=ROOT, env=env, stdout=subprocess.DEVNULL,
                              stderr=subprocess.STDOUT)
    result = {"url": BASE, "dataset_version": dataset["dataset_version"], "checks": {}}
    try:
        wait_healthy()
        with urlopen(BASE + "/api/sp3/catalog?source=real", timeout=60) as response:
            api = json.loads(response.read())
        assert api["dataset"]["dataset_version"] == dataset["dataset_version"]
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(BASE, wait_until="domcontentloaded")
            page.wait_for_function("document.querySelector('#backendStatusText').textContent.includes('API')",
                                   timeout=20000)
            page.evaluate("showWorkspace()")
            page.evaluate("setAuthMode('register')")
            page.locator("#registerName").fill("Sinh viên kiểm thử")
            page.locator("#registerMssv").fill("TEST2026")
            page.locator("#registerPassword").fill("TestPass2026!")
            page.locator("#btnSubmitRegister").click()
            page.locator("#workspaceApp").wait_for(state="visible", timeout=20000)

            page.evaluate("setSp3Source('real')")
            page.evaluate("switchTab('activities')")
            expected = f"{summary['schedulable_canonical']} hoạt động"
            page.wait_for_function(f"document.querySelector('#validCountBadge').textContent.includes({json.dumps(expected)})",
                                   timeout=30000)
            catalog_text = page.evaluate("document.querySelector('#validActivitiesList').textContent")
            drafts_text = page.evaluate("document.querySelector('#sp3NewDraftsList')?.textContent || ''")
            checks = {
                "catalog_count_matches_dataset": expected,
                "unknown_cost_shown_as_unknown": "Chi phí: Chưa rõ" in " ".join(catalog_text.split()),
                "rule_based_points_labelled_estimate": "(ước tính)" in catalog_text,
                "unbound_activity_marked_not_counted": "Không tính vào mục tiêu điểm" in catalog_text,
                "exclusions_are_automatic_not_review_tasks": "Không tự xếp lịch" in drafts_text,
                "date_only_reason_visible": "không nêu giờ bắt đầu" in drafts_text,
            }
            page.screenshot(path=str(OUT / "01_real_catalog.png"), full_page=False)
            page.evaluate("switchTab('plan')")
            page.locator("#btnRunPlanner").click()
            page.locator("#plannerActiveResult").wait_for(state="visible", timeout=60000)
            plan_text = page.evaluate("document.querySelector('#plannerActiveResult').textContent")
            plan_api = page.evaluate("planStages.first && planStages.first.dataset && planStages.first.dataset.dataset_version")
            checks["plan_generated_from_same_dataset_version"] = plan_api == dataset["dataset_version"]
            checks["plan_has_selected_activities"] = page.evaluate(
                "(planStages.first.plan.selected_activities || []).length") > 0
            checks["plan_status"] = page.evaluate("planStages.first.plan.status")
            page.screenshot(path=str(OUT / "02_real_plan.png"), full_page=False)
            # The page loads Tailwind from a CDN; in an offline sandbox that script is missing. That is an
            # environment limit, not an application error, so it is reported separately.
            checks["page_errors"] = [e for e in errors if "tailwind is not defined" not in e]
            result["environment_errors"] = [e for e in errors if "tailwind is not defined" in e]
            browser.close()
        result["checks"] = checks
        failed = [k for k, v in checks.items() if v is False or (k == "page_errors" and v)]
        result["passed"] = not failed
        result["failed"] = failed
        (OUT / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if not failed else 1
    finally:
        server.terminate()
        server.wait(timeout=10)


if __name__ == "__main__":
    sys.exit(main())
