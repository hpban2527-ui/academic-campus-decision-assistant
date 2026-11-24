"""Automated verification for the standalone First-Login Interactive User Tour module."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from api.server import app

INDEX_HTML = ROOT / "web" / "index.html"
USER_TOUR_JS = ROOT / "web" / "user_tour.js"


def _check_js_delimiter_balance(source: str) -> None:
    """Verify balanced (), [], and {} while skipping JS strings and comments."""
    stack: list[str] = []
    pairs = {"(": ")", "[": "]", "{": "}"}
    closing = set(pairs.values())
    i = 0
    n = len(source)
    state = "code"
    quote = ""
    prev_non_ws = ""

    while i < n:
        ch = source[i]
        nxt = source[i + 1] if i + 1 < n else ""

        if state == "line_comment":
            if ch == "\n":
                state = "code"
            i += 1
            continue

        if state == "block_comment":
            if ch == "*" and nxt == "/":
                state = "code"
                i += 2
                continue
            i += 1
            continue

        if state == "string":
            if ch == "\\":
                i += 2
                continue
            if ch == quote:
                state = "code"
                prev_non_ws = quote
            i += 1
            continue

        if state == "regex":
            if ch == "\\":
                i += 2
                continue
            if ch == "/":
                state = "code"
                prev_non_ws = "/"
            i += 1
            continue

        # Normal code state
        if ch == "/" and nxt == "/":
            state = "line_comment"
            i += 2
            continue
        if ch == "/" and nxt == "*":
            state = "block_comment"
            i += 2
            continue
        if ch in ("'", '"', "`"):
            state = "string"
            quote = ch
            i += 1
            continue
        if ch == "/" and prev_non_ws in ("", "(", "[", "{", ",", "=", ":", "!", "&", "|", "?", ";", "return"):
            state = "regex"
            i += 1
            continue

        if ch in pairs:
            stack.append(pairs[ch])
        elif ch in closing:
            assert stack and stack[-1] == ch, f"Unbalanced delimiter {ch!r} at index {i}"
            stack.pop()

        if not ch.isspace():
            prev_non_ws = ch
        i += 1

    assert not stack, f"Unclosed delimiters remaining: {stack}"


def test_index_html_loads_user_tour_in_head_preserving_last_inline_script() -> None:
    html = INDEX_HTML.read_text(encoding="utf-8")
    tag = '<script src="/static/user_tour.js" defer></script>'

    assert html.count(tag) == 1
    head_close = html.index("</head>")
    assert html.index(tag) < head_close, "External script tag must stay inside <head> before </head>."

    # Guard against breaking tests/test_onboarding_ui.py which executes scripts[scripts.length - 1]
    scripts = re.findall(r"<script\b[^>]*>([\s\S]*?)</script>", html, re.IGNORECASE)
    assert scripts, "Expected inline scripts in web/index.html"
    last_script = scripts[-1]
    assert "function switchTab" in last_script
    assert "function completeOnboarding" in last_script

    # Keep web/index.html zero-conflict: no inline tour markup or styles
    assert "ul-tour-" not in html
    assert "btnStartUserTour" not in html


def test_static_endpoint_serves_user_tour_module() -> None:
    client = TestClient(app)

    home_res = client.get("/")
    assert home_res.status_code == 200
    assert "/static/user_tour.js" in home_res.text

    js_res = client.get("/static/user_tour.js")
    assert js_res.status_code == 200
    content_type = js_res.headers.get("content-type", "").lower()
    assert "javascript" in content_type or "ecmascript" in content_type
    assert "UniLifeUserTour" in js_res.text


def test_user_tour_module_structure_resilience_and_accessibility() -> None:
    source = USER_TOUR_JS.read_text(encoding="utf-8")
    _check_js_delimiter_balance(source)

    # IIFE encapsulation + public API surface
    assert "(function (global)" in source
    for member in (
        "global.UniLifeUserTour",
        "start",
        "stop",
        "next",
        "prev",
        "goTo",
        "isActive",
        "hasCompleted",
        "reset",
        "getSteps",
        "registerSteps",
        "reposition",
    ):
        assert member in source, f"Missing API symbol {member}"

    # All 6 steps & merge-resilient fallback selectors
    for expected_selector in (
        "#workspaceOverview",
        "#confirmedPlanDashboard",
        "#sidebarNav",
        "#activitiesTimelineSection",
        "#viewPlan",
        "toggleUserDropdown",
    ):
        assert expected_selector in source, f"Missing expected selector {expected_selector}"

    # Non-blocking overlay, light theme sync, dev-mode guard, keyboard & ARIA support
    assert "pointer-events: none" in source
    assert "pointer-events: auto" in source
    assert "ul-tour-light" in source
    assert "light-theme" in source
    assert "dev-mode" in source
    assert "unilife_tour_v1_done_" in source
    assert "Hoàn thành ✓" in source
    assert "!Number.isInteger(parsed) || parsed < 0 || parsed >= activeSteps.length" in source
    assert "unilife_server_boot_id" in source
    assert "syncServerBootSession" in source
    assert "wipeLocalLoginSessions" in source
    for key in ("ArrowRight", "ArrowLeft", "Escape"):
        assert key in source
    for aria in ("role", "aria-label", "aria-labelledby"):
        assert aria in source


def test_server_boot_id_cookie_health_and_lifespan_session_wipe(tmp_path, monkeypatch) -> None:
    from api import server

    ephemeral_file = tmp_path / "ephemeral_session.json"
    ephemeral_file.write_text('{"schema_version": 3, "session_scores": {"STALE": {}}}', encoding="utf-8")
    monkeypatch.setattr(server, "SESSION_FILE", ephemeral_file)
    monkeypatch.setattr(server, "session_scores", {"STALE": {"current": {"C1": 10}, "projected": {"C1": 0}}})
    monkeypatch.setenv("UNILIFE_PERSIST_SESSION", "0")

    with TestClient(app) as client:
        # Startup lifespan must wipe any stale on-disk or in-memory session state
        assert server.session_scores == {}
        assert not ephemeral_file.exists()

        health_res = client.get("/api/health")
        assert health_res.status_code == 200
        assert health_res.json().get("server_boot_id") == server.SERVER_BOOT_ID

        home_res = client.get("/")
        assert home_res.status_code == 200
        assert home_res.cookies.get("unilife_server_boot_id") == server.SERVER_BOOT_ID

        # Simulate active session data persisted during runtime
        server.session_scores["25127999"] = server._default_student_scores()
        server._save_session_to_disk()
        assert ephemeral_file.exists()

    # Shutdown lifespan (Ctrl + C equivalent) must wipe runtime and disk session data
    assert server.session_scores == {}
    assert not ephemeral_file.exists()


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for runtime tour VM test")
def test_user_tour_runtime_state_machine_in_node() -> None:
    js = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert');
const code = fs.readFileSync('web/user_tour.js', 'utf8');

const storage = new Map();
const elements = new Map();
let mockCookie = '';

function makeClassList(initial = []) {
  const set = new Set(initial);
  return {
    add: (...cls) => cls.forEach(c => set.add(c)),
    remove: (...cls) => cls.forEach(c => set.delete(c)),
    contains: c => set.has(c),
    toggle: (c, force) => {
      const next = force === undefined ? !set.has(c) : Boolean(force);
      if (next) set.add(c); else set.delete(c);
      return next;
    },
  };
}

function makeNode(tag, id = '') {
  const node = {
    tagName: tag.toUpperCase(),
    id,
    className: '',
    textContent: '',
    style: {},
    children: [],
    parentNode: null,
    hidden: false,
    disabled: false,
    isConnected: true,
    offsetWidth: 360,
    offsetHeight: 220,
    attributes: {},
    classList: makeClassList(),
    listeners: {},
    setAttribute(k, v) { this.attributes[k] = String(v); if (k === 'id') { this.id = String(v); elements.set(this.id, this); } },
    getAttribute(k) { return this.attributes[k] ?? null; },
    appendChild(child) {
      child.parentNode = this;
      this.children.push(child);
      if (child.id) elements.set(child.id, child);
      return child;
    },
    insertBefore(child, ref) {
      child.parentNode = this;
      const idx = this.children.indexOf(ref);
      if (idx === -1) this.children.push(child);
      else this.children.splice(idx, 0, child);
      if (child.id) elements.set(child.id, child);
      return child;
    },
    removeChild(child) {
      this.children = this.children.filter(c => c !== child);
      child.parentNode = null;
    },
    addEventListener(type, fn) {
      this.listeners[type] = this.listeners[type] || [];
      this.listeners[type].push(fn);
    },
    getBoundingClientRect() {
      return { top: 60, left: 40, right: 440, bottom: 200, width: 400, height: 140 };
    },
    scrollIntoView() {},
  };
  if (id) elements.set(id, node);
  return node;
}

const body = makeNode('body');
const head = makeNode('head');
const workspaceApp = makeNode('div', 'workspaceApp');
const header = makeNode('header');
const themeBtn = makeNode('button', 'btnThemeToggle');
const viewDashboard = makeNode('div', 'viewDashboard');
const viewActivities = makeNode('div', 'viewActivities');
const viewPlan = makeNode('div', 'viewPlan');
viewActivities.classList.add('hidden');
viewPlan.classList.add('hidden');

const overviewBanner = makeNode('div', 'workspaceOverview');
const confirmedPlan = makeNode('div', 'confirmedPlanDashboard');
const sidebarNav = makeNode('aside', 'sidebarNav');
const timelineSection = makeNode('div', 'activitiesTimelineSection');
const planTablist = makeNode('div', 'planTablist');
const userDropdownBtn = makeNode('button', 'userDropdownBtn');

header.appendChild(themeBtn);
header.appendChild(userDropdownBtn);
workspaceApp.appendChild(header);
workspaceApp.appendChild(sidebarNav);
workspaceApp.appendChild(viewDashboard);
workspaceApp.appendChild(viewActivities);
workspaceApp.appendChild(viewPlan);
viewDashboard.appendChild(overviewBanner);
viewDashboard.appendChild(confirmedPlan);
viewActivities.appendChild(timelineSection);
viewPlan.appendChild(planTablist);
body.appendChild(workspaceApp);

const selectorMap = {
  '#workspaceOverview > div:first-child': null,
  '#workspaceOverview': overviewBanner,
  '#viewDashboard': viewDashboard,
  '#confirmedPlanDashboard': confirmedPlan,
  '#sidebarNav nav': null,
  '#sidebarNav': sidebarNav,
  '#activitiesTimelineSection': timelineSection,
  '#viewPlan [role="tablist"]': planTablist,
  '#workspaceApp header button[onclick*="toggleUserDropdown"]': userDropdownBtn,
};

let currentTab = 'dashboard';
const sandbox = {
  console, Date, Math, JSON, Array, Object, String, Number, Boolean, Error, TypeError, URLSearchParams,
  innerWidth: 1440,
  innerHeight: 900,
  location: { search: '' },
  setTimeout: (fn) => { fn(); return 1; },
  clearTimeout: () => {},
  requestAnimationFrame: (fn) => { fn(); return 1; },
  cancelAnimationFrame: () => {},
  addEventListener() {},
  matchMedia: () => ({ matches: false }),
  localStorage: {
    get length() { return storage.size; },
    key: idx => Array.from(storage.keys())[idx] ?? null,
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k),
  },
  switchTab(tab) {
    currentTab = tab;
    viewDashboard.classList.toggle('hidden', tab !== 'dashboard');
    viewActivities.classList.toggle('hidden', tab !== 'activities');
    viewPlan.classList.toggle('hidden', tab !== 'plan');
  },
  document: {
    readyState: 'complete',
    get cookie() { return mockCookie; },
    body,
    head,
    documentElement: body,
    getElementById: id => elements.get(id) || null,
    querySelector: sel => (sel in selectorMap ? selectorMap[sel] : null),
    createElement: tag => makeNode(tag),
    createElementNS: (_ns, tag) => makeNode(tag),
    addEventListener(type, fn) { body.addEventListener(type, fn); },
  },
};
sandbox.window = sandbox;
sandbox.localStorage.setItem('unilife_current_user', 'STUDENT_A');

vm.createContext(sandbox);
vm.runInContext(code, sandbox);

const tour = sandbox.UniLifeUserTour;
assert(tour, 'UniLifeUserTour API should be mounted on window');
assert.strictEqual(tour.isActive(), true, 'Tour should auto-start for first-time STUDENT_A');
assert.strictEqual(tour.hasCompleted('STUDENT_A'), false);
assert(elements.get('btnStartUserTour'), 'Header replay button should be injected');

// Step through all 6 steps and click/invoke "Hoàn thành" on the last step
assert.strictEqual(tour.prev(), false, 'Cannot move before first step');
for (let i = 0; i < 5; i++) {
  assert.strictEqual(tour.next(), true);
}
assert.strictEqual(elements.get('ulTourNextBtn').textContent, 'Hoàn thành ✓');
assert.strictEqual(tour.next(), false);
assert.strictEqual(tour.isActive(), false);
assert.strictEqual(tour.hasCompleted('STUDENT_A'), true);

// Switching to STUDENT_B should allow tour again
sandbox.localStorage.setItem('unilife_current_user', 'STUDENT_B');
assert.strictEqual(tour.hasCompleted('STUDENT_B'), false);
assert.strictEqual(tour.start({ force: false }), true);
assert.strictEqual(tour.prev(), false, 'Cannot move before first step');
tour.stop({ markDone: true, status: 'skipped' });
assert.strictEqual(tour.hasCompleted('STUDENT_B'), true);

// Server boot sync wipes local accounts/sessions on boot change, preserves theme, and keeps same-boot sessions
sandbox.localStorage.setItem('unilife_users', JSON.stringify([{ student_id: 'STUDENT_A' }]));
sandbox.localStorage.setItem('unilife_student', JSON.stringify({ student_id: 'STUDENT_A' }));
sandbox.localStorage.setItem('unilife_data_STUDENT_A', '{"profile":{}}');
sandbox.localStorage.setItem('unilife_theme', 'light');
mockCookie = 'unilife_server_boot_id=boot-2';
tour.syncServerBootSession();
assert.strictEqual(sandbox.localStorage.getItem('unilife_users'), null);
assert.strictEqual(sandbox.localStorage.getItem('unilife_current_user'), null);
assert.strictEqual(sandbox.localStorage.getItem('unilife_student'), null);
assert.strictEqual(sandbox.localStorage.getItem('unilife_data_STUDENT_A'), null);
assert.strictEqual(sandbox.localStorage.getItem('unilife_tour_v1_done_STUDENT_A'), null);
assert.strictEqual(sandbox.localStorage.getItem('unilife_theme'), 'light');
assert.strictEqual(sandbox.localStorage.getItem('unilife_server_boot_id'), 'boot-2');

// Refreshing against the same boot ID keeps active session intact
sandbox.localStorage.setItem('unilife_users', JSON.stringify([{ student_id: 'STUDENT_C' }]));
sandbox.localStorage.setItem('unilife_current_user', 'STUDENT_C');
tour.syncServerBootSession();
assert.strictEqual(sandbox.localStorage.getItem('unilife_current_user'), 'STUDENT_C');

// Reset + custom steps registration (and auto-skip missing element)
tour.reset('STUDENT_A');
assert.strictEqual(tour.hasCompleted('STUDENT_A'), false);
const updated = tour.registerSteps([
  { id: 'hidden-step', tab: 'dashboard', selectors: ['#missingId'], title: 'Hidden', content: 'Skip me' },
  { id: 'visible-step', tab: 'dashboard', selectors: ['#workspaceOverview'], title: 'Custom', content: 'Works' },
]);
assert.strictEqual(updated.length, 2);
assert.strictEqual(tour.start({ force: true }), true);
assert.strictEqual(elements.get('ulTourTitle').textContent, 'Custom');

console.log(JSON.stringify({ ok: true, currentTab }));
"""
    proc = subprocess.run(
        ["node", "-e", js],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(proc.stdout.strip().splitlines()[-1])
    assert data["ok"] is True
