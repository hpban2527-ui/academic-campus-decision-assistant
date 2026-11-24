"""Browser check of the real simulation-date lifecycle.

Drives the real page in a headless Chromium-family browser (Edge or Chrome) through the Chrome DevTools
Protocol against a real local FastAPI server (standard library only, like verify_review_dashboard_e2e.py):
register, plan and review, advance time, confirm participation, switch terms, reload and log in again.

  python scripts/verify_term_clock_e2e.py          # screenshots go to a temporary folder (printed at the end)

Exit code 0 means every check passed or no browser is installed (the skip is printed).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import verify_review_dashboard_e2e as base  # noqa: E402  (the DevTools client and the shared page helpers)

SERVER_PORT, DEBUG_PORT = 8782, 9342
URL = f"http://127.0.0.1:{SERVER_PORT}"
MSSV = "TRM2030"
HK3, HK1 = "HK3_2025_2026", "HK1_2026_2027"
# The real store has many activities with an unstated fee: a fee cap would hard-exclude them, so none is set here.
PREFERENCE = {**base.PREFERENCE, "limits": {"max_activities": 4, "max_duration_minutes": None, "max_fee": None}}


def stored(page, expression: str):
    return json.loads(page.js(f"JSON.stringify((() => {{ const d = readLocalUserData(currentStudent.student_id); return {expression}; }})())"))


def chip(page) -> str:
    return page.js("document.querySelector('#termPill').innerText.replace(/\\s+/g, ' ').trim()")


def plan_and_confirm(page, term: str, as_of_day: str) -> dict:
    page.js(f"confirmedPreference = {json.dumps(PREFERENCE)}; preferenceDraft = confirmedPreference;")
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!!planStages.first && cachedPlanOptions.length > 0", 60)
    base.close_options(page)
    plan = page.js("JSON.parse(JSON.stringify(planStages.first))")
    assert plan["term_id"] == term and plan["as_of"][:10] == as_of_day, (plan["term_id"], plan["as_of"])
    assert plan["plan"]["context"]["term_id"] == term
    # With a confirmed preference the plan goes through the review screen, which confirms it.
    page.js("document.getElementById('btnOpenReview').click()")
    page.wait("!!prvDraft && !prvDraft.busy", 30)
    page.js("document.querySelector('#prvPanel button[onclick=\"prvConfirm()\"]').click()")
    page.wait("document.getElementById('planReviewScreen').classList.contains('hidden') && !document.getElementById('cpdContent').classList.contains('hidden')", 40)
    confirmed = stored(page, "d.confirmed_plan")
    assert confirmed["term_id"] == term and confirmed["as_of"][:10] == as_of_day
    assert page.js("!!cpdCompletionState && cpdCompletionState.termId") == term
    return confirmed


def advance_and_complete(page) -> tuple[str, int, str]:
    page.wait("!!cpdCompletionState?.progress")
    before = page.js("cpdCompletionState.progress")
    activity_id, status = min(
        ((key, value) for key, value in before["activities"].items()
         if value["status"] == "NOT_DUE" and before["projected_by_activity"].get(key, 0) > 0),
        key=lambda row: row[1]["available_at"],
    )
    day = status["available_at"][:10]
    page.js("document.getElementById('simulationDateButton').click()")
    page.wait("document.getElementById('simulationDateDialog').open")
    assert page.js("document.getElementById('simulationDateInput').min") == "2026-05-17"
    assert page.js("document.getElementById('simulationDateInput').max") == "2026-08-28"
    page.js("document.getElementById('simulationDateCancel').click()")
    assert page.js("!document.getElementById('simulationDateDialog').open && termClock.as_of.slice(0, 10) === '2026-05-17'")

    page.js(f"""window.__clockFetch = window.fetch;
      window.fetch = (url, ...args) => String(url).endsWith('/api/clock/advance')
          ? Promise.reject(new Error('Offline')) : window.__clockFetch(url, ...args);
      document.getElementById('simulationDateButton').click();
      document.getElementById('simulationDateInput').value = {json.dumps(day)};
      document.getElementById('simulationDateApply').click();""")
    page.wait("document.getElementById('simulationDateError').textContent.includes('thử lại')")
    assert page.js("document.getElementById('simulationDateDialog').open && termClock.as_of.slice(0, 10) === '2026-05-17'")
    page.js("""window.__clockPosts = 0;
      window.fetch = (url, ...args) => {
        if (String(url).endsWith('/api/clock/advance')) window.__clockPosts++;
        return window.__clockFetch(url, ...args);
      };
      document.getElementById('simulationDateApply').click();
      document.getElementById('simulationDateApply').click();""")
    page.wait(f"!document.getElementById('simulationDateDialog').open && cpdCompletionState?.progress?.as_of === '{day}T23:59:59+07:00'")
    assert page.js("window.__clockPosts") == 1
    assert page.js("planStages.first === null && cachedPlanOptions.length === 0 && !prvDraft")
    assert page.js("cpdCompletionState.progress.score_summary.baseline_total") == before["score_summary"]["baseline_total"]
    assert page.js("""(() => {
      const version = termClock.clock_version;
      timelineGoToFirstActivity();
      return termClock.clock_version === version;
    })()""")
    page.js(f"cpdOpenActivity(activityToken({json.dumps(activity_id)}))")
    page.wait("document.getElementById('cpdConfirmCompletion')?.disabled === false")
    page.js("document.getElementById('cpdConfirmCompletion').click()")
    page.wait(f"cpdCompletionState.progress.activities[{json.dumps(activity_id)}].status === 'COMPLETED'")
    score = page.js("cpdCompletionState.progress.score_summary.baseline_total")
    assert score > before["score_summary"]["baseline_total"]
    return day, score, activity_id


def main() -> int:
    browser = base.find_browser()
    if browser is None:
        print("SKIP: no Edge/Chrome/Chromium found.")
        return 0
    out = Path(tempfile.mkdtemp(prefix="term-clock-"))
    base.OUT = out
    session_file = out / "session.json"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src"), "UNILIFE_SESSION_FILE": str(session_file)}
    env.pop("UNILIFE_COMPLETION_AS_OF", None)
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    chrome = subprocess.Popen(
        [browser, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={out / 'browser'}",
         "--window-size=1440,1100", "--no-first-run", "--disable-gpu", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
    try:
        base.wait_http(URL + "/api/health")
        base.wait_http(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        targets = json.load(urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
        page = base.Cdp(next(item for item in targets if item["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.addScriptToEvaluateOnNewDocument", source=(
            "window.__errors = []; window.alert = m => window.__errors.push('alert: ' + m); window.addEventListener('error', e => window.__errors.push(String(e.message)));"
            "window.addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));"))
        page.call("Emulation.setDeviceMetricsOverride", width=1440, height=1100, deviceScaleFactor=1, mobile=False)
        page.call("Page.navigate", url=URL)
        page.wait("document.readyState === 'complete' && typeof switchTerm === 'function' && !!termClock", 30)
        terms = {item["term_id"]: item for item in json.load(urlopen(URL + "/api/terms"))["terms"]}
        assert set(terms) == {HK3, HK1}

        base.register(page, "Term tester", MSSV)
        page.wait("!!termClock && !document.getElementById('workspaceApp').classList.contains('hidden')")
        # A new account opens in the latest term; its page shows that term's simulated date.
        assert page.js("termClock.term_id") == HK1
        assert "Ngày mô phỏng 29/08/2026" in chip(page), chip(page)
        page.shot("1_hk1_start")

        # HK3: its own date, target and busy schedule, then plan and confirm.
        page.js(f"switchTerm({json.dumps(HK3)})")
        page.wait(f"!termSwitching && termClock.term_id === {json.dumps(HK3)}")
        assert "Ngày mô phỏng 17/05/2026" in chip(page), chip(page)
        assert page.js("document.getElementById('termSelectHeader').value") == HK3
        page.js("""(() => { currentProfileDraft.drl_target = 85; currentProfileDraft.goal.target_score = 85;
          addOnboardingBusyEntry({ category: 'class', weekday: 2, date: '2026-05-20', start: '09:00', end: '11:00' }, 'profile');
          persistCurrentUserData(); })()""")
        hk3_busy = stored(page, "d.profile.busy_schedule.entries.map(e => [e.date, e.start, e.end])")
        assert hk3_busy == [["2026-05-20", "09:00", "11:00"]], hk3_busy
        hk3_plan = plan_and_confirm(page, HK3, "2026-05-17")
        assert stored(page, "d.planner.target_total") == 85
        page.shot("2_hk3_confirmed")
        advanced_day, score, activity_id = advance_and_complete(page)
        advanced_label = date.fromisoformat(advanced_day).strftime("%d/%m/%Y")
        assert stored(page, "d.confirmed_plan") == hk3_plan

        # HK1: nothing of HK3 leaks in; its own target and busy schedule; its own plan.
        page.js(f"switchTerm({json.dumps(HK1)})")
        page.wait(f"!termSwitching && termClock.term_id === {json.dumps(HK1)}")
        assert "Ngày mô phỏng 29/08/2026" in chip(page), chip(page)
        assert stored(page, "d.confirmed_plan") is None
        assert stored(page, "d.profile.busy_schedule.entries.length") == 0
        assert stored(page, "d.profile.drl_target") == 80
        page.js("""(() => { addOnboardingBusyEntry({ category: 'work', weekday: 1, date: '2026-09-08', start: '13:00', end: '15:00' }, 'profile');
          persistCurrentUserData(); })()""")
        hk1_plan = plan_and_confirm(page, HK1, "2026-08-29")
        assert hk1_plan["plan_version"] != hk3_plan["plan_version"]
        page.shot("3_hk1_confirmed")

        # Back to HK3: the advanced date, score and original plan are restored.
        page.js(f"switchTerm({json.dumps(HK3)})")
        page.wait(f"!termSwitching && termClock.term_id === {json.dumps(HK3)}")
        assert f"Ngày mô phỏng {advanced_label}" in chip(page), chip(page)
        assert stored(page, "d.confirmed_plan.plan_version") == hk3_plan["plan_version"]
        assert stored(page, "d.profile.busy_schedule.entries.map(e => [e.date, e.start, e.end])") == hk3_busy
        assert stored(page, "d.profile.drl_target") == 85
        assert stored(page, "d.terms['%s'].confirmed_plan.plan_version" % HK1) == hk1_plan["plan_version"]
        page.wait("!document.getElementById('cpdContent').classList.contains('hidden')")
        page.wait(f"cpdCompletionState?.progress?.score_summary.baseline_total === {score}")

        # Reload: the term the student left and its confirmed plan come back.
        page.call("Page.reload")
        page.wait("typeof switchTerm === 'function' && !!termClock && !!currentStudent && !!cpdCompletionState?.progress", 40)
        page.wait("!document.getElementById('workspaceApp').classList.contains('hidden')", 30)
        assert page.js("termClock.term_id") == HK3
        assert f"Ngày mô phỏng {advanced_label}" in chip(page), chip(page)
        assert stored(page, "d.confirmed_plan.plan_version") == hk3_plan["plan_version"]
        progress = page.js("JSON.parse(JSON.stringify(cpdCompletionState.progress))")
        assert progress["term_id"] == HK3 and progress["as_of"][:10] == advanced_day, progress["as_of"]
        assert progress["activities"][activity_id]["status"] == "COMPLETED"
        assert progress["score_summary"]["baseline_total"] == score
        page.js(f"""logoutLocalAccount();
          document.getElementById('loginMssv').value = {json.dumps(MSSV)};
          document.getElementById('loginPassword').value = 'TestPass2026!';
          document.getElementById('btnSubmitLogin').click();""")
        page.wait(f"currentStudent?.student_id === '{MSSV}' && cpdCompletionState?.progress?.score_summary.baseline_total === {score}")
        assert f"Ngày mô phỏng {advanced_label}" in chip(page), chip(page)

        # The same chip is visible on a phone-sized viewport.
        page.call("Emulation.setDeviceMetricsOverride", width=390, height=844, deviceScaleFactor=2, mobile=True)
        page.call("Emulation.setTouchEmulationEnabled", enabled=True)
        assert page.js("document.getElementById('termPill').getBoundingClientRect().width") > 0
        assert advanced_label in chip(page) and page.js("document.getElementById('termSelectHeader').getBoundingClientRect().width") > 0
        page.js("document.getElementById('simulationDateButton').click()")
        page.wait("document.getElementById('simulationDateDialog').open")
        assert page.js("""(() => {
          const box = document.getElementById('simulationDateDialog').getBoundingClientRect();
          return box.width > 0 && box.left >= 0 && box.right <= innerWidth;
        })()""")
        page.shot("4_mobile_chip")
        page.js("document.getElementById('simulationDateCancel').click(); setSp3Source('synthetic')")
        assert page.js("document.getElementById('simulationDateButton').disabled && !document.getElementById('simulationDateHint').hidden")

        errors = page.js("window.__errors || []")
        assert not [error for error in errors if error != "Uncaught ReferenceError: tailwind is not defined"], errors
        if "Uncaught ReferenceError: tailwind is not defined" in errors:
            print("ENVIRONMENT: Tailwind CDN did not load. Desktop and mobile interaction checks ran without CDN styling.")
        print(f"PASS: plan, review, advance, complete, reload, login, and switch terms. Screenshots: {out}")
        return 0
    finally:
        chrome.terminate()
        server.terminate()


if __name__ == "__main__":
    raise SystemExit(main())
