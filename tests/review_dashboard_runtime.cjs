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
let storageQuota = Infinity;
let quotaFailures = 0;
const listeners = new Map();
const timers = new Map();
const intervals = new Map();
let nextTimer = 0;
const optionReleases = [];
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set(['planReviewScreen', 'planOptionsScreen', 'planDiffModal'].includes(id) ? ['hidden'] : []);
    const value = { id, value: id === 'inputPlanTarget' ? '80' : '', textContent: '', innerText: '', innerHTML: '',
      className: '', style: {}, dataset: {}, children: [{}, {}], hidden: false, checked: true, disabled: false,
      offsetParent: {}, scrollTop: 0, scrollHeight: 0,
      classList: { add: (...items) => items.forEach(x => classes.add(x)),
        remove: (...items) => items.forEach(x => classes.delete(x)), contains: x => classes.has(x),
        toggle(x, force) { const on = force === undefined ? !classes.has(x) : force; on ? classes.add(x) : classes.delete(x); return on; } },
      attributes: {}, setAttribute(name, item) { value.attributes[name] = item; }, getAttribute(name) { return value.attributes[name] ?? null; }, removeAttribute(name) { delete value.attributes[name]; },
      appendChild(child) { if (child.parentNode) child.parentNode.children = child.parentNode.children.filter(x => x !== child); child.parentNode = value; value.children.push(child); },
      insertBefore(child) { value.appendChild(child); }, remove() {},
      focus() { sandbox.document.activeElement = value; }, contains(child) { for (let item = child; item; item = item.parentNode) if (item === value) return true; return id === 'prvChangePanel' && /^prv(Choose|Cancel|Remove|More|Apply|Change)/.test(child?.id || ''); }, scrollIntoView() {}, setSelectionRange() {}, insertAdjacentHTML() {}, insertAdjacentElement() {},
      addEventListener() {}, querySelector() { return null; }, querySelectorAll() { return []; },
      closest(selector) { if (selector === '.hidden') { for (let item = value; item; item = item.parentNode) if (item.classList.contains('hidden')) return item; return null; } return { classList: { add() {}, remove() {}, toggle() {} } }; } };
    elements.set(id, value);
    const parents = {onboardingOptionsHost:'onboardingPlanStep', onboardingReviewHost:'onboardingPlanStep',
      onboardingPlanStep:'onboardingModal', onboardingNextButton:'onboardingModal', onboardingBackButton:'onboardingModal',
      planDiffError:'planDiffModal', prvConfirmError:'prvPanel', prvPanel:'planReviewScreen', posError:'planOptionsScreen'};
    value.parentNode = id === 'body' ? null : element(parents[id] || 'body');
    if (['planOptionsScreen', 'planReviewScreen'].includes(id)) { value.attributes.role = 'dialog'; value.attributes['aria-modal'] = 'true'; }
  }
  return elements.get(id);
}
const sandbox = { console, Date, Math, JSON, Set, Map, Array, Object, Number, String, Boolean, RegExp, Error, Promise, URLSearchParams,
  parseInt, parseFloat, isNaN, isFinite, encodeURIComponent, decodeURIComponent, btoa, atob, escape, unescape,
  tailwind: {}, performance: { now: () => 0 }, navigator: { clipboard: { writeText: async () => {} } },
  setTimeout(callback, delay) { const id = ++nextTimer; timers.set(id, {callback, delay}); return id; },
  clearTimeout: id => timers.delete(id),
  setInterval(callback) { const id = ++nextTimer; intervals.set(id, callback); return id; },
  clearInterval: id => intervals.delete(id),
  addEventListener() {}, removeEventListener() {}, requestAnimationFrame: callback => callback(), scrollTo() {},
  alert() {}, confirm: () => true,
  localStorage: { getItem: key => storage.has(key) ? storage.get(key) : null,
    get length() { return storage.size; }, key: index => [...storage.keys()][index] ?? null,
    setItem(key, value) {
      if (failWrites) throw new Error('Synthetic storage failure');
      value = String(value);
      let size = 2 * (key.length + value.length);
      for (const [storedKey, storedValue] of storage) if (storedKey !== key) size += 2 * (storedKey.length + storedValue.length);
      if (size > storageQuota) {
        quotaFailures += 1;
        const error = new Error('Setting the value exceeded the quota.'); error.name = 'QuotaExceededError'; throw error;
      }
      storage.set(key, value);
    },
    removeItem: key => storage.delete(key) },
  document: { readyState: 'loading', body: element('body'), activeElement: element('initialFocus'),
    getElementById: element, querySelector: () => null, querySelectorAll: () => [],
    addEventListener(name, callback) { if (!listeners.has(name)) listeners.set(name, []); listeners.get(name).push(callback); }, contains: () => true, createElement: () => element('created') },
  innerWidth: input.mobile ? 390 : 1440,
  matchMedia: () => ({ matches: !input.mobile }),
  fetch: async (url, options) => {
    const body = options?.body ? JSON.parse(options.body) : null;
    requests.push({ url, body });
    if (url.includes('/api/sp3/confirmed-plan') && options?.method === 'POST') {
      if (input.failConfirmation) { input.failConfirmation = false; return {ok:false,status:503,json:async () => ({detail:'Please retry confirmation'})}; }
      return {ok:true,json:async () => ({student_id:'25127881',plan_version:input.options[1].result.plan.plan_version,activities:{}})};
    }
    if (url.includes('/personalized/options')) {
      if (input.failure === 'options') throw new Error('Failed to fetch');
      if (input.holdOptions) return new Promise(resolve => optionReleases.push(resolve));
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
// The page loads its semester clocks from the API; the Python caller passes the same ones (api.term_clock)
// and the sandbox selects the latest term, like a new account.
const termClocks = input.clocks;
run(`termList = ${JSON.stringify(termClocks)}; applyTermClock(termList[termList.length - 1]);`);
// Accounts are stored split by term: read them through the page, as the page does.
const readAccount = id => JSON.parse(JSON.stringify(sandbox.readLocalUserData(id)));
const saved = () => readAccount('SYN-REVIEW-01');
(async () => {
  // Reproduce an origin already filled by legacy real-source planner snapshots.
  let legacyAccount = null;
  if (input.scenario === 'storage' || input.scenario === 'onboarding_quota') {
    legacyAccount = sandbox.createDefaultLocalUserData('LEGACY-DEMO');
    legacyAccount.confirmed_plan_result = input.options[1].result;
    legacyAccount.planner.cached_plan_options = input.options;
    legacyAccount.planner.plan_stages = {first: input.options[1].result, replan: null, whatif: null};
    legacyAccount.planner.custom_plan_backup = input.options[0].result;
    legacyAccount.profile.avatar_data_url = 'data:image/png;base64,keep-avatar';
    legacyAccount.saved_activities = [{activity_id: 'preserve-saved-activity'}];
    storage.set('unilife_data_LEGACY-DEMO', JSON.stringify(legacyAccount));
    storage.set('unrelated-app', 'preserve-unrelated-data');
    storageQuota = 2 * JSON.stringify(legacyAccount).length + 65536;
  }
  if (input.scenario === 'storage') {
    const original = JSON.stringify(legacyAccount);
    const compact = sandbox.serializeLocalUserData(legacyAccount);
    assert.ok(compact.length < original.length / 2, 'real planner payloads should be substantially smaller');
    const restored = sandbox.deserializeLocalUserData(JSON.parse(compact));
    assert.equal(JSON.stringify(restored), original, 'all results, offers, scores and profile data survive');
    restored.planner.cached_plan_options[1].result.plan.status = 'MUTATED';
    assert.equal(restored.planner.plan_stages.first.plan.status, input.options[1].result.plan.status);
    assert.equal(restored.confirmed_plan_result.plan.status, input.options[1].result.plan.status);
    assert.equal(JSON.stringify(legacyAccount), original, 'serialization must not mutate live state');
    const small = sandbox.createDefaultLocalUserData('SMALL');
    assert.equal(sandbox.serializeLocalUserData(small), JSON.stringify(small));
    const next = JSON.parse(original); next.student_id = 'NEXT-DEMO';
    sandbox.writeLocalUserData('NEXT-DEMO', next);
    assert.ok(quotaFailures > 0, 'exercise actual quota recovery');
    // The page reads an account as the view of its active term (plus the slices of the other terms: none here).
    const plain = id => { const view = readAccount(id); assert.deepEqual(view.terms, {}); delete view.terms; return JSON.stringify(view); };
    assert.equal(plain('LEGACY-DEMO'), original);
    // A written account is stored split by term, so its key order may differ: compare the content.
    assert.deepEqual(JSON.parse(plain('NEXT-DEMO')), next);
    assert.equal(storage.get('unrelated-app'), 'preserve-unrelated-data');
    assert.equal(sandbox.isLocalStorageQuotaError({code: 1014}), true);
    assert.equal(sandbox.isLocalStorageQuotaError(new Error('different failure')), false);
    const beforeFailure = storage.get('unilife_data_NEXT-DEMO');
    storageQuota = 1;
    assert.throws(() => sandbox.writeLocalUserData('NEXT-DEMO', {...next, updated_at:'unsaved'}), /dung lượng/);
    assert.equal(storage.get('unilife_data_NEXT-DEMO'), beforeFailure);
    assert.deepEqual(JSON.parse(plain('NEXT-DEMO')), next);
    console.log(JSON.stringify({passed:true,scenario:input.scenario,raw:original.length,compact:compact.length})); return;
  }
  if (input.scenario?.startsWith('onboarding')) {
    const settle = async () => { for (let i = 0; i < 80; i++) await Promise.resolve(); };
    const user = {student_id:'25127881', full_name:'Onboarding reviewer', major:'CNTT'};
    const key = 'unilife_data_' + user.student_id;
    const data = () => readAccount(user.student_id);
    storage.set(key, JSON.stringify(sandbox.createDefaultLocalUserData(user.student_id, true)));
    storage.set('unilife_users', JSON.stringify([user]));
    sandbox.beginOnboarding(user); await settle();
    assert.equal(element('simulationDateButton').disabled, false, 'registration enables the simulation date control');
    assert.equal(element('onboardingStepLabel').textContent, 'Bước 1 / 5');
    run(`SP3_SOURCE = 'synthetic'; onboardingStep = 3;
      selectOnboardingTargetPreset(85);
      selectOnboardingCategoryChoice('C1');
      selectOnboardingModeChoice('any'); selectOnboardingCampusChoice('any');
      finishOnboardingTopics(true);
      addOnboardingBusyEntry({category:'class', title:'Saved class', date:'2026-11-09',
        weekday:0, start:'14:00', end:'15:00'});
      renderOnboardingStep();`);
    assert.equal(element('onboardingNextButton').textContent, 'Lập lịch & review');
    element('workspaceApp').classList.add('hidden');
    if (input.scenario === 'onboarding_stale') input.holdOptions = true;
    if (input.scenario === 'onboarding_quota_blocked') {
      storageQuota = 1;
      await sandbox.rdOnboardingBuildPlan();
      assert.equal(run('rdOnboardingFlow.busy'), false, 'an initial storage error must release the loading state');
      assert.ok(element('onboardingPlanError').textContent.includes('dung lượng'));
      assert.equal(element('onboardingRetryPlan').classList.contains('hidden'), false);
      storageQuota = Infinity;
      sandbox.previousOnboardingStep();
    }
    sandbox.nextOnboardingStep();
    const calls = () => requests.filter(x => x.url.includes('/personalized/options'));
    if (input.scenario === 'onboarding_stale') {
      assert.equal(calls().length, 1);
      sandbox.previousOnboardingStep();
      assert.equal(run('onboardingStep'), 3);
      input.holdOptions = false; sandbox.nextOnboardingStep(); await settle();
      optionReleases[0]({ok:true,json:async () => ({options:[...input.options].reverse()})});
      await settle();
      assert.equal(run('cachedPlanOptions[0].strategy'), input.options[0].strategy);
    }
    await settle();
    assert.equal(calls().length, input.scenario === 'onboarding_stale' ? 2 : 1);
    assert.equal(calls()[0].body.total_target, 85);
    assert.equal(calls()[0].body.preference.limits.max_duration_minutes, null);
    assert.ok(calls()[0].body.preference.category_priorities.some(c => c.category_id === 'C1'));
    assert.equal(calls()[0].body.availability, undefined, 'synthetic planning uses its own fixture calendar');
    assert.ok(run('buildCanonicalAvailability()').busy_intervals.some(b => b.start.includes('2026-11-09T14:00')));
    assert.equal(data().profile.drl_target, 85);
    assert.equal(data().confirmed_plan, null);
    assert.equal(data().onboarding_status, 'IN_PROGRESS');
    assert.equal(data().profile.completed_onboarding, false);
    assert.equal(element('onboardingModal').classList.contains('hidden'), false);
    assert.equal(element('welcomeModal').classList.contains('hidden'), true);
    assert.equal(element('workspaceApp').classList.contains('hidden'), true);
    assert.equal(element('planOptionsScreen').parentNode.id, 'onboardingOptionsHost');
    assert.equal(element('planReviewScreen').parentNode.id, 'onboardingReviewHost');
    assert.equal(element('planOptionsScreen').getAttribute('aria-modal'), null);
    if (input.scenario === 'onboarding_error') {
      assert.equal(run('!!planStages.first'), false);
      assert.ok(element('onboardingPlanError').textContent);
      assert.equal(element('onboardingRetryPlan').classList.contains('hidden'), false);
      assert.equal(data().profile.completed_onboarding, false);
      input.failure = null; await sandbox.rdOnboardingBuildPlan();
      assert.equal(calls().length, 2);
    }
    assert.equal(element('planOptionsScreen').classList.contains('hidden'), false);
    assert.equal(element('onboardingStepLabel').textContent, 'Bước 4 / 5');
    assert.equal(run('planStages.first.requested_total_target'), 85);
    // Even the standalone confirm shortcut must pass through review inside onboarding.
    sandbox.reviewDashChoosePlanOption(1, 'confirm');
    assert.equal(element('planReviewScreen').classList.contains('hidden'), false);
    assert.equal(element('onboardingStepLabel').textContent, 'Bước 5 / 5');
    assert.equal(data().confirmed_plan, null);
    if (input.scenario === 'onboarding_back') {
      const token = sandbox.activityToken(input.activityId);
      element('prv-change-' + token).focus(); await sandbox.prvOpenChange(token);
      const escape = {key:'Escape', defaultPrevented:false, preventDefault(){this.defaultPrevented=true;}, stopPropagation(){}};
      for (const listener of listeners.get('keydown') || []) listener(escape);
      assert.equal(run('onboardingStep'), 5);
      assert.equal(run('prvDraft.panel.mode'), 'summary', 'Esc closes the change panel before navigating wizard steps');
      await sandbox.prvOpenChange(token); sandbox.prvApplyRemoval();
      sandbox.confirm = () => false; sandbox.previousOnboardingStep();
      assert.equal(run('onboardingStep'), 5, 'declining discard preserves the edited review');
      sandbox.confirm = () => true;
      sandbox.previousOnboardingStep();
      assert.equal(run('onboardingStep'), 4);
      sandbox.previousOnboardingStep();
      assert.equal(run('onboardingStep'), 3);
      sandbox.previousOnboardingStep(); assert.equal(run('onboardingStep'), 2);
      sandbox.nextOnboardingStep(); assert.equal(run('onboardingStep'), 3);
      sandbox.nextOnboardingStep(); await settle();
      assert.equal(calls().length, 2);
      sandbox.reviewDashChoosePlanOption(1, 'review');
    }
    // Step 5 confirms from the review panel: the wizard's Next button is hidden, and Tab must skip it and
    // still wrap inside the dialog (last visible control -> first, Shift+Tab first -> last).
    const modal = element('onboardingModal');
    const backButton = element('onboardingBackButton');
    const nextButton = element('onboardingNextButton');
    assert.equal(nextButton.hidden, true, 'review uses its own confirm action');
    assert.equal(backButton.hidden, false, 'back navigation remains visible');
    modal.querySelectorAll = () => [backButton, nextButton];
    backButton.focus();
    for (const listener of listeners.get('keydown') || []) listener({key:'Tab',preventDefault(){this.defaultPrevented=true;}});
    assert.equal(sandbox.document.activeElement.id, 'onboardingBackButton');
    if (input.scenario === 'onboarding_reload') {
      assert.equal(data().onboarding_step, 5);
      sandbox.reviewDashCloseAccountDialogs(); sandbox.beginOnboarding(user); await settle();
      assert.equal(run('onboardingStep'), 4);
      assert.equal(calls().length, 1, 'resume reuses saved engine options');
      assert.equal(element('planOptionsScreen').parentNode.id, 'onboardingOptionsHost');
      sandbox.reviewDashChoosePlanOption(1, 'review');
    }
    if (input.scenario === 'onboarding_storage') {
      failWrites = true; sandbox.nextOnboardingStep(); failWrites = false;
      assert.equal(data().confirmed_plan, null);
      assert.equal(data().profile.completed_onboarding, false);
      assert.equal(element('onboardingModal').classList.contains('hidden'), false);
      assert.ok(element('onboardingPlanError').textContent);
    }
    if (input.scenario === 'onboarding_confirm_error') {
      input.failConfirmation = true; sandbox.nextOnboardingStep(); await settle();
      assert.equal(data().confirmed_plan, null);
      assert.equal(data().profile.completed_onboarding, false);
      assert.equal(element('onboardingModal').classList.contains('hidden'), false);
      assert.equal(element('onboardingNextButton').disabled, false, 'failed confirmation allows retry');
      assert.ok(element('onboardingPlanError').textContent);
    }
    sandbox.nextOnboardingStep(); await settle();
    assert.equal(data().confirmed_plan.plan_version, input.options[1].result.plan.plan_version);
    assert.equal(data().onboarding_status, 'COMPLETED');
    assert.equal(data().profile.completed_onboarding, true);
    assert.equal(element('onboardingModal').classList.contains('hidden'), true);
    assert.equal(element('viewDashboard').classList.contains('hidden'), false);
    assert.equal(element('planOptionsScreen').parentNode.id, 'body');
    assert.equal(element('planReviewScreen').parentNode.id, 'body');
    assert.equal(element('planOptionsScreen').getAttribute('aria-modal'), 'true');
    if (input.scenario === 'onboarding_quota') {
      assert.ok(quotaFailures > 0, 'quota must be hit during the actual onboarding flow');
      const legacyView = readAccount('LEGACY-DEMO'); delete legacyView.terms;
      assert.equal(JSON.stringify(legacyView), JSON.stringify(legacyAccount));
      assert.equal(JSON.stringify(sandbox.readLocalUserData(user.student_id).confirmed_plan_result), JSON.stringify(input.options[1].result));
      sandbox.reviewDashCloseAccountDialogs();
      sandbox.restoreLocalPlannerState(sandbox.readLocalUserData(user.student_id));
      assert.equal(run('currentPlannerData.plan.plan_version'), input.options[1].result.plan.plan_version);
      assert.equal(run('cachedPlanOptions.length'), input.options.length);
      assert.equal(JSON.stringify(sandbox.cpdResultForConfirmed(sandbox.reviewDashReadState())), JSON.stringify(input.options[1].result));
      assert.equal(storage.get('unrelated-app'), 'preserve-unrelated-data');
    }
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
  if (run('!!(prvDraft.panel.alternatives && prvDraft.panel.alternatives.data)')) {
    // The shared feasibility block was put back on every listed preview.
    assert.equal(run('prvDraft.panel.alternatives.data.shared'), undefined);
    assert.equal(run('prvDraft.panel.alternatives.data.items.every(i => !!i.preview.result.feasibility)'), true);
  }
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
    assert.ok(panel().includes(input.impact.projected_total > input.impact.target_total ? ' — vượt mục tiêu.' : ' — đủ điểm.'));
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
  if (run('prvDraft.source') === 'synthetic') {
    assert.equal(call.body.availability, undefined, 'synthetic review keeps the fixture calendar');
  } else {
    assert.ok(call.body.availability.weekly_blocks.length);
  }
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
  sandbox.writeLocalUserData('SYN-REVIEW-01', empty);
  failWrites = true;
  await assert.rejects(sandbox.UniLifePlanReviewContract.confirmPlan({ student_id: 'SYN-REVIEW-01', strategy: 'BALANCED', result: input.options[1].result }), /storage failure/);
  failWrites = false;
  assert.equal(saved().confirmed_plan, null);
  run("currentStudent = {student_id:'SYN-REVIEW-02',full_name:'Second synthetic reviewer'};");
  assert.equal(sandbox.reviewDashReadState().plan, null);
  console.log(JSON.stringify({ passed: true, flows: ['review-swap-confirm-dashboard', 'pending-and-invalidation', 'cancel-and-accept-diff', 'selected-strategy', 'add-hidden', 'storage-failure', 'account-isolation'] }));
})().catch(error => { console.error(error.stack); process.exitCode = 1; });
