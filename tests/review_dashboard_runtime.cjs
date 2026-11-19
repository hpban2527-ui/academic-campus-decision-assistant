// Execute the real page controllers without a network or a browser installation.
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
const html = fs.readFileSync('web/index.html', 'utf8');
const storage = new Map();
const elements = new Map();
const requests = [];
let failWrites = false;
const listeners = new Map();
const timers = new Map();
const intervals = new Map();
let nextTimer = 0;
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(['planReviewScreen', 'planOptionsScreen', 'planDiffModal'].includes(id) ? ['hidden'] : []);
    const value = { id, value: id === 'inputPlanTarget' ? '80' : '', textContent: '', innerText: '', innerHTML: '',
      className: '', style: {}, dataset: {}, children: [{}, {}], hidden: false, checked: true, disabled: false,
      offsetParent: {}, scrollTop: 0, scrollHeight: 0,
      classList: { add: (...items) => items.forEach(x => classes.add(x)),
        remove: (...items) => items.forEach(x => classes.delete(x)), contains: x => classes.has(x),
        toggle(x, force) { const on = force === undefined ? !classes.has(x) : force; on ? classes.add(x) : classes.delete(x); return on; } },
      setAttribute() {}, getAttribute() { return null; }, appendChild() {}, remove() {},
      focus() { sandbox.document.activeElement = value; }, contains(child) { return child?.id === id || (id === 'prvChangePanel' && /^prv(Choose|Cancel|Remove|More|Apply|Change)/.test(child?.id || '')); }, scrollIntoView() {}, setSelectionRange() {}, insertAdjacentHTML() {}, insertAdjacentElement() {},
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      closest() { return { classList: { add() {}, remove() {}, toggle() {} } }; } };
    elements.set(id, value);
  }
  return elements.get(id);
}
const sandbox = { console, Date, Math, JSON, Set, Map, Array, Object, Number, String, Boolean, RegExp, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, escape, unescape,
  tailwind: {}, performance: { now: () => 0 }, navigator: { clipboard: { writeText: async () => {} } },
  setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; },
  clearTimeout: id => timers.delete(id),
  setInterval(callback) { const id = ++nextTimer; intervals.set(id, callback); return id; },
  clearInterval: id => intervals.delete(id),
  addEventListener() {}, removeEventListener() {}, requestAnimationFrame: callback => callback(), scrollTo() {},
  alert() {}, confirm: () => true,
  localStorage: { getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem(key, value) { if (failWrites) throw new Error('Synthetic storage failure'); storage.set(key, String(value)); },
    removeItem: key => storage.delete(key) },
  document: { readyState: 'loading', body: element('body'), activeElement: element('initialFocus'),
    getElementById: element, querySelector: () => null, querySelectorAll: () => [],
    addEventListener(name, callback) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(callback); }, contains: () => true, createElement: () => element('created') },
  innerWidth: input.mobile ? 390 : 1440,
  matchMedia: () => ({ matches: !input.mobile }),
  fetch: async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : null;
    requests.push({ url, body });
    if (url.includes('/personalized/options')) {
      if (input.failure === 'options') throw new Error('Failed to fetch');
      return { ok: true, json: async () => ({options: input.options}) };
    }
    let part = null;
    if (url.includes('/personalized/alternatives')) part = 'alternatives';
    else if (url.includes('/personalized/swap-preview')) part = 'impact';
    else if (url.includes('/personalized/what-if-skip')) part = 'suggestion';
    if (!part) return { ok: false, status: 404, json: async () => ({}) };
    if (input.failure === part) throw new Error('Failed to fetch');
    const data = body.base_result.plan.plan_version === input.dashboard?.baseVersion ? input.dashboard : input;
    return { ok: true, json: async () => data[part] };
  }
};
sandbox.window = sandbox;
sandbox.input = input;
vm.createContext(sandbox);
for (const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/gi)) {
  if (!/\bsrc\s*=/.test(match[1]) && match[2].trim()) vm.runInContext(match[2], sandbox);
}
const run = code => vm.runInContext(code, sandbox);
const saved = () => JSON.parse(storage.get('unilife_data_SYN-REVIEW-01'));
(async () => {
  if (input.scenario?.startsWith('onboarding')) {
    const user = {student_id:'25127881', full_name:'Onboarding reviewer', major:'CNTT'};
    const key = 'unilife_data_' + user.student_id;
    const data = () => JSON.parse(storage.get(key));
    storage.set(key, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
    storage.set('unilife_users', JSON.stringify([user]));
    sandbox.beginOnboarding(user);
    run(`SP3_SOURCE = 'synthetic'; onboardingStep = 3;
      selectOnboardingTargetPreset(85);
      selectOnboardingCategoryChoice('C1');
      selectOnboardingModeChoice('any'); selectOnboardingCampusChoice('any');
      finishOnboardingTopics(true);
      addOnboardingBusyEntry({category:'class', title:'Saved class', date:'2026-11-09',
        weekday:0, start:'14:00', end:'15:00'});
      renderOnboardingStep();`);
    assert.equal(element('onboardingNextButton').textContent, 'Lập lịch & review');
    const delayed = input.scenario === 'onboarding_delayed' || input.scenario === 'onboarding_switch';
    if (delayed) element('workspaceApp').classList.add('hidden');
    sandbox.nextOnboardingStep();
    if (delayed) {
      assert.equal(requests.filter(x => x.url.includes('/personalized/options')).length, 0);
      if (input.scenario === 'onboarding_switch') run("currentStudent = {student_id:'25127882'};");
      for (const [id, timer] of [...timers]) {
        if (timer.delay === 400) { timers.delete(id); timer.callback(); }
      }
      for (const callback of [...intervals.values()]) callback();
      if (input.scenario === 'onboarding_switch') {
        assert.equal(requests.filter(x => x.url.includes('/personalized/options')).length, 0);
        console.log(JSON.stringify({passed:true,scenario:input.scenario}));return;
      }
    }
    for (let i = 0; i < 60; i++) await Promise.resolve();
    const calls = () => requests.filter(x => x.url.includes('/personalized/options'));
    assert.equal(calls().length, 1, 'profile completion requests a plan exactly once');
    assert.equal(calls()[0].body.total_target, 85);
    assert.equal(calls()[0].body.preference.limits.max_duration_minutes, null);
    assert.ok(calls()[0].body.preference.category_priorities.some(c => c.category_id === 'C1'));
    assert.ok(calls()[0].body.availability.busy_intervals.some(b => b.start.includes('2026-11-09T14:00')));
    assert.equal(data().profile.drl_target, 85);
    assert.equal(data().confirmed_plan, null);
    assert.equal(element('onboardingModal').classList.contains('hidden'), true);
    assert.equal(element('welcomeModal').classList.contains('hidden'), true);
    assert.equal([...timers.values()].some(t => t.callback === sandbox.finishWelcome), false);
    assert.equal(element('viewPlan').classList.contains('hidden'), false);
    if (input.scenario === 'onboarding_error') {
      assert.equal(run('!!planStages.first'), false);
      assert.equal(element('plannerErrorState').classList.contains('hidden'), false);
      assert.equal(element('btnRunPlanner').disabled, false);
      assert.equal(element('planOptionsScreen').classList.contains('hidden'), true);
      assert.equal(data().profile.completed_onboarding, true, 'saved profile survives a planning error');
      input.failure = null; await sandbox.runSp3Planner();
      assert.equal(calls().length, 2, 'the user can retry without repeating onboarding');
    }
    assert.equal(element('planOptionsScreen').classList.contains('hidden'), false);
    assert.equal(run('planStages.first.requested_total_target'), 85);
    sandbox.reviewDashChoosePlanOption(1, 'review');
    assert.equal(element('planReviewScreen').classList.contains('hidden'), false);
    assert.equal(data().confirmed_plan, null, 'review must not confirm automatically');
    sandbox.reviewDashBackToPlanOptions();
    sandbox.reviewDashChoosePlanOption(1, 'review');
    assert.equal(calls().length, input.scenario === 'onboarding_error' ? 2 : 1);
    sandbox.prvConfirm();
    assert.equal(data().confirmed_plan.plan_version, input.options[1].result.plan.plan_version);
    assert.equal(element('viewDashboard').classList.contains('hidden'), false);
    console.log(JSON.stringify({passed:true,scenario:input.scenario}));return;
  }
  run(`currentStudent = {student_id: 'SYN-REVIEW-01', full_name: 'Synthetic reviewer'};
    currentProfileDraft = createDefaultLocalUserData('SYN-REVIEW-01').profile;
    currentProfileDraft.drl_target = 80;
    confirmedPreference = input.preference;
    cachedPlanOptions = input.options;
    selectedPlanOptionIndex = 1;
    planStages.first = input.options[1].result;
    currentPlannerData = planStages.first;
    SP3_SOURCE = 'synthetic';`);
  const original = JSON.stringify(input.options);
  sandbox.reviewDashChoosePlanOption(1, 'review');
  assert.equal(element('planReviewScreen').classList.contains('hidden'), false);
  assert.equal(run('prvDraft.result.plan.plan_version'), input.options[1].result.plan.plan_version);
  const changingId = input.activityId || 'SEM-A';
  element('prv-change-' + sandbox.activityToken(changingId)).focus();
  const pendingChange = sandbox.prvOpenChange(sandbox.activityToken(changingId));
  const started = requests.filter(x => /personalized\/(alternatives|swap-preview|what-if-skip)/.test(x.url));
  assert.equal(started.length, 3, 'all previews must start without waiting for another preview');
  await pendingChange;
  const panel = () => element(input.mobile ? 'prvList' : 'prvPanel').innerHTML;
  const initialActions = element('prvList').innerHTML.match(/data-review-actions[\s\S]*?<\/div>/g) || [];
  assert.equal(initialActions.length, input.options[1].result.plan.selected_activities.length);
  for (const actions of initialActions) {
    assert.equal((actions.match(/<button /g) || []).length, 1);
    assert.ok(actions.includes('Thay đổi'));
    assert.ok(!actions.includes('>Bỏ<') && !actions.includes('>Nếu bỏ<'));
  }
  assert.equal(element('prvList').innerHTML.includes('id="prvChangePanel"'), !!input.mobile);
  assert.equal(element('prvPanel').innerHTML.includes('id="prvChangePanel"'), !input.mobile);
  const removeRequest = requests.find(x => x.url.includes('/personalized/swap-preview'));
  assert.equal(removeRequest.body.add_activity_id, null);
  assert.equal(removeRequest.body.base_result.plan.plan_version, input.options[1].result.plan.plan_version);
  const mode = input.scenario || 'flow';
  if (mode === 'real_source') {
    assert.equal(run('prvDraft.source'), 'real');
    assert.ok(started.every(call => call.url.includes('source=real')));
    assert.equal(run('prvDraft.result.data_source'), 'OPERATIONAL-DATASET');
    sandbox.prvApplyRemoval(); sandbox.prvConfirm();
    assert.equal(saved().confirmed_plan.source, 'OPERATIONAL-DATASET');
    assert.equal(saved().confirmed_plan.plan_version, input.impact.result.plan.plan_version);
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }

  if (mode === 'alternatives_failure') {
    assert.ok(panel().includes('data-change-impact'));
    assert.equal(run('!!prvDraft.panel.impact.data'), true);
    sandbox.prvApplyRemoval();
    assert.equal(run('prvDraft.result.plan.plan_version'), input.impact.result.plan.plan_version);
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  if (mode === 'impact_failure') {
    assert.equal(run('prvDraft.panel.impact.data'), undefined);
    assert.ok(panel().includes('Không kết nối được máy chủ'));
    assert.ok(panel().includes('prvApplyAlternative(0)'));
    sandbox.prvApplyAlternative(0);
    assert.equal(run('prvDraft.result.plan.plan_version'), input.alternatives.items[0].preview.result.plan.plan_version);
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  if (mode === 'empty') {
    assert.ok(panel().includes('Không có hoạt động thay thế hợp lịch.'));
    assert.ok(panel().includes('data-change-impact'));
    sandbox.prvApplyRemoval();
    assert.equal(run('prvDraft.result.plan.plan_version'), input.impact.result.plan.plan_version);
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  assert.ok(panel().includes('data-change-impact'));
  assert.ok(panel().includes(String(input.impact.projected_total)));
  assert.equal(run('prvDraft.steps.length'), 0, 'previews must not edit the plan');
  if (mode === 'above_target') {
    assert.ok(panel().includes(', vẫn đạt mục tiêu'));
    assert.ok(panel().includes('>Bỏ</button>'));
    assert.ok(!panel().includes('Bỏ, không thay'));
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  if (mode === 'suggestion_two' || mode === 'suggestion_one') {
    const count = input.suggestion.added_activity_ids.length;
    assert.equal(panel().includes('data-change-suggestion'), count >= 2);
    if (count >= 2) {
      sandbox.prvApplySuggestion();
      assert.equal(run('prvDraft.result.plan.plan_version'), input.suggestion.result.plan.plan_version);
      assert.ok(element('prvList').innerHTML.includes('Đã áp dụng gợi ý'));
      sandbox.prvUndo(1);
      assert.equal(run('prvDraft.result.plan.plan_version'), input.options[1].result.plan.plan_version);
    }
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  if (mode === 'focus') {
    assert.equal(sandbox.document.activeElement.id, 'prvChangePanel');
    for (const listener of listeners.get('keydown') || []) listener({key:'Escape',preventDefault(){},stopPropagation(){}});
    assert.equal(run('prvDraft.panel.mode'), 'summary');
    assert.equal(sandbox.document.activeElement.id, 'prv-change-' + sandbox.activityToken(changingId));
    await sandbox.prvOpenChange(sandbox.activityToken(changingId));sandbox.prvCancelChange();
    assert.equal(sandbox.document.activeElement.id, 'prv-change-' + sandbox.activityToken(changingId));
    sandbox.prvShowDetail(sandbox.activityToken(changingId));
    element('prv-detail-change-' + sandbox.activityToken(changingId)).focus();
    await sandbox.prvOpenChange(sandbox.activityToken(changingId));sandbox.prvCancelChange();
    assert.equal(run('prvDraft.panel.mode'), 'detail');
    assert.equal(sandbox.document.activeElement.id, 'prv-detail-change-' + sandbox.activityToken(changingId));
    console.log(JSON.stringify({passed:true,scenario:mode}));return;
  }
  const call = requests.find(x => x.url.includes('/personalized/alternatives'));
  assert.equal(call.body.limit, 10);
  assert.equal(call.body.preference.strategy, input.options[1].strategy);
  assert.equal(call.body.preference.limits.max_duration_minutes, null);
  assert.ok(call.body.availability.weekly_blocks.length);
  assert.equal((panel().match(/onclick="prvApplyAlternative/g)||[]).length, Math.min(3,input.alternatives.items.length));
  if (input.alternatives.items.length > 3) {
    assert.ok(panel().includes('Xem thêm'));sandbox.prvShowAllAlternatives();
    assert.equal((panel().match(/onclick="prvApplyAlternative/g)||[]).length, input.alternatives.items.length);
    let previousIndex = -1;
    for (const item of input.alternatives.items) {
      const index = panel().indexOf(sandbox.escapeHTML(item.title), previousIndex + 1);
      assert.ok(index > previousIndex, 'API order must be preserved');previousIndex = index;
    }
  }
  sandbox.prvApplyAlternative(0);
  assert.equal(run('prvDraft.steps.length'), 1);
  assert.ok(element('prvList').innerHTML.includes('Đã đổi'));
  sandbox.prvUndo(1);
  assert.equal(run('prvDraft.result.plan.plan_version'), input.options[1].result.plan.plan_version);
  await sandbox.prvOpenChange(sandbox.activityToken(changingId));
  assert.ok(panel().includes('Bỏ, không thay'));
  sandbox.prvApplyRemoval();
  assert.equal(run('prvDraft.result.plan.plan_version'), input.impact.result.plan.plan_version);
  assert.ok(element('prvList').innerHTML.includes('Đã bỏ'));
  assert.equal(run('prvSummary(prvDraft.result).violations'), 0);
  sandbox.prvUndo(2);
  await sandbox.prvOpenChange(sandbox.activityToken(changingId));sandbox.prvApplyAlternative(0);
  sandbox.prvConfirm();
  assert.ok(saved().confirmed_plan.option_label.includes('đã chỉnh'));
  assert.equal(saved().confirmed_plan.plan_version, input.alternatives.items[0].preview.result.plan.plan_version);
  assert.equal(element('viewDashboard').classList.contains('hidden'), false);
  assert.equal(element('cpdContent').classList.contains('hidden'), false);
  assert.equal(JSON.stringify(input.options), original, 'review must not mutate cached engine options');
  const confirmed = JSON.stringify(saved().confirmed_plan);
  run('planStages.first = input.options[0].result; currentPlannerData = planStages.first;');
  const dashboardId = input.dashboard.activityId;
  element('cpd-change-' + sandbox.activityToken(dashboardId)).focus();
  await sandbox.cpdOpenChange(sandbox.activityToken(dashboardId));
  assert.equal(run('prvDraft.origin'), 'dashboard');
  sandbox.prvApplyRemoval();
  assert.equal(element('planDiffModal').classList.contains('hidden'), false);
  assert.equal(JSON.stringify(saved().confirmed_plan), confirmed);
  sandbox.cpdConfirmDiffCancel();
  assert.equal(JSON.stringify(saved().confirmed_plan), confirmed);
  sandbox.prvCancelChange();
  assert.equal(sandbox.document.activeElement.id, 'cpd-change-' + sandbox.activityToken(dashboardId));
  sandbox.reviewDashNotePlannerResult();
  assert.equal(saved().pending_plan_notice, true);
  run("customBusyIntervals.push({start:'2026-11-13T19:00:00+07:00',end:'2026-11-13T20:00:00+07:00'}); persistCurrentUserData();");
  assert.equal(saved().invalidated.value, true);
  assert.equal(JSON.stringify(saved().confirmed_plan), confirmed);
  let settled = false;
  const pending = sandbox.UniLifePlanReviewContract.confirmPlan({ student_id: 'SYN-REVIEW-01', strategy: 'BALANCED', result: input.options[1].result });
  pending.then(() => { settled = true; });
  await Promise.resolve();
  assert.equal(settled, false, 'opening a diff is not confirmation');
  sandbox.cpdConfirmDiffCancel();
  assert.equal((await pending).confirmed, false);
  assert.equal(JSON.stringify(saved().confirmed_plan), confirmed);
  const accepted = sandbox.UniLifePlanReviewContract.confirmPlan({ student_id: 'SYN-REVIEW-01', strategy: 'BALANCED', result: input.options[1].result });
  sandbox.cpdConfirmDiffAccept();
  assert.equal((await accepted).persisted, true);
  assert.equal(saved().confirmed_plan.plan_version, input.options[1].result.plan.plan_version);
  assert.equal(saved().pending_plan_notice, false);
  sandbox.reviewDashChoosePlanOption(0, 'review');
  assert.equal(run('activePlanPreference.strategy'), 'MINIMUM_EFFORT');
  const beforeAdd = requests.length;
  sandbox.openAvailableCalendarSlot('2026-11-09T10:00:00+07:00', '2026-11-09T11:00:00+07:00');
  assert.equal(requests.length, beforeAdd);
  const empty = saved(); empty.confirmed_plan = null;
  storage.set('unilife_data_SYN-REVIEW-01', JSON.stringify(empty));
  failWrites = true;
  await assert.rejects(sandbox.UniLifePlanReviewContract.confirmPlan({ student_id: 'SYN-REVIEW-01', strategy: 'BALANCED', result: input.options[1].result }), /storage failure/);
  failWrites = false;
  assert.equal(saved().confirmed_plan, null);
  run("currentStudent = {student_id:'SYN-REVIEW-02',full_name:'Second synthetic reviewer'};");
  assert.equal(sandbox.reviewDashReadState().plan, null);
  console.log(JSON.stringify({ passed: true, flows: ['review-swap-confirm-dashboard', 'pending-and-invalidation', 'cancel-and-accept-diff', 'selected-strategy', 'add-hidden', 'storage-failure', 'account-isolation'] }));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
