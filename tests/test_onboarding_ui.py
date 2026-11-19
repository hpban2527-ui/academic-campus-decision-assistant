from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from api.sp3_real import real_plan_options
from api.sp3_service import personalized_plan_options
from personalization.models import StudentPreference
from personalization.scoring import ActivityFeatures, PreferenceUtilityEngine
from sp3.availability import resolve_availability

HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_dashboard_assistant_is_replaced_by_one_time_onboarding_and_profile_editor() -> None:
    assert 'id="unilifeAssistant"' not in HTML
    assert 'id="onboardingModal"' in HTML
    assert 'id="onboardingWizard"' not in HTML
    assert "NOT_STARTED" in HTML and "IN_PROGRESS" in HTML and "COMPLETED" in HTML
    assert "AI chỉnh sửa hồ sơ" not in HTML
    assert 'id="profileAiInput"' not in HTML
    assert 'id="onboardingScores"' not in HTML
    assert "Bước 1 / 3" in HTML
    assert "hydrateOnboardingFormFromDraft" not in HTML
    assert "resetOnboardingAssistantState" not in HTML
    assert "mapTopicInputsToTopicIds" in HTML
    assert "mapPriorityInputsToCategories" in HTML
    assert "syncBusyScheduleAndIntervals" in HTML
    assert "function isAvailabilityCellBusy" in HTML
    assert "renderPlanOptionsSelectorBase" not in HTML


def test_profile_schedule_workspace_and_local_migration_are_present() -> None:
    assert "Hồ sơ & Lịch" in HTML
    for marker in (
        'id="profileScheduleTabProfile"',
        'id="profileScheduleTabSchedule"',
        'id="profileSchedulePanelProfile"',
        'id="profileSchedulePanelSchedule"',
        "Kế hoạch thông minh",
    ):
        assert marker in HTML
    assert "migrateLocalUserData" in HTML
    assert "onboarding_status" in HTML
    assert "canonical_availability" in HTML
    assert "customBusyIntervals.push(...expanded)" in HTML
    assert "assistantAvailableIntervals.push(...expanded)" in HTML
    assert "availableExceptionDays" in HTML
    assert "function logoutLocalAccount()" in HTML
    assert "manual_busy_intervals" in HTML and "unavailable_slots" in HTML
    assert "plannerRequestGeneration" in HTML


def test_plan_option_cache_and_swap_controls_are_real_handlers() -> None:
    assert "/api/sp3/personalized/options" in HTML
    assert "function plannerPreferencePayload(preference)" in HTML
    assert "weeklyHours * 60" in HTML
    assert "cachedPlanOptions" in HTML
    assert "selectCachedPlanOption" in HTML
    assert "function initialReadyPlanOptionIndex(options, preferredStrategy)" in HTML
    assert "option.status === 'READY' && option.result" in HTML
    assert "Chi tiết và tùy chỉnh" in HTML
    assert "previewSmartSwap" in HTML
    assert "undoCustomPlan" in HTML
    assert "Smart Swap chưa được hỗ trợ an toàn cho nguồn hoạt động thật" in HTML
    for marker in ("PLANNED · đã xếp", "OPEN · rảnh đã xác nhận", "BUSY · bận", "UNKNOWN/OUTSIDE"):
        assert marker in HTML
    for handler in ("openPlannedActivityDetails", "openAvailableCalendarSlot", "openBusyCalendarSlot", "previewCalendarActivityChange"):
        assert f"function {handler}" in HTML
    assert "/api/sp3/personalized/${kind}-preview" in HTML
    assert "calendarPreviewChange" in HTML


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_onboarding_busy_schedule_and_preference_edits_are_authoritative() -> None:
    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {}, className: '', children: [{}, {}],
      classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}
    });
  }
  return elements.get(id);
}

