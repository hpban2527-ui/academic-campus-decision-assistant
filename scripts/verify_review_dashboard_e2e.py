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


def register(page: Cdp, name: str, mssv: str) -> None:
    page.js("showWorkspace()")
    page.js("setAuthMode('register')")
    page.js(f"""(() => {{
      document.getElementById('registerName').value = {json.dumps(name)};
      document.getElementById('registerMssv').value = {json.dumps(mssv)};
      document.getElementById('registerPassword').value = 'TestPass2026!';
      document.getElementById('btnSubmitRegister').click();
    }})()""")
    page.wait(f"!!currentStudent && currentStudent.student_id === {json.dumps(mssv)} "
              "&& !document.getElementById('onboardingWizard').classList.contains('hidden')")
    # A new account starts the one-time onboarding wizard; finish it so the workspace opens.
    page.js(f"""(() => {{ const key = localUserDataKey({json.dumps(mssv)}); const data = JSON.parse(localStorage.getItem(key));
      data.onboarding_status = 'COMPLETED'; localStorage.setItem(key, JSON.stringify(data));
      document.getElementById('onboardingWizard').classList.add('hidden'); showWorkspace(); }})()""")
    page.wait("!document.getElementById('workspaceApp').classList.contains('hidden')")


def visible(page: Cdp, element_id: str) -> bool:
    return bool(page.js(f"(() => {{ const el = document.getElementById({json.dumps(element_id)}); return !!el && !el.classList.contains('hidden'); }})()"))


def main() -> int:
    browser = find_browser()
    if browser is None:
        print("SKIP: no Edge/Chrome/Chromium found; use the manual checklist in docs/adr.")
        return 0
    OUT.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src")}
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "api.server:app", "--host", "127.0.0.1", "--port", str(SERVER_PORT)],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
    )
    profile = tempfile.mkdtemp(prefix="review-dash-")
    chrome = subprocess.Popen(
        [browser, "--headless=new", f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}",
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

        # 1. Empty state: a brand-new account has nothing confirmed.
        register(page, "Sinh vien kiem thu", "RVW2026")
        page.js("switchTab('dashboard')")
        assert visible(page, "cpdEmpty") and not visible(page, "cpdContent"), "empty state expected"
        assert "chưa chốt kế hoạch nào" in page.js("document.getElementById('cpdEmpty').innerText")
        assert not visible(page, "cpdBannerPending") and not visible(page, "cpdBannerInvalid")
        page.shot("1_empty_state")

        # 2. Plan, then confirm from the planner screen.
        page.js("switchTab('plan')")
        page.wait("!!planStages.first && !document.getElementById('plannerActiveResult').classList.contains('hidden')", 40)
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

        # 8. Confirming again replaces the plan and clears both banners.
        page.js("switchTab('plan')")
        page.js("document.getElementById('btnConfirmPlan').click()")
        page.wait("!document.getElementById('viewDashboard').classList.contains('hidden')")
        assert not visible(page, "cpdBannerPending") and not visible(page, "cpdBannerInvalid")

        # 9. Another account has its own (empty) dashboard.
        page.js("logoutLocalAccount()")
        page.js("showWorkspace()")
        register(page, "Nguoi dung thu hai", "RVW2027")
        page.js("switchTab('dashboard')")
        assert visible(page, "cpdEmpty"), "confirmed plans are per account"
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
