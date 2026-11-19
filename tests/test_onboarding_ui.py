from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from api.sp3_real import real_plan_options
from api.sp3_service import personalized_plan_options
from personalization.models import StudentPreference


ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT / "web" / "index.html").read_text(encoding="utf-8")


def test_dashboard_assistant_is_replaced_by_one_time_onboarding_and_profile_editor() -> None:
    assert 'id="unilifeAssistant"' not in HTML
    assert 'id="onboardingModal"' in HTML
    assert 'id="onboardingWizard"' not in HTML
    assert "NOT_STARTED" in HTML and "IN_PROGRESS" in HTML and "COMPLETED" in HTML
    assert "AI chỉnh sửa hồ sơ" in HTML
    assert "/api/profile-assistant/interpret" in HTML
    assert 'id="onboardingScores"' not in HTML
    assert "Bước 1 / 3" in HTML
    assert "hydrateOnboardingFormFromDraft" not in HTML
    assert "resetOnboardingAssistantState" not in HTML
    assert "mapTopicInputsToTopicIds" in HTML
    assert "mapPriorityInputsToCategories" in HTML
    assert "syncBusyScheduleAndIntervals" in HTML
    assert "editProfileProposalInterval" in HTML
    assert "JSON.stringify(change.new)" not in HTML
    assert "renderProfileProposalChanges" in HTML
    assert "function isAvailabilityCellBusy" in HTML
    assert "renderPlanOptionsSelectorBase" not in HTML


def test_profile_schedule_workspace_and_local_migration_are_present() -> None:
    assert "Hồ sơ & Lịch" in HTML
    for label in ("Hồ sơ sinh viên", "Lịch cá nhân", "Kế hoạch thông minh"):
        assert label in HTML
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
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent,
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
    raw = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
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
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent,
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
    raw = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
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
    # Available override is also emitted in canonical availability exceptions
    assert any(ex["date"] == "2026-11-16" and ex["blocks"] == [{"start_time": "08:15", "end_time": "10:45"}] for ex in rec["availability"]["exceptions"])

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
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent,
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
    raw = subprocess.check_output(["node", "-e", js], cwd=ROOT, text=True)
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
    assert pref_dict["hard_exclusions"]["campus_ids"] == ["DONG_HOA"]

    # SP3 synthetic & real accept the exact preference payload
    pref = StudentPreference.model_validate(pref_dict)
    syn = personalized_plan_options(pref, target_total=fin["target"], busy_intervals=[], availability_request=fin["availability"])
    real = real_plan_options(pref, target_total=fin["target"], busy_intervals=[], availability_request=fin["availability"])
    assert [o["strategy"] for o in syn["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]
    assert [o["strategy"] for o in real["options"]] == ["MINIMUM_EFFORT", "BALANCED", "PREFERENCE_FIRST"]




