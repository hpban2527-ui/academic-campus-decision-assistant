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
      focus() {}, scrollIntoView() {}, setSelectionRange() {}, insertAdjacentHTML() {}, insertAdjacentElement() {},
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      closest() { return { classList: { add() {}, remove() {}, toggle() {} } }; } };
    elements.set(id, value);
  }
  return elements.get(id);
}
const sandbox = { console, Date, Math, JSON, Set, Map, Array, Object, Number, String, Boolean, RegExp, Error, Promise,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, escape, unescape,
  tailwind: {}, performance: { now: () => 0 }, navigator: { clipboard: { writeText: async () => {} } },
  setTimeout: () => 1, clearTimeout() {}, setInterval: () => 1, clearInterval() {},
  addEventListener() {}, removeEventListener() {}, requestAnimationFrame: callback => callback(), scrollTo() {},
  alert() {}, confirm: () => true,
  localStorage: { getItem: key => storage.has(key) ? storage.get(key) : null,
    setItem(key, value) { if (failWrites) throw new Error('Synthetic storage failure'); storage.set(key, String(value)); },
    removeItem: key => storage.delete(key) },
  document: { readyState: 'loading', body: element('body'), activeElement: element('initialFocus'),
    getElementById: element, querySelector: () => null, querySelectorAll: () => [],
    addEventListener() {}, contains: () => true, createElement: () => element('created') },
  fetch: async (url, options) => {
    requests.push({ url, body: options?.body ? JSON.parse(options.body) : null });
    if (url.includes('/personalized/alternatives')) return { ok: true, json: async () => input.alternatives };
    return { ok: false, status: 404, json: async () => ({}) };
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
  await sandbox.prvLoadAlternatives(sandbox.activityToken('SEM-A'));
  const call = requests.find(x => x.url.includes('/personalized/alternatives'));
  assert.equal(call.body.preference.strategy, input.options[1].strategy);
  assert.equal(call.body.preference.limits.max_duration_minutes, null);
  assert.ok(call.body.availability.weekly_blocks.length);
  sandbox.prvApplyAlternative(0);
  assert.equal(run('prvDraft.steps.length'), 1);
  assert.equal(run('prvDraft.result.plan.plan_version'), input.alternatives.items[0].preview.result.plan.plan_version);
  sandbox.prvConfirm();
  assert.ok(saved().confirmed_plan.option_label.includes('đã chỉnh'));
  assert.equal(saved().confirmed_plan.plan_version, input.alternatives.items[0].preview.result.plan.plan_version);
  assert.equal(element('viewDashboard').classList.contains('hidden'), false);
  assert.equal(element('cpdContent').classList.contains('hidden'), false);
  assert.equal(JSON.stringify(input.options), original, 'review must not mutate cached engine options');
  const confirmed = JSON.stringify(saved().confirmed_plan);
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
