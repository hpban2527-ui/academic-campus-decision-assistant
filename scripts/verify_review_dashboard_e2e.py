"""Browser check of the confirmed-plan calendar dashboard (REVIEW-DASH).

Drives the real page in a headless Chromium-family browser (Edge or Chrome) through the Chrome
DevTools Protocol, against a real local FastAPI server. It uses only the standard library, so it
needs no Playwright. Run from the repository root:

  python scripts/verify_review_dashboard_e2e.py            # screenshots go to artifacts/review_dashboard/

Exit code 0 means every check passed or no browser is installed (the skip is printed).
Nothing here makes a score official; the page labels demo scores as synthetic.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "artifacts" / "review_dashboard"
SERVER_PORT = 8771
DEBUG_PORT = 9335
BASE = f"http://127.0.0.1:{SERVER_PORT}"
BROWSERS = (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
)


class Cdp:
    """A minimal WebSocket client for one DevTools page target."""

    def __init__(self, url: str) -> None:
        host_port, path = url[len("ws://"):].split("/", 1)
        host, port = host_port.split(":")
        self.sock = socket.create_connection((host, int(port)), timeout=60)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((
            f"GET /{path} HTTP/1.1\r\nHost: {host_port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        ).encode())
        header = b""
        while b"\r\n\r\n" not in header:
            header += self.sock.recv(1)
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        assert accept in header.decode(), "WebSocket handshake failed"
        self.next_id = 0

    def _read(self, count: int) -> bytes:
        data = b""
        while len(data) < count:
            chunk = self.sock.recv(count - len(data))
            if not chunk:
                raise ConnectionError("DevTools connection closed")
            data += chunk
        return data

    def _frame(self) -> bytes:
        payload = b""
        while True:
            first, second = self._read(2)
            length = second & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload += self._read(length)
            if first & 0x80:
                return payload

    def call(self, method: str, **params):
        self.next_id += 1
        body = json.dumps({"id": self.next_id, "method": method, "params": params}).encode()
        mask = os.urandom(4)
        header = bytes([0x81])
        if len(body) < 126:
            header += bytes([0x80 | len(body)])
        elif len(body) < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", len(body))
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", len(body))
        self.sock.sendall(header + mask + bytes(byte ^ mask[index % 4] for index, byte in enumerate(body)))
        while True:
            message = json.loads(self._frame())
            if message.get("id") == self.next_id:
                if "error" in message:
                    raise RuntimeError(f"{method}: {message['error']}")
                return message["result"]

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        if "exceptionDetails" in result:
            raise RuntimeError(result["exceptionDetails"].get("exception", {}).get("description", str(result)))
        return result["result"].get("value")

    def shot(self, name: str) -> None:
        data = self.call("Page.captureScreenshot", format="png")["data"]
        (OUT / f"{name}.png").write_bytes(base64.b64decode(data))

    def wait(self, expression: str, timeout: float = 20.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self.js(expression):
                return
            time.sleep(0.2)
        raise AssertionError(f"timed out waiting for: {expression}")


def find_browser() -> str | None:
    return next((path for path in BROWSERS if Path(path).exists()), None) or shutil.which("chromium")


def wait_http(url: str) -> None:
    for _ in range(120):
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.5)
    raise RuntimeError(f"{url} did not become ready")


def register(page: Cdp, name: str, mssv: str, *, plan_onboarding: bool = False, target: int = 80) -> None:
    page.js("showWorkspace()")
    page.js("setAuthMode('register')")
    page.js(f"""(() => {{
      document.getElementById('registerName').value = {json.dumps(name)};
      document.getElementById('registerMssv').value = {json.dumps(mssv)};
      document.getElementById('registerPassword').value = 'TestPass2026!';
      document.getElementById('registerPasswordConfirm').value = 'TestPass2026!';
      document.getElementById('btnSubmitRegister').click();
    }})()""")
    page.wait(f"!!onboardingDraft && onboardingDraft.student_id === {json.dumps(mssv)} "
              "&& !document.getElementById('onboardingModal').classList.contains('hidden')")
    if plan_onboarding:
        count_sp3_calls(page)
        page.js(f"""onboardingStep = 3;
          selectOnboardingTargetPreset({target}); selectOnboardingCategoryChoice('ANY');
          selectOnboardingModeChoice('any'); selectOnboardingCampusChoice('any');
          finishOnboardingTopics(true); renderOnboardingStep();
          document.getElementById('onboardingNextButton').click();""")
    else:
        # Other scenarios use a saved account fixture and exercise planning separately.
        # The real onboarding transition is covered with plan_onboarding=True below.
        page.js("""(() => { const hook = window.reviewDashAfterOnboarding;
          window.reviewDashAfterOnboarding = undefined;
          try { completeOnboarding(); finishWelcome(); }
          finally { window.reviewDashAfterOnboarding = hook; } })()""")
    page.wait(f"!!currentStudent && currentStudent.student_id === {json.dumps(mssv)}")
    if not plan_onboarding:
        page.js("applyCurrentStudent(currentStudent)")
    page.wait("!document.getElementById('workspaceApp').classList.contains('hidden')")


def visible(page: Cdp, element_id: str) -> bool:
    return bool(page.js(f"(() => {{ const el = document.getElementById({json.dumps(element_id)}); return !!el && !el.classList.contains('hidden'); }})()"))


PREFERENCE = {
    "topic_preferences": [{"topic_id": "mathematics", "weight": 5}, {"topic_id": "artificial_intelligence", "weight": 4}],
    "category_priorities": [{"category_id": "C4", "weight": 5}],
    "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
    "mode_preferences": [{"mode": "online", "weight": 5}],
    "time_preferences": [{"time_slot": "weekday_evening", "weight": 4}],
    "limits": {"max_activities": 4, "max_duration_minutes": None, "max_fee": 200000},
    "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
    "strategy": "BALANCED",
}


def stored_plan(page: Cdp) -> dict | None:
    return json.loads(page.js("JSON.stringify(readLocalUserData(currentStudent.student_id).confirmed_plan)"))


def change_review_and_confirm(page: Cdp, tag: str, mobile: bool) -> dict:
    """Exercise the shared panel, undo, remove-only, confirmation and dashboard diff cancellation."""
    assert page.js("Array.from(document.querySelectorAll('[data-review-actions]')).every(el => el.querySelectorAll('button').length === 1)")
    button = "document.querySelector('[data-review-actions] button')"
    page.js(f"{button}.focus(); {button}.click()")
    page.wait("prvDraft.panel.mode === 'change' && !prvDraft.busy")
    assert page.js("document.querySelectorAll('#prvChangePanel').length") == 1
    assert page.js("document.activeElement.id") == "prvChangePanel"
    assert page.js("!!document.querySelector('#prvChangePanel [data-change-impact]')")
    assert page.js("!!document.querySelector('#prvList [data-review-row] #prvChangePanel')") == mobile
    assert page.js("prvDraft.steps.length") == 0
    press(page, "Escape", "Escape", 27)
    assert page.js("document.activeElement.matches('[data-review-actions] button')")
    page.js(f"{button}.click()")
    page.wait("prvDraft.panel.mode === 'change' && !prvDraft.busy")
    items = page.js("prvDraft.panel.alternatives.data.items.length")
    assert items > 0, "the synthetic fixture must offer a replacement"
    assert page.js("document.querySelectorAll('#prvChangePanel button[onclick^=\"prvApplyAlternative\"]').length") == min(3, items)
    if items > 3:
        page.js("document.getElementById('prvMoreChanges').click()")
        assert page.js("document.querySelectorAll('#prvChangePanel button[onclick^=\"prvApplyAlternative\"]').length") == items
    assert page.js("!!document.querySelector('[data-change-suggestion]')") == page.js("prvDraft.panel.suggestion.data.added_activity_ids.length >= 2")
    page.shot(f"change_{tag}_1_panel")
    page.js("document.getElementById('prvChoose-0').click()")
    assert "Đã đổi" in page.js("document.getElementById('prvList').innerText")
    page.js("document.querySelector('#prvList button[onclick^=\"prvUndo\"]').click()")
    assert page.js("prvDraft.steps.length") == 0
    before = page.js("prvActivities(prvDraft.result).map(a => a.activity_id)")
    page.js(f"{button}.click()")
    page.wait("prvDraft.panel.mode === 'change' && !prvDraft.busy")
    impact = page.js("JSON.parse(JSON.stringify(prvDraft.panel.impact.data))")
    assert not impact["target_met"], "the synthetic removal fixture must fall below target"
    assert page.js("document.getElementById('prvRemoveChoice').innerText") == f"Bỏ, không thay (còn {impact['projected_total']}/{impact['target_total']})"
    page.js("document.getElementById('prvRemoveChoice').click()")
    after = page.js("prvActivities(prvDraft.result).map(a => a.activity_id)")
    assert len(after) == len(before) - 1 and set(after) < set(before)
    assert "Đã bỏ" in page.js("document.getElementById('prvList').innerText")
    assert page.js("prvDraft.result.plan.plan_version") == impact["result"]["plan"]["plan_version"]
    page.js("document.querySelector('#prvPanel button[onclick=\"prvConfirm()\"]').click()")
    page.wait("document.getElementById('planReviewScreen').classList.contains('hidden') && !document.getElementById('cpdContent').classList.contains('hidden')")
    confirmed = stored_plan(page)
    assert sorted(a["activity_id"] for a in confirmed["activities"]) == sorted(after)
    assert confirmed["plan_version"] == impact["result"]["plan"]["plan_version"]
    activity_id = confirmed["activities"][0]["activity_id"]
    page.js(f"cpdOpenActivity(activityToken({json.dumps(activity_id)}))")
    page.js("document.querySelector('#cpdDetail button[onclick^=\"cpdOpenChange\"]').focus(); document.activeElement.click()")
    page.wait("prvDraft?.origin === 'dashboard' && !prvDraft.busy")
    page.js("document.getElementById('prvRemoveChoice').click()")
    assert visible(page, "planDiffModal")
    assert stored_plan(page) == confirmed
    page.shot(f"change_{tag}_2_diff")
    page.js("document.querySelector('#planDiffModal button[onclick=\"cpdConfirmDiffCancel()\"]').click()")
    assert not visible(page, "planDiffModal") and stored_plan(page) == confirmed
    page.js("document.getElementById('prvCancelChange').click()")
    assert page.js("document.activeElement.id.startsWith('cpd-change-')")
    return confirmed


def review_flow(page: Cdp) -> None:
    """Review edits, dashboard cancellation, invalidation and confirmed replanning."""
    register(page, "Review tester", "RVW2028")
    page.js(f"confirmedPreference = {json.dumps(PREFERENCE)}; preferenceDraft = confirmedPreference;")
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!!planStages.first && cachedPlanOptions.length > 0", 40)
    close_options(page)
    assert visible(page, "confirmPlanBar")
    assert page.js("document.getElementById('btnOpenReview').innerText.trim()") == "Review kế hoạch"

    # Review screen: rows, summary, 0 violations.
    page.js("document.getElementById('btnOpenReview').click()")
    assert visible(page, "planReviewScreen")
    rows = page.js("document.querySelectorAll('#prvList article').length")
    assert rows >= 3, rows
    summary = page.js("document.getElementById('prvPanel').innerText")
    target_met = page.js("prvDraft.result.plan.score_summary.remaining_total === 0")
    assert ("Đạt mục tiêu" if target_met else "Chưa đạt mục tiêu") in summary and "0 vi phạm" in summary, summary
    page.shot("review_1_open")

    plan = change_review_and_confirm(page, "review_desktop", False)

    # Change the busy schedule: the plan is flagged as affected.
    page.js("""(() => { customBusyIntervals.push({ start: '2026-11-09T08:00:00+07:00', end: '2026-11-09T12:00:00+07:00' });
      persistCurrentUserData(); renderConfirmedPlanDashboard(); })()""")
    assert visible(page, "cpdBannerInvalid")
    assert "Kế hoạch bị ảnh hưởng" in page.js("document.getElementById('cpdBannerInvalid').innerText")
    page.shot("review_5_invalidated")

    # Replan with the new busy time: the new plan is offered, the old one stays until confirmed.
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!!planStages.first && !document.getElementById('btnRunPlanner').disabled")
    close_options(page)
    assert visible(page, "confirmPlanBar")
    assert stored_plan(page)["plan_version"] == plan["plan_version"], "replanning must not overwrite the confirmed plan"
    new_plan = json.loads(page.js("JSON.stringify(planStages.first.plan)"))
    page.js("document.getElementById('btnConfirmPlan').click()")
    assert visible(page, "planDiffModal")
    diff = page.js("document.getElementById('planDiffBody').innerText")
    old_total = plan["score_summary"]["projected_total"]
    new_total = new_plan["score_summary"]["projected_total"]
    assert f"{old_total}đ → {new_total}đ" in diff, diff
    for label in ("Thêm mới", "Bị bỏ", "Đổi giờ", "Giữ nguyên"):
        assert label in diff, label
    counts = []
    for label in ("Thêm mới", "Đổi giờ", "Giữ nguyên"):
        heading = page.js(f"document.querySelector('[data-diff=\"{label}\"] h4').innerText")
        counts.append(int(heading.split("(")[1].rstrip(")")))
    assert sum(counts) == len(new_plan["selected_activities"]), (counts, diff)
    page.shot("review_6_diff")
    page.js("document.getElementById('btnConfirmDiff').click()")
    page.wait("!document.getElementById('viewDashboard').classList.contains('hidden')")
    updated = stored_plan(page)
    assert updated["plan_version"] == new_plan["plan_version"]
    assert not visible(page, "cpdBannerPending") and not visible(page, "cpdBannerInvalid")
    agenda = page.js("document.getElementById('cpdCalendar').innerText")
    for item in updated["activities"]:
        assert item["title"] in agenda, item["title"]
    page.shot("review_7_dashboard_updated")


OPTION_NAMES = {"MINIMUM_EFFORT": "Ít thời gian", "BALANCED": "Cân bằng", "PREFERENCE_FIRST": "Theo sở thích"}


def close_options(page: Cdp) -> None:
    """Screen 05 opens by itself after every first plan; the older flows below work on the planner page."""
    page.js("reviewDashClosePlanOptions()")
    assert not visible(page, "planOptionsScreen")


def press(page: Cdp, key: str, code: str, key_code: int) -> None:
    for kind in ("keyDown", "keyUp"):
        page.call("Input.dispatchKeyEvent", type=kind, key=key, code=code, windowsVirtualKeyCode=key_code)


def count_sp3_calls(page: Cdp) -> None:
    """Counts fetch() calls to /api/sp3/ so a test can prove a click did not recompute anything."""
    page.js("""(() => { window.__sp3Calls = 0; if (window.__fetchWrapped) return; window.__fetchWrapped = true;
      const original = window.fetch.bind(window);
      window.fetch = (...args) => { if (String(args[0]).includes('/api/sp3/')) window.__sp3Calls += 1; return original(...args); }; })()""")


def options_flow(page: Cdp, tag: str, mssv: str, mobile: bool) -> None:
    """plan -> screen 05 (auto) -> Esc -> reopen -> second card -> review -> back -> review -> swap -> confirm ->
    dashboard shows the option label; then plan again -> "Xac nhan luon" (diff) -> dashboard."""
    register(page, f"Options {tag}", mssv)
    page.js(f"confirmedPreference = {json.dumps(PREFERENCE)}; preferenceDraft = confirmedPreference;")
    count_sp3_calls(page)
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!!planStages.first && cachedPlanOptions.length > 0", 40)
    page.wait("!document.getElementById('planOptionsScreen').classList.contains('hidden')")

    screen = "document.getElementById('planOptionsScreen')"
    assert page.js(f"{screen}.getAttribute('role')") == "dialog" and page.js(f"{screen}.getAttribute('aria-modal')") == "true"
    assert page.js(f"{screen}.contains(document.activeElement)"), "focus must move into the dialog"
    assert "Mục tiêu 80 điểm · Dữ liệu giả lập" in page.js("document.getElementById('posSubtitle').innerText")
    options = page.js("cachedPlanOptions.map(o => ({s: o.strategy, t: o.projected_total, n: o.activity_count, m: o.duration_minutes, met: o.target_met}))")
    cards = page.js("document.querySelectorAll('#posCards [data-pos-card]').length")
    assert cards == len(options) and 1 <= cards <= 3, (cards, options)
    assert page.js("document.getElementById('posCards').innerText").count("Gợi ý") == 1
    for index, option in enumerate(options):
        text = page.js(f"document.querySelector('[data-pos-card=\"{index}\"]').innerText")
        hours = f"{int(option['m'] / 6 + 0.5) / 10:g}"
        assert OPTION_NAMES[option["s"]] in text and f"{option['t']}đ" in text and "/ mục tiêu 80đ" in text, text
        assert f"{option['n']} hoạt động · {hours} giờ" in text, (hours, text)
        assert "Độ hợp sở thích" in text and "Chọn & review" in text and "Xác nhận luôn" in text, text
        assert ("Đạt mục tiêu" in text and "Chưa đạt" not in text) == bool(option["met"]), text
    note = page.js("document.getElementById('posNote').innerText")
    assert ("Một số chiến lược cho ra cùng một lịch nên đã được gộp." in note) == (cards < 3), note
    assert "điểm rèn luyện chính thức do trường công nhận" in page.js(f"{screen}.innerText")
    if page.js("getComputedStyle(document.querySelector('#posCards > div')).display") == "grid":
        tops = page.js("[...document.querySelectorAll('#posCards [data-pos-card]')].map(c => Math.round(c.getBoundingClientRect().top))")
        lefts = page.js("[...document.querySelectorAll('#posCards [data-pos-card]')].map(c => Math.round(c.getBoundingClientRect().left))")
        if mobile:
            assert tops == sorted(set(tops)) and len(set(lefts)) == 1, ("cards must stack on mobile", tops, lefts)
            assert page.js(f"{screen}.scrollWidth <= {screen}.clientWidth + 1"), "no horizontal scroll on mobile"
        elif cards == 3:
            assert len(set(tops)) == 1, ("3 columns on desktop", tops)
    else:
        print("note: Tailwind CDN not reachable (offline?); layout assertions skipped")
    page.shot(f"options_{tag}_1_screen")

    # Esc closes it and focus leaves the dialog; the confirm bar reopens it without any API call.
    press(page, "Escape", "Escape", 27)
    assert not visible(page, "planOptionsScreen"), "Esc must close screen 05"
    page.wait(f"!{screen}.contains(document.activeElement)")
    assert not page.js("document.body.classList.contains('overflow-hidden')")
    page.js("window.__sp3Calls = 0")
    page.js("document.getElementById('btnOpenPlanOptions').click()")
    assert visible(page, "planOptionsScreen") and page.js("window.__sp3Calls") == 0

    # Second card -> review (cached option, no API call), back link, review again.
    pick = 1 if cards > 1 else 0
    label = OPTION_NAMES[options[pick]["s"]]
    page.js(f"document.querySelector('[data-pos-card=\"{pick}\"] [data-pos-action=\"review\"]').click()")
    assert not visible(page, "planOptionsScreen") and visible(page, "planReviewScreen")
    assert page.js("selectedPlanOptionIndex") == pick and page.js("prvDraft.optionLabel") == label
    assert page.js(f"prvDraft.result.plan.plan_version === cachedPlanOptions[{pick}].result.plan.plan_version")
    assert label in page.js("document.getElementById('prvSubtitle').innerText")
    page.shot(f"options_{tag}_2_review")
    page.js("document.getElementById('prvBackToOptions').click()")
    assert visible(page, "planOptionsScreen") and not visible(page, "planReviewScreen")
    assert page.js("window.__sp3Calls") == 0, "choosing a card and going back must not call the API"
    page.js(f"document.querySelector('[data-pos-card=\"{pick}\"] [data-pos-action=\"review\"]').click()")
    assert visible(page, "planReviewScreen")

    plan = change_review_and_confirm(page, tag, mobile)
    assert label in page.js("document.getElementById('cpdToday').innerText")
    page.shot(f"options_{tag}_3_dashboard")

    # Plan again; "Xac nhan luon" on the first card goes through the diff modal because a plan is confirmed.
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!document.getElementById('btnRunPlanner').disabled && !document.getElementById('planOptionsScreen').classList.contains('hidden')")
    assert stored_plan(page)["plan_version"] == plan["plan_version"], "planning must not touch the confirmed plan"
    first_label = OPTION_NAMES[page.js("cachedPlanOptions[0].strategy")]
    first_version = page.js("cachedPlanOptions[0].result.plan.plan_version")
    page.js("document.querySelector('[data-pos-card=\"0\"] [data-pos-action=\"confirm\"]').click()")
    assert visible(page, "planDiffModal"), "a diff must be shown before replacing a confirmed plan"
    page.shot(f"options_{tag}_4_confirm_diff")
    page.js("document.getElementById('btnConfirmDiff').click()")
    page.wait("!document.getElementById('viewDashboard').classList.contains('hidden')")
    assert not visible(page, "planOptionsScreen") and not visible(page, "planDiffModal")
    updated = stored_plan(page)
    assert updated["plan_version"] == first_version and updated["option_label"] == first_label, updated["option_label"]


def confirm_now_without_a_plan(page: Cdp, mssv: str) -> None:
    """"Xac nhan luon" with nothing confirmed yet goes straight to the dashboard (no diff modal)."""
    register(page, "Confirm now", mssv)
    page.js(f"confirmedPreference = {json.dumps(PREFERENCE)}; preferenceDraft = confirmedPreference;")
    page.js("switchTab('plan'); runSp3Planner();")
    page.wait("!!planStages.first && !document.getElementById('planOptionsScreen').classList.contains('hidden')", 40)
    page.js("document.querySelector('[data-pos-card] [data-pos-action=\"confirm\"]').click()")
    page.wait("!document.getElementById('viewDashboard').classList.contains('hidden') && !document.getElementById('cpdContent').classList.contains('hidden')")
    assert not visible(page, "planDiffModal") and not visible(page, "planOptionsScreen")
    assert stored_plan(page)["option_label"] in OPTION_NAMES.values()


def friendly_errors(page: Cdp, mssv: str) -> None:
    """Real-source planning works; an older server's 422 still receives the friendly Vietnamese mapping."""
    assert page.js("reviewDashFriendlyError('plan review is not yet available for source=real', 'real')").startswith(
        "Chức năng này chưa hỗ trợ kho bài thật. Hãy chuyển nguồn dữ liệu sang “Dữ liệu giả lập (MVP)”")
    assert page.js("reviewDashFriendlyError('Failed to fetch', 'synthetic')") == "Không kết nối được máy chủ. Hãy kiểm tra server rồi thử lại."
    assert page.js("reviewDashFriendlyError('boom')") == "Không thể lập kế hoạch: boom"
    register(page, "Real source", mssv)
    page.js(f"confirmedPreference = {json.dumps(PREFERENCE)}; preferenceDraft = confirmedPreference;")
    page.js("SP3_SOURCE = 'real'")
    try:
        page.js("switchTab('plan'); runSp3Planner();")
        page.wait("!!planStages.first && !document.getElementById('planOptionsScreen').classList.contains('hidden')", 40)
        assert page.js("planStages.first.data_source") == "SP1-STORE-V2"
        close_options(page)
        # Simulate an older server for the compatibility error case; no model is called.
        page.js("""window.__reviewOriginalFetch = window.fetch;
          window.fetch = (url, options) => String(url).includes('/personalized/options')
            ? Promise.resolve(new Response(JSON.stringify({detail:'multi-strategy options are not yet available for source=real'}), {status:422,headers:{'Content-Type':'application/json'}}))
            : window.__reviewOriginalFetch(url, options);""")
        page.js("runSp3Planner()")
        page.wait("document.getElementById('plannerEmptyState').innerText.includes('chưa hỗ trợ kho bài thật')", 40)
        assert not visible(page, "planOptionsScreen"), "a failed plan must not open screen 05"
    finally:
        page.js("if (window.__reviewOriginalFetch) { window.fetch = window.__reviewOriginalFetch; delete window.__reviewOriginalFetch; } SP3_SOURCE = 'synthetic';")