const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){},
  performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => getEl('created')
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {
  // 1. Create account -> onboarding -> save -> reload
  const user = { student_id: '25127888', full_name: 'Student One', class: '25CTT1', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);
  sandbox.updateOnboardingProfileField('faculty', 'Khoa CNTT');
  sandbox.toggleOnboardingBusySlot('class|2026-11-09|morning');
  sandbox.toggleOnboardingBusySlot('work|2026-11-11|evening');
  sandbox.setOnboardingSemesterBusy(true);
  sandbox.updateOnboardingGoalField('target_score', 90);
  sandbox.updateOnboardingGoalField('format', 'Trực tuyến');
  vm.runInContext(`
    onboardingDraft.profile.goal.topics = ['Trí tuệ nhân tạo', 'Ngoại ngữ'];
    onboardingDraft.profile.goal.priorities = ['Học thuật / nghiên cứu', 'Tình nguyện / cộng đồng'];
    completeOnboarding();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127888', full_name: 'Student One', major: 'Khoa CNTT' })", sandbox);

  const snap = expr => JSON.parse(JSON.stringify(vm.runInContext(expr, sandbox)));

  const afterOnboarding = snap(`({
    target: Number(document.getElementById('inputPlanTarget').value),
    weekly: currentProfileDraft.weekly_intervals,
    exceptions: currentProfileDraft.exceptions,
    topics: confirmedPreference.topic_preferences,
    categories: confirmedPreference.category_priorities,
    modes: confirmedPreference.mode_preferences,
    busyCount: plannerAvailabilityPayload().busy_intervals.length
  })`);

  // 2. Add unrelated manual weekly rule, legacy exception, and unrelated preference fields
  vm.runInContext(`
    currentProfileDraft.weekly_intervals.push({ kind: 'busy', weekday: 4, start: '13:00', end: '15:00', recurrence: 'weekly', source: 'manual', confirmed: true });
    currentProfileDraft.exceptions.push({ date: '2026-11-15', kind: 'busy', start: '09:00', end: '11:00', source: 'manual', confirmed: true });
    confirmedPreference.campus_preferences = [{ campus_id: 'NVC', weight: 4 }];
    confirmedPreference.hard_exclusions = { campus_ids: ['DONG_HOA'], modes: [], time_slots: [] };
    confirmedPreference.topic_preferences[0].weight = 3;
    persistCurrentUserData();
    persistCurrentUserData();
  `, sandbox);

  // 3. Remove one onboarding busy slot (work|2026-11-11|evening -> weekday 2) & reload
  vm.runInContext(`
    const idx = currentProfileDraft.weekly_intervals.findIndex(item => item.source === 'busy_schedule' && item.weekday === 2);
    removeProfileWeeklyInterval(idx);
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127888', full_name: 'Student One', major: 'Khoa CNTT' })", sandbox);
  const afterRemoveSlot = snap(`({
    slots: currentProfileDraft.busy_schedule.slots,
    weekly: currentProfileDraft.weekly_intervals,
    exceptions: currentProfileDraft.exceptions,
    busyIntervals: plannerAvailabilityPayload().busy_intervals
  })`);

  // 4. Toggle semester recurrence OFF -> save twice -> reload
  vm.runInContext(`
    currentProfileDraft.busy_schedule.applies_to_semester = false;
    syncBusyScheduleAndIntervals(currentProfileDraft);
    restoreOnboardingBusySchedule(currentProfileDraft.busy_schedule, readLocalUserData('25127888'));
    persistCurrentUserData();
    persistCurrentUserData();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127888', full_name: 'Student One', major: 'Khoa CNTT' })", sandbox);
  const afterToggleOff = snap(`({
    weekly: currentProfileDraft.weekly_intervals,
    exceptions: currentProfileDraft.exceptions,
    busyIntervals: plannerAvailabilityPayload().busy_intervals
  })`);

  // 5. Toggle semester recurrence back ON -> save twice -> reload
  vm.runInContext(`
    currentProfileDraft.busy_schedule.applies_to_semester = true;
    syncBusyScheduleAndIntervals(currentProfileDraft);
    restoreOnboardingBusySchedule(currentProfileDraft.busy_schedule, readLocalUserData('25127888'));
    persistCurrentUserData();
    persistCurrentUserData();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127888', full_name: 'Student One', major: 'Khoa CNTT' })", sandbox);
  const afterToggleOn = snap(`({
    weekly: currentProfileDraft.weekly_intervals,
    exceptions: currentProfileDraft.exceptions,
    busyIntervals: plannerAvailabilityPayload().busy_intervals
  })`);

  // 6. Remove an interest & category in Profile -> save twice -> reload
  vm.runInContext(`
    document.getElementById('profileInterestFields').value = 'Trí tuệ nhân tạo';
    document.getElementById('profileSkills').value = 'Python';
    document.getElementById('profilePersonalGoals').value = 'Đạt 90 điểm';
    document.getElementById('profileFavoriteActivities').value = 'Học thuật / nghiên cứu';
    saveProfilePreferences();
    persistCurrentUserData();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127888', full_name: 'Student One', major: 'Khoa CNTT' })", sandbox);
  const afterEditInterest = snap(`({
    storedProfile: readLocalUserData('25127888').profile,
    confirmedPreference: plannerPreferencePayload(confirmedPreference),
    availability: plannerAvailabilityPayload(),
    target: Number(document.getElementById('inputPlanTarget').value)
  })`);

  console.log(JSON.stringify({
    afterOnboarding,
    afterRemoveSlot,
    afterToggleOff,
    afterToggleOn,
    afterEditInterest
  }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    # 1. Onboarding initial state
    assert res["afterOnboarding"]["target"] == 90
    assert [t["topic_id"] for t in res["afterOnboarding"]["topics"]] == ["artificial_intelligence", "foreign_language"]
    assert [c["category_id"] for c in res["afterOnboarding"]["categories"]] == ["C1", "C4"]
    assert [m["mode"] for m in res["afterOnboarding"]["modes"]] == ["online"]
    assert len(res["afterOnboarding"]["weekly"]) == 2
    assert res["afterOnboarding"]["busyCount"] == 52

    # 3. After removing one busy slot: only Monday morning (busy_schedule) + Friday manual rule remain
    assert res["afterRemoveSlot"]["slots"] == ["class|2026-11-09|morning"]
    assert len(res["afterRemoveSlot"]["weekly"]) == 2
    assert {(w["weekday"], w["source"]) for w in res["afterRemoveSlot"]["weekly"]} == {(0, "busy_schedule"), (4, "manual")}
    assert len(res["afterRemoveSlot"]["exceptions"]) == 1
    assert res["afterRemoveSlot"]["exceptions"][0]["date"] == "2026-11-15"
    # Ensure no Wednesday 17:00-21:00 busy interval remains
    assert not any("T17:00:00+07:00" in b["start"] for b in res["afterRemoveSlot"]["busyIntervals"])

    # 4. After toggling semester recurrence OFF: busy_schedule weekly rule removed, manual weekly rule preserved, single-date exception added
    assert [(w["weekday"], w["source"]) for w in res["afterToggleOff"]["weekly"]] == [(4, "manual")]
    assert {(e["date"], e["source"]) for e in res["afterToggleOff"]["exceptions"]} == {
        ("2026-11-15", "manual"),
        ("2026-11-09", "busy_schedule"),
    }
    # Monday morning should only appear on 2026-11-09, not on 2026-11-16
    assert any(b["start"] == "2026-11-09T07:00:00+07:00" for b in res["afterToggleOff"]["busyIntervals"])
    assert not any(b["start"] == "2026-11-16T07:00:00+07:00" for b in res["afterToggleOff"]["busyIntervals"])

    # 5. After toggling semester recurrence back ON: busy_schedule exception removed, weekly restored, no duplicates
    assert {(w["weekday"], w["source"]) for w in res["afterToggleOn"]["weekly"]} == {(0, "busy_schedule"), (4, "manual")}
    assert [(e["date"], e["source"]) for e in res["afterToggleOn"]["exceptions"]] == [("2026-11-15", "manual")]
    assert any(b["start"] == "2026-11-16T07:00:00+07:00" for b in res["afterToggleOn"]["busyIntervals"])
    starts = [(b["start"], b["end"]) for b in res["afterToggleOn"]["busyIntervals"]]
    assert len(starts) == len(set(starts))

    # 6. After removing foreign_language & C4 in Profile: edits are authoritative, unrelated preferences preserved
    edited_pref = res["afterEditInterest"]["confirmedPreference"]
    stored_profile = res["afterEditInterest"]["storedProfile"]
    assert edited_pref["topic_preferences"] == [{"topic_id": "artificial_intelligence", "weight": 3}]
    assert edited_pref["category_priorities"] == [{"category_id": "C1", "weight": 5}]
    assert edited_pref["mode_preferences"] == [{"mode": "online", "weight": 5}]
    assert edited_pref["campus_preferences"] == [{"campus_id": "NVC", "weight": 4}]
    assert edited_pref["hard_exclusions"]["campus_ids"] == ["DONG_HOA"]
    assert stored_profile["preference_patch"]["preferred_topics"] == ["artificial_intelligence"]
    assert stored_profile["preference_patch"]["preferred_categories"] == ["C1"]
    assert stored_profile["goal"]["topics"] == ["Trí tuệ nhân tạo"]

    # 7. SP3 synthetic & real accept the exact post-edit payload
    pref = StudentPreference.model_validate(edited_pref)
    syn = personalized_plan_options(
        pref,
        target_total=res["afterEditInterest"]["target"],
        busy_intervals=[],
        availability_request=res["afterEditInterest"]["availability"],
    )
    real = real_plan_options(
        pref,
        target_total=res["afterEditInterest"]["target"],
        busy_intervals=[],
        availability_request=res["afterEditInterest"]["availability"],
    )
    assert [o["strategy"] for o in syn["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]
    assert [o["strategy"] for o in real["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_onboarding_busy_calendar_drag_15min_recurrence_exceptions_and_sp3() -> None:
    assert "Áp dụng giống nhau cho cả học kỳ" in HTML
    assert "startOnboardingGridDrag" in HTML
    assert "onboardingWeeklyParticipationHours" in HTML
    assert 'id="onboardingMaxActivities"' not in HTML

    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {}, className: '', children: [{}, {}],
      classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}, remove(){}
    });
  }
  return elements.get(id);
}

const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){},
  performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ style: {}, className: '', textContent: '', remove(){} })
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {
  const snap = expr => JSON.parse(JSON.stringify(vm.runInContext(expr, sandbox)));
  const user = { student_id: '25127777', full_name: 'Drag Tester', class: '25CTT2', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);
  vm.runInContext("onboardingStep = 2; renderOnboardingStep();", sandbox);

  // 1. Real pointer drag on Monday (2026-11-09): 08:15 (60px) -> 10:45 (180px)
  // 07:00 = 0px, 48px/hr => 08:15 = 1.25*48 = 60px, 10:45 = 3.75*48 = 180px
  vm.runInContext(`
    const fakeCol = {
      getBoundingClientRect: () => ({ top: 100, height: 672 }),
      setPointerCapture(){},
      appendChild(){}
    };
    setOnboardingSemesterBusy(true);
    setOnboardingBusyCategory('class');
    startOnboardingGridDrag({ button: 0, clientY: 160, pointerId: 1, currentTarget: fakeCol, target: fakeCol }, '2026-11-09', 0);
    moveOnboardingGridDrag({ clientY: 280 });
    endOnboardingGridDrag({ clientY: 280 });

    // Drag a second block in 'work' category on Wednesday: 18:30 (552px) -> 20:15 (636px)
    setOnboardingBusyCategory('work');
    startOnboardingGridDrag({ button: 0, clientY: 652, pointerId: 2, currentTarget: fakeCol, target: fakeCol }, '2026-11-11', 2);
    moveOnboardingGridDrag({ clientY: 736 });
    endOnboardingGridDrag({ clientY: 736 });
  `, sandbox);

  // 2. Edit the work block to 18:15-20:00, then add a partial/full override on 2026-11-16 (available 08:15-10:45) and one-off busy on 2026-11-14 (14:15-16:00)
  vm.runInContext(`
    const workEntry = onboardingDraft.profile.busy_schedule.entries.find(e => e.category === 'work');
    updateOnboardingBusyEntry(workEntry.id, { start: '18:15', end: '20:00' });
    overrideOnboardingRecurringBlock('2026-11-16', '08:15', '10:45', 'class');
    addOnboardingBusyOverride({ date: '2026-11-14', kind: 'busy', start: '14:15', end: '16:00', category: 'personal' });
    setOnboardingWeeklyHours('6.5');
    onboardingDraft.profile.goal.target_score = 88;
    onboardingDraft.profile.goal.topics = ['Công nghệ'];
    completeOnboarding();
  `, sandbox);

  await vm.runInContext("applyCurrentStudent({ student_id: '25127777', full_name: 'Drag Tester', major: 'CNTT' })", sandbox);
  const recurringSnap = snap(`({
    entries: currentProfileDraft.busy_schedule.entries,
    overrides: currentProfileDraft.busy_schedule.overrides,
    availability: plannerAvailabilityPayload(),
    preference: plannerPreferencePayload(confirmedPreference),
    target: Number(document.getElementById('inputPlanTarget').value)
  })`);

  // 3. Test one-off week mode (applies_to_semester = false): only 2026-11-09 & 2026-11-11 should be busy, NOT 2026-11-23
  vm.runInContext(`
    currentProfileDraft.busy_schedule.applies_to_semester = false;
    syncBusyScheduleAndIntervals(currentProfileDraft);
    persistCurrentUserData();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127777', full_name: 'Drag Tester', major: 'CNTT' })", sandbox);
  const oneOffSnap = snap(`({
    weekly: currentProfileDraft.weekly_intervals,
    availability: plannerAvailabilityPayload()
  })`);

  console.log(JSON.stringify({ recurringSnap, oneOffSnap }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    rec = res["recurringSnap"]
    assert rec["target"] == 88
    assert rec["preference"]["limits"]["max_duration_minutes"] == 390  # 6.5h * 60
    assert [(e["category"], e["start"], e["end"]) for e in rec["entries"]] == [
        ("class", "08:15", "10:45"),
        ("work", "18:15", "20:00"),
    ]
    busy = rec["availability"]["busy_intervals"]
    # Monday 2026-11-09 and 2026-11-23 are busy 08:15-10:45, but 2026-11-16 was overridden to available!
    assert any(b["start"] == "2026-11-09T08:15:00+07:00" and b["end"] == "2026-11-09T10:45:00+07:00" for b in busy)
    assert not any(b["start"].startswith("2026-11-16T08:15") for b in busy)
    assert any(b["start"] == "2026-11-23T08:15:00+07:00" and b["end"] == "2026-11-23T10:45:00+07:00" for b in busy)
    # One-off busy exception on Saturday 2026-11-14 14:15-16:00 is present
    assert any(b["start"] == "2026-11-14T14:15:00+07:00" and b["end"] == "2026-11-14T16:00:00+07:00" for b in busy)
    # Available override preserves the full 07:00-21:00 template in resolved SP3 availability
    resolved = resolve_availability(
        rec["availability"],
        window_start="2026-11-09T00:00:00+07:00",
        window_end="2026-11-23T23:59:59+07:00",
    )
    avail = resolved["available_intervals"]
    day_09 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-09")]
    day_16 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-16")]
    day_23 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-23")]
    assert day_09 == [
        ("2026-11-09T07:00:00+07:00", "2026-11-09T08:15:00+07:00"),
        ("2026-11-09T10:45:00+07:00", "2026-11-09T21:00:00+07:00"),
    ]
    assert day_16 == [("2026-11-16T07:00:00+07:00", "2026-11-16T21:00:00+07:00")]
    assert day_23 == [
        ("2026-11-23T07:00:00+07:00", "2026-11-23T08:15:00+07:00"),
        ("2026-11-23T10:45:00+07:00", "2026-11-23T21:00:00+07:00"),
    ]

    # One-off week mode: no weekly_intervals, 2026-11-09 busy, 2026-11-23 free
    one_off = res["oneOffSnap"]
    assert one_off["weekly"] == []
    one_off_busy = one_off["availability"]["busy_intervals"]
    assert any(b["start"] == "2026-11-09T08:15:00+07:00" for b in one_off_busy)
    assert not any(b["start"] == "2026-11-23T08:15:00+07:00" for b in one_off_busy)

    # SP3 synthetic & real accept the exact payload
    pref = StudentPreference.model_validate(rec["preference"])
    syn = personalized_plan_options(pref, target_total=rec["target"], busy_intervals=[], availability_request=rec["availability"])
    real = real_plan_options(pref, target_total=rec["target"], busy_intervals=[], availability_request=rec["availability"])
    assert [o["strategy"] for o in syn["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]
    assert [o["strategy"] for o in real["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_onboarding_step3_progressive_goals_back_edit_custom_target_and_sp3() -> None:
    assert "analyzeOnboardingGoal" not in HTML
    assert "Mục tiêu học kỳ này" in HTML
    assert "Tóm tắt lựa chọn" in HTML
    assert "ONBOARDING_ALL_TOPICS" in HTML

    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {}, className: '', children: [{}, {}],
      classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}, remove(){}, scrollIntoView(){}, setSelectionRange(){}
    });
  }
  return elements.get(id);
}

const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){},
  performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ style: {}, className: '', textContent: '', remove(){} })
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {
  const snap = expr => JSON.parse(JSON.stringify(vm.runInContext(expr, sandbox)));
  const user = { student_id: '25127666', full_name: 'Goal Tester', class: '25CTT3', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);

  // Navigate Step 1 -> Step 2 -> Step 3
  vm.runInContext("nextOnboardingStep(); nextOnboardingStep();", sandbox);
  const initialReady = snap("({ ready: isOnboardingGoalReady(), activeQ: activeOnboardingGoalQuestion, nextDisabled: document.getElementById('onboardingNextButton').disabled, topicCount: ONBOARDING_ALL_TOPICS.length })");

  // Q1 preset -> auto-advances to Q2, then Edit Q1 -> custom target 87
  vm.runInContext(`
    selectOnboardingTargetPreset(80);
    editOnboardingGoalQuestion(1);
    document.getElementById('onboardingCustomTargetInput').value = '87';
    confirmOnboardingCustomTarget();
  `, sandbox);
  const afterQ1 = snap("({ activeQ: activeOnboardingGoalQuestion, score: onboardingDraft.profile.goal.target_score, ready: isOnboardingGoalReady() })");

  // Q2 -> Q3 -> Q4
  vm.runInContext(`
    selectOnboardingCategoryChoice('C4');
    selectOnboardingModeChoice('online_only');
    selectOnboardingCampusChoice('only_nvc');
  `, sandbox);
  const afterQ4 = snap("({ activeQ: activeOnboardingGoalQuestion, ready: isOnboardingGoalReady(), nextDisabled: document.getElementById('onboardingNextButton').disabled })");

  // Navigate Back to Step 2 and Forward to Step 3 -> answers preserved!
  vm.runInContext("previousOnboardingStep(); nextOnboardingStep();", sandbox);
  const afterBackForward = snap("({ step: onboardingStep, goal: onboardingDraft.profile.goal, ready: isOnboardingGoalReady() })");

  // Q5 multi-select topics -> finish -> confirm via nextOnboardingStep() -> reload
  vm.runInContext(`
    toggleOnboardingTopicId('chemistry');
    toggleOnboardingTopicId('foreign_language');
    toggleOnboardingTopicId('safety');
    finishOnboardingTopics(false);
    nextOnboardingStep();
  `, sandbox);

  await vm.runInContext("applyCurrentStudent({ student_id: '25127666', full_name: 'Goal Tester', major: 'CNTT' })", sandbox);
  const finalState = snap(`({
    target: Number(document.getElementById('inputPlanTarget').value),
    drl_target: currentProfileDraft.drl_target,
    preference: plannerPreferencePayload(confirmedPreference),
    availability: plannerAvailabilityPayload(),
    storedGoal: readLocalUserData('25127666').profile.goal
  })`);

  console.log(JSON.stringify({ initialReady, afterQ1, afterQ4, afterBackForward, finalState }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert res["initialReady"] == {"ready": False, "activeQ": 1, "nextDisabled": True, "topicCount": 19}
    assert res["afterQ1"] == {"activeQ": 2, "score": 87, "ready": False}
    assert res["afterQ4"] == {"activeQ": 5, "ready": True, "nextDisabled": False}
    assert res["afterBackForward"]["step"] == 3
    assert res["afterBackForward"]["ready"] is True
    assert res["afterBackForward"]["goal"]["target_score"] == 87
    assert res["afterBackForward"]["goal"]["mode_choice"] == "online_only"
    assert res["afterBackForward"]["goal"]["campus_choice"] == "only_nvc"

    fin = res["finalState"]
    assert fin["target"] == 87
    assert fin["drl_target"] == 87
    pref_dict = fin["preference"]
    assert [t["topic_id"] for t in pref_dict["topic_preferences"]] == ["chemistry", "foreign_language", "safety"]
    assert [c["category_id"] for c in pref_dict["category_priorities"]] == ["C4"]
    assert [m["mode"] for m in pref_dict["mode_preferences"]] == ["online"]
    assert pref_dict["hard_exclusions"]["modes"] == ["offline", "hybrid"]
    assert [c["campus_id"] for c in pref_dict["campus_preferences"]] == ["NVC"]
    assert pref_dict["hard_exclusions"]["campus_ids"] == ["DONG_HOA", "OTHER"]

    # SP3 synthetic & real accept the exact preference payload
    pref = StudentPreference.model_validate(pref_dict)
    syn = personalized_plan_options(pref, target_total=fin["target"], busy_intervals=[], availability_request=fin["availability"])
    real = real_plan_options(pref, target_total=fin["target"], busy_intervals=[], availability_request=fin["availability"])
    assert [o["strategy"] for o in syn["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]
    assert [o["strategy"] for o in real["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_post_task3_availability_override_zero_target_and_campus_exclusions() -> None:
    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {}, className: '', children: [{}, {}],
      classList: { add(){}, remove(){}, toggle(){ return false; }, contains(){ return false; } },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}, remove(){}, scrollIntoView(){}, setSelectionRange(){}
    });
  }
  return elements.get(id);
}

const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){},
  performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ style: {}, className: '', textContent: '', remove(){} })
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {
  const snap = expr => JSON.parse(JSON.stringify(vm.runInContext(expr, sandbox)));

  // User A: DRL target = 0, two recurring busy blocks on Monday (08:15-10:45 & 14:00-16:00), override 08:15-10:45 on 2026-11-16, campus = only_nvc
  const userA = { student_id: '25127000', full_name: 'Zero Target NVC', class: '25CTT1', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + userA.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(userA.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([userA]));
  sandbox.beginOnboarding(userA);
  vm.runInContext(`
    nextOnboardingStep();
    setOnboardingSemesterBusy(true);
    addOnboardingBusyEntry({ category: 'class', weekday: 0, date: '2026-11-09', start: '08:15', end: '10:45' });
    addOnboardingBusyEntry({ category: 'work', weekday: 0, date: '2026-11-09', start: '14:00', end: '16:00' });
    overrideOnboardingRecurringBlock('2026-11-16', '08:15', '10:45', 'class');
    nextOnboardingStep();
    document.getElementById('onboardingCustomTargetInput').value = '0';
    confirmOnboardingCustomTarget();
    selectOnboardingCategoryChoice('ANY');
    selectOnboardingModeChoice('any');
    selectOnboardingCampusChoice('only_nvc');
    finishOnboardingTopics(true);
    nextOnboardingStep();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127000', full_name: 'Zero Target NVC', major: 'CNTT' })", sandbox);
  const stateA = snap(`({
    inputTarget: Number(document.getElementById('inputPlanTarget').value),
    drlTarget: currentProfileDraft.drl_target,
    goalTarget: currentProfileDraft.goal.target_score,
    plannerTarget: readLocalUserData('25127000').planner.target_total,
    availability: plannerAvailabilityPayload(),
    preference: plannerPreferencePayload(confirmedPreference)
  })`);

  // User B: campus = only_dong_hoa
  const userB = { student_id: '25127001', full_name: 'Only Dong Hoa', class: '25CTT1', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + userB.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(userB.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([userA, userB]));
  sandbox.beginOnboarding(userB);
  vm.runInContext(`
    nextOnboardingStep();
    nextOnboardingStep();
    selectOnboardingTargetPreset(80);
    selectOnboardingCategoryChoice('C1');
    selectOnboardingModeChoice('any');
    selectOnboardingCampusChoice('only_dong_hoa');
    finishOnboardingTopics(true);
    nextOnboardingStep();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127001', full_name: 'Only Dong Hoa', major: 'CNTT' })", sandbox);
  const stateB = snap(`({
    target: Number(document.getElementById('inputPlanTarget').value),
    availability: plannerAvailabilityPayload(),
    preference: plannerPreferencePayload(confirmedPreference)
  })`);

  console.log(JSON.stringify({ stateA, stateB }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    # 1. Verify actual resolved SP3 available_intervals on 2026-11-16 preserve all other free hours (07:00-14:00 & 16:00-21:00)
    state_a = res["stateA"]
    resolved = resolve_availability(
        state_a["availability"],
        window_start="2026-11-09T00:00:00+07:00",
        window_end="2026-11-23T23:59:59+07:00",
    )
    avail = resolved["available_intervals"]
    day_09 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-09")]
    day_16 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-16")]
    assert day_09 == [
        ("2026-11-09T07:00:00+07:00", "2026-11-09T08:15:00+07:00"),
        ("2026-11-09T10:45:00+07:00", "2026-11-09T14:00:00+07:00"),
        ("2026-11-09T16:00:00+07:00", "2026-11-09T21:00:00+07:00"),
    ]
    assert day_16 == [
        ("2026-11-16T07:00:00+07:00", "2026-11-16T14:00:00+07:00"),
        ("2026-11-16T16:00:00+07:00", "2026-11-16T21:00:00+07:00"),
    ]

    # 2. Verify DRL target 0 is preserved everywhere
    assert state_a["inputTarget"] == 0
    assert state_a["drlTarget"] == 0
    assert state_a["goalTarget"] == 0
    assert state_a["plannerTarget"] == 0

    # 3. Verify only_nvc and only_dong_hoa against all 4 campus IDs + unknown offline/online
    features = {
        "ACT-NVC": ActivityFeatures(frozenset(), "NVC", frozenset()),
        "ACT-DH": ActivityFeatures(frozenset(), "DONG_HOA", frozenset()),
        "ACT-ONLINE": ActivityFeatures(frozenset(), "ONLINE", frozenset()),
        "ACT-OTHER": ActivityFeatures(frozenset(), "OTHER", frozenset()),
        "ACT-UNK-OFF": ActivityFeatures(frozenset(), None, frozenset()),
        "ACT-UNK-ON": ActivityFeatures(frozenset(), None, frozenset()),
    }
    activities = {
        "ACT-NVC": {"activity_id": "ACT-NVC", "mode": "offline"},
        "ACT-DH": {"activity_id": "ACT-DH", "mode": "offline"},
        "ACT-ONLINE": {"activity_id": "ACT-ONLINE", "mode": "online"},
        "ACT-OTHER": {"activity_id": "ACT-OTHER", "mode": "offline"},
        "ACT-UNK-OFF": {"activity_id": "ACT-UNK-OFF", "mode": "offline"},
        "ACT-UNK-ON": {"activity_id": "ACT-UNK-ON", "mode": "online"},
    }

    pref_nvc = StudentPreference.model_validate(state_a["preference"])
    eng_nvc = PreferenceUtilityEngine(pref_nvc, features, activities)
    assert eng_nvc.hard_exclusion_reasons("ACT-NVC") == []
    assert eng_nvc.hard_exclusion_reasons("ACT-ONLINE") == []
    assert eng_nvc.hard_exclusion_reasons("ACT-UNK-ON") == []
    assert eng_nvc.hard_exclusion_reasons("ACT-DH") == ["campus:DONG_HOA"]
    assert eng_nvc.hard_exclusion_reasons("ACT-OTHER") == ["campus:OTHER"]
    assert eng_nvc.hard_exclusion_reasons("ACT-UNK-OFF") == ["campus:unknown"]

    pref_dh = StudentPreference.model_validate(res["stateB"]["preference"])
    eng_dh = PreferenceUtilityEngine(pref_dh, features, activities)
    assert eng_dh.hard_exclusion_reasons("ACT-DH") == []
    assert eng_dh.hard_exclusion_reasons("ACT-ONLINE") == []
    assert eng_dh.hard_exclusion_reasons("ACT-UNK-ON") == []
    assert eng_dh.hard_exclusion_reasons("ACT-NVC") == ["campus:NVC"]
    assert eng_dh.hard_exclusion_reasons("ACT-OTHER") == ["campus:OTHER"]
    assert eng_dh.hard_exclusion_reasons("ACT-UNK-OFF") == ["campus:unknown"]

    # Both synthetic and real SP3 sources work with target=0 & campus exclusions
    for pref_obj, target_val, avail_req in (
        (pref_nvc, state_a["drlTarget"], state_a["availability"]),
        (pref_dh, res["stateB"]["target"], res["stateB"]["availability"]),
    ):
        syn = personalized_plan_options(pref_obj, target_total=target_val, busy_intervals=[], availability_request=avail_req)
        real = real_plan_options(pref_obj, target_total=target_val, busy_intervals=[], availability_request=avail_req)
        assert [o["strategy"] for o in syn["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]
        assert [o["strategy"] for o in real["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_profile_and_schedule_subtabs_shared_state_and_non_destructive_conflict() -> None:
    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\b[^>]*>([\s\S]*?)<\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {}, className: '', children: [{}, {}],
      classList: {
        add(...cs){ cs.forEach(c => classes.add(c)); },
        remove(...cs){ cs.forEach(c => classes.delete(c)); },
        toggle(c, force){ if (force === undefined) { if (classes.has(c)) { classes.delete(c); return false; } classes.add(c); return true; } if (force) classes.add(c); else classes.delete(c); return force; },
        contains(c){ return classes.has(c); }
      },
      setAttribute(){}, querySelector(){ return null; }, querySelectorAll(){ return []; },
      insertAdjacentHTML(){}, focus(){}, appendChild(){}, remove(){}, scrollIntoView(){}, setSelectionRange(){}
    });
  }
  return elements.get(id);
}

const sandbox = {
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {}, setInterval: () => 1, clearInterval: () => {},
  addEventListener(){}, removeEventListener(){}, alert(){},
  performance: { now: () => 0 },
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  fetch: async () => ({ ok: false, status: 404, json: async () => ({}) }),
  document: {
    body: getEl('body'), readyState: 'complete', addEventListener(){},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({ style: {}, className: '', textContent: '', remove(){} })
  }
};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {
  const snap = expr => JSON.parse(JSON.stringify(vm.runInContext(expr, sandbox)));

  // 1. Create account, finish onboarding with initial schedule + score_history + avatar
  const user = { student_id: '25127444', full_name: 'Tab Tester', class: '25CTT1', major: 'CNTT' };
  const initData = sandbox.createDefaultLocalUserData(user.student_id, true);
  initData.profile.score_history = [{ semester: 'HK2 2025-2026', score: 86 }];
  initData.profile.avatar_data_url = 'data:image/png;base64,abc';
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(initData));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);
  vm.runInContext(`
    nextOnboardingStep();
    setOnboardingSemesterBusy(true);
    addOnboardingBusyEntry({ category: 'class', weekday: 0, date: '2026-11-09', start: '08:00', end: '10:00' });
    setOnboardingWeeklyHours('5');
    nextOnboardingStep();
    selectOnboardingTargetPreset(80);
    selectOnboardingCategoryChoice('C1');
    selectOnboardingModeChoice('prefer_online');
    selectOnboardingCampusChoice('prefer_nvc');
    toggleOnboardingTopicId('technology');
    finishOnboardingTopics(false);
    nextOnboardingStep();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127444', full_name: 'Tab Tester', major: 'CNTT' })", sandbox);

  // 2. Test tab switching: Hồ sơ <-> Lịch
  vm.runInContext("setProfileScheduleTab('schedule');", sandbox);
  const onScheduleTab = snap("({ tab: activeProfileScheduleTab, profileHidden: document.getElementById('profileSchedulePanelProfile').classList.contains('hidden'), scheduleHidden: document.getElementById('profileSchedulePanelSchedule').classList.contains('hidden') })");
  vm.runInContext("setProfileScheduleTab('profile');", sandbox);
  const onProfileTab = snap("({ tab: activeProfileScheduleTab, profileHidden: document.getElementById('profileSchedulePanelProfile').classList.contains('hidden'), scheduleHidden: document.getElementById('profileSchedulePanelSchedule').classList.contains('hidden') })");

  // 3. Edit Hồ sơ sub-tab & save -> verify unrelated fields preserved
  vm.runInContext(`
    document.getElementById('psFullName').value = 'Tab Tester Updated';
    document.getElementById('psFaculty').value = 'Khoa Toán - Tin';
    document.getElementById('psCohort').value = '2024';
    document.getElementById('psProgram').value = 'Chất lượng cao';
    document.getElementById('psSemester').value = 'HK3 · 2025–2026';
    document.getElementById('psDrlTarget').value = '92';
    psSelectCategory('C4');
    psSelectMode('online_only');
    psSelectCampus('only_nvc');
    psToggleTopic('volunteer');
    saveProfileScheduleEdits();
  `, sandbox);

  // 4. Attach an existing plan with a scheduled activity on Tuesday 2026-11-10 09:00-11:00, then drag a conflicting busy block in Lịch tab
  vm.runInContext(`
    const existingPlan = {
      plan: {
        selected_activities: [{
          activity_id: 'SEM-A',
          scheduled_blocks: [{ start: '2026-11-10T09:00:00+07:00', end: '2026-11-10T11:00:00+07:00' }]
        }]
      },
      feasibility: { candidates: [{ activity: { activity_id: 'SEM-A', title: 'Hội thảo Khoa học' } }] }
    };
    planStages.first = existingPlan;
    currentPlannerData = existingPlan;
    planInputsDirty = false;
    setProfileScheduleTab('schedule');
    addOnboardingBusyEntry({ category: 'work', weekday: 1, date: '2026-11-10', start: '08:30', end: '10:30' }, 'profile');
    overrideOnboardingRecurringBlock('2026-11-16', '08:00', '10:00', 'class', 'profile');
  `, sandbox);
  const conflictSnap = snap(`({
    dirty: planInputsDirty,
    conflicts: detectPlanBusyConflicts(),
    noticeHidden: document.getElementById('schedulePlanConflictNotice').classList.contains('hidden'),
    noticeHtml: document.getElementById('schedulePlanConflictNotice').innerHTML,
    planStillIntact: currentPlannerData?.plan?.selected_activities?.[0]?.activity_id === 'SEM-A'
  })`);

  // 5. Reload and verify persistence across tabs & onboarding model
  await vm.runInContext("applyCurrentStudent({ student_id: '25127444', full_name: 'Tab Tester Updated', major: 'Khoa Toán - Tin' })", sandbox);
  const reloaded = snap(`({
    profile: readLocalUserData('25127444').profile,
    preference: plannerPreferencePayload(confirmedPreference),
    availability: plannerAvailabilityPayload(),
    target: Number(document.getElementById('inputPlanTarget').value)
  })`);

  console.log(JSON.stringify({ onScheduleTab, onProfileTab, conflictSnap, reloaded }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert res["onScheduleTab"] == {"tab": "schedule", "profileHidden": True, "scheduleHidden": False}
    assert res["onProfileTab"] == {"tab": "profile", "profileHidden": False, "scheduleHidden": True}

    conf = res["conflictSnap"]
    assert conf["dirty"] is True
    assert conf["conflicts"] == [{"activity_id": "SEM-A", "title": "Hội thảo Khoa học"}]
    assert conf["noticeHidden"] is False
    assert "Hội thảo Khoa học" in conf["noticeHtml"]
    assert conf["planStillIntact"] is True  # non-destructive!

    rel = res["reloaded"]
    assert rel["target"] == 92
    assert rel["profile"]["faculty"] == "Khoa Toán - Tin"
    assert rel["profile"]["semester"] == "HK3 · 2025–2026"
    # Unrelated fields preserved!
    assert rel["profile"]["score_history"] == [{"semester": "HK2 2025-2026", "score": 86}]
    assert rel["profile"]["avatar_data_url"] == "data:image/png;base64,abc"
    assert rel["preference"]["limits"]["max_duration_minutes"] == 300  # 5h * 60 preserved!
    assert [c["category_id"] for c in rel["preference"]["category_priorities"]] == ["C4"]
    assert rel["preference"]["hard_exclusions"]["modes"] == ["offline", "hybrid"]
    assert rel["preference"]["hard_exclusions"]["campus_ids"] == ["DONG_HOA", "OTHER"]
    assert set(t["topic_id"] for t in rel["preference"]["topic_preferences"]) == {"technology", "volunteer"}

    # Resolved SP3 availability honors both the new Tuesday busy block AND the Monday 2026-11-16 available override
    resolved = resolve_availability(
        rel["availability"],
        window_start="2026-11-09T00:00:00+07:00",
        window_end="2026-11-17T23:59:59+07:00",
    )
    avail = resolved["available_intervals"]
    tue_10 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-10")]
    mon_16 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-16")]
    assert tue_10 == [
        ("2026-11-10T07:00:00+07:00", "2026-11-10T08:30:00+07:00"),
        ("2026-11-10T10:30:00+07:00", "2026-11-10T21:00:00+07:00"),
    ]
    assert mon_16 == [("2026-11-16T07:00:00+07:00", "2026-11-16T21:00:00+07:00")]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_task5_options_cards_duplicates_partial_failure_and_review_contract() -> None:
    pref = StudentPreference.model_validate({
        "topic_preferences": [{"topic_id": "technology", "weight": 5}],
        "category_priorities": [{"category_id": "C1", "weight": 5}],
        "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
        "mode_preferences": [],
        "time_preferences": [],
        "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
        "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
        "strategy": "BALANCED",
    })
    real_opts = real_plan_options(pref, target_total=80, busy_intervals=[], availability_request=None)
    assert [o["strategy"] for o in real_opts["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]

    # Build a synthetic partial-failure + duplicate payload derived from real_opts
    opts_with_dup_and_fail = json.loads(json.dumps(real_opts["options"]))
    opts_with_dup_and_fail[1]["duplicate_of"] = "MINIMUM_EFFORT"
    opts_with_dup_and_fail[2] = {
        "strategy": "PREFERENCE_FIRST",
        "status": "FAILED",
        "error": "Không tìm thấy lịch hợp lệ cho chiến lược này.",
        "result": None,
    }

    js = f"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\\b[^>]*>([\\s\\S]*?)<\\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {{
  if (!elements.has(id)) {{
    const classes = new Set();
    elements.set(id, {{
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {{}}, className: '', children: [{{}}, {{}}],
      classList: {{
        add(...cs){{ cs.forEach(c => classes.add(c)); }},
        remove(...cs){{ cs.forEach(c => classes.delete(c)); }},
        toggle(c, force){{ if (force === undefined) {{ if (classes.has(c)) {{ classes.delete(c); return false; }} classes.add(c); return true; }} if (force) classes.add(c); else classes.delete(c); return force; }},
        contains(c){{ return classes.has(c); }}
      }},
      setAttribute(){{}}, querySelector(){{ return null; }}, querySelectorAll(){{ return []; }},
      insertAdjacentHTML(){{}}, focus(){{}}, appendChild(){{}}, remove(){{}}, scrollIntoView(){{}}, setSelectionRange(){{}}
    }});
  }}
  return elements.get(id);
}}

const sandbox = {{
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {{}}, setInterval: () => 1, clearInterval: () => {{}},
  addEventListener(){{}}, removeEventListener(){{}}, alert(){{}},
  performance: {{ now: () => 0 }},
  localStorage: {{
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  }},
  fetch: async () => ({{ ok: false, status: 404, json: async () => ({{}}) }}),
  document: {{
    body: getEl('body'), readyState: 'complete', addEventListener(){{}},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({{ style: {{}}, className: '', textContent: '', remove(){{}} }})
  }}
}};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {{
  sandbox.__realOptions = {json.dumps(real_opts["options"])};
  sandbox.__mixedOptions = {json.dumps(opts_with_dup_and_fail)};

  // 1. Render real-source 3 strategy cards
  vm.runInContext(`
    cachedPlanOptions = __realOptions;
    selectedPlanOptionIndex = initialReadyPlanOptionIndex(__realOptions, 'BALANCED');
    renderPlanOptionsSelector();
  `, sandbox);
  const realCardsHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;

  // 2. Render duplicate + partial failure cards, verify selecting ready card 1 works and failed card 2 is ignored
  vm.runInContext(`
    cachedPlanOptions = __mixedOptions;
    selectedPlanOptionIndex = 0;
    selectCachedPlanOption(1);
    selectCachedPlanOption(2);
  `, sandbox);
  const mixedHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;
  const selectedAfterMixed = vm.runInContext("selectedPlanOptionIndex", sandbox);

  // 3. Open dedicated review screen -> test missing contract message, then registered contract delegation
  sandbox.openPlanReviewScreen(1);
  const reviewHidden = sandbox.document.getElementById('planReviewScreen').classList.contains('hidden');
  const reviewHtml = sandbox.document.getElementById('planReviewScreen').innerHTML;
  await sandbox.confirmSelectedPlanViaContract();
  const missingContractMsg = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  let delegatedPayload = null;
  sandbox.window.UniLifePlanReviewContract = {{
    async confirmPlan(payload) {{ delegatedPayload = payload; }}
  }};
  await sandbox.confirmSelectedPlanViaContract();

  console.log(JSON.stringify({{
    realCardsHtml,
    mixedHtml,
    selectedAfterMixed,
    reviewHidden,
    reviewHtml,
    missingContractMsg,
    delegatedStrategy: delegatedPayload?.strategy || null
  }}));
}})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    for strategy in ("MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"):
        assert f'data-strategy-card="{strategy}"' in res["realCardsHtml"]
    assert "Chưa biết (chưa xác minh)" in res["realCardsHtml"]

    assert 'data-strategy-card="PREFERENCE_FIRST" data-status="FAILED"' in res["mixedHtml"]
    assert "Trùng lịch với phương án" in res["mixedHtml"]
    assert res["selectedAfterMixed"] == 1

    assert res["reviewHidden"] is False
    assert "Màn hình Rà soát kế hoạch" in res["reviewHtml"]
    assert "Chưa có module confirmed_plan của Thảo Duyên" in res["missingContractMsg"]
    assert res["delegatedStrategy"] == "BALANCED"








  // 1. Create account, finish onboarding with initial schedule + score_history + avatar
  const user = { student_id: '25127444', full_name: 'Tab Tester', class: '25CTT1', major: 'CNTT' };
  const initData = sandbox.createDefaultLocalUserData(user.student_id, true);
  initData.profile.score_history = [{ semester: 'HK2 2025-2026', score: 86 }];
  initData.profile.avatar_data_url = 'data:image/png;base64,abc';
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(initData));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);
  vm.runInContext(`
    nextOnboardingStep();
    setOnboardingSemesterBusy(true);
    addOnboardingBusyEntry({ category: 'class', weekday: 0, date: '2026-11-09', start: '08:00', end: '10:00' });
    setOnboardingWeeklyHours('5');
    nextOnboardingStep();
    selectOnboardingTargetPreset(80);
    selectOnboardingCategoryChoice('C1');
    selectOnboardingModeChoice('prefer_online');
    selectOnboardingCampusChoice('prefer_nvc');
    toggleOnboardingTopicId('technology');
    finishOnboardingTopics(false);
    nextOnboardingStep();
  `, sandbox);
  await vm.runInContext("applyCurrentStudent({ student_id: '25127444', full_name: 'Tab Tester', major: 'CNTT' })", sandbox);

  // 2. Test tab switching: Hồ sơ <-> Lịch
  vm.runInContext("setProfileScheduleTab('schedule');", sandbox);
  const onScheduleTab = snap("({ tab: activeProfileScheduleTab, profileHidden: document.getElementById('profileSchedulePanelProfile').classList.contains('hidden'), scheduleHidden: document.getElementById('profileSchedulePanelSchedule').classList.contains('hidden') })");
  vm.runInContext("setProfileScheduleTab('profile');", sandbox);
  const onProfileTab = snap("({ tab: activeProfileScheduleTab, profileHidden: document.getElementById('profileSchedulePanelProfile').classList.contains('hidden'), scheduleHidden: document.getElementById('profileSchedulePanelSchedule').classList.contains('hidden') })");

  // 3. Edit Hồ sơ sub-tab & save -> verify unrelated fields preserved
  vm.runInContext(`
    document.getElementById('psFullName').value = 'Tab Tester Updated';
    document.getElementById('psFaculty').value = 'Khoa Toán - Tin';
    document.getElementById('psCohort').value = '2024';
    document.getElementById('psProgram').value = 'Chất lượng cao';
    document.getElementById('psSemester').value = 'HK3 · 2025–2026';
    document.getElementById('psDrlTarget').value = '92';
    psSelectCategory('C4');
    psSelectMode('online_only');
    psSelectCampus('only_nvc');
    psToggleTopic('volunteer');
    saveProfileScheduleEdits();
  `, sandbox);

  // 4. Attach an existing plan with a scheduled activity on Tuesday 2026-11-10 09:00-11:00, then drag a conflicting busy block in Lịch tab
  vm.runInContext(`
    const existingPlan = {
      plan: {
        selected_activities: [{
          activity_id: 'SEM-A',
          scheduled_blocks: [{ start: '2026-11-10T09:00:00+07:00', end: '2026-11-10T11:00:00+07:00' }]
        }]
      },
      feasibility: { candidates: [{ activity: { activity_id: 'SEM-A', title: 'Hội thảo Khoa học' } }] }
    };
    planStages.first = existingPlan;
    currentPlannerData = existingPlan;
    planInputsDirty = false;
    setProfileScheduleTab('schedule');
    addOnboardingBusyEntry({ category: 'work', weekday: 1, date: '2026-11-10', start: '08:30', end: '10:30' }, 'profile');
    overrideOnboardingRecurringBlock('2026-11-16', '08:00', '10:00', 'class', 'profile');
  `, sandbox);
  const conflictSnap = snap(`({
    dirty: planInputsDirty,
    conflicts: detectPlanBusyConflicts(),
    noticeHidden: document.getElementById('schedulePlanConflictNotice').classList.contains('hidden'),
    noticeHtml: document.getElementById('schedulePlanConflictNotice').innerHTML,
    planStillIntact: currentPlannerData?.plan?.selected_activities?.[0]?.activity_id === 'SEM-A'
  })`);

  // 5. Reload and verify persistence across tabs & onboarding model
  await vm.runInContext("applyCurrentStudent({ student_id: '25127444', full_name: 'Tab Tester Updated', major: 'Khoa Toán - Tin' })", sandbox);
  const reloaded = snap(`({
    profile: readLocalUserData('25127444').profile,
    preference: plannerPreferencePayload(confirmedPreference),
    availability: plannerAvailabilityPayload(),
    target: Number(document.getElementById('inputPlanTarget').value)
  })`);

  console.log(JSON.stringify({ onScheduleTab, onProfileTab, conflictSnap, reloaded }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert res["onScheduleTab"] == {"tab": "schedule", "profileHidden": True, "scheduleHidden": False}
    assert res["onProfileTab"] == {"tab": "profile", "profileHidden": False, "scheduleHidden": True}

    conf = res["conflictSnap"]
    assert conf["dirty"] is True
    assert conf["conflicts"] == [{"activity_id": "SEM-A", "title": "Hội thảo Khoa học"}]
    assert conf["noticeHidden"] is False
    assert "Hội thảo Khoa học" in conf["noticeHtml"]
    assert conf["planStillIntact"] is True  # non-destructive!

    rel = res["reloaded"]
    assert rel["target"] == 92
    assert rel["profile"]["faculty"] == "Khoa Toán - Tin"
    assert rel["profile"]["semester"] == "HK3 · 2025–2026"
    # Unrelated fields preserved!
    assert rel["profile"]["score_history"] == [{"semester": "HK2 2025-2026", "score": 86}]
    assert rel["profile"]["avatar_data_url"] == "data:image/png;base64,abc"
    assert rel["preference"]["limits"]["max_duration_minutes"] == 300  # 5h * 60 preserved!
    assert [c["category_id"] for c in rel["preference"]["category_priorities"]] == ["C4"]
    assert rel["preference"]["hard_exclusions"]["modes"] == ["offline", "hybrid"]
    assert rel["preference"]["hard_exclusions"]["campus_ids"] == ["DONG_HOA", "OTHER"]
    assert set(t["topic_id"] for t in rel["preference"]["topic_preferences"]) == {"technology", "volunteer"}

    # Resolved SP3 availability honors both the new Tuesday busy block AND the Monday 2026-11-16 available override
    resolved = resolve_availability(
        rel["availability"],
        window_start="2026-11-09T00:00:00+07:00",
        window_end="2026-11-17T23:59:59+07:00",
    )
    avail = resolved["available_intervals"]
    tue_10 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-10")]
    mon_16 = [(i["start"], i["end"]) for i in avail if i["start"].startswith("2026-11-16")]
    assert tue_10 == [
        ("2026-11-10T07:00:00+07:00", "2026-11-10T08:30:00+07:00"),
        ("2026-11-10T10:30:00+07:00", "2026-11-10T21:00:00+07:00"),
    ]
    assert mon_16 == [("2026-11-16T07:00:00+07:00", "2026-11-16T21:00:00+07:00")]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_task5_options_cards_duplicates_partial_failure_and_review_contract() -> None:
    pref = StudentPreference.model_validate({
        "topic_preferences": [{"topic_id": "technology", "weight": 5}],
        "category_priorities": [{"category_id": "C1", "weight": 5}],
        "campus_preferences": [{"campus_id": "NVC", "weight": 5}],
        "mode_preferences": [],
        "time_preferences": [],
        "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
        "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
        "strategy": "BALANCED",
    })
    real_opts = real_plan_options(pref, target_total=80, busy_intervals=[], availability_request=None)
    assert [o["strategy"] for o in real_opts["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]

    # Build a synthetic partial-failure + duplicate payload derived from real_opts
    opts_with_dup_and_fail = json.loads(json.dumps(real_opts["options"]))
    opts_with_dup_and_fail[1]["duplicate_of"] = "MINIMUM_EFFORT"
    opts_with_dup_and_fail[2] = {
        "strategy": "PREFERENCE_FIRST",
        "status": "FAILED",
        "error": "Không tìm thấy lịch hợp lệ cho chiến lược này.",
        "result": None,
    }

    js = f"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script\\b[^>]*>([\\s\\S]*?)<\\/script>/gi)].map(m => m[1]);
const mainScript = scripts[scripts.length - 1];

const storage = new Map();
const elements = new Map();
function getEl(id) {{
  if (!elements.has(id)) {{
    const classes = new Set();
    elements.set(id, {{
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, style: {{}}, className: '', children: [{{}}, {{}}],
      classList: {{
        add(...cs){{ cs.forEach(c => classes.add(c)); }},
        remove(...cs){{ cs.forEach(c => classes.delete(c)); }},
        toggle(c, force){{ if (force === undefined) {{ if (classes.has(c)) {{ classes.delete(c); return false; }} classes.add(c); return true; }} if (force) classes.add(c); else classes.delete(c); return force; }},
        contains(c){{ return classes.has(c); }}
      }},
      setAttribute(){{}}, querySelector(){{ return null; }}, querySelectorAll(){{ return []; }},
      insertAdjacentHTML(){{}}, focus(){{}}, appendChild(){{}}, remove(){{}}, scrollIntoView(){{}}, setSelectionRange(){{}}
    }});
  }}
  return elements.get(id);
}}

const sandbox = {{
  console, Date, Math, Number, String, Boolean, Array, Object, Set, Map, RegExp, JSON, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, unescape, escape,
  setTimeout: () => 1, clearTimeout: () => {{}}, setInterval: () => 1, clearInterval: () => {{}},
  addEventListener(){{}}, removeEventListener(){{}}, alert(){{}},
  performance: {{ now: () => 0 }},
  localStorage: {{
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  }},
  fetch: async () => ({{ ok: false, status: 404, json: async () => ({{}}) }}),
  document: {{
    body: getEl('body'), readyState: 'complete', addEventListener(){{}},
    getElementById: id => getEl(id), querySelector: () => null, querySelectorAll: () => [],
    createElement: () => ({{ style: {{}}, className: '', textContent: '', remove(){{}} }})
  }}
}};
sandbox.window = sandbox;
vm.createContext(sandbox);
vm.runInContext(mainScript, sandbox);

(async () => {{
  sandbox.__realOptions = {json.dumps(real_opts["options"])};
  sandbox.__mixedOptions = {json.dumps(opts_with_dup_and_fail)};

  // 1. Render real-source 3 strategy cards
  vm.runInContext(`
    cachedPlanOptions = __realOptions;
    selectedPlanOptionIndex = initialReadyPlanOptionIndex(__realOptions, 'BALANCED');
    renderPlanOptionsSelector();
  `, sandbox);
  const realCardsHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;

  // 2. Render duplicate + partial failure cards, verify selecting ready card 1 works and failed card 2 is ignored
  vm.runInContext(`
    cachedPlanOptions = __mixedOptions;
    selectedPlanOptionIndex = 0;
    selectCachedPlanOption(1);
    selectCachedPlanOption(2);
  `, sandbox);
  const mixedHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;
  const selectedAfterMixed = vm.runInContext("selectedPlanOptionIndex", sandbox);

  // 3. Open dedicated review screen -> test missing contract message, then registered contract delegation
  sandbox.openPlanReviewScreen(1);
  const reviewHidden = sandbox.document.getElementById('planReviewScreen').classList.contains('hidden');
  const reviewHtml = sandbox.document.getElementById('planReviewScreen').innerHTML;
  await sandbox.confirmSelectedPlanViaContract();
  const missingContractMsg = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  let delegatedPayload = null;
  sandbox.window.UniLifePlanReviewContract = {{
    async confirmPlan(payload) {{ delegatedPayload = payload; }}
  }};
  await sandbox.confirmSelectedPlanViaContract();

  console.log(JSON.stringify({{
    realCardsHtml,
    mixedHtml,
    selectedAfterMixed,
    reviewHidden,
    reviewHtml,
    missingContractMsg,
    delegatedStrategy: delegatedPayload?.strategy || null
  }}));
}})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    for strategy in ("MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"):
        assert f'data-strategy-card="{strategy}"' in res["realCardsHtml"]
    assert "Chưa biết (chưa xác minh)" in res["realCardsHtml"]

    assert 'data-strategy-card="PREFERENCE_FIRST" data-status="FAILED"' in res["mixedHtml"]
    assert "Trùng lịch với phương án" in res["mixedHtml"]
    assert res["selectedAfterMixed"] == 1

    assert res["reviewHidden"] is False
    assert "Màn hình Rà soát kế hoạch" in res["reviewHtml"]
    assert "Chưa có module confirmed_plan của Thảo Duyên" in res["missingContractMsg"]
    assert res["delegatedStrategy"] == "BALANCED"







