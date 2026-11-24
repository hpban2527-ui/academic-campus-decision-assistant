/**
 * UniLife First-Login Interactive User Tour
 * -----------------------------------------
 * Standalone, zero-conflict walkthrough module mounted via `/static/user_tour.js`.
 * Self-injects scoped CSS, non-blocking SVG spotlight overlay, step popover, and
 * header replay button without modifying inline page logic or teammate sections.
 */
(function (global) {
  'use strict';

  if (!global || !global.document) return;
  const doc = global.document;

  // =========================================================================
  // 1. Configuration & Storage Constants
  // =========================================================================
  const TOUR_VERSION = '1.0';
  const STORAGE_PREFIX = 'unilife_tour_v1_done_';
  const CURRENT_USER_KEY = 'unilife_current_user';
  const BOOT_ID_KEY = 'unilife_server_boot_id';
  const BOOT_COOKIE_NAME = 'unilife_server_boot_id';
  const LOCAL_USERS_KEY = 'unilife_users';
  const LEGACY_STUDENT_KEY = 'unilife_student';
  const USER_DATA_PREFIX = 'unilife_data_';
  const BLOCKING_MODAL_IDS = [
    'loginModal',
    'onboardingModal',
    'welcomeModal',
    'planOptionsScreen',
    'planReviewScreen',
    'planDiffModal',
    'activityTimelineModal',
  ];

  const STYLE_ID = 'unilife-user-tour-styles';
  const ROOT_ID = 'ulTourRoot';
  const TRIGGER_BTN_ID = 'btnStartUserTour';
  const FLOATING_BTN_ID = 'btnStartUserTourFloating';

  const DEFAULT_STEPS = [
    {
      id: 'overview',
      tab: 'dashboard',
      action: null,
      selectors: ['#workspaceOverview > div:first-child', '#workspaceOverview', '#viewDashboard'],
      badge: 'Bước 1 · Tổng quan',
      title: 'Chào mừng bạn đến với UniLife!',
      content: 'Đây là không gian Tổng quan giúp bạn theo dõi nhanh tổng điểm rèn luyện (ĐRL), số hoạt động đã tham gia, mục tiêu học kỳ và các gợi ý hoạt động nổi bật.',
      tip: 'Bạn có thể nhấn phím ← / → để chuyển bước hoặc Esc để tạm đóng hướng dẫn bất kỳ lúc nào.',
      placement: 'bottom',
      openMobileSidebar: false,
    },
    {
      id: 'confirmed-plan',
      tab: 'dashboard',
      action: null,
      selectors: ['#confirmedPlanDashboard'],
      badge: 'Bước 2 · Lịch đã chốt',
      title: 'Theo dõi Kế hoạch đã chốt',
      content: 'Sau khi chọn và xác nhận kế hoạch tối ưu, lịch hoạt động của bạn sẽ hiển thị tại đây theo chế độ Hôm nay / Tuần / Tháng để bạn theo dõi và xác nhận hoàn thành.',
      tip: 'Nếu hồ sơ hoặc lịch bận thay đổi, UniLife sẽ báo ngay để bạn dễ dàng cập nhật lại kế hoạch.',
      placement: 'bottom',
      openMobileSidebar: false,
    },
    {
      id: 'sidebar-nav',
      tab: 'dashboard',
      action: null,
      selectors: ['#sidebarNav nav', '#sidebarNav'],
      badge: 'Bước 3 · Điều hướng',
      title: 'Thanh điều hướng các chức năng chính',
      content: 'Dùng thanh bên trái để di chuyển nhanh giữa Tổng quan, Khám phá hoạt động và khu vực Cài đặt hồ sơ & Lịch lập kế hoạch.',
      tip: 'Trên màn hình nhỏ, bạn có thể bấm biểu tượng menu (☰) ở góc trên bên trái để mở thanh điều hướng.',
      placement: 'right',
      openMobileSidebar: true,
    },
    {
      id: 'discover-activities',
      tab: 'activities',
      action: 'discover',
      selectors: ['#activitiesTimelineSection', '#timelineSectionInner', '#viewActivities'],
      badge: 'Bước 4 · Khám phá hoạt động',
      title: 'Khám phá hoạt động theo dòng thời gian',
      content: 'Duyệt toàn bộ hoạt động thực tế của trường theo từng ngày, lọc theo lĩnh vực, hình thức tổ chức hoặc hạn đăng ký sắp hết hạn.',
      tip: 'Bấm trực tiếp vào bất kỳ thẻ hoạt động nào để xem chi tiết thời gian, địa điểm và điểm ĐRL ước tính.',
      placement: 'bottom',
      openMobileSidebar: false,
    },
    {
      id: 'settings-planner',
      tab: 'plan',
      action: null,
      selectors: ['#viewPlan [role="tablist"]', '#viewPlan > div:first-child', '#tabBtnPlan', '#viewPlan'],
      badge: 'Bước 5 · Cài đặt & Lập lịch',
      title: 'Chỉnh sửa mục tiêu, lịch bận & lập lại kế hoạch',
      content: 'Tại đây bạn có thể chuyển đổi giữa tab Hồ sơ (chỉnh mục tiêu ĐRL, sở thích) và tab Lịch (cập nhật lịch bận/rảnh, tạo 3 phương án đề xuất, hoán đổi hoạt động thay thế và chốt kế hoạch mới).',
      tip: 'Mọi thay đổi ở Lịch bận/rảnh sẽ tự động được áp dụng khi bạn bấm Lập kế hoạch mới.',
      placement: 'bottom',
      openMobileSidebar: false,
    },
    {
      id: 'profile-and-replay',
      tab: 'dashboard',
      action: null,
      selectors: ['#workspaceApp header button[onclick*="toggleUserDropdown"]', '#headerAvatar', '#btnThemeToggle', '#workspaceApp header'],
      badge: 'Bước 6 · Hồ sơ & Tiện ích',
      title: 'Hồ sơ sinh viên, Sáng/Tối & Xem lại hướng dẫn',
      content: 'Bấm vào tài khoản góc phải để mở Hồ sơ sinh viên (xem bảng điểm các kỳ, lịch sử hoạt động, ảnh đại diện), đổi tài khoản hoặc đăng xuất. Dùng thanh trên cùng để chuyển giao diện Sáng/Tối.',
      tip: 'Cần xem lại hướng dẫn này? Hãy bấm nút “Hướng dẫn (?)” ngay trên thanh tiêu đề bất cứ lúc nào!',
      placement: 'bottom',
      openMobileSidebar: false,
    },
  ];

  // =========================================================================
  // 2. Utilities & Safe Storage
  // =========================================================================
  function normalizeStudentId(id) {
    return String(id == null ? '' : id).trim().toUpperCase();
  }

  function storageKey(studentId) {
    const normalized = normalizeStudentId(studentId);
    return STORAGE_PREFIX + (normalized || 'GUEST');
  }

  function readStorage(key) {
    try {
      return global.localStorage ? global.localStorage.getItem(key) : null;
    } catch (_err) {
      return null;
    }
  }

  function writeStorage(key, value) {
    try {
      if (global.localStorage) global.localStorage.setItem(key, String(value));
      return true;
    } catch (_err) {
      return false;
    }
  }

  function removeStorage(key) {
    try {
      if (global.localStorage) global.localStorage.removeItem(key);
      return true;
    } catch (_err) {
      return false;
    }
  }

  function readCookie(name) {
    try {
      if (typeof doc.cookie !== 'string' || !doc.cookie) return '';
      const target = String(name) + '=';
      const parts = doc.cookie.split(';');
      for (let i = 0; i < parts.length; i++) {
        const item = parts[i].trim();
        if (item.indexOf(target) === 0) {
          return decodeURIComponent(item.slice(target.length));
        }
      }
    } catch (_err) {
      /* ignore cookie read errors */
    }
    return '';
  }

  function collectSessionStorageKeys() {
    const keys = [LOCAL_USERS_KEY, CURRENT_USER_KEY, LEGACY_STUDENT_KEY];
    try {
      const ls = global.localStorage;
      if (ls && typeof ls.length === 'number' && typeof ls.key === 'function') {
        for (let i = 0; i < ls.length; i++) {
          const key = ls.key(i);
          if (!key) continue;
          if (key.indexOf(USER_DATA_PREFIX) === 0 || key.indexOf(STORAGE_PREFIX) === 0) {
            if (keys.indexOf(key) === -1) keys.push(key);
          }
        }
      }
    } catch (_err) {
      /* ignore storage enumeration failure */
    }
    return keys;
  }

  function wipeLocalLoginSessions() {
    const keys = collectSessionStorageKeys();
    let hadSession = false;
    for (let i = 0; i < keys.length; i++) {
      const key = keys[i];
      if (readStorage(key) !== null) hadSession = true;
      removeStorage(key);
    }
    return hadSession;
  }

  function reconcileServerBootId(serverBootId, allowReload) {
    const normalizedBoot = String(serverBootId || '').trim();
    if (!normalizedBoot) return false;

    const storedBootId = readStorage(BOOT_ID_KEY);
    if (storedBootId === normalizedBoot) return false;

    const hadSession = wipeLocalLoginSessions();
    writeStorage(BOOT_ID_KEY, normalizedBoot);
    state.lastAutoCheckedStudentId = null;

    if (allowReload && hadSession) {
      const workspace = doc.getElementById('workspaceApp');
      const onboarding = doc.getElementById('onboardingModal');
      const activeUiShown = (workspace && !isNodeHidden(workspace)) || (onboarding && !isNodeHidden(onboarding));
      if (activeUiShown && global.location && typeof global.location.reload === 'function') {
        global.location.reload();
      }
    }
    return true;
  }

  function syncServerBootSession() {
    const cookieBootId = readCookie(BOOT_COOKIE_NAME);
    if (cookieBootId) {
      reconcileServerBootId(cookieBootId, false);
      return Promise.resolve(cookieBootId);
    }

    if (typeof global.fetch !== 'function') {
      return Promise.resolve('');
    }

    return global.fetch('/api/health', { cache: 'no-store' })
      .then(res => (res && res.ok && typeof res.json === 'function' ? res.json() : null))
      .then(data => {
        const bootId = data && data.server_boot_id ? String(data.server_boot_id) : '';
        if (bootId) reconcileServerBootId(bootId, true);
        return bootId;
      })
      .catch(() => '');
  }

  function capitalize(str) {
    return str ? str.charAt(0).toUpperCase() + str.slice(1) : '';
  }

  function viewIdForTab(tab) {
    return tab ? 'view' + capitalize(String(tab)) : '';
  }

  function getSearchParam(name) {
    try {
      const search = global.location && global.location.search ? global.location.search : '';
      if (!search || typeof URLSearchParams !== 'function') return null;
      return new URLSearchParams(search).get(name);
    } catch (_err) {
      return null;
    }
  }

  function prefersReducedMotion() {
    try {
      return Boolean(global.matchMedia && global.matchMedia('(prefers-reduced-motion: reduce)').matches);
    } catch (_err) {
      return false;
    }
  }

  function getCurrentStudentId() {
    const fromStorage = readStorage(CURRENT_USER_KEY);
    if (normalizeStudentId(fromStorage)) return normalizeStudentId(fromStorage);

    try {
      if (global.currentStudent && normalizeStudentId(global.currentStudent.student_id)) {
        return normalizeStudentId(global.currentStudent.student_id);
      }
    } catch (_err) {
      /* ignore */
    }

    const headerMssv = doc.getElementById('headerUserMssv');
    if (headerMssv && normalizeStudentId(headerMssv.textContent)) {
      return normalizeStudentId(headerMssv.textContent);
    }
    return '';
  }

  function hasCompleted(studentId) {
    const sid = normalizeStudentId(studentId || getCurrentStudentId());
    if (!sid) return false;
    return Boolean(readStorage(storageKey(sid)));
  }

  function markCompleted(studentId, status) {
    const sid = normalizeStudentId(studentId || getCurrentStudentId());
    if (!sid) return false;
    const payload = JSON.stringify({
      version: TOUR_VERSION,
      status: status || 'completed',
      completed_at: new Date().toISOString(),
    });
    return writeStorage(storageKey(sid), payload);
  }

  function normalizeStep(raw, idx) {
    const selectors = Array.isArray(raw.selectors)
      ? raw.selectors.filter(s => typeof s === 'string' && s.trim())
      : (typeof raw.selector === 'string' && raw.selector.trim() ? [raw.selector.trim()] : []);

    return {
      id: String(raw.id || ('step-' + (idx + 1))),
      tab: raw.tab ? String(raw.tab) : null,
      action: raw.action ? String(raw.action) : null,
      selectors,
      badge: String(raw.badge || ('Bước ' + (idx + 1))),
      title: String(raw.title || ''),
      content: String(raw.content || ''),
      tip: raw.tip ? String(raw.tip) : '',
      placement: String(raw.placement || 'bottom'),
      openMobileSidebar: Boolean(raw.openMobileSidebar),
    };
  }

  // =========================================================================
  // 3. Module State
  // =========================================================================
  let activeSteps = DEFAULT_STEPS.map(normalizeStep);
  const state = {
    active: false,
    currentIndex: 0,
    targetEl: null,
    expectedViewId: null,
    isInternalTabSwitch: false,
    mobileSidebarOpenedByTour: false,
    autoTriggerTimer: null,
    repositionTimer: null,
    observerDebounceTimer: null,
    rafId: null,
    lastAutoCheckedStudentId: null,
    urlTourTriggered: false,
  };

  let ui = null;

  // =========================================================================
  // 4. Scoped Styles & DOM Builder
  // =========================================================================
  function injectStyles() {
    if (doc.getElementById(STYLE_ID)) return;
    const style = doc.createElement('style');
    style.id = STYLE_ID;
    style.textContent = [
      '.ul-tour-root {',
      '  position: fixed; inset: 0; z-index: 90; pointer-events: none;',
      '  font-family: Inter, "Be Vietnam Pro", system-ui, -apple-system, sans-serif;',
      '}',
      '.ul-tour-root.ul-tour-hidden { display: none; }',
      '.ul-tour-backdrop {',
      '  position: fixed; inset: 0; width: 100vw; height: 100vh; z-index: 90;',
      '  pointer-events: none;',
      '}',
      '.ul-tour-backdrop path {',
      '  fill: rgba(2, 6, 23, 0.68); pointer-events: none;',
      '  transition: fill 0.25s ease;',
      '}',
      'body.ul-tour-light .ul-tour-backdrop path { fill: rgba(15, 23, 42, 0.45); }',
      '.ul-tour-ring {',
      '  position: fixed; z-index: 90; pointer-events: none; border-radius: 14px;',
      '  box-shadow: 0 0 0 2px #6366f1, 0 0 0 6px rgba(99, 102, 241, 0.28), 0 0 28px rgba(56, 189, 248, 0.25);',
      '  transition: top 0.26s cubic-bezier(0.22, 1, 0.36, 1), left 0.26s cubic-bezier(0.22, 1, 0.36, 1),',
      '              width 0.26s cubic-bezier(0.22, 1, 0.36, 1), height 0.26s cubic-bezier(0.22, 1, 0.36, 1),',
      '              opacity 0.2s ease;',
      '}',
      '.ul-tour-card {',
      '  position: fixed; z-index: 95; pointer-events: auto;',
      '  width: 380px; max-width: calc(100vw - 24px); border-radius: 18px;',
      '  background: linear-gradient(165deg, #0f172a 0%, #0e1524 100%);',
      '  border: 1px solid rgba(99, 102, 241, 0.45); color: #f8fafc;',
      '  box-shadow: 0 24px 48px -12px rgba(2, 6, 23, 0.72), 0 0 0 1px rgba(148, 163, 184, 0.08);',
      '  padding: 18px 18px 16px;',
      '  transition: top 0.26s cubic-bezier(0.22, 1, 0.36, 1), left 0.26s cubic-bezier(0.22, 1, 0.36, 1),',
      '              opacity 0.2s ease, transform 0.2s ease;',
      '}',
      'body.ul-tour-light .ul-tour-card {',
      '  background: #ffffff; border-color: #cbd5e1; color: #0f172a;',
      '  box-shadow: 0 20px 44px -12px rgba(15, 23, 42, 0.24), 0 0 0 1px rgba(99, 102, 241, 0.14);',
      '}',
      '.ul-tour-header { display: flex; align-items: center; justify-content: space-between; gap: 8px; }',
      '.ul-tour-badge {',
      '  display: inline-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 9999px;',
      '  font-size: 11px; font-weight: 700; letter-spacing: 0.02em;',
      '  background: rgba(99, 102, 241, 0.16); color: #a5b4fc; border: 1px solid rgba(99, 102, 241, 0.35);',
      '}',
      'body.ul-tour-light .ul-tour-badge {',
      '  background: #eef2ff; color: #4338ca; border-color: #c7d2fe;',
      '}',
      '.ul-tour-close {',
      '  width: 28px; height: 28px; border-radius: 8px; border: 1px solid transparent;',
      '  background: transparent; color: #94a3b8; cursor: pointer; font-size: 15px; line-height: 1;',
      '  display: inline-flex; align-items: center; justify-content: center; transition: background 0.15s, color 0.15s;',
      '}',
      '.ul-tour-close:hover { background: rgba(148, 163, 184, 0.14); color: #ffffff; }',
      'body.ul-tour-light .ul-tour-close { color: #64748b; }',
      'body.ul-tour-light .ul-tour-close:hover { background: #f1f5f9; color: #0f172a; }',
      '.ul-tour-progress-track {',
      '  margin-top: 12px; height: 4px; width: 100%; border-radius: 9999px; overflow: hidden;',
      '  background: rgba(148, 163, 184, 0.18);',
      '}',
      'body.ul-tour-light .ul-tour-progress-track { background: #e2e8f0; }',
      '.ul-tour-progress-bar {',
      '  height: 100%; border-radius: 9999px;',
      '  background: linear-gradient(90deg, #6366f1 0%, #38bdf8 100%);',
      '  transition: width 0.25s ease;',
      '}',
      '.ul-tour-title { margin: 12px 0 6px; font-size: 16px; font-weight: 800; line-height: 1.35; color: #ffffff; }',
      'body.ul-tour-light .ul-tour-title { color: #0f172a; }',
      '.ul-tour-content { margin: 0; font-size: 13.5px; line-height: 1.55; color: #cbd5e1; }',
      'body.ul-tour-light .ul-tour-content { color: #475569; }',
      '.ul-tour-tip {',
      '  margin-top: 11px; padding: 9px 11px; border-radius: 10px; font-size: 12px; line-height: 1.45;',
      '  background: rgba(30, 41, 59, 0.7); border: 1px solid rgba(56, 189, 248, 0.22); color: #bae6fd;',
      '}',
      'body.ul-tour-light .ul-tour-tip {',
      '  background: #f1f5f9; border-color: #cbd5e1; color: #0369a1;',
      '}',
      '.ul-tour-dots { display: flex; align-items: center; gap: 6px; margin-top: 14px; }',
      '.ul-tour-dot {',
      '  width: 7px; height: 7px; padding: 0; border: 0; border-radius: 9999px; cursor: pointer;',
      '  background: rgba(148, 163, 184, 0.35); transition: width 0.2s ease, background 0.2s ease;',
      '}',
      '.ul-tour-dot.ul-tour-dot-active { width: 20px; background: #6366f1; }',
      'body.ul-tour-light .ul-tour-dot { background: #cbd5e1; }',
      'body.ul-tour-light .ul-tour-dot.ul-tour-dot-active { background: #4f46e5; }',
      '.ul-tour-footer {',
      '  margin-top: 14px; padding-top: 12px; border-top: 1px solid rgba(148, 163, 184, 0.16);',
      '  display: flex; align-items: center; justify-content: space-between; gap: 8px;',
      '}',
      'body.ul-tour-light .ul-tour-footer { border-top-color: #e2e8f0; }',
      '.ul-tour-actions { display: flex; align-items: center; gap: 8px; }',
      '.ul-tour-btn {',
      '  border-radius: 10px; font-size: 12.5px; font-weight: 700; padding: 7px 13px; cursor: pointer;',
      '  transition: background 0.15s ease, color 0.15s ease, border-color 0.15s ease, opacity 0.15s ease;',
      '}',
      '.ul-tour-btn:disabled { opacity: 0.4; cursor: not-allowed; }',
      '.ul-tour-btn-ghost {',
      '  background: transparent; border: 1px solid transparent; color: #94a3b8; padding-left: 6px; padding-right: 6px;',
      '}',
      '.ul-tour-btn-ghost:hover:not(:disabled) { color: #f8fafc; }',
      'body.ul-tour-light .ul-tour-btn-ghost { color: #64748b; }',
      'body.ul-tour-light .ul-tour-btn-ghost:hover:not(:disabled) { color: #0f172a; }',
      '.ul-tour-btn-secondary {',
      '  background: rgba(15, 23, 42, 0.8); border: 1px solid #334155; color: #e2e8f0;',
      '}',
      '.ul-tour-btn-secondary:hover:not(:disabled) { background: #1e293b; border-color: #475569; }',
      'body.ul-tour-light .ul-tour-btn-secondary { background: #f8fafc; border-color: #cbd5e1; color: #334155; }',
      'body.ul-tour-light .ul-tour-btn-secondary:hover:not(:disabled) { background: #f1f5f9; }',
      '.ul-tour-btn-primary {',
      '  background: linear-gradient(135deg, #4f46e5 0%, #2563eb 100%);',
      '  border: 1px solid rgba(129, 140, 248, 0.5); color: #ffffff;',
      '  box-shadow: 0 6px 16px -4px rgba(79, 70, 229, 0.5);',
      '}',
      '.ul-tour-btn-primary:hover:not(:disabled) { filter: brightness(1.08); }',
      '.ul-tour-floating-trigger {',
      '  position: fixed; right: 20px; bottom: 20px; z-index: 60; pointer-events: auto;',
      '  display: inline-flex; align-items: center; gap: 6px; padding: 9px 14px; border-radius: 9999px;',
      '  background: #0e1524; color: #e2e8f0; border: 1px solid #334155;',
      '  font-size: 12px; font-weight: 700; cursor: pointer;',
      '  box-shadow: 0 10px 24px rgba(2, 6, 23, 0.45);',
      '}',
      'body.ul-tour-light .ul-tour-floating-trigger {',
      '  background: #ffffff; color: #1e293b; border-color: #cbd5e1;',
      '}',
      '@media (prefers-reduced-motion: reduce) {',
      '  .ul-tour-ring, .ul-tour-card, .ul-tour-progress-bar, .ul-tour-dot {',
      '    transition: none !important;',
      '  }',
      '}',
    ].join('\n');
    (doc.head || doc.body || doc.documentElement).appendChild(style);
  }

  function createEl(tag, className, text) {
    const node = doc.createElement(tag);
    if (className) node.className = className;
    if (text != null) node.textContent = String(text);
    return node;
  }

  function ensureUI() {
    if (ui && doc.getElementById(ROOT_ID)) return ui;
    injectStyles();

    const root = createEl('div', 'ul-tour-root ul-tour-hidden');
    root.id = ROOT_ID;

    let backdropPath = null;
    let backdropSvg = null;
    if (typeof doc.createElementNS === 'function') {
      const SVG_NS = 'http://www.w3.org/2000/svg';
      backdropSvg = doc.createElementNS(SVG_NS, 'svg');
      backdropSvg.setAttribute('class', 'ul-tour-backdrop');
      backdropSvg.setAttribute('aria-hidden', 'true');
      backdropPath = doc.createElementNS(SVG_NS, 'path');
      backdropPath.setAttribute('fill-rule', 'evenodd');
      backdropSvg.appendChild(backdropPath);
      root.appendChild(backdropSvg);
    }

    const ring = createEl('div', 'ul-tour-ring');
    ring.setAttribute('aria-hidden', 'true');
    root.appendChild(ring);

    const card = createEl('div', 'ul-tour-card');
    card.setAttribute('role', 'dialog');
    card.setAttribute('aria-modal', 'false');
    card.setAttribute('aria-labelledby', 'ulTourTitle');
    card.setAttribute('aria-describedby', 'ulTourContent');

    const header = createEl('div', 'ul-tour-header');
    const badge = createEl('span', 'ul-tour-badge');
    badge.id = 'ulTourBadge';
    const closeBtn = createEl('button', 'ul-tour-close', '✕');
    closeBtn.type = 'button';
    closeBtn.setAttribute('aria-label', 'Đóng hướng dẫn');
    closeBtn.addEventListener('click', () => stop({ markDone: true, status: 'skipped' }));
    header.appendChild(badge);
    header.appendChild(closeBtn);

    const progressTrack = createEl('div', 'ul-tour-progress-track');
    const progressBar = createEl('div', 'ul-tour-progress-bar');
    progressBar.style.width = '0%';
    progressTrack.appendChild(progressBar);

    const title = createEl('h3', 'ul-tour-title');
    title.id = 'ulTourTitle';

    const content = createEl('p', 'ul-tour-content');
    content.id = 'ulTourContent';

    const tip = createEl('div', 'ul-tour-tip');
    tip.id = 'ulTourTip';

    const dots = createEl('div', 'ul-tour-dots');
    dots.id = 'ulTourDots';

    const footer = createEl('div', 'ul-tour-footer');
    const skipBtn = createEl('button', 'ul-tour-btn ul-tour-btn-ghost', 'Bỏ qua');
    skipBtn.type = 'button';
    skipBtn.id = 'ulTourSkipBtn';
    skipBtn.addEventListener('click', () => stop({ markDone: true, status: 'skipped' }));

    const actions = createEl('div', 'ul-tour-actions');
    const prevBtn = createEl('button', 'ul-tour-btn ul-tour-btn-secondary', 'Quay lại');
    prevBtn.type = 'button';
    prevBtn.id = 'ulTourPrevBtn';
    prevBtn.addEventListener('click', () => prev());

    const nextBtn = createEl('button', 'ul-tour-btn ul-tour-btn-primary', 'Tiếp theo →');
    nextBtn.type = 'button';
    nextBtn.id = 'ulTourNextBtn';
    nextBtn.addEventListener('click', () => next());

    actions.appendChild(prevBtn);
    actions.appendChild(nextBtn);
    footer.appendChild(skipBtn);
    footer.appendChild(actions);

    card.appendChild(header);
    card.appendChild(progressTrack);
    card.appendChild(title);
    card.appendChild(content);
    card.appendChild(tip);
    card.appendChild(dots);
    card.appendChild(footer);
    root.appendChild(card);

    (doc.body || doc.documentElement).appendChild(root);

    ui = {
      root,
      backdropSvg,
      backdropPath,
      ring,
      card,
      badge,
      progressBar,
      title,
      content,
      tip,
      dots,
      skipBtn,
      prevBtn,
      nextBtn,
    };
    return ui;
  }

  function injectTriggerButton() {
    const workspace = doc.getElementById('workspaceApp');
    if (!workspace) return null;

    const existingHeaderBtn = doc.getElementById(TRIGGER_BTN_ID);
    const existingFloatingBtn = doc.getElementById(FLOATING_BTN_ID);
    const themeBtn = doc.getElementById('btnThemeToggle');

    if (themeBtn && themeBtn.parentNode) {
      if (existingFloatingBtn && existingFloatingBtn.parentNode) {
        existingFloatingBtn.parentNode.removeChild(existingFloatingBtn);
      }
      if (existingHeaderBtn) return existingHeaderBtn;

      const btn = createEl(
        'button',
        'px-2.5 sm:px-3 py-1.5 rounded-xl bg-[#0e1524] border border-[#1b2537] text-slate-300 hover:text-white hover:bg-[#11192b] text-xs font-semibold transition flex items-center gap-1.5'
      );
      btn.id = TRIGGER_BTN_ID;
      btn.type = 'button';
      btn.setAttribute('aria-label', 'Mở hướng dẫn sử dụng');
      btn.setAttribute('title', 'Xem lại hướng dẫn sử dụng UniLife');

      const icon = createEl(
        'span',
        'inline-flex h-4 w-4 items-center justify-center rounded-full border border-indigo-400/50 bg-indigo-500/20 text-[10px] font-extrabold text-indigo-300',
        '?'
      );
      icon.setAttribute('aria-hidden', 'true');
      const label = createEl('span', 'hidden sm:inline', 'Hướng dẫn');

      btn.appendChild(icon);
      btn.appendChild(label);
      btn.addEventListener('click', () => start({ force: true, startIndex: 0 }));

      themeBtn.parentNode.insertBefore(btn, themeBtn.nextSibling);
      return btn;
    }

    if (existingHeaderBtn || existingFloatingBtn) {
      return existingHeaderBtn || existingFloatingBtn;
    }

    const fallback = createEl('button', 'ul-tour-floating-trigger');
    fallback.id = FLOATING_BTN_ID;
    fallback.type = 'button';
    fallback.setAttribute('aria-label', 'Mở hướng dẫn sử dụng');
    fallback.setAttribute('title', 'Xem lại hướng dẫn sử dụng UniLife');
    const q = createEl('span', '', '?');
    q.setAttribute('aria-hidden', 'true');
    const text = createEl('span', '', 'Hướng dẫn');
    fallback.appendChild(q);
    fallback.appendChild(text);
    fallback.addEventListener('click', () => start({ force: true, startIndex: 0 }));
    workspace.appendChild(fallback);
    return fallback;
  }

  // =========================================================================
  // 5. Visibility, Theme & Guard Helpers
  // =========================================================================
  function isNodeHidden(node) {
    if (!node) return true;
    if (node.hidden === true) return true;
    if (node.classList && typeof node.classList.contains === 'function' && node.classList.contains('hidden')) {
      return true;
    }
    return false;
  }

  function isVisible(el) {
    if (!el) return false;
    if (el.isConnected === false) return false;

    let cursor = el;
    while (cursor && cursor !== doc) {
      if (isNodeHidden(cursor)) return false;
      if (typeof global.getComputedStyle === 'function') {
        try {
          const style = global.getComputedStyle(cursor);
          if (style && (style.display === 'none' || style.visibility === 'hidden')) return false;
        } catch (_err) {
          /* ignore mock elements */
        }
      }
      cursor = cursor.parentNode;
    }

    if (typeof el.getBoundingClientRect === 'function') {
      const rect = el.getBoundingClientRect();
      if (!rect || rect.width <= 0 || rect.height <= 0) return false;
    }
    return true;
  }

  function hasOpenBlockingModal() {
    for (let i = 0; i < BLOCKING_MODAL_IDS.length; i++) {
      const modal = doc.getElementById(BLOCKING_MODAL_IDS[i]);
      if (modal && !isNodeHidden(modal)) return true;
    }
    return false;
  }

  function syncTheme() {
    if (!doc.body || !doc.body.classList) return;
    const workspace = doc.getElementById('workspaceApp');
    const isLight = Boolean(workspace && workspace.classList && workspace.classList.contains('light-theme'));
    if (typeof doc.body.classList.toggle === 'function') {
      doc.body.classList.toggle('ul-tour-light', isLight);
    }
  }

  function canAutoStart() {
    const workspace = doc.getElementById('workspaceApp');
    if (!workspace || isNodeHidden(workspace)) return false;
    if (doc.body && doc.body.classList && doc.body.classList.contains('dev-mode')) return false;
    if (hasOpenBlockingModal()) return false;
    if (getSearchParam('notour') === '1') return false;

    const studentId = getCurrentStudentId();
    if (!studentId) return false;

    if (getSearchParam('tour') === '1' && !state.urlTourTriggered) {
      return true;
    }
    return !hasCompleted(studentId);
  }

  function resolveStepTarget(step) {
    if (!step || !Array.isArray(step.selectors)) return null;
    for (let i = 0; i < step.selectors.length; i++) {
      const selector = step.selectors[i];
      try {
        const el = doc.querySelector ? doc.querySelector(selector) : null;
        if (el && isVisible(el)) return el;
      } catch (_err) {
        /* ignore malformed selector */
      }
    }
    return null;
  }

  function tabViewExists(tab) {
    if (!tab) return true;
    const hasDashboardMarker = Boolean(doc.getElementById('viewDashboard'));
    if (!hasDashboardMarker) return true;
    return Boolean(doc.getElementById(viewIdForTab(tab)));
  }

  // =========================================================================
  // 6. Positioning & Spotlight Rendering
  // =========================================================================
  function measureRect(el) {
    if (el && typeof el.getBoundingClientRect === 'function') {
      const r = el.getBoundingClientRect();
      return {
        top: r.top,
        left: r.left,
        right: r.right,
        bottom: r.bottom,
        width: r.width,
        height: r.height,
      };
    }
    return { top: 80, left: 40, right: 440, bottom: 200, width: 400, height: 120 };
  }

  function buildSpotlightPath(vw, vh, box) {
    const outer = `M0,0 H${vw} V${vh} H0 Z`;
    if (!box || box.width <= 0 || box.height <= 0) return outer;

    const x = Math.max(0, Math.round(box.left));
    const y = Math.max(0, Math.round(box.top));
    const w = Math.max(0, Math.min(vw - x, Math.round(box.width)));
    const h = Math.max(0, Math.min(vh - y, Math.round(box.height)));
    if (w <= 0 || h <= 0) return outer;

    const r = Math.min(14, Math.floor(w / 2), Math.floor(h / 2));
    const hole = [
      `M${x + r},${y}`,
      `H${x + w - r}`,
      `A${r},${r} 0 0 1 ${x + w},${y + r}`,
      `V${y + h - r}`,
      `A${r},${r} 0 0 1 ${x + w - r},${y + h}`,
      `H${x + r}`,
      `A${r},${r} 0 0 1 ${x},${y + h - r}`,
      `V${y + r}`,
      `A${r},${r} 0 0 1 ${x + r},${y}`,
      'Z',
    ].join(' ');
    return `${outer} ${hole}`;
  }

  function clamp(val, min, max) {
    if (max < min) return min;
    return Math.max(min, Math.min(max, val));
  }

  function positionOverlay() {
    if (!state.active || !ui || !state.targetEl) return;

    const vw = global.innerWidth || 1280;
    const vh = global.innerHeight || 800;
    const raw = measureRect(state.targetEl);
    const pad = 6;
    const box = {
      top: clamp(raw.top - pad, 4, vh - 8),
      left: clamp(raw.left - pad, 4, vw - 8),
      width: Math.min(vw - 8, raw.width + pad * 2),
      height: Math.min(vh - 8, raw.height + pad * 2),
    };
    box.right = box.left + box.width;
    box.bottom = box.top + box.height;

    if (ui.backdropSvg) {
      ui.backdropSvg.setAttribute('viewBox', `0 0 ${vw} ${vh}`);
    }
    if (ui.backdropPath) {
      ui.backdropPath.setAttribute('d', buildSpotlightPath(vw, vh, box));
    }

    ui.ring.style.top = `${Math.round(box.top)}px`;
    ui.ring.style.left = `${Math.round(box.left)}px`;
    ui.ring.style.width = `${Math.round(box.width)}px`;
    ui.ring.style.height = `${Math.round(box.height)}px`;

    const card = ui.card;
    const cardW = card.offsetWidth || Math.min(380, vw - 24);
    const cardH = card.offsetHeight || 250;
    const margin = 12;
    const gap = 14;
    const step = activeSteps[state.currentIndex] || {};

    const candidates = [];
    [step.placement, 'bottom', 'top', 'right', 'left'].forEach(side => {
      if (side && candidates.indexOf(side) === -1) candidates.push(side);
    });

    let chosen = null;
    for (let i = 0; i < candidates.length; i++) {
      const side = candidates[i];
      if (side === 'bottom' && vh - box.bottom >= cardH + gap + margin) {
        chosen = {
          top: box.bottom + gap,
          left: clamp(box.left, margin, vw - cardW - margin),
        };
        break;
      }
      if (side === 'top' && box.top >= cardH + gap + margin) {
        chosen = {
          top: box.top - cardH - gap,
          left: clamp(box.left, margin, vw - cardW - margin),
        };
        break;
      }
      if (side === 'right' && vw - box.right >= cardW + gap + margin) {
        chosen = {
          top: clamp(box.top, margin, vh - cardH - margin),
          left: box.right + gap,
        };
        break;
      }
      if (side === 'left' && box.left >= cardW + gap + margin) {
        chosen = {
          top: clamp(box.top, margin, vh - cardH - margin),
          left: box.left - cardW - gap,
        };
        break;
      }
    }

    if (!chosen) {
      // Target spans most of the viewport (e.g. full-width timeline); anchor card cleanly at bottom-right.
      chosen = {
        top: clamp(vh - cardH - margin - 6, margin, vh - cardH - margin),
        left: clamp(vw - cardW - margin - 6, margin, vw - cardW - margin),
      };
    }

    card.style.top = `${Math.round(clamp(chosen.top, margin, vh - cardH - margin))}px`;
    card.style.left = `${Math.round(clamp(chosen.left, margin, vw - cardW - margin))}px`;
  }

  function scheduleReposition() {
    if (!state.active) return;
    if (state.rafId && typeof global.cancelAnimationFrame === 'function') {
      global.cancelAnimationFrame(state.rafId);
    }
    if (typeof global.requestAnimationFrame === 'function') {
      state.rafId = global.requestAnimationFrame(() => positionOverlay());
    } else {
      positionOverlay();
    }
  }

  // =========================================================================
  // 7. Step Navigation & Lifecycle
  // =========================================================================
  function releaseMobileSidebarIfOwned() {
    if (!state.mobileSidebarOpenedByTour) return;
    state.mobileSidebarOpenedByTour = false;
    if (typeof global.toggleMobileSidebar === 'function') {
      try {
        global.toggleMobileSidebar(false);
      } catch (_err) {
        /* ignore */
      }
    }
  }

  function switchTabSafely(step) {
    if (!step || !step.tab) {
      state.expectedViewId = null;
      return;
    }
    state.expectedViewId = viewIdForTab(step.tab);
    if (typeof global.switchTab !== 'function') return;

    state.isInternalTabSwitch = true;
    try {
      global.switchTab(step.tab, step.action || undefined);
    } finally {
      state.isInternalTabSwitch = false;
    }
  }

  function hasRemainingStep(fromIndex, dir) {
    for (let i = fromIndex + dir; i >= 0 && i < activeSteps.length; i += dir) {
      if (tabViewExists(activeSteps[i].tab)) return true;
    }
    return false;
  }

  function renderStepUI(index) {
    const step = activeSteps[index];
    const total = activeSteps.length;
    const progressPct = total > 0 ? Math.round(((index + 1) / total) * 100) : 100;

    ui.badge.textContent = step.badge || `Bước ${index + 1} / ${total}`;
    ui.progressBar.style.width = `${progressPct}%`;
    ui.title.textContent = step.title;
    ui.content.textContent = step.content;

    if (step.tip) {
      ui.tip.textContent = step.tip;
      ui.tip.style.display = 'block';
    } else {
      ui.tip.textContent = '';
      ui.tip.style.display = 'none';
    }

    while (ui.dots.firstChild) ui.dots.removeChild(ui.dots.firstChild);
    for (let i = 0; i < total; i++) {
      const dot = createEl('button', i === index ? 'ul-tour-dot ul-tour-dot-active' : 'ul-tour-dot');
      dot.type = 'button';
      dot.setAttribute('aria-label', `Chuyển đến bước ${i + 1}`);
      dot.addEventListener('click', () => goTo(i, i >= state.currentIndex ? 1 : -1));
      ui.dots.appendChild(dot);
    }

    ui.prevBtn.disabled = !hasRemainingStep(index, -1);
    const isLast = !hasRemainingStep(index, 1);
    ui.nextBtn.textContent = isLast ? 'Hoàn thành ✓' : 'Tiếp theo →';
  }

  function activateStep(index, target) {
    ensureUI();
    syncTheme();

    state.active = true;
    state.currentIndex = index;
    state.targetEl = target;
    ui.root.classList.remove('ul-tour-hidden');

    renderStepUI(index);
    positionOverlay();

    if (typeof target.scrollIntoView === 'function') {
      try {
        const rect = measureRect(target);
        const vh = global.innerHeight || 800;
        if (rect.top < 16 || rect.bottom > vh - 16) {
          target.scrollIntoView({
            behavior: prefersReducedMotion() ? 'auto' : 'smooth',
            block: 'center',
            inline: 'nearest',
          });
          global.clearTimeout(state.repositionTimer);
          state.repositionTimer = global.setTimeout(() => positionOverlay(), 280);
        }
      } catch (_err) {
        /* ignore in minimal DOM */
      }
    }
  }

  function goTo(startIndex, direction) {
    const dir = direction < 0 ? -1 : 1;
    if (!activeSteps.length) return false;

    const parsed = Number(startIndex);
    if (!Number.isInteger(parsed) || parsed < 0 || parsed >= activeSteps.length) {
      return false;
    }
    let idx = parsed;
    while (idx >= 0 && idx < activeSteps.length) {
      const step = activeSteps[idx];
      if (tabViewExists(step.tab)) {
        switchTabSafely(step);

        const vw = global.innerWidth || 1440;
        if (step.openMobileSidebar && vw < 1024 && typeof global.toggleMobileSidebar === 'function') {
          try {
            global.toggleMobileSidebar(true);
            state.mobileSidebarOpenedByTour = true;
          } catch (_err) {
            /* ignore */
          }
        } else {
          releaseMobileSidebarIfOwned();
        }

        const target = resolveStepTarget(step);
        if (target) {
          activateStep(idx, target);
          return true;
        }
      }
      idx += dir;
    }

    if (state.active && dir > 0) {
      stop({ markDone: true, status: 'completed' });
    }
    return false;
  }

  function start(options) {
    const opts = options || {};
    const force = Boolean(opts.force);
    const startIndex = Number.isInteger(opts.startIndex) ? opts.startIndex : 0;

    syncTheme();
    ensureUI();
    injectTriggerButton();

    if (!force && !canAutoStart()) return false;

    const studentId = getCurrentStudentId();
    if (studentId) state.lastAutoCheckedStudentId = studentId;
    if (getSearchParam('tour') === '1') state.urlTourTriggered = true;

    const started = goTo(startIndex, 1);
    if (!started && tabViewExists('dashboard') && typeof global.switchTab === 'function') {
      state.isInternalTabSwitch = true;
      try {
        global.switchTab('dashboard');
      } finally {
        state.isInternalTabSwitch = false;
      }
    }
    return started;
  }

  function stop(options) {
    const opts = options || {};
    const markDone = Boolean(opts.markDone);
    const status = opts.status || 'dismissed';

    global.clearTimeout(state.autoTriggerTimer);
    global.clearTimeout(state.repositionTimer);
    if (state.rafId && typeof global.cancelAnimationFrame === 'function') {
      global.cancelAnimationFrame(state.rafId);
      state.rafId = null;
    }

    releaseMobileSidebarIfOwned();

    state.active = false;
    state.targetEl = null;
    state.expectedViewId = null;

    if (ui && ui.root) {
      ui.root.classList.add('ul-tour-hidden');
    }

    if (markDone) {
      markCompleted(getCurrentStudentId(), status);
    }
  }

  function next() {
    if (!state.active) return false;
    if (state.currentIndex + 1 >= activeSteps.length || !goTo(state.currentIndex + 1, 1)) {
      stop({ markDone: true, status: 'completed' });
      return false;
    }
    return true;
  }

  function prev() {
    if (!state.active) return false;
    if (state.currentIndex - 1 < 0) return false;
    return goTo(state.currentIndex - 1, -1);
  }

  function registerSteps(customSteps) {
    if (!Array.isArray(customSteps)) {
      throw new TypeError('UniLifeUserTour.registerSteps expects an array of steps.');
    }
    const normalized = customSteps
      .filter(item => item && typeof item === 'object' && (item.title || item.content))
      .map(normalizeStep);
    if (!normalized.length) {
      throw new Error('UniLifeUserTour.registerSteps requires at least one valid step.');
    }
    activeSteps = normalized;
    if (state.active) goTo(0, 1);
    return getSteps();
  }

  function getSteps() {
    return activeSteps.map(step => Object.assign({}, step, { selectors: step.selectors.slice() }));
  }

  function reset(studentId) {
    const sid = normalizeStudentId(studentId || getCurrentStudentId());
    if (sid && state.lastAutoCheckedStudentId === sid) {
      state.lastAutoCheckedStudentId = null;
    }
    return sid ? removeStorage(storageKey(sid)) : false;
  }

  // =========================================================================
  // 8. Lifecycle Listeners & MutationObserver
  // =========================================================================
  function evaluateWorkspaceState() {
    syncTheme();
    const workspace = doc.getElementById('workspaceApp');
    if (!workspace || isNodeHidden(workspace)) {
      state.lastAutoCheckedStudentId = null;
      if (state.active) stop({ markDone: false, status: 'workspace_hidden' });
      return;
    }

    injectTriggerButton();

    if (state.active && !state.isInternalTabSwitch) {
      if (hasOpenBlockingModal()) {
        stop({ markDone: false, status: 'interrupted_by_modal' });
        return;
      }
      if (state.expectedViewId) {
        const expectedEl = doc.getElementById(state.expectedViewId);
        if (expectedEl && isNodeHidden(expectedEl)) {
          stop({ markDone: false, status: 'tab_changed' });
          return;
        }
      }
    }

    const studentId = getCurrentStudentId();
    if (!state.active && studentId && studentId !== state.lastAutoCheckedStudentId && canAutoStart()) {
      state.lastAutoCheckedStudentId = studentId;
      global.clearTimeout(state.autoTriggerTimer);
      state.autoTriggerTimer = global.setTimeout(() => {
        if (!state.active && canAutoStart()) {
          start({ force: false, startIndex: 0 });
        }
      }, 550);
    }
  }

  function bindGlobalListeners() {
    doc.addEventListener('keydown', event => {
      if (!state.active || !event || event.defaultPrevented) return;
      if (event.key === 'Escape') {
        if (typeof event.preventDefault === 'function') event.preventDefault();
        stop({ markDone: true, status: 'skipped' });
      } else if (event.key === 'ArrowRight') {
        if (typeof event.preventDefault === 'function') event.preventDefault();
        next();
      } else if (event.key === 'ArrowLeft') {
        if (typeof event.preventDefault === 'function') event.preventDefault();
        prev();
      }
    });

    if (typeof global.addEventListener === 'function') {
      global.addEventListener('resize', scheduleReposition);
      global.addEventListener('scroll', scheduleReposition, true);
    }

    if (typeof global.MutationObserver === 'function' && doc.body) {
      const observer = new global.MutationObserver(() => {
        global.clearTimeout(state.observerDebounceTimer);
        state.observerDebounceTimer = global.setTimeout(evaluateWorkspaceState, 250);
      });
      observer.observe(doc.body, {
        attributes: true,
        attributeFilter: ['class', 'hidden'],
        subtree: true,
      });
    }
  }

  function init() {
    bindGlobalListeners();
    evaluateWorkspaceState();
  }

  // Synchronously wipe stale local accounts before DOMContentLoaded restores sessions if server rebooted.
  syncServerBootSession();

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

  // =========================================================================
  // 9. Public Extensible API
  // =========================================================================
  global.UniLifeUserTour = {
    version: TOUR_VERSION,
    start,
    stop,
    next,
    prev,
    goTo,
    isActive: () => state.active,
    hasCompleted,
    reset,
    getSteps,
    registerSteps,
    reposition: positionOverlay,
    syncServerBootSession,
    wipeLocalLoginSessions,
  };
})(typeof window !== 'undefined' ? window : globalThis);
