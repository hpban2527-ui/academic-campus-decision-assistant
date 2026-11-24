"""Front-end storage and calendar logic of the one-clock-per-semester change (web/index.html).

The pure helpers (between the TERM-CORE markers) run in Node's vm; the account storage tests load the whole page
script into a stubbed sandbox, like tests/test_onboarding_ui.py. The full browser flow is
scripts/verify_term_clock_e2e.py.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from api.term_clock import list_terms  # noqa: E402

HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
CLOCKS = [clock.as_dict() for clock in list_terms()]
HK3, HK1 = "HK3_2025_2026", "HK1_2026_2027"
needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend logic tests")

CORE_HEADER = """
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const core = html.split('// TERM-CORE START')[1].split('// TERM-CORE END')[0].split('\\n').slice(1).join('\\n');
const sandbox = {};
vm.createContext(sandbox);
vm.runInContext(core, sandbox);
const run = expression => JSON.parse(JSON.stringify(vm.runInContext(expression, sandbox)));
const TERMS = __TERMS__;
"""

PAGE_HEADER = """
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\\b[^>]*>([\\s\\S]*?)<\\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];
const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id, value: '', innerText: '', textContent: '', innerHTML: '', checked: true, disabled: false, style: {},
      className: '', children: [{}, {}], dataset: {},
      classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}
    });
  }
  return elements.get(id);
}
const TERMS = __TERMS__;
const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){}, performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async url => {
    const match = String(url).match(/api\\/clock\\?term_id=([^&]+)/);
    const clock = match && TERMS.find(term => term.term_id === decodeURIComponent(match[1]));
    return clock ? { ok: true, status: 200, json: async () => clock } : { ok: false, status: 404, json: async () => ({}) };
  },
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => getEl('created')
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);
vm.runInContext('termList = ' + JSON.stringify(TERMS) + '; applyTermClock(termList[termList.length - 1]);', sandbox);
const run = expression => JSON.parse(JSON.stringify(vm.runInContext(expression, sandbox)));
"""


def node(header: str, body: str) -> dict:
    source = header.replace("__TERMS__", json.dumps(CLOCKS)) + "\n(async () => {\n" + body + "\n})().catch(error => { console.error(error); process.exit(1); });"
    return json.loads(subprocess.check_output(["node"], input=source, cwd=ROOT, text=True, encoding="utf-8"))


# ---------------------------------------------------------------- calendar helpers (pure)
@needs_node
def test_confirmed_activity_lists_follow_completion_deadlines_and_show_actions() -> None:
    header = PAGE_HEADER.replace(
        "vm.runInContext(mainScript, sandbox);",
        "vm.runInContext(scripts.find(script => script.includes('var cpdView')), sandbox);\n"
        "vm.runInContext(mainScript, sandbox);",
    )
    out = node(header, """
      const activity = (id, start, end) => ({ activity_id: id, title: id, mode: 'online', effective_gain: 5,
        scheduled_blocks: [{ start, end }] });
      const plan = { term_id: 'HK1_2026_2027', as_of: TERMS[1].as_of, activities: [
        activity('webinar', '2026-09-24T10:00:00+07:00', '2026-09-24T10:30:00+07:00'),
        activity('future', '2026-09-30T10:00:00+07:00', '2026-09-30T11:00:00+07:00'),
        activity('quiz', '2026-09-24T10:00:00+07:00', '2026-09-24T10:30:00+07:00'),
        activity('multi', '2026-09-28T10:00:00+07:00', '2026-09-28T11:00:00+07:00'),
      ] };
      plan.activities[3].scheduled_blocks.push({ start: '2026-10-01T10:00:00+07:00', end: '2026-10-01T11:00:00+07:00' });
      sandbox.testPlan = plan;
      vm.runInContext(`applyTermClock({ ...termClock, as_of: '2026-09-29T23:59:59+07:00' });
        cpdCompletionState = { progress: { as_of: '2026-09-29T23:59:59+07:00', activities: {
          webinar: { status: 'READY', available_at: '2026-09-24T10:30:00+07:00', question: 'Bạn đã hoàn thành chưa?' },
          future: { status: 'NOT_DUE', available_at: '2026-09-30T11:00:00+07:00' },
          quiz: { status: 'NOT_DUE', available_at: '2026-10-02T23:59:00+07:00' },
          multi: { status: 'NOT_DUE', available_at: '2026-10-01T11:00:00+07:00' }
        }, projected_by_activity: { webinar: 5 } } };`, sandbox);
      const groups = run('cpdActivityGroups(testPlan)');
      vm.runInContext("cpdActivityTab = 'upcoming'; cpdRenderActivityList(testPlan)", sandbox);
      const upcoming = getEl('cpdActivityList').innerHTML;
      vm.runInContext("cpdActivityTab = 'past'; cpdRenderActivityList(testPlan)", sandbox);
      const past = getEl('cpdActivityList').innerHTML;
      vm.runInContext("cpdCompletionState.progress.activities.webinar = { status: 'COMPLETED', confirmed_added: 5 }; cpdRenderActivityList(testPlan)", sandbox);
      const completed = getEl('cpdActivityList').innerHTML;
      console.log(JSON.stringify({
        upcomingIds: groups.upcoming.map(row => row.activity.activity_id), pastIds: groups.past.map(row => row.activity.activity_id),
        upcoming, past, completed,
      }));
    """)
    assert set(out["upcomingIds"]) == {"future", "quiz", "multi"}
    assert out["pastIds"] == ["webinar"]
    assert "cpdConfirmActivityCompletion" not in out["upcoming"]
    assert "Xác nhận đã hoàn thành" in out["past"]
    assert 'id="cpdListComplete-' in out["past"]
    assert "Đã hoàn thành · +5 điểm" in out["completed"]
    assert "cpdConfirmActivityCompletion" not in out["completed"]
    assert out["past"].count('data-cpd-activity="webinar"') == 1


@needs_node
def test_legacy_shared_demo_date_cannot_assign_a_plan_to_a_semester() -> None:
    out = node(CORE_HEADER, """
      const result = context => ({ plan: { context, selected_activities: [] } });
      const noEvidence = { confirmed_plan_result: result({ as_of: '2026-11-08T20:00:00+07:00' }) };
      const dated = { confirmed_plan_result: result({ as_of: '2026-11-08T20:00:00+07:00' }) };
      dated.confirmed_plan_result.plan.selected_activities = [{ scheduled_blocks: [{ start: '2026-06-01T09:00:00+07:00' }] }];
      console.log(JSON.stringify({
        ambiguous: run(`termEvidenceOfLegacy(${JSON.stringify(noEvidence)}, ${JSON.stringify(TERMS)})`),
        dated: run(`termEvidenceOfLegacy(${JSON.stringify(dated)}, ${JSON.stringify(TERMS)})`),
      }));
    """)
    assert out == {"ambiguous": None, "dated": HK3}


@needs_node
def test_synthetic_requests_do_not_inherit_the_selected_semesters_calendar() -> None:
    out = node(PAGE_HEADER, """
      const result = {};
      for (const clock of TERMS) {
        vm.runInContext('applyTermClock(' + JSON.stringify(clock) + ')', sandbox);
        const real = run("plannerAvailabilityPayload('real')");
        const synthetic = run("JSON.parse(JSON.stringify({ availability: plannerAvailabilityPayload('synthetic') }))");
        result[clock.term_id] = { from: real.effective_from, until: real.effective_until, synthetic };
      }
      console.log(JSON.stringify(result));
    """)
    for clock in CLOCKS:
        assert out[clock["term_id"]] == {
            "from": clock["term_start"], "until": clock["term_end"], "synthetic": {},
        }


@needs_node
def test_week_rows_and_contract_week_follow_each_terms_dates() -> None:
    out = node(CORE_HEADER, """
      const result = {};
      for (const clock of TERMS) {
        const rows = run(`termWeekRows(${JSON.stringify(clock)})`);
        result[clock.term_id] = {
          rows: rows.length, first: rows[0], last: rows[rows.length - 1],
          contract: run(`termContractWeekStart(${JSON.stringify(clock)})`),
          opens: run(`termDefaultWeekStart(${JSON.stringify(clock)})`),
          inside: ['2026-05-16', '2026-05-17', '2026-08-28', '2026-08-29', '2026-11-15', '2026-11-16'].map(
            day => run(`termContainsDay(${JSON.stringify(clock)}, '${day}')`)),
        };
      }
      console.log(JSON.stringify(result));
    """)
    # HK3 2026-05-17 (Sun) .. 2026-08-28 (Fri): Monday rows from 05-11 to 08-24 = 16; the availability contract needs a
    # Monday inside the range: 05-18; the grid opens on the week of as_of (05-11).
    assert out[HK3] == {"rows": 16, "first": "2026-05-11", "last": "2026-08-24", "contract": "2026-05-18",
                        "opens": "2026-05-11", "inside": [False, True, True, False, False, False]}
    # HK1 2026-08-29 (Sat) .. 2026-11-15 (Sun): Monday rows from 08-24 to 11-09 = 12.
    assert out[HK1] == {"rows": 12, "first": "2026-08-24", "last": "2026-11-09", "contract": "2026-08-31",
                        "opens": "2026-08-24", "inside": [False, False, False, True, True, False]}


@needs_node
def test_labels_map_to_term_ids() -> None:
    out = node(CORE_HEADER, """
      console.log(JSON.stringify(['HK3 \\u00b7 2025\\u20132026', 'HK1 \\u00b7 2026\\u20132027', 'HK1 2026-2027', 'HK2', '', null]
        .map(label => run(`termIdFromLabel(${JSON.stringify(label)})`))));
    """)
    assert out == [HK3, HK1, HK1, None, None, None]


@needs_node
def test_advanced_clock_rejects_old_plan_catalog_and_review_responses() -> None:
    checked = node(PAGE_HEADER, """
      const before = TERMS[1];
      const after = { ...before, as_of: '2026-09-12T23:59:59+07:00', clock_version: 'clk-advanced' };
      vm.runInContext('applyTermClock(' + JSON.stringify(after) + ')', sandbox);
      const cases = [before, { result: before }, { options: [{ result: before }] },
                     { ...before, items: [] }, after, TERMS[0],
                     { plan: { context: { term_id: before.term_id, as_of: before.as_of } } },
                     { term_id: 'SYNTHETIC-DEMO', clock_version: 'synthetic' }];
      console.log(JSON.stringify(cases.map(item => run('isCurrentTermResponse(' + JSON.stringify(item) + ')'))));
    """)
    assert checked == [False, False, False, False, True, False, False, True]


# ---------------------------------------------------------------- term-scoped storage (pure)
@needs_node
def test_switching_hk3_hk1_hk3_restores_each_terms_state_unchanged() -> None:
    out = node(CORE_HEADER, """
      const student = { faculty: 'CNTT', cohort: '24', program: 'Chuan', preferences: { skills: 'python' }, score_history: [{ semester: 'HK2', score: 80 }] };
      const hk3 = {
        schema_version: 3, student_id: '1', onboarding_status: 'COMPLETED', confirmed_preference: { a: 1 },
        category_scores: { C1: { current: 17 } }, saved_activities: [{ commit_id: 'x' }], confirmed_plan: { plan_version: 'p3' },
        planner: { target_total: 85, plan_stages: { first: null } }, canonical_availability: { effective_from: 'A3' },
        profile: { ...student, term_id: 'HK3_2025_2026', drl_target: 85, goal: { target_score: 85 }, weekly_intervals: [{ weekday: 0 }],
                   exceptions: [{ date: 'D3' }], busy_schedule: { week_start: 'W3', entries: [{ id: 'e3' }] } },
      };
      const stored1 = run(`termViewToStored(${JSON.stringify(hk3)})`);
      // Open HK1 for the first time: an empty slice, student-level fields kept.
      const viewHk1 = run(`termStoredToView(${JSON.stringify(stored1)}, 'HK1_2026_2027')`);
      viewHk1.profile.drl_target = 70;
      viewHk1.confirmed_plan = { plan_version: 'p1' };
      viewHk1.profile.busy_schedule = { week_start: 'W1', entries: [{ id: 'e1' }] };
      const stored2 = run(`termViewToStored(${JSON.stringify(viewHk1)})`);
      const backHk3 = run(`termStoredToView(${JSON.stringify(stored2)}, 'HK3_2025_2026')`);
      const backHk1 = run(`termStoredToView(${JSON.stringify(stored2)}, 'HK1_2026_2027')`);
      console.log(JSON.stringify({ hk3, viewHk1, stored1, stored2, backHk3, backHk1 }));
    """)
    hk3, view_hk1, stored1, stored2 = out["hk3"], out["viewHk1"], out["stored1"], out["stored2"]
    # Student-level fields stay at the top; term-scoped fields move into the term's slice.
    assert stored1["profile"] == {k: v for k, v in hk3["profile"].items() if k in {"faculty", "cohort", "program", "preferences", "score_history", "term_id"}}
    assert stored1["confirmed_preference"] == {"a": 1} and "confirmed_plan" not in stored1 and "planner" not in stored1
    assert stored1["schema_version"] == 3 and set(stored1["terms"]) == {HK3}
    assert stored1["terms"][HK3]["profile"]["drl_target"] == 85
    # HK1 started empty: nothing of HK3 leaked into it.
    assert out["viewHk1"]["profile"]["term_id"] == HK1
    assert set(stored2["terms"]) == {HK3, HK1}
    # Back to HK3: each term's own state is restored unchanged.
    for key in ("category_scores", "saved_activities", "confirmed_plan", "planner", "canonical_availability"):
        assert out["backHk3"][key] == hk3[key], key
    assert out["backHk3"]["profile"]["busy_schedule"] == hk3["profile"]["busy_schedule"]
    assert out["backHk3"]["profile"]["drl_target"] == 85 and out["backHk3"]["profile"]["term_id"] == HK3
    assert out["backHk1"]["confirmed_plan"] == {"plan_version": "p1"} and out["backHk1"]["profile"]["drl_target"] == 70
    assert out["backHk1"]["profile"]["busy_schedule"]["week_start"] == "W1"
    assert out["backHk1"]["profile"]["faculty"] == "CNTT" and out["backHk3"]["profile"]["score_history"] == hk3["profile"]["score_history"]


@needs_node
def test_legacy_blob_is_assigned_to_a_term_only_by_stored_evidence() -> None:
    out = node(CORE_HEADER, """
      const plan = (context, blocks = []) => ({ plan: { context, selected_activities: blocks.map(start => ({ scheduled_blocks: [{ start }] })) } });
      const base = { schema_version: 2, student_id: '2', category_scores: { C1: 1 }, confirmed_plan: { plan_version: 'old' },
                     profile: { faculty: 'F', semester: 'HK1 \\u00b7 2026\\u20132027', drl_target: 90, busy_schedule: { entries: [1] } } };
      const cases = {
        byTermId: { ...base, confirmed_plan_result: plan({ term_id: 'HK1_2026_2027', as_of: '2026-05-17T00:00:00+07:00' }) },
        byClock: { ...base, confirmed_plan_result: plan({ as_of: '2026-05-17T08:00:00+07:00' }) },
        byDates: { ...base, planner: { plan_stages: { first: plan({}, ['2026-10-02T09:00:00+07:00', '2026-10-09T09:00:00+07:00']) } } },
        synthetic: { ...base, confirmed_plan_result: plan({ term_id: 'SYNTHETIC-DEMO', as_of: '2026-11-08T20:00:00+07:00' }) },
        conflicting: { ...base, confirmed_plan_result: plan({ term_id: 'HK3_2025_2026' }), planner: { plan_stages: { first: plan({ term_id: 'HK1_2026_2027' }) } } },
        noEvidence: { ...base },
        broken: { schema_version: 1, planner: null, profile: null, confirmed_plan_result: 7 },
      };
      const result = {};
      for (const [name, blob] of Object.entries(cases)) {
        const stored = run(`termMigrateLegacy(${JSON.stringify(blob)}, ${JSON.stringify(TERMS)}, 'HK1_2026_2027')`);
        result[name] = { slices: Object.keys(stored.terms), active: stored.profile.term_id, schema: stored.schema_version,
                         planIn: Object.keys(stored.terms).filter(k => stored.terms[k].confirmed_plan), topLeak: 'confirmed_plan' in stored };
      }
      console.log(JSON.stringify(result));
    """)
    unassigned = "_unassigned"
    assert out["byTermId"]["slices"] == [HK1] and out["byTermId"]["planIn"] == [HK1]
    assert out["byClock"]["slices"] == [unassigned]  # a simulated date alone does not establish ownership
    assert out["byDates"]["slices"] == [HK1]  # every planned block is inside HK1
    assert out["synthetic"]["slices"] == [unassigned]  # the synthetic scenario is not a semester
    assert out["conflicting"]["slices"] == [unassigned] and out["noEvidence"]["slices"] == [unassigned]
    for name in ("byClock", "synthetic", "conflicting", "noEvidence"):
        assert out[name]["planIn"] == [unassigned] and out[name]["active"] == HK1  # set aside; the chosen label opens HK1
    assert out["broken"]["slices"] == [unassigned] and out["broken"]["active"] == HK1
    assert all(item["schema"] == 3 and not item["topLeak"] for item in out.values())


# ---------------------------------------------------------------- the page's own storage code
@needs_node
def test_page_storage_loads_legacy_accounts_and_restores_terms_after_switching() -> None:
    out = node(PAGE_HEADER, """
      const write = (id, blob) => sandbox.localStorage.setItem('unilife_data_' + id, JSON.stringify(blob));
      const stored = id => JSON.parse(sandbox.localStorage.getItem('unilife_data_' + id));
      const planResult = term => ({ plan: { context: { term_id: term, as_of: '2026-08-29T00:00:00+07:00' }, selected_activities: [] } });
      // 1. an old account whose plan names HK1; 2. an old account with no evidence; 3. a corrupted record.
      write('1', { schema_version: 2, student_id: '1', onboarding_status: 'COMPLETED', profile: { faculty: 'F', semester: 'HK1 \\u00b7 2026\\u20132027', drl_target: 77 },
                   confirmed_plan: { plan_version: 'p-old' }, confirmed_plan_result: planResult('HK1_2026_2027') });
      write('2', { schema_version: 2, student_id: '2', profile: { faculty: 'G', semester: 'HK3 \\u00b7 2025\\u20132026', drl_target: 66 }, confirmed_plan: { plan_version: 'p-lost' } });
      write('3', { schema_version: 2, planner: 'oops', profile: 5 });
      const viewOne = run("readLocalUserData('1')");
      const viewTwo = run("readLocalUserData('2')");
      let broken = 'no error';
      try { run("readLocalUserData('3').profile.term_id"); } catch (error) { broken = String(error.message); }
      // 4. HK3 -> HK1 -> HK3 on a fresh account
      const fresh = run("createDefaultLocalUserData('9', true)");
      sandbox.localStorage.setItem('unilife_users', JSON.stringify([]));
      vm.runInContext("writeLocalUserData('9', createDefaultLocalUserData('9', true))", sandbox);
      const opened = run("readLocalUserData('9').profile.term_id");
      await vm.runInContext("setAccountTerm('9', 'HK3_2025_2026')", sandbox);
      vm.runInContext("(() => { const d = readLocalUserData('9'); d.profile.drl_target = 88; d.profile.goal.target_score = 88; d.confirmed_plan = { plan_version: 'p3' };" +
                      " d.profile.busy_schedule.entries = [{ id: 'busy3' }]; writeLocalUserData('9', d); })()", sandbox);
      await vm.runInContext("setAccountTerm('9', 'HK1_2026_2027')", sandbox);
      const hk1 = run("(() => { const d = readLocalUserData('9'); return { term: d.profile.term_id, target: d.profile.drl_target, plan: d.confirmed_plan, busy: d.profile.busy_schedule.entries, label: d.profile.semester, week: d.profile.busy_schedule.week_start, from: d.canonical_availability.effective_from, until: d.canonical_availability.effective_until }; })()");
      await vm.runInContext("setAccountTerm('9', 'HK3_2025_2026')", sandbox);
      const hk3 = run("(() => { const d = readLocalUserData('9'); return { term: d.profile.term_id, target: d.profile.drl_target, plan: d.confirmed_plan, busy: d.profile.busy_schedule.entries, label: d.profile.semester, week: d.profile.busy_schedule.week_start, from: d.canonical_availability.effective_from, until: d.canonical_availability.effective_until }; })()");
      console.log(JSON.stringify({ viewOne: { term: viewOne.profile.term_id, plan: viewOne.confirmed_plan, target: viewOne.profile.drl_target, faculty: viewOne.profile.faculty },
        viewTwo: { term: viewTwo.profile.term_id, plan: viewTwo.confirmed_plan, target: viewTwo.profile.drl_target, faculty: viewTwo.profile.faculty },
        storedOne: Object.keys(stored('1').terms), storedTwo: Object.keys(stored('2').terms), schemaOne: stored('1').schema_version,
        asideTwo: stored('2').terms._unassigned.confirmed_plan, broken, opened, hk1, hk3, hk3Slices: Object.keys(stored('9').terms).sort() }));
    """)
    # Old account with a plan that names HK1: its state follows the plan into HK1 and nothing is lost.
    assert out["viewOne"] == {"term": HK1, "plan": {"plan_version": "p-old"}, "target": 77, "faculty": "F"}
    assert out["storedOne"] == [HK1] and out["schemaOne"] == 3
    # Old account without evidence: the chosen label opens HK3, but the old plan and target are set aside, not shown.
    assert out["viewTwo"]["term"] == HK3 and out["viewTwo"]["plan"] is None and out["viewTwo"]["target"] == 80
    assert out["viewTwo"]["faculty"] == "G"  # student-level data is kept
    assert set(out["storedTwo"]) == {"_unassigned", HK3} and out["asideTwo"] == {"plan_version": "p-lost"}
    assert out["broken"] == "no error"  # a corrupted record is merged with defaults; it never throws
    # HK3 -> HK1 -> HK3
    assert out["opened"] == HK1  # a new account opens in the latest term
    assert out["hk1"]["term"] == HK1 and out["hk1"]["plan"] is None and out["hk1"]["busy"] == [] and out["hk1"]["target"] == 80
    assert out["hk3"] == {"term": HK3, "target": 88, "plan": {"plan_version": "p3"}, "busy": [{"id": "busy3"}],
                          "label": "HK3 · 2025–2026", "week": "2026-05-11", "from": "2026-05-17", "until": "2026-08-28"}
    assert (out["hk1"]["week"], out["hk1"]["from"], out["hk1"]["until"]) == ("2026-08-24", "2026-08-29", "2026-11-15")
    assert out["hk3Slices"] == sorted([HK3, HK1])


@needs_node
def test_busy_grid_greys_days_outside_the_term_and_weekly_blocks_keep_weekday_and_hours() -> None:
    out = node(PAGE_HEADER, """
      const result = {};
      for (const term of ['HK3_2025_2026', 'HK1_2026_2027']) {
        vm.runInContext(`applyTermClock(termList.find(t => t.term_id === '${term}'))`, sandbox);
        result[term] = {
          weeks: run('termWeekRows(termClock).length'),
          // the first week row starts before the term; its days before term_start are outside
          firstWeekOutside: run("(() => { const first = termWeekRows(termClock)[0]; return [0,1,2,3,4,5,6].map(i => !termContainsDay(termClock, addDaysToIsoDate(first, i))); })()"),
          weekly: run("expandWeeklyProfileIntervals([{ weekday: 2, start: '09:30', end: '11:00' }], termClock.term_start, termClock.term_end)"
                      + ".map(i => [i.start, i.end])"),
          clampBefore: run("termClampWeekStart('2026-01-05')"), clampAfter: run("termClampWeekStart('2027-01-04')"),
          neighbors: run("[termWeekHasNeighbor(termWeekRows(termClock)[0], -1), termWeekHasNeighbor(termWeekRows(termClock)[0], 1)]"),
        };
      }
      console.log(JSON.stringify(result));
    """)
    hk3, hk1 = out[HK3], out[HK1]
    assert (hk3["weeks"], hk1["weeks"]) == (16, 12)
    assert hk3["firstWeekOutside"] == [True, True, True, True, True, True, False]  # Mon 05-11 .. Sat 05-16 greyed, Sun 05-17 in
    assert hk1["firstWeekOutside"] == [True, True, True, True, True, False, False]  # Mon 08-24 .. Fri 08-28 greyed, Sat 08-29 in
    # A Wednesday 09:30-11:00 block: weekday and hours never shift, one block per Wednesday of the term.
    assert len(hk3["weekly"]) == 15 and len(hk1["weekly"]) == 11  # Wednesdays 05-20..08-26 and 09-02..11-11
    for term, rows, first in ((HK3, hk3["weekly"], "2026-05-20"), (HK1, hk1["weekly"], "2026-09-02")):
        assert rows[0][0] == f"{first}T09:30:00+07:00" and all(a[11:] == "09:30:00+07:00" and b[11:] == "11:00:00+07:00" for a, b in rows)
        assert all(date.fromisoformat(a[:10]).weekday() == 2 for a, _ in rows)
    assert hk3["clampBefore"] == "2026-05-11" and hk3["clampAfter"] == "2026-08-24"
    assert hk1["clampBefore"] == "2026-08-24" and hk1["clampAfter"] == "2026-11-09"
    assert hk3["neighbors"] == [False, True] and hk1["neighbors"] == [False, True]