def after_onboarding(page: Cdp, mssv_saved: str, mssv_missing: str) -> None:
    """Final onboarding click -> one plan request -> options -> review -> confirm -> dashboard."""
    register(page, "After onboarding", mssv_saved, plan_onboarding=True, target=70)
    page.wait("!!planStages.first && !document.getElementById('planOptionsScreen').classList.contains('hidden')", 40)
    assert page.js("document.getElementById('inputPlanTarget').value") == "70"
    assert page.js("planStages.first.requested_total_target") == 70
    assert not page.js("document.getElementById('viewPlan').classList.contains('hidden')"), "planner page must be shown"
    assert page.js("window.__sp3Calls") == 1, "the first plan must be requested exactly once"
    assert not visible(page, "welcomeModal")
    assert stored_plan(page) is None, "profile completion must not confirm a plan"
    assert "Mục tiêu 70 điểm" in page.js("document.getElementById('posSubtitle').innerText")
    assert page.js("runSp3Planner.name") == "runSp3Planner", "the temporary stub must be removed again"
    page.js("document.querySelector('[data-pos-card] [data-pos-action=\"review\"]').click()")
    assert visible(page, "planReviewScreen") and stored_plan(page) is None
    assert page.js("prvDraft.result.requested_total_target") == 70
    page.js("document.querySelector('#prvPanel button[onclick=\"prvConfirm()\"]').click()")
    page.wait("!document.getElementById('viewDashboard').classList.contains('hidden') && !!readLocalUserData(currentStudent.student_id).confirmed_plan")
    assert stored_plan(page)["target_total"] == 70

    page.js("logoutLocalAccount()")
    page.js("showWorkspace()")
    register(page, "No saved goal", mssv_missing)
    # Model an unset goal at the read boundary. Registration and profile
    # migration normally supply a default before this helper runs.
    page.js("""(() => {
      const read = readLocalUserData;
      const studentId = currentStudent.student_id;
      window.readLocalUserData = id => {
        const data = read(id);
        if (id === studentId) data.profile.drl_target = null;
        return data;
      };
      currentProfileDraft.drl_target = null;
      window.__sp3Calls = 0;
      try { reviewDashAfterOnboarding(); } finally { window.readLocalUserData = read; }
    })()""")
    page.wait("!!document.getElementById('rdTargetPrompt')")
    assert page.js("document.getElementById('rdTargetPrompt').innerText") == "Bạn muốn đạt bao nhiêu điểm rèn luyện học kỳ này?"
    assert page.js("document.activeElement.id") == "inputPlanTarget"
    time.sleep(1.0)
    assert not page.js("!!planStages.first") and page.js("window.__sp3Calls") == 0, "no silent default plan"
    assert not visible(page, "planOptionsScreen")


