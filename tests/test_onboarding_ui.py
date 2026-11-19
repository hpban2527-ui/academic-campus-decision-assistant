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
def test_task5_options_cards_duplicates_partial_failure_and_review_navigation() -> None:
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

  // 1. Real-source 3 strategy cards
  vm.runInContext(`
    SP3_SOURCE = 'real';
    cachedPlanOptions = __realOptions;
    selectedPlanOptionIndex = initialReadyPlanOptionIndex(__realOptions, 'BALANCED');
    setPlannerScreenMode('options');
    renderPlanOptionsSelector();
  `, sandbox);
  const realCardsHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;

  // 2. Duplicate + partial failure cards: selecting ready card 1 works, failed card 2 is ignored
  vm.runInContext(`
    cachedPlanOptions = __mixedOptions;
    selectedPlanOptionIndex = 0;
    selectCachedPlanOption(1);
    selectCachedPlanOption(2);
  `, sandbox);
  const mixedHtml = sandbox.document.getElementById('planOptionsSelector').innerHTML;
  const selectedAfterMixed = vm.runInContext('selectedPlanOptionIndex', sandbox);

  // 3. Mutually exclusive Options <-> Review screens + Back button + real-source swap disabled
  sandbox.openPlanReviewScreen(1);
  const onReview = {{
    optionsHidden: sandbox.document.getElementById('smartPlanSection').classList.contains('hidden'),
    reviewHidden: sandbox.document.getElementById('planReviewScreen').classList.contains('hidden'),
    reviewHtml: sandbox.document.getElementById('planReviewScreen').innerHTML,
  }};
  sandbox.setPlannerScreenMode('options');
  const afterBack = {{
    optionsHidden: sandbox.document.getElementById('smartPlanSection').classList.contains('hidden'),
    reviewHidden: sandbox.document.getElementById('planReviewScreen').classList.contains('hidden'),
  }};

  console.log(JSON.stringify({{ realCardsHtml, mixedHtml, selectedAfterMixed, onReview, afterBack }}));
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

    # Options and Review are mutually exclusive
    assert res["onReview"]["optionsHidden"] is True
    assert res["onReview"]["reviewHidden"] is False
    assert "Bước 2 · Rà soát kế hoạch" in res["onReview"]["reviewHtml"]
    assert 'data-review-action="change" disabled' in res["onReview"]["reviewHtml"]
    assert res["afterBack"] == {"optionsHidden": False, "reviewHidden": True}


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_task5_review_swap_remove_and_confirmation_persistence_semantics() -> None:
    pref = StudentPreference.model_validate({
        "topic_preferences": [{"topic_id": "mathematics", "weight": 5}],
        "category_priorities": [{"category_id": "C1", "weight": 5}],
        "campus_preferences": [],
        "mode_preferences": [],
        "time_preferences": [],
        "limits": {"max_activities": None, "max_duration_minutes": None, "max_fee": None},
        "hard_exclusions": {"campus_ids": [], "modes": [], "time_slots": []},
        "strategy": "BALANCED",
    })
    syn_opts = personalized_plan_options(pref, target_total=80, busy_intervals=[], availability_request=None)

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
  sandbox.__synOptions = {json.dumps(syn_opts["options"])};
  vm.runInContext(`
    SP3_SOURCE = 'synthetic';
    cachedPlanOptions = __synOptions;
    selectedPlanOptionIndex = initialReadyPlanOptionIndex(__synOptions, 'BALANCED');
    openPlanReviewScreen(selectedPlanOptionIndex);
  `, sandbox);

  const reviewHtml = sandbox.document.getElementById('planReviewScreen').innerHTML;
  const firstActId = vm.runInContext('currentPlannerData.plan.selected_activities[0].activity_id', sandbox);

  // Swap & Remove actions work on synthetic without throwing ReferenceError
  sandbox.openReviewActivitySwap(firstActId);
  const swapModalOpen = !sandbox.document.getElementById('smartSwapModal').classList.contains('hidden');
  sandbox.openPlannedActivityDetails(firstActId);
  const removeModalHtml = sandbox.document.getElementById('smartSwapContent').innerHTML;

  // Confirmation semantics:
  // 1) Missing contract
  const rMissing = await sandbox.confirmSelectedPlanViaContract();
  const msgMissing = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  // 2) Contract returns persisted=false (must NOT report success)
  sandbox.window.UniLifePlanReviewContract = {{
    async confirmPlan() {{ return {{ persisted: false, error: 'Server offline' }}; }}
  }};
  const rNotPersisted = await sandbox.confirmSelectedPlanViaContract();
  const msgNotPersisted = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  // 3) Contract throws error (must catch safely & NOT report success)
  sandbox.window.UniLifePlanReviewContract = {{
    async confirmPlan() {{ throw new Error('Network timeout'); }}
  }};
  const rError = await sandbox.confirmSelectedPlanViaContract();
  const msgError = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  // 4) Contract confirms actual persistence
  sandbox.window.UniLifePlanReviewContract = {{
    async confirmPlan(payload) {{ return {{ persisted: true, plan_id: 'plan-1', strategy: payload.strategy }}; }}
  }};
  const rSuccess = await sandbox.confirmSelectedPlanViaContract();
  const msgSuccess = sandbox.document.getElementById('planReviewConfirmStatus').textContent;

  console.log(JSON.stringify({{
    reviewHtml,
    swapModalOpen,
    removeModalHtml,
    rMissing, msgMissing,
    rNotPersisted, msgNotPersisted,
    rError, msgError,
    rSuccess, msgSuccess
  }}));
}})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert 'data-review-action="change" onclick=' in res["reviewHtml"]
    assert 'data-review-action="remove"' not in res["reviewHtml"]
    assert res["swapModalOpen"] is True
    assert "Thay đổi" in res["removeModalHtml"]

    assert res["rMissing"] == {"confirmed": False, "reason": "CONTRACT_UNAVAILABLE"}
    assert "Chưa có module confirmed_plan của Thảo Duyên" in res["msgMissing"]

    assert res["rNotPersisted"] == {"confirmed": False, "reason": "Server offline"}
    assert "✓" not in res["msgNotPersisted"] and "Server offline" in res["msgNotPersisted"]

    assert res["rError"] == {"confirmed": False, "reason": "Network timeout"}
    assert "✓" not in res["msgError"] and "Network timeout" in res["msgError"]

    assert res["rSuccess"]["confirmed"] is True
    assert "✓ Kế hoạch đã được xác nhận và lưu thành công." in res["msgSuccess"]


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is required for frontend integration test")
def test_navigation_view_isolation_onboarding_to_dashboard_and_program_select() -> None:
    # 1. #viewProfile must NOT have xl:grid on its top-level element (which overrode hidden at >=1280px)
    assert '<div id="viewProfile" class="hidden">' in HTML
    assert 'id="viewProfile" class="hidden space-y-6 xl:min-h' not in HTML
    # 2. All 3 program controls are selects with exactly 2 choices
    assert '<select id="profileProgram"' in HTML
    assert '<select id="psProgram"' in HTML
    assert '<select id="onboardingProgram"' in HTML
    assert 'STUDENT_PROGRAMS = ["Chương trình Chuẩn", "Chương trình Chất lượng cao"]' in HTML

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
    const classes = new Set(id.startsWith('view') && id !== 'viewDashboard' ? ['hidden'] : []);
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: true, disabled: false, hidden: classes.has('hidden'), style: {}, className: '', children: [{}, {}],
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
  requestAnimationFrame: fn => fn(), scrollTo(){},
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
  // A. Legacy program normalization
  const norm = {
    clc: sandbox.normalizeStudentProgram('CLC'),
    chatLuongCao: sandbox.normalizeStudentProgram('Chất lượng cao'),
    daiTra: sandbox.normalizeStudentProgram('Đại trà'),
    chuan: sandbox.normalizeStudentProgram('Chương trình chuẩn'),
    empty: sandbox.normalizeStudentProgram(''),
  };

  // B. Legacy saved account migration preserves unrelated data & normalizes program
  const legacySaved = {
    schema_version: 1,
    student_id: '25127111',
    profile: { faculty: 'CNTT', program: 'CLC', score_history: [{ semester: 'HK1', score: 85 }] }
  };
  sandbox.localStorage.setItem('unilife_data_25127111', JSON.stringify(legacySaved));
  const migrated = sandbox.readLocalUserData('25127111');

  // C. Registration -> onboarding (select CLC) -> completeOnboarding -> finishWelcome -> lands on dashboard
  const user = { student_id: '25127222', full_name: 'Nav Tester', class: '25CTT1', major: 'CNTT' };
  sandbox.localStorage.setItem('unilife_data_' + user.student_id, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
  sandbox.localStorage.setItem('unilife_users', JSON.stringify([user]));
  sandbox.beginOnboarding(user);
  vm.runInContext(`
    updateOnboardingProfileField('program', 'Chương trình Chất lượng cao');
    nextOnboardingStep();
    nextOnboardingStep();
    selectOnboardingTargetPreset(80);
    selectOnboardingCategoryChoice('C1');
    selectOnboardingModeChoice('any');
    selectOnboardingCampusChoice('any');
    finishOnboardingTopics(true);
    nextOnboardingStep();
    finishWelcome();
  `, sandbox);

  const afterWelcome = {
    dashboardVisible: !sandbox.document.getElementById('viewDashboard').classList.contains('hidden') && !sandbox.document.getElementById('viewDashboard').hidden,
    profileHidden: sandbox.document.getElementById('viewProfile').classList.contains('hidden') && sandbox.document.getElementById('viewProfile').hidden,
  };

  // D. Switch across every sidebar page and verify ONLY that single view is visible
  const tabs = ['dashboard', 'profile', 'calculator', 'activities', 'snapshot', 'plan', 'testSuites', 'inspector'];
  const tabIsolation = {};
  for (const t of tabs) {
    sandbox.switchTab(t);
    const visible = tabs.filter(other => {
      const el = sandbox.document.getElementById('view' + sandbox.capitalize(other));
      return !el.classList.contains('hidden') && !el.hidden;
    });
    tabIsolation[t] = visible;
  }

  // E. Reload and verify program persisted to both Student Profile and Planning Profile
  await vm.runInContext("applyCurrentStudent({ student_id: '25127222', full_name: 'Nav Tester', major: 'CNTT' })", sandbox);
  const reloadedProgram = {
    stored: sandbox.readLocalUserData('25127222').profile.program,
    profileSelect: sandbox.document.getElementById('profileProgram').value,
    psHtmlHasSelected: sandbox.document.getElementById('profileScheduleProfileBody').innerHTML.includes('value="Chương trình Chất lượng cao" selected'),
  };

  console.log(JSON.stringify({ norm, migratedProgram: migrated.profile.program, migratedScores: migrated.profile.score_history, afterWelcome, tabIsolation, reloadedProgram }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert res["norm"] == {
        "clc": "Chương trình Chất lượng cao",
        "chatLuongCao": "Chương trình Chất lượng cao",
        "daiTra": "Chương trình Chuẩn",
        "chuan": "Chương trình Chuẩn",
        "empty": "Chương trình Chuẩn",
    }
    assert res["migratedProgram"] == "Chương trình Chất lượng cao"
    assert res["migratedScores"] == [{"semester": "HK1", "score": 85}]
    assert res["afterWelcome"] == {"dashboardVisible": True, "profileHidden": True}
    for tab, visible_list in res["tabIsolation"].items():
        assert visible_list == [tab]
    assert res["reloadedProgram"] == {
        "stored": "Chương trình Chất lượng cao",
        "profileSelect": "Chương trình Chất lượng cao",
        "psHtmlHasSelected": True,
    }


def test_profile_schedule_strict_separation_activity_calendar_availability_and_no_demos():
    """Verify TASK 2: Hồ sơ & Lịch strict subpage separation, activity calendar first,
    separate personal availability subview affecting SP3, no demo scenarios, and
    options -> review -> confirm returning to activity calendar.
    """
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")

    # 1. Static DOM & demo-scenario removal checks
    for forbidden in [
        'id="planStepper"',
        'id="planChangeCard"',
        "Tình huống mẫu",
        "Khi lịch của bạn thay đổi",
        "Khi bạn bỏ một hoạt động",
        "Mô phỏng thay đổi lịch",
    ]:
        assert forbidden not in html, f"Demo scenario markup/copy must be removed: {forbidden}"

    view_plan_start = html.index('id="viewPlan"')
    view_profile_start = html.index('id="viewProfile"')
    view_plan_html = html[view_plan_start:view_profile_start]

    profile_panel_start = view_plan_html.index('id="profileSchedulePanelProfile"')
    schedule_panel_start = view_plan_html.index('id="profileSchedulePanelSchedule"')
    profile_panel_html = view_plan_html[profile_panel_start:schedule_panel_start]
    schedule_panel_html = view_plan_html[schedule_panel_start:]

    # Profile subpage contains ONLY planning preferences, no Planner calendars or options
    assert 'id="profileScheduleProfileBody"' in profile_panel_html
    for must_not_be_in_profile in [
        'id="planCalendarView"',
        'id="smartPlanSection"',
        'id="planReviewScreen"',
        'id="profileAvailabilitySubview"',
    ]:
        assert must_not_be_in_profile not in profile_panel_html

    # Schedule subpage owns all 4 mutually exclusive subviews + required buttons
    for must_be_in_schedule in [
        'id="scheduleActivityCalendarSubview"',
        'id="profileAvailabilitySubview"',
        'id="smartPlanSection"',
        'id="btnOpenPersonalAvailability"',
        "Lịch bận/rảnh của tôi",
        "Lập kế hoạch lần đầu",
    ]:
        assert must_be_in_schedule in schedule_panel_html
    # Review is the shared full-screen dialog, outside the mutually exclusive schedule subviews.
    assert 'id="planReviewScreen"' in html
    assert html.count('id="planReviewScreen"') == 1
    assert 'aria-modal="true"' in html[html.index('id="planReviewScreen"'):html.index('id="planReviewScreen"') + 250]

    # 2. Runtime behavior in Node VM + actual Python SP3 resolve_availability check
    js = r"""
const fs = require('fs');
const vm = require('vm');
const html = fs.readFileSync('web/index.html', 'utf8');
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

const elements = new Map();
function makeEl(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {
      id, value: id === 'inputPlanTarget' ? '80' : '', innerText: '', textContent: '', innerHTML: '',
      checked: false, disabled: false, hidden: false, style: {}, dataset: {},
      classList: {
        add: (...c) => c.forEach(x => classes.add(x)),
        remove: (...c) => c.forEach(x => classes.delete(x)),
        toggle: (c, f) => { if (f === undefined) { classes.has(c) ? classes.delete(c) : classes.add(c); } else if (f) classes.add(c); else classes.delete(c); },
        contains: c => classes.has(c)
      },
      setAttribute(k, v) { this[k] = v; },
      getAttribute(k) { return this[k]; },
      focus() {}, scrollIntoView() {}, scrollTo() {},
      querySelector() { return makeEl(id + ':q'); },
      querySelectorAll() { return []; },
      appendChild() {}
    });
  }
  return elements.get(id);
}

const storage = new Map();
let fetchCalls = 0;
const sandbox = {
  console, Math, Date, JSON, Set, Map, Array, Object, Number, String, Boolean, RegExp, Promise, Error,
  parseInt, parseFloat, isNaN, encodeURIComponent, decodeURIComponent, btoa, atob, escape, unescape,
  setTimeout: () => 0, clearTimeout: () => {}, requestAnimationFrame: cb => cb(),
  localStorage: {
    getItem: k => storage.has(k) ? storage.get(k) : null,
    setItem: (k, v) => storage.set(k, String(v)),
    removeItem: k => storage.delete(k)
  },
  document: {
    readyState: 'complete',
    body: { classList: { toggle() {}, add() {}, remove() {} }, style: {}, appendChild() {} },
    getElementById: id => makeEl(id),
    querySelector: () => makeEl('qs'),
    querySelectorAll: () => [],
    addEventListener: () => {},
    createElement: () => makeEl('dyn_' + Math.random())
  },
  window: { addEventListener: () => {}, scrollTo: () => {}, innerWidth: 1440 },
  tailwind: {},
  navigator: { clipboard: { writeText: async () => {} } },
  fetch: async () => { fetchCalls += 1; return { ok: false, json: async () => ({}) }; },
  alert: () => {}, confirm: () => true,
};
sandbox.window.document = sandbox.document;
sandbox.window.localStorage = sandbox.localStorage;
vm.createContext(sandbox);
vm.runInContext(scripts, sandbox);

function subviewState() {
  const ids = ['scheduleActivityCalendarSubview', 'profileAvailabilitySubview', 'smartPlanSection', 'planReviewScreen'];
  const visible = ids.filter(id => {
    const el = sandbox.document.getElementById(id);
    return !el.classList.contains('hidden') && !el.hidden;
  });
  return {
    tab: vm.runInContext('activeProfileScheduleTab', sandbox),
    subview: vm.runInContext('activeScheduleSubview', sandbox),
    profileHidden: sandbox.document.getElementById('profileSchedulePanelProfile').classList.contains('hidden'),
    scheduleHidden: sandbox.document.getElementById('profileSchedulePanelSchedule').classList.contains('hidden'),
    visibleSubviews: visible,
    emptyVisible: !sandbox.document.getElementById('plannerEmptyState').classList.contains('hidden'),
    activeVisible: !sandbox.document.getElementById('plannerActiveResult').classList.contains('hidden'),
    confirmBadgeText: sandbox.document.getElementById('planConfirmationBadge').textContent,
    confirmBadgeHidden: sandbox.document.getElementById('planConfirmationBadge').classList.contains('hidden'),
  };
}

(async () => {
  await vm.runInContext("currentStudent = { student_id: '25127333', full_name: 'Task2 Tester', major: 'CNTT' }; applyCurrentStudent(currentStudent);", sandbox);
  vm.runInContext("SP3_SOURCE = 'real';", sandbox);
  fetchCalls = 0;

  // 1. Switching to plan tab must NOT silently run SP3 planner
  sandbox.switchTab('plan');
  const fetchAfterSwitchToPlan = fetchCalls;

  // 2. Profile tab shows ONLY profile panel
  sandbox.setProfileScheduleTab('profile');
  const onProfile = subviewState();

  // 3. Schedule tab opens on activity calendar subview first with empty state (no plan yet)
  sandbox.setProfileScheduleTab('schedule');
  const onScheduleEmpty = subviewState();

  // 4. Open personal availability separately, add a busy block, save & return to activity calendar
  sandbox.openPersonalAvailabilitySubview();
  const onAvailability = subviewState();
  vm.runInContext(`
    addOnboardingBusyEntry({
      category: 'class',
      title: 'Thực hành CTDL',
      date: '2026-11-09',
      weekday: 0,
      start: '09:00',
      end: '11:00',
      recurring: true
    }, 'profile');
    saveAndClosePersonalAvailability();
  `, sandbox);
  const afterSaveAvailability = subviewState();

  // 5. Simulate 3 options generated -> choose option -> review -> confirm unavailable -> confirm available
  const samplePlan = {
    mode: 'DEMO_ONLY',
    requested_total_target: 80,
    activities: [{ activity_id: 'ACT-MON', title: 'Workshop CTDL Sáng Thứ 2' }],
    plan: {
      plan_version: 'sp3plan-0123456789abcdef',
      context: { as_of: '2026-10-01T08:00:00+07:00' },
      based_on: {},
      status: 'TARGET_MET',
      score_summary: { baseline_total: 0, projected_total: 80, gain_total: 80, official_baseline_verified: false },
      selected_activities: [{
        activity_id: 'ACT-MON',
        scheduled_blocks: [{ start: '2026-11-09T09:30:00+07:00', end: '2026-11-09T10:30:00+07:00' }]
      }]
    },
    availability: { available_intervals: [] },
    feasibility: { candidates: [{ activity: { activity_id: 'ACT-MON', title: 'Workshop CTDL Sáng Thứ 2' }, feasibility: { status: 'FEASIBLE' } }] }
  };
  vm.runInContext(`
    cachedPlanOptions = [
      { strategy: 'MINIMUM_EFFORT', status: 'READY', projected_total: 80, remaining_total: 0, activity_count: 1, total_duration_hours: 1, utility: 10, result: ${JSON.stringify(samplePlan)} },
      { strategy: 'BALANCED', status: 'READY', projected_total: 80, remaining_total: 0, activity_count: 1, total_duration_hours: 1, utility: 12, result: ${JSON.stringify(samplePlan)} },
      { strategy: 'PREFERENCE_FIRST', status: 'READY', projected_total: 80, remaining_total: 0, activity_count: 1, total_duration_hours: 1, utility: 15, result: ${JSON.stringify(samplePlan)} }
    ];
    selectCachedPlanOption(1);
    setPlannerScreenMode('options');
  `, sandbox);
  const onOptions = subviewState();

  sandbox.openPlanReviewScreen(1);
  const onReview = subviewState();

  // Confirm without contract -> stays preview (unconfirmed)
  delete sandbox.window.UniLifePlanReviewContract;
  const confirmNoContract = await sandbox.confirmSelectedPlanViaContract();
  const afterNoContract = {
    confirmedFlag: vm.runInContext('currentPlanConfirmed', sandbox),
    subview: vm.runInContext('activeScheduleSubview', sandbox),
  };

  // Register teammate confirmation contract -> returns confirmed: true -> returns to activity calendar with confirmed badge
  sandbox.window.UniLifePlanReviewContract = {
    confirmPlan: async () => ({ confirmed: true, status: 'CONFIRMED' })
  };
  const confirmWithContract = await sandbox.confirmSelectedPlanViaContract();
  const afterConfirmed = subviewState();
  const conflictNoticeHtml = sandbox.document.getElementById('schedulePlanConflictNotice').innerHTML;
  const conflictNoticeHidden = sandbox.document.getElementById('schedulePlanConflictNotice').classList.contains('hidden');

  // Reload and verify canonical_availability + confirmed state persisted
  await vm.runInContext("currentStudent = { student_id: '25127333', full_name: 'Task2 Tester', major: 'CNTT' }; applyCurrentStudent(currentStudent);", sandbox);
  sandbox.setProfileScheduleTab('schedule');
  const afterReload = subviewState();
  const canonicalAvailability = sandbox.plannerAvailabilityPayload();

  console.log(JSON.stringify({
    fetchAfterSwitchToPlan,
    onProfile,
    onScheduleEmpty,
    onAvailability,
    afterSaveAvailability,
    onOptions,
    onReview,
    confirmNoContract,
    afterNoContract,
    confirmWithContract: { confirmed: confirmWithContract.confirmed },
    afterConfirmed,
    conflictNoticeHidden,
    conflictNoticeHasActivity: conflictNoticeHtml.includes('Workshop CTDL Sáng Thứ 2'),
    afterReload,
    canonicalAvailability,
  }));
})();
"""
    raw = subprocess.check_output(["node"], input=js, cwd=ROOT, text=True, encoding="utf-8")
    res = json.loads(raw)

    assert res["fetchAfterSwitchToPlan"] == 0
    assert res["onProfile"]["profileHidden"] is False
    assert res["onProfile"]["scheduleHidden"] is True

    assert res["onScheduleEmpty"]["profileHidden"] is True
    assert res["onScheduleEmpty"]["scheduleHidden"] is False
    assert res["onScheduleEmpty"]["visibleSubviews"] == ["scheduleActivityCalendarSubview"]
    assert res["onScheduleEmpty"]["emptyVisible"] is True
    assert res["onScheduleEmpty"]["activeVisible"] is False

    assert res["onAvailability"]["visibleSubviews"] == ["profileAvailabilitySubview"]
    assert res["afterSaveAvailability"]["visibleSubviews"] == ["scheduleActivityCalendarSubview"]

    assert res["onOptions"]["visibleSubviews"] == ["smartPlanSection"]
    assert res["onReview"]["visibleSubviews"] == ["planReviewScreen"]

    assert res["confirmNoContract"]["confirmed"] is False
    assert res["afterNoContract"] == {"confirmedFlag": False, "subview": "review"}

    assert res["confirmWithContract"]["confirmed"] is True
    assert res["afterConfirmed"]["visibleSubviews"] == ["scheduleActivityCalendarSubview"]
    assert res["afterConfirmed"]["activeVisible"] is True
    assert "đã xác nhận" in res["afterConfirmed"]["confirmBadgeText"]

    # Real saved busy block (Mon 09:00-11:00) conflicts with ACT-MON (Mon 09:30-10:30) without overwriting plan
    assert res["conflictNoticeHidden"] is False
    assert res["conflictNoticeHasActivity"] is True

    # Reload preserves confirmed plan and SP3 availability excludes Mon 09:00-11:00
    assert res["afterReload"]["visibleSubviews"] == ["scheduleActivityCalendarSubview"]
    assert res["afterReload"]["activeVisible"] is True
    assert "đã xác nhận" in res["afterReload"]["confirmBadgeText"]

    # Verify saved canonical_availability actually removes Mon 09:00-11:00 in Python SP3 resolve_availability
    resolved = resolve_availability(
        res["canonicalAvailability"],
        window_start="2026-11-09T00:00:00+07:00",
        window_end="2026-11-09T23:59:59+07:00",
    )
    mon_slots = [
        (iv["start"], iv["end"])
        for iv in resolved["available_intervals"]
        if iv["start"].startswith("2026-11-09")
    ]
    assert mon_slots == [
        ("2026-11-09T07:00:00+07:00", "2026-11-09T09:00:00+07:00"),
        ("2026-11-09T11:00:00+07:00", "2026-11-09T21:00:00+07:00"),
    ]