def real_source_clock(page: Cdp) -> None:
    """The dashboard's "Hom nay" follows the confirmed plan's source: the real store's demo date is 2026-10-01."""
    register(page, "Real clock", "RVW2030")
    page.js("""(async () => {
      const response = await fetch('/api/sp3/demo/plan?source=real', { method: 'POST',
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scenario: 'first_plan', total_target: 80, busy_intervals: [] }) });
      confirmConfirmedPlan(await response.json(), 'Kho thật');
      switchTab('dashboard');
    })()""")
    header = page.js("document.getElementById('cpdToday').innerText")
    assert "01/10/2026" in header, header
    agenda = page.js("document.getElementById('cpdCalendar').innerText")
    # Every real activity starts more than a week after that date, so today's agenda is empty.
    assert "Hoạt động gần nhất diễn ra vào" in agenda and "25/10/2026" in agenda, agenda
    page.shot("review_8_real_clock")


def completion_flow(page: Cdp) -> None:
    """Confirm an activity in the browser, then verify the persisted capped award."""
    register(page, "Completion test student", "RVW2050")
    page.js("""(async () => {
        SP3_SOURCE = 'synthetic';
        planStages.first = await fetchSp3Plan('first_plan', 80, []);
        currentPlanStage = 'first';
        confirmCurrentPlanFromUi();
    })()""")
    page.wait("readLocalUserData(currentStudent.student_id).confirmed_plan?.completion_synced && !cpdCompletionState?.loading")

    def open_activity(activity_id: str) -> None:
        page.js(f"""(() => {{
            const action = "cpdOpenActivity('" + activityToken({json.dumps(activity_id)}) + "')";
            document.querySelector('#cpdCalendar button[onclick="' + action + '"]').click();
        }})()""")

    open_activity("SEM-A")
    assert "+5đ dự kiến" in page.js("document.getElementById('cpdDetail').innerText")
    open_activity("QUIZ-M")
    assert "8/10 câu" in page.js("document.getElementById('cpdDetail').innerText")
    page.wait("document.getElementById('cpdConfirmCompletion')?.disabled === false")
    page.js("document.getElementById('cpdConfirmCompletion').click()")
    page.wait("document.querySelector('[data-cpd-completed]')?.textContent.endsWith('+5 điểm')")
    assert page.js("studentCategoryScores.C1.current") == 27

    open_activity("SEM-A")
    page.wait("document.getElementById('cpdConfirmCompletion')?.disabled === false")
    page.js("document.getElementById('cpdConfirmCompletion').click()")
    page.wait("document.querySelector('[data-cpd-completed]')?.textContent.endsWith('+3 điểm')")
    assert page.js("studentCategoryScores.C1.current") == 30
    assert page.js("!Object.hasOwn(cpdCompletionState.progress.projected_by_activity, 'SEM-A')")
    assert page.js("cpdCompletionState.progress.score_summary.baseline_total") == 65
    page.shot("completion_capped_award")

    # Simulate a stale local score cache. Reload must fetch the saved result
    # and refresh both the dashboard and score tracker from the server.
    page.js("""(() => {
        const data = readLocalUserData(currentStudent.student_id);
        data.category_scores.C1.current = 22;
        data.saved_activities = [];
        localStorage.setItem(localUserDataKey(currentStudent.student_id), JSON.stringify(data));
    })()""")
    page.call("Page.reload")
    page.wait("typeof currentStudent !== 'undefined' && currentStudent?.student_id === 'RVW2050' && !!cpdCompletionState?.progress")
    page.js("showWorkspace(); switchTab('dashboard');")
    open_activity("SEM-A")
    page.wait("document.querySelector('[data-cpd-completed]')?.textContent.endsWith('+3 điểm')")
    assert page.js("studentCategoryScores.C1.current") == 30
    assert not page.js("!!document.getElementById('cpdConfirmCompletion')")
    retry = page.js("""(async () => {
        const reply = await fetch('/api/sp3/confirmed-plan/complete', {
            method: 'POST', headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({student_id: currentStudent.student_id, plan_version: cpdCompletionState.version,
                                  activity_id: 'SEM-A', affirmed: true})
        });
        return (await reply.json()).scores;
    })()""")
    assert retry["category_scores"]["C1"]["current"] == 30
    assert len(retry["saved_activities"]) == 2


def main() -> int:
    browser = find_browser()
    if browser is None:
        print("SKIP: no Edge/Chrome/Chromium found; use the manual checklist in docs/adr.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    profile = tempfile.mkdtemp(prefix="review-dash-")
    session_file = Path(profile) / "test-session.json"
    session_file.write_text(json.dumps({
        "schema_version": 3,
        "session_scores": {"RVW2050": {
            "current": {"C1": 22, "C2": 15, "C3": 10, "C4": 10, "C5": 0},
            "projected": {"C1": 0, "C2": 0, "C3": 0, "C4": 0, "C5": 0},
        }},
    }), encoding="utf-8")
    env = {
        **os.environ, "PYTHONPATH": str(ROOT / "src"), "UNILIFE_SESSION_FILE": str(session_file),
        "UNILIFE_COMPLETION_AS_OF": "2026-11-16T08:00:00+07:00",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    chrome = subprocess.Popen(
        [browser, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={Path(profile) / 'browser'}",
         "--window-size=1440,1100", "--no-first-run", "--disable-gpu", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    try:
        wait_http(BASE + "/api/health")
        wait_http(f"http://127.0.0.1:{DEBUG_PORT}/json/version")
        targets = json.load(urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
        page = Cdp(next(item for item in targets if item["type"] == "page")["webSocketDebuggerUrl"])
        page.call("Page.enable")
        page.call("Runtime.enable")
        page.call("Page.addScriptToEvaluateOnNewDocument", source=(
            "window.__errors = []; window.addEventListener('error', e => window.__errors.push(String(e.message)));"
            "window.addEventListener('unhandledrejection', e => window.__errors.push(String(e.reason)));"
        ))
        page.call("Emulation.setDeviceMetricsOverride", width=1440, height=1100, deviceScaleFactor=1, mobile=False)
        page.call("Page.navigate", url=BASE)
        page.wait("document.readyState === 'complete' && typeof confirmConfirmedPlan === 'function'")

        if "--completion-only" in sys.argv:
            completion_flow(page)
            assert not page.js("window.__errors || []")
            print("PASS: dashboard completion, capped award, reload and retry")
            return 0

        # 1. Empty state: a brand-new account has nothing confirmed.
        register(page, "Synthetic test student", "RVW2026")
        page.js("confirmedPreference = null; preferenceDraft = null;")
        page.js("switchTab('dashboard')")
        assert visible(page, "cpdEmpty") and not visible(page, "cpdContent"), "empty state expected"
        assert "chưa chốt kế hoạch nào" in page.js("document.getElementById('cpdEmpty').innerText")
        assert not visible(page, "cpdBannerPending") and not visible(page, "cpdBannerInvalid")
        page.shot("1_empty_state")

        # 2. Plan, then confirm from the planner screen.
        page.js("switchTab('plan'); runSp3Planner();")
        page.wait("!!planStages.first && !document.getElementById('plannerActiveResult').classList.contains('hidden')", 40)
        # The onboarding profile can supply the confirmed preference on the first plan run.
        assert visible(page, "planOptionsScreen"), "screen 05 opens after the first plan"
        cards = page.js("document.querySelectorAll('#posCards [data-pos-card]').length")
        if page.js("!!confirmedPreference"):
            assert cards == 3
        else:
            assert cards == 1
            single = page.js("document.getElementById('planOptionsScreen').innerText")
            assert "Kế hoạch đề xuất" in single and "Xác nhận nguyện vọng để so sánh 3 phương án." in single, single
            assert "Gợi ý" not in single and "Độ hợp sở thích" not in single
        close_options(page)
        assert visible(page, "confirmPlanBar"), "confirm bar must sit next to the plan result"
        assert page.js("document.getElementById('btnConfirmPlan').innerText.trim()") == "Xác nhận kế hoạch"
        page.shot("2_plan_with_confirm_bar")
        page.js("document.getElementById('btnConfirmPlan').click()")
        page.wait("!document.getElementById('viewDashboard').classList.contains('hidden') && !document.getElementById('cpdContent').classList.contains('hidden')")

        stored = json.loads(page.js("JSON.stringify(readLocalUserData(currentStudent.student_id).confirmed_plan)"))
        assert stored["activities"], "confirmed plan lists activities"
        for key in ("plan_version", "based_on", "confirmed_at", "source", "option_label", "target_total",
                    "score_summary", "activities", "as_of"):
            assert key in stored, key
        first = stored["activities"][0]
        for key in ("activity_id", "title", "criterion", "effective_gain", "mode", "campus", "location",
                    "registration_deadline", "completion_requirements", "scheduled_blocks", "source_url"):
            assert key in first, key
        # Numbers on the page are the engine's, not the calculator's.
        summary = stored["score_summary"]
        text = page.js("document.getElementById('cpdProgress').innerText")
        assert f"{summary['baseline_total']}đ" in text and f"{summary['projected_total']}đ" in text, text
        assert f"{stored['target_total']}đ" in text
        assert "còn 80đ" not in page.js("document.getElementById('cpdContent').innerText").lower()
        assert page.js("document.getElementById('overviewDrlScore').offsetParent === null"), "old overview cards stay hidden"

        # 3. Today view: the demo date, not the system date.
        header = page.js("document.getElementById('cpdToday').innerText")
        assert stored["as_of"][:10][8:10] + "/" + stored["as_of"][:10][5:7] in header, header
        agenda = page.js("document.getElementById('cpdCalendar').innerText")
        for activity in stored["activities"]:
            assert activity["title"] in agenda, activity["title"]
        assert "Hạn đăng ký" in agenda
        page.shot("3_today_agenda")

        # 4. Week view with a faded busy schedule, then month view.
        page.js("""(() => { customBusyIntervals.push({ start: '2026-11-10T13:00:00+07:00', end: '2026-11-10T16:00:00+07:00' });
          persistCurrentUserData(); setConfirmedPlanView('week'); })()""")
        busy_blocks = page.js("document.querySelectorAll('#cpdCalendar [title=\"Lịch bận của bạn\"]').length")
        assert busy_blocks >= 1, "busy schedule must be drawn as a faded background"
        assert page.js("document.querySelectorAll('#cpdCalendar .plan-calendar-event').length") >= 1
        page.shot("4_week_view")
        page.js("setConfirmedPlanView('month')")
        assert "Tháng 11/2026" in page.js("document.getElementById('cpdCalendar').innerText")
        page.shot("5_month_view")

        # 5. An availability change after confirming marks the plan as affected.
        assert visible(page, "cpdBannerInvalid"), "changing the busy schedule must invalidate the plan"
        assert "Lịch rảnh/bận" in page.js("document.getElementById('cpdInvalidReason').innerText")
        page.shot("6_invalidated_banner")

        # 6. Re-running the planner raises a notice and leaves the confirmed plan alone.
        before = page.js("JSON.stringify(readLocalUserData(currentStudent.student_id).confirmed_plan)")
        page.js("switchTab('plan'); runSp3Planner()")
        page.wait("!document.getElementById('btnRunPlanner').disabled && !!planStages.first")
        close_options(page)
        page.js("switchTab('dashboard')")
        assert visible(page, "cpdBannerPending"), "pending-plan banner expected"
        assert "Có kế hoạch mới chưa chốt" in page.js("document.getElementById('cpdBannerPending').innerText")
        after = page.js("JSON.stringify(readLocalUserData(currentStudent.student_id).confirmed_plan)")
        assert before == after, "re-running the planner must not overwrite the confirmed plan"
        page.shot("7_pending_banner")
        page.js("document.querySelector('#cpdBannerPending button').click()")
        assert not page.js("document.getElementById('viewPlan').classList.contains('hidden')"), "banner button opens Lập lịch"

        # 7. Click an event: the detail panel opens with the activity's fields.
        page.js("switchTab('dashboard'); setConfirmedPlanView('today')")
        page.js("document.querySelector('#cpdCalendar button[onclick^=\"cpdOpenActivity\"]').click()")
        assert visible(page, "cpdDetail")
        detail = page.js("document.getElementById('cpdDetail').innerText")
        assert "Thời gian tổ chức" in detail and "Quyền lợi ĐRL" in detail
        page.shot("8_activity_detail")

        # 8. Confirming again shows what changes first, then replaces the plan and clears both banners.
        page.js("switchTab('plan'); runSp3Planner();")
        page.js("document.getElementById('btnConfirmPlan').click()")
        assert visible(page, "planDiffModal"), "a diff must be shown before replacing a confirmed plan"
        page.js("document.getElementById('btnConfirmDiff').click()")
        page.wait("!document.getElementById('viewDashboard').classList.contains('hidden')")
        assert not visible(page, "planDiffModal")
        assert not visible(page, "cpdBannerPending") and not visible(page, "cpdBannerInvalid")

        # 9. Review flow with a confirmed preference, then the real store's demo clock.
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        review_flow(page)
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        real_source_clock(page)

        # 9b. Screen 05 (plan options): desktop and a phone-sized viewport, then the small helpers.
        for tag, width, height, mobile, mssv in (("desktop", 1440, 1100, False, "RVW2040"), ("mobile", 390, 844, True, "RVW2041")):
            page.call("Emulation.setDeviceMetricsOverride", width=width, height=height, deviceScaleFactor=2 if mobile else 1, mobile=mobile)
            page.js("logoutLocalAccount()")
            page.js("showWorkspace()")
            options_flow(page, tag, mssv, mobile)
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        confirm_now_without_a_plan(page, "RVW2042")
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        friendly_errors(page, "RVW2043")
        for width, height, mobile, saved_id, missing_id in (
            (1440, 1100, False, "RVW2044", "RVW2045"),
            (390, 844, True, "RVW2046", "RVW2047"),
        ):
            page.call("Emulation.setDeviceMetricsOverride", width=width, height=height,
                      deviceScaleFactor=2 if mobile else 1, mobile=mobile)
            page.js("logoutLocalAccount()")
            page.js("showWorkspace()")
            after_onboarding(page, saved_id, missing_id)
        page.call("Emulation.setDeviceMetricsOverride", width=1440, height=1100, deviceScaleFactor=1, mobile=False)

        # 10. Another account has its own (empty) dashboard.
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        register(page, "Nguoi dung thu hai", "RVW2027")
        page.js("switchTab('dashboard')")
        assert visible(page, "cpdEmpty"), "confirmed plans are per account"
        page.js("logoutLocalAccount()")
        completion_flow(page)
        page_errors = page.js("window.__errors || []")
        assert not page_errors, page_errors
        print("PASS: confirmed-plan dashboard checks (screenshots in artifacts/review_dashboard/)")
        return 0
    finally:
        chrome.terminate()
        server.terminate()
        shutil.rmtree(profile, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
