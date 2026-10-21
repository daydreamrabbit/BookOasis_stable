// scan_activity_status.js – 백그라운드 스캔 상태 폴링 및 카테고리 스피너 제어 루틴 (ui.js에서 분리)
import { state } from './state.js';
import { notificationItemHtml } from './notification_render.js';
import { initNotificationCards, restoreCardExpansions } from './notification_cards.js';
import { parseServerDateTime, formatRelativeTime } from './utils/time.js';
import { evaluateScanPollingState } from './scan_status_polling_policy.js';

let statusIntervalId = null;
let wasScanningPrevious = false;
let lastActiveLibIds = new Set();
let lastIsHeaderScanning = false;
let scanLatchTimerMap = new Map();
let latestSystemStatus = null;
let refreshStatusPoll = null;
let lastStatusErrorSignature = '';
let lastStatusErrorAt = 0;
let seenRecentBatchScanIds = null;
let seenRecentLibraryScanIds = null;
let pollingScanType = null;
let pollingStartedAt = 0;
let observedActiveScan = false;
let consecutiveIdlePolls = 0;
let statusPollGeneration = 0;
let pollingProbe = false;
let activityTab = 'all';
let activityDetails = { history: [], upcoming: [] };
let activityDetailsLoading = false;
let activityHistoryExpanded = false;
let activityUpcomingExpanded = false;
let dismissedActivity = new Set();
let currentActivityTasks = [];

function activityIdentity(task) {
  return JSON.stringify([task.type || task.task_type, task.id ?? task.key ?? task.run_id,
    task.finished_at || task.started_at || task.enqueued_at || '']);
}

function activityStorageKey() {
  return `bookoasis:scan-activity:hidden:${window.currentUser?.id ?? window.currentUser?.username ?? document.getElementById('session-username-display')?.textContent ?? 'session'}`;
}

function hideActivityItems(ids) {
  ids.forEach(id => dismissedActivity.add(id));
  dismissedActivity = new Set([...dismissedActivity].slice(-400));
  try { localStorage.setItem(activityStorageKey(), JSON.stringify([...dismissedActivity])); } catch { /* Storage can be disabled. */ }
  if (latestSystemStatus) renderScanActivity(latestSystemStatus);
}

function activityNotice(message = '') {
  const el = document.getElementById('scan-activity-notice');
  if (el) { el.textContent = message; el.hidden = !message; }
}

async function loadActivityDetails() {
  if (window.currentUser?.role !== 'admin' || activityDetailsLoading) return;
  activityDetailsLoading = true;
  try {
    const response = await fetch('/api/system/scan-activity', { cache: 'no-store' });
    if (!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error();
    const data = await response.json();
    if (!data.success || !Array.isArray(data.history) || !Array.isArray(data.upcoming)) throw new Error();
    activityDetails = data;
    activityNotice(data.unavailable?.length ? '일부 예약을 조회하지 못했습니다. 예약·대기열에서 확인해 주세요.' : '');
    if (latestSystemStatus) renderScanActivity(latestSystemStatus);
  } catch {
    activityNotice('이력·예약을 갱신하지 못했습니다. 기존 표시를 유지합니다. 다시 열어 재시도하세요.');
  } finally { activityDetailsLoading = false; }
}

function renderUpcomingActivity() {
  const el = document.getElementById('scan-activity-upcoming');
  if (!el) return;
  el.hidden = activityTab === 'attention' || window.currentUser?.role !== 'admin';
  const upcoming = activityDetails.upcoming.filter(item => new Date(item.next_run_at).getTime() >= Date.now());
  el.innerHTML = `<div class="scan-activity-section-heading"><strong>다음 예약</strong>${upcoming.length > 2 ? `<button type="button" data-scan-upcoming-more>${activityUpcomingExpanded ? '접기' : `${upcoming.length - 2}개 더 보기`}</button>` : ''}</div>`
    + (upcoming.length ? upcoming.slice(0, activityUpcomingExpanded ? undefined : 2).map(item => {
      const date = new Date(item.next_run_at);
      return `<div class="scan-activity-upcoming-row"><time datetime="${escapeActivityAttribute(item.next_run_at)}">${escapeActivityText(date.toLocaleString(undefined, { month:'numeric',day:'numeric',hour:'2-digit',minute:'2-digit' }))}</time><div><strong>${escapeActivityText(item.name)}</strong><small>${escapeActivityText(item.db_type)} · 예약식 ${escapeActivityText(item.cron)}</small></div></div>`;
    }).join('') : '<p class="scan-activity-note">등록된 다음 예약이 없습니다.</p>');
}

const STATUS_POLL_INTERVAL_MS = 2000;
const QUEUE_VISIBILITY_GRACE_MS = 8000;

export function refreshSystemStatus() {
  return refreshStatusPoll ? refreshStatusPoll() : startSystemStatusPolling(undefined, { probe: true });
}

export function stopSystemStatusPolling() {
  statusPollGeneration++;
  if (statusIntervalId) clearInterval(statusIntervalId);
  statusIntervalId = null;
  refreshStatusPoll = null;
  pollingScanType = null;
  pollingStartedAt = 0;
  observedActiveScan = false;
  consecutiveIdlePolls = 0;
}

function escapeActivityText(value) {
  const node = document.createElement('div');
  node.textContent = String(value ?? '');
  return node.innerHTML;
}

function escapeActivityAttribute(value) {
  return escapeActivityText(value).replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function isRecentlyFinishedScan(task) {
  const finishedAt = parseServerDateTime(task?.finished_at);
  if (!finishedAt) return false;
  const age = Date.now() - finishedAt.getTime();
  return age >= -60000 && age <= 120000;
}

function getScanActivityTaskInfo(task, isPending = false, isRecent = false) {
  const taskType = task?.type || task?.task_type || 'background';
  const kwargs = task?.kwargs || {};
  const libraryId = kwargs.library_id;
  const dbType = kwargs.db_type || state.currentLibraryType || 'general';
  const rawStage = String(task?.stage || '').trim();
  // 예전 서버 버전이 저장한 내부 enum은 사용자에게 그대로 노출하지 않는다.
  const stage = rawStage === 'book_scan' ? '도서 파일 처리 중' : rawStage;
  const names = {
    library_scan: '카테고리 스캔',
    metadata_auto_collect: '자동 메타데이터 수집',
    folder_watch: '폴더 감시 스캔',
    cover_scan: '표지 스캔',
    lazy_scan: '미디어 검색',
    batch_book_scan: '선택 도서 스캔',
    gdrive_copy: 'Drive 복사',
  };
  const batchCount = Array.isArray(kwargs.book_ids) ? kwargs.book_ids.length : 0;
  const isSingleBookScan = taskType === 'batch_book_scan' && batchCount === 1;
  const singleBookLabel = isRecent && isSingleBookScan && kwargs.book_title
    ? String(kwargs.book_title)
    : '도서 1권';
  const title = taskType === 'batch_book_scan'
    ? `${task?.library_name ? `${task.library_name} · ` : ''}${isSingleBookScan ? singleBookLabel : `선택 도서 ${batchCount}권`}`
    : task?.library_name
      || (taskType === 'lazy_scan' ? '전체 시스템' : libraryId != null ? `Library ${libraryId} (${dbType})` : '백그라운드 작업');
  const taskName = isSingleBookScan ? '도서 스캔' : (names[taskType] || '백그라운드 작업');
  const statusLabel = task?.status === 'failed' ? '실패' : task?.status === 'cancelled' ? '취소' : '완료';
  let detail = isRecent
    ? (stage || (statusLabel === '완료' ? '스캔 완료' : `스캔 ${statusLabel}`))
    : isPending ? (stage || `${taskName} 대기 중`) : stage || `${taskName} 진행 중`;
  if (taskType === 'lazy_scan' && !isRecent) {
    const target = String(kwargs.series_name || '').trim()
      || (Array.isArray(kwargs.book_ids) && kwargs.book_ids.length ? `선택 도서 ${kwargs.book_ids.length}권` : '');
    if (target && !detail.includes(target)) detail += ` · ${target}`;
  }
  return { title, detail };
}

function formatScanActivityElapsed(task) {
  let elapsedSeconds = null;
  if (task?.elapsed_seconds !== null && task?.elapsed_seconds !== undefined
      && Number.isFinite(Number(task.elapsed_seconds))) {
    elapsedSeconds = Math.max(0, Math.floor(Number(task.elapsed_seconds)));
  } else {
    const startedAt = task?.started_at || task?.enqueued_at;
    if (!startedAt) return '';
    const started = parseServerDateTime(startedAt);
    if (!started) return '';
    elapsedSeconds = Math.max(0, Math.floor((Date.now() - started.getTime()) / 1000));
  }
  if (elapsedSeconds < 60) return `${elapsedSeconds}초`;
  const minutes = Math.floor(elapsedSeconds / 60);
  if (minutes < 60) return `${minutes}분`;
  return `${Math.floor(minutes / 60)}시간 ${minutes % 60}분`;
}

function systemWarningItemHtml(warning) {
  const count = Number(warning?.fail_count || 0);
  const since = warning?.last_ok_at
    ? `마지막 성공 ${formatRelativeTime(warning.last_ok_at)}`
    : `첫 실패 ${formatRelativeTime(warning?.first_failed_at)}`;
  const detail = `${since} · 연속 ${count}회 실패 · ${warning?.message || ''}`;
  return `<div class="scan-activity-item is-failed is-system-warning" data-role="system-warning">
    <span class="scan-activity-item-icon"><i class="fa-solid fa-triangle-exclamation" aria-hidden="true"></i></span>
    <div class="scan-activity-item-copy">
      <div class="scan-activity-item-title">${escapeActivityText(warning?.label)} 실패 중</div>
      <div class="scan-activity-item-detail" title="${escapeActivityAttribute(detail)}">${escapeActivityText(detail)}</div>
    </div><span class="scan-activity-item-time">경고</span></div>`;
}

// Keep queue history intact; root outages have a dedicated problem card with a grace period.
function isRootUnavailableFailure(task) {
  return task?.status === 'failed' && String(task.stage || '').includes('[root_unreachable]');
}

function renderScanActivity(data) {
  latestSystemStatus = data;
  const button = document.getElementById('btn-scan-activity');
  const summary = document.getElementById('scan-activity-summary');
  const list = document.getElementById('scan-activity-list');
  if (!button || !summary || !list) return;

  const running = data?.raw_status?.running || null;
  const pending = Array.isArray(data?.raw_status?.pending) ? data.raw_status.pending : [];
  const recentBookScans = Array.isArray(data?.raw_status?.recent_book_scans)
    ? data.raw_status.recent_book_scans
    : [];
  const recentLibraryScans = Array.isArray(data?.raw_status?.recent_library_scans)
    ? data.raw_status.recent_library_scans.filter(task => !isRootUnavailableFailure(task))
    : [];
  const metadataActivities = Array.isArray(data?.raw_status?.metadata_activities)
    ? data.raw_status.metadata_activities
    : [];
  const isActive = Boolean(data?.success && data?.is_active);
  const systemWarnings = Array.isArray(data?.system_warnings) ? data.system_warnings : [];
  const problemCards = Array.isArray(data?.problem_cards) ? data.problem_cards : [];
  const warningCount = systemWarnings.length + problemCards.length;
  const hasWarning = warningCount > 0;
  initNotificationCards(list, { refresh: refreshSystemStatus });
  button.classList.toggle('is-active', isActive);
  button.classList.toggle('has-warning', hasWarning);
  document.querySelectorAll('[data-role="scan-activity-mirror"]').forEach(el => {
    el.classList.toggle('is-active', isActive);
    el.classList.toggle('has-warning', hasWarning);
  });

  const tasks = [];
  if (running) tasks.push({ task: running, pending: false });
  pending.forEach(task => tasks.push({ task, pending: true }));
  recentLibraryScans.forEach(task => tasks.push({ task, pending: false, recent: true }));
  recentBookScans.forEach(task => tasks.push({ task, pending: false, recent: true }));
  metadataActivities.forEach(task => tasks.push({
    task,
    pending: false,
    recent: task?.status !== 'running',
  }));
  if (tasks.length === 0 && isActive && Array.isArray(data?.tasks)) {
    data.tasks.forEach(detail => tasks.push({
      task: { type: 'background', library_name: '시스템 유지보수', stage: detail },
      pending: false,
    }));
  }
  // The queue status intentionally exposes only a short completion window.
  // Panel history is read separately; do not feed old history into list-refresh logic.
  const present = new Set(tasks.map(({task}) => activityIdentity(task)));
  activityDetails.history.forEach(task => {
    if (!present.has(activityIdentity(task))) {
      present.add(activityIdentity(task));
      tasks.push({task, pending:false, recent:true});
    }
  });
  tasks.sort((a,b) => Number(Boolean(a.recent)) - Number(Boolean(b.recent))
    || (a.recent && b.recent ? (parseServerDateTime(b.task.finished_at)?.getTime() || 0) - (parseServerDateTime(a.task.finished_at)?.getTime() || 0) : 0));
  const visible = tasks.filter(({task,recent}) => !recent || !dismissedActivity.has(activityIdentity(task)));
  currentActivityTasks = visible;
  const attention = visible.filter(({task,recent}) => recent && ['failed','cancelled'].includes(task.status));
  const jobs = visible.filter(item => !item.recent);
  const counts = { all: visible.length + warningCount, attention: attention.length + warningCount, jobs: jobs.length };
  const labels = { all:'전체', attention:'확인 필요', jobs:'작업' };
  document.querySelectorAll('[data-scan-tab]').forEach(el => {
    const tab = el.dataset.scanTab;
    el.textContent = `${labels[tab]} ${counts[tab]}`;
    el.setAttribute('aria-pressed', String(tab === activityTab));
  });
  const clear = document.getElementById('btn-clear-scan-activity');
  if (clear) clear.disabled = !visible.some(({task,recent}) => recent && task.status === 'completed');
  const indicator = document.getElementById('scan-activity-indicator');
  if (indicator) { indicator.textContent = counts.attention || jobs.length || ''; indicator.classList.toggle('has-count', Boolean(counts.attention || jobs.length)); }
  button.classList.toggle('has-warning', counts.attention > 0);
  renderUpcomingActivity();
  button.title = counts.all > 0 ? `스캔 활동 ${counts.all}건` : '스캔 활동';
  if (counts.attention) button.title += ` · 확인 필요 ${counts.attention}건`;
  document.querySelectorAll('[data-role="scan-activity-mirror"]').forEach(el=>el.classList.toggle('has-warning',counts.attention>0));
  const activeMetadataCount = metadataActivities.filter(task => task?.status === 'running').length;
  const recentMetadataCount = metadataActivities.filter(task => task?.status !== 'running').length;
  const failedMetadataCount = metadataActivities.filter(task => task?.status === 'failed').length;
  summary.textContent = running
    ? `실행 중 · 대기열 ${pending.length}건`
    : activeMetadataCount ? `자동 메타데이터 수집 ${activeMetadataCount}건`
    : pending.length ? `대기열 ${pending.length}건`
      : failedMetadataCount ? `자동 메타데이터 수집 실패 ${failedMetadataCount}건`
        : recentMetadataCount ? `자동 메타데이터 수집 완료 ${recentMetadataCount}건`
        : recentLibraryScans.length ? `최근 카테고리 스캔 ${recentLibraryScans.length}건`
          : recentBookScans.length ? `최근 도서 스캔 ${recentBookScans.length}건`
            : jobs.length ? '실행 중' : visible.length ? `최근 이력 ${visible.length}건` : '대기 중';
  if (counts.attention) summary.textContent += ` · 확인 필요 ${counts.attention}건`;
  const warningsHtml = activityTab === 'jobs' ? '' : systemWarnings.map(systemWarningItemHtml).join('') + problemCards.map(card => notificationItemHtml({
    id: card.group_key, kind: 'problem', tone: card.severity === 'action_required' ? 'error' : 'notice',
    source: card.source, title_key: card.title_key,
    raw_detail: `${card.db_type} · 카테고리 ${card.library_id ?? '-'} · ${card.open_count}건`,
    updated_at: card.last_seen_at, card, actions: card.actions,
  })).join('');
  let filtered = activityTab === 'jobs' ? jobs : activityTab === 'attention' ? attention : visible;
  const more = activityTab === 'all' && !activityHistoryExpanded && filtered.filter(item => item.recent).length > 3;
  if (more) { let recentCount=0; filtered=filtered.filter(item => !item.recent || ++recentCount<=3); }
  if (filtered.length === 0) {
    list.innerHTML = warningsHtml || `
      <div class="scan-activity-empty">
        <i class="fa-regular fa-circle-check" aria-hidden="true"></i>
        <span>${activityTab === 'attention' ? '확인이 필요한 항목이 없습니다.' : activityTab === 'jobs' ? '진행·대기 중인 작업이 없습니다.' : '표시할 스캔 활동이 없습니다.'}</span>
      </div>`;
    restoreCardExpansions(list);
    return;
  }

  list.innerHTML = warningsHtml + filtered.map(({ task, pending: isPending, recent: isRecent }) => {
    const info = getScanActivityTaskInfo(task, isPending, isRecent);
    const recentStatus = task?.status || 'completed';
    const itemStateClass = isPending ? ' is-pending'
      : isRecent ? ` is-${recentStatus}`
        : '';
    const iconClass = isPending
      ? 'fa-clock'
      : isRecent
        ? (recentStatus === 'completed' ? 'fa-circle-check' : 'fa-circle-exclamation')
        : 'fa-circle-notch fa-spin';
    const started = parseServerDateTime(task.started_at)?.getTime();
    const finished = parseServerDateTime(task.finished_at)?.getTime();
    const duration = Number.isFinite(started) && Number.isFinite(finished) && finished >= started
      ? formatScanActivityElapsed({elapsed_seconds:(finished-started)/1000}) : '';
    const elapsed = isRecent
      ? `${recentStatus === 'failed' ? '실패' : recentStatus === 'cancelled' ? '중단' : '완료'}${duration ? ` · ${duration}` : ''}`
      : isPending ? '' : formatScanActivityElapsed(task);
    const libId=task.kwargs?.library_id,dbType=task.kwargs?.db_type || 'general';
    const actions = libId != null ? `<div class="scan-activity-item-actions"><button type="button" data-scan-open="${escapeActivityAttribute(libId)}" data-db-type="${escapeActivityAttribute(dbType)}">카테고리 열기</button>${isRecent && recentStatus !== 'completed' && task.type === 'library_scan' && window.currentUser?.role === 'admin' ? `<button type="button" data-notify-action="rescan_library" data-library-id="${escapeActivityAttribute(libId)}" data-db-type="${escapeActivityAttribute(dbType)}">재스캔</button>` : ''}</div>` : '';
    return `
      <div class="scan-activity-item${itemStateClass}">
        <span class="scan-activity-item-icon">
          <i class="fa-solid ${iconClass}" aria-hidden="true"></i>
        </span>
        <div class="scan-activity-item-copy">
          <div class="scan-activity-item-title" title="${escapeActivityAttribute(info.title)}">${escapeActivityText(info.title)}</div>
          <div class="scan-activity-item-detail" title="${escapeActivityAttribute(info.detail)}">${escapeActivityText(info.detail)}</div>
          ${isRecent && task.finished_at ? `<div class="scan-activity-item-date">${escapeActivityText(formatRelativeTime(task.finished_at, {fallback:''}))}</div>` : ''}
          ${actions}
        </div>
        <span class="scan-activity-item-side"><span class="scan-activity-item-time">${escapeActivityText(elapsed)}</span>${isRecent ? `<button type="button" class="scan-activity-dismiss" data-scan-dismiss="${escapeActivityAttribute(activityIdentity(task))}" aria-label="이 활동 숨기기" title="표시만 숨깁니다. 서버 이력은 유지됩니다.">×</button>` : ''}</span>
      </div>`;
  }).join('') + (more ? '<button type="button" class="scan-activity-more" data-scan-history-more>최근 이력 더 보기</button>' : '');
  restoreCardExpansions(list);
}

function positionScanActivityPopover() {
  const button = document.getElementById('btn-scan-activity');
  const popover = document.getElementById('scan-activity-popover');
  if (!button || !popover || popover.hidden) return;
  const rect = button.getBoundingClientRect();
  const top = Math.min(Math.max(8, rect.bottom + 8), Math.max(8, innerHeight - 160));
  const width = Math.min(410, innerWidth - 16);
  Object.assign(popover.style, {
    position: 'fixed', width: `${width}px`,
    top: `${top}px`, bottom: 'auto', right: 'auto',
    left: `${Math.max(8, Math.min(rect.right - width, innerWidth - width - 8))}px`,
    maxHeight: `${Math.max(0, Math.min(620, innerHeight - top - 8))}px`, overflowY: 'hidden',
  });
}

function setScanActivityPopoverOpen(open) {
  const button = document.getElementById('btn-scan-activity');
  const popover = document.getElementById('scan-activity-popover');
  if (!button || !popover) return;
  popover.hidden = !open;
  button.setAttribute('aria-expanded', open ? 'true' : 'false');
  if (open && latestSystemStatus) renderScanActivity(latestSystemStatus);
  if (open) {
    positionScanActivityPopover();
    refreshSystemStatus();
    loadActivityDetails();
  }
}

function initScanActivityPopover() {
  const button = document.getElementById('btn-scan-activity');
  const closeButton = document.getElementById('btn-close-scan-activity');
  const popover = document.getElementById('scan-activity-popover');
  if (!button || !closeButton || !popover || button.dataset.bound === '1') return;
  button.dataset.bound = '1';
  try {
    const ids=JSON.parse(localStorage.getItem(activityStorageKey()) || '[]');
    if(Array.isArray(ids))dismissedActivity=new Set(ids.filter(id=>typeof id==='string').slice(-400));
  } catch { /* Ignore unavailable or corrupt browser storage. */ }
  // Sticky headers can establish a containing block for fixed descendants.
  document.body.appendChild(popover);
  window.addEventListener('resize', positionScanActivityPopover);
  button.addEventListener('click', event => {
    event.stopPropagation();
    setScanActivityPopoverOpen(popover.hidden);
  });
  closeButton.addEventListener('click', () => setScanActivityPopoverOpen(false));
  const footer=document.querySelector('.scan-activity-footer');
  if(footer)footer.hidden=window.currentUser?.role !== 'admin';
  popover.addEventListener('click', async event => {
    const tab=event.target.closest('[data-scan-tab]');
    if(tab){activityTab=tab.dataset.scanTab;if(latestSystemStatus)renderScanActivity(latestSystemStatus);}
    const dismiss=event.target.closest('[data-scan-dismiss]');
    if(dismiss)hideActivityItems([dismiss.dataset.scanDismiss]);
    if(event.target.closest('#btn-clear-scan-activity'))hideActivityItems(currentActivityTasks.filter(({task,recent})=>recent&&task.status==='completed').map(({task})=>activityIdentity(task)));
    if(event.target.closest('[data-scan-history-more]')){activityHistoryExpanded=true;if(latestSystemStatus)renderScanActivity(latestSystemStatus);}
    if(event.target.closest('[data-scan-upcoming-more]')){activityUpcomingExpanded=!activityUpcomingExpanded;renderUpcomingActivity();}
    const open=event.target.closest('[data-scan-open]');
    if(open){
      setScanActivityPopoverOpen(false);
      if(open.dataset.dbType!==state.currentLibraryType)await window.switchLibraryType?.(open.dataset.dbType);
      window.selectCategory?.(String(open.dataset.scanOpen));
    }
    if(event.target.closest('#btn-scan-activity-settings')){
      setScanActivityPopoverOpen(false);
      window.selectCategory?.('settings');
      document.querySelector('.settings-tab-btn[data-settings-tab="schedule"]')?.click();
    }
  });
  popover.addEventListener('click', event => event.stopPropagation());
  document.addEventListener('click', () => setScanActivityPopoverOpen(false));
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') setScanActivityPopoverOpen(false);
  });
}

function applyCategoryScanSpinnersState() {
  const headerSpinner = document.getElementById('header-category-scan-spinner');
  if (headerSpinner) {
    headerSpinner.style.display = lastIsHeaderScanning ? 'inline-block' : 'none';
  }

  document.querySelectorAll('li[data-role="sidebar-category-dynamic"]').forEach(li => {
    const libId = li.getAttribute('data-category-id') || li.getAttribute('data-id');
    const sp = li.querySelector('.category-scan-spinner');
    if (sp) {
      // 사이드바에는 항상 현재 세션 타입(state.currentLibraryType)의 카테고리만 렌더링되므로,
      // 그 타입 기준으로 복합키를 만들어야 다른 타입의 동일 id 스캔과 섞이지 않는다.
      const isScanning = libId && lastActiveLibIds.has(`${state.currentLibraryType}:${libId}`);
      sp.style.display = isScanning ? 'inline-block' : 'none';
    }
  });
}

function updateCategoryScanSpinners(data, scanRefresh = {}) {
  const now = Date.now();
  const currentActiveLibIds = new Set();
  let isGlobalOrCurrentLibScanning = false;

  if (data && data.success && data.is_active) {
    wasScanningPrevious = true;

    const checkTask = (t) => {
      if (!t) return;
      const taskType = t.type || t.task_type;
      const kwargs = t.kwargs || {};
      const libId = kwargs.library_id;
      // library_id는 물리 DB(db_type)마다 별도 시퀀스라, 타입 없이 숫자만 비교하면
      // 서로 다른 세션의 라이브러리가 우연히 같은 id를 가질 때 스캔 스피너가 엉뚱한
      // 카테고리 옆에도 뜨는 버그가 생긴다 - 반드시 "dbType:libId" 복합키로 구분한다.
      const taskDbType = kwargs.db_type || 'general';

      if (taskType === 'lazy_scan') {
        isGlobalOrCurrentLibScanning = true;
      } else if (libId !== undefined && libId !== null) {
        currentActiveLibIds.add(`${taskDbType}:${libId}`);
        if (taskDbType === state.currentLibraryType && String(state.currentLibraryId) === String(libId)) {
          isGlobalOrCurrentLibScanning = true;
        }
      } else {
        isGlobalOrCurrentLibScanning = true;
      }
    };

    if (data.raw_status) {
      if (data.raw_status.running) checkTask(data.raw_status.running);
      if (Array.isArray(data.raw_status.pending)) {
        data.raw_status.pending.forEach(checkTask);
      }
    }

    if (currentActiveLibIds.size === 0 && data.tasks && data.tasks.length > 0) {
      isGlobalOrCurrentLibScanning = true;
    }

    currentActiveLibIds.forEach(libId => {
      scanLatchTimerMap.set(libId, now);
    });
  } else {
    if (wasScanningPrevious) {
      wasScanningPrevious = false;
      // 스캔이 끝난 라이브러리의 상세 화면이 열려 있으면 그 상세도 함께 갱신한다
      // (아래에서 scanLatchTimerMap을 비우기 전의 활성 목록으로 판단해야 한다).
      const detailView = document.getElementById('book-detail-view');
      const detailLibraryKey = `${state.currentLibraryType}:${state.detailLibraryId}`;
      const shouldRefreshDetail = Boolean(
        !scanRefresh.detailRefreshed
        && detailView
        && detailView.style.display !== 'none'
        && state.detailSeriesName
        && state.detailBookIds?.length
        && (lastActiveLibIds.has(detailLibraryKey) || lastIsHeaderScanning)
      );
      scanLatchTimerMap.clear();
      console.log('[ScanSpinner] 🏁 백그라운드 스캔 완수. 리스트 자동 갱신');
      if (!scanRefresh.dashboardInvalidated && typeof window.invalidateDashboardData === 'function') {
        window.invalidateDashboardData();
      }
      if (state.currentLibraryId === 'home' && !scanRefresh.handledBatchScans) {
        if (typeof window.loadDashboardData === 'function') window.loadDashboardData({ force: true });
      } else if (state.currentLibraryId === 'history') {
        if (typeof window.loadReadingHistory === 'function') window.loadReadingHistory();
      } else if (state.currentLibraryId !== 'settings') {
        if (scanRefresh.listInvalidated) {
          // 같은 폴링에서 완료된 도서 스캔이 이미 이 목록을 무효화했다 - 이중 갱신하지 않는다.
        } else if (typeof window.invalidateBookListAfterScan === 'function') {
          window.invalidateBookListAfterScan();
        } else if (typeof window.loadBooksList === 'function') {
          window.loadBooksList(false);
        }
      }
      if (shouldRefreshDetail && typeof window.openBookDetail === 'function') {
        window.openBookDetail(
          null,
          state.detailSeriesName,
          state.detailLibraryId,
          state.detailRepresentativeBookId,
          state.detailDisplayTitle
        );
      }
    }
  }

  // 3초 유예(Latch) 타임 이내 항목 유지하여 태스크 전환 순간 미세 깜빡임 완벽 방지
  const effectiveActiveLibIds = new Set();
  scanLatchTimerMap.forEach((ts, libId) => {
    if (now - ts < 3000) {
      effectiveActiveLibIds.add(libId);
    } else {
      scanLatchTimerMap.delete(libId);
    }
  });

  lastActiveLibIds = effectiveActiveLibIds;
  lastIsHeaderScanning = isGlobalOrCurrentLibScanning || effectiveActiveLibIds.has(`${state.currentLibraryType}:${state.currentLibraryId}`);

  applyCategoryScanSpinnersState();
}

// 2초 폴링 사이에 끝나 is_active 전환을 못 본 빠른 도서 스캔(단일/시리즈 즉시 스캔)도
// 서버가 내려주는 recent_book_scans로 감지해서 현재 목록과 열려 있는 상세를 갱신한다.
function refreshDetailAfterBookScan(data) {
  const none = { listInvalidated: false, detailRefreshed: false };
  const recentScans = (Array.isArray(data?.raw_status?.recent_book_scans)
    ? data.raw_status.recent_book_scans
    : []).filter(task => task?.type === 'batch_book_scan');
  const currentIds = new Set(recentScans.map(task => String(task.id ?? task.key ?? '')));

  const isInitialStatus = seenRecentBatchScanIds === null;
  const newlyFinished = recentScans.filter(task =>
    ['completed', 'failed', 'cancelled'].includes(task?.status)
    && (isInitialStatus
      ? isRecentlyFinishedScan(task)
      : !seenRecentBatchScanIds.has(String(task.id ?? task.key ?? '')))
  );
  seenRecentBatchScanIds = currentIds;
  if (!newlyFinished.length) return none;

  const currentType = String(state.currentLibraryType || 'general');
  const currentLibraryId = String(state.currentLibraryId || '');
  const affectsList = newlyFinished.some(task => {
    const kwargs = task.kwargs || {};
    const taskLibraryId = kwargs.library_id;
    return String(kwargs.db_type || 'general') === currentType
      && (
        taskLibraryId == null
        || currentLibraryId === 'all'
        || currentLibraryId === 'favorite'
        || String(taskLibraryId) === currentLibraryId
      );
  });
  let listInvalidated = false;
  if (affectsList && typeof window.invalidateBookListAfterScan === 'function') {
    window.invalidateBookListAfterScan();
    listInvalidated = true;
  }

  const detailView = document.getElementById('book-detail-view');
  if (typeof window.openBookDetail !== 'function'
      || !detailView || detailView.style.display === 'none'
      || !state.detailBookIds?.length) {
    return { listInvalidated, detailRefreshed: false };
  }

  const detailBookIds = new Set(state.detailBookIds.map(id => String(id)));
  const affectsDetail = newlyFinished.some(task => {
    const kwargs = task.kwargs || {};
    if (String(kwargs.db_type || 'general') !== currentType) return false;
    const scannedIds = Array.isArray(kwargs.book_ids) ? kwargs.book_ids : [];
    return scannedIds.some(id => detailBookIds.has(String(id)));
  });
  if (!affectsDetail) return { listInvalidated, detailRefreshed: false };

  console.log('[ScanDetailRefresh] 도서 스캔 완료로 열린 상세 페이지를 갱신합니다.');
  window.openBookDetail(
    null,
    state.detailSeriesName,
    state.detailLibraryId,
    state.detailRepresentativeBookId,
    state.detailDisplayTitle
  );
  return { listInvalidated, detailRefreshed: true };
}

// 카테고리 스캔은 파일 수가 적으면 2초 상태 폴링 사이에 끝날 수 있다.
// 최근 완료 이력을 이용해 running -> idle 전환을 놓쳐도 현재 목록/상세/홈을 갱신한다.
function refreshAfterLibraryScan(data) {
  const none = {
    listInvalidated: false,
    detailRefreshed: false,
    dashboardInvalidated: false,
  };
  const recentScans = (Array.isArray(data?.raw_status?.recent_library_scans)
    ? data.raw_status.recent_library_scans
    : []).filter(task => ['library_scan', 'cover_scan'].includes(task?.type));
  const currentIds = new Set(recentScans.map(task => String(task.id ?? task.key ?? '')));
  const isInitialStatus = seenRecentLibraryScanIds === null;
  const newlyFinished = recentScans.filter(task =>
    ['completed', 'failed', 'cancelled'].includes(task?.status)
    && (isInitialStatus
      ? isRecentlyFinishedScan(task)
      : !seenRecentLibraryScanIds.has(String(task.id ?? task.key ?? '')))
  );
  seenRecentLibraryScanIds = currentIds;
  if (!newlyFinished.length) return none;

  const currentType = String(state.currentLibraryType || 'general');
  const currentLibraryId = String(state.currentLibraryId || '');
  const affectsCurrentView = newlyFinished.some(task => {
    const kwargs = task.kwargs || {};
    const taskLibraryId = kwargs.library_id;
    return String(kwargs.db_type || 'general') === currentType
      && (currentLibraryId === 'home'
        || currentLibraryId === 'history'
        || taskLibraryId == null
        || currentLibraryId === 'all'
        || currentLibraryId === 'favorite'
        || String(taskLibraryId) === currentLibraryId);
  });
  if (!affectsCurrentView) return none;

  if (currentLibraryId === 'home') {
    window.invalidateDashboardData?.();
    window.loadDashboardData?.({ force: true });
    return { ...none, dashboardInvalidated: true };
  }
  if (currentLibraryId === 'history') {
    window.loadReadingHistory?.();
    return { ...none, listInvalidated: true };
  }
  if (!['settings', 'plugins'].includes(currentLibraryId)
      && !currentLibraryId.startsWith('plugin_')) {
    window.invalidateBookListAfterScan?.();
  }

  const detailView = document.getElementById('book-detail-view');
  const detailLibraryId = String(state.detailLibraryId ?? '');
  const affectsDetail = Boolean(
    detailView
    && detailView.style.display !== 'none'
    && state.detailSeriesName
    && state.detailBookIds?.length
    && newlyFinished.some(task => {
      const kwargs = task.kwargs || {};
      return String(kwargs.db_type || 'general') === currentType
        && kwargs.library_id != null
        && String(kwargs.library_id) === detailLibraryId;
    })
  );
  if (affectsDetail && typeof window.openBookDetail === 'function') {
    window.openBookDetail(
      null,
      state.detailSeriesName,
      state.detailLibraryId,
      state.detailRepresentativeBookId,
      state.detailDisplayTitle,
    );
    return { listInvalidated: true, detailRefreshed: true, dashboardInvalidated: false };
  }
  return { ...none, listInvalidated: true };
}

window.addEventListener('library:categories-rendered', () => {
  applyCategoryScanSpinnersState();
});

export function startSystemStatusPolling(type = state.currentLibraryType || 'general', { probe = false } = {}) {
  if (!probe) pollingProbe = false;
  pollingScanType = String(type || state.currentLibraryType || 'general');
  pollingStartedAt = Date.now();
  observedActiveScan = false;
  consecutiveIdlePolls = 0;
  if (statusIntervalId) return refreshStatusPoll?.();
  pollingProbe = probe;
  const generation = ++statusPollGeneration;
  let inFlight = null;
  let queuedRefresh = null;

  const poll = () => {
    if (generation !== statusPollGeneration) return Promise.resolve();
    if (inFlight) return inFlight;
    inFlight = (async () => {
    try {
      const res = await fetch(`/api/system/status?type=${encodeURIComponent(pollingScanType || 'general')}`, { cache: 'no-store' });
      const body = await res.text();
      if (generation !== statusPollGeneration) return;
      let data;
      try {
        data = JSON.parse(body);
      } catch {
        // Reverse proxies can return an HTML 502/504 page while the app is
        // busy. Keep the last valid scan state and avoid a console error on
        // every two-second poll.
        const signature = `${res.status}:${body.slice(0, 80)}`;
        const now = Date.now();
        if (signature !== lastStatusErrorSignature || now - lastStatusErrorAt > 10000) {
          console.warn('[ScanSpinner] 상태 조회 응답이 JSON이 아닙니다.', res.status);
          lastStatusErrorSignature = signature;
          lastStatusErrorAt = now;
        }
        return;
      }
      if (!res.ok || !data?.success) return;
      lastStatusErrorSignature = '';
      const scanRefresh = refreshDetailAfterBookScan(data);
      const libraryRefresh = refreshAfterLibraryScan(data);
      updateCategoryScanSpinners(data, {
        ...scanRefresh,
        listInvalidated: scanRefresh.listInvalidated || libraryRefresh.listInvalidated,
        detailRefreshed: scanRefresh.detailRefreshed || libraryRefresh.detailRefreshed,
        dashboardInvalidated: scanRefresh.dashboardInvalidated || libraryRefresh.dashboardInvalidated,
      });
      renderScanActivity(data);

      // Initial load/open is a one-shot check when idle; queued requests retain
      // their visibility grace period. Active work always continues polling.
      if (pollingProbe && !data.is_active) {
        stopSystemStatusPolling();
        return;
      }

      const pollingState = evaluateScanPollingState({
        isActive: Boolean(data.is_active),
        observedActive: observedActiveScan,
        consecutiveIdlePolls,
        pollingStartedAt,
        now: Date.now(),
        graceMs: QUEUE_VISIBILITY_GRACE_MS,
      });
      observedActiveScan = pollingState.observedActive;
      consecutiveIdlePolls = pollingState.consecutiveIdlePolls;
      if (pollingState.shouldStop) stopSystemStatusPolling();
    } catch (err) {
      const now = Date.now();
      if (now - lastStatusErrorAt > 10000) {
        console.warn('[ScanSpinner] 상태 조회 실패:', err);
        lastStatusErrorAt = now;
      }
    }
    })().finally(() => { inFlight = null; });
    return inFlight;
  };

  refreshStatusPoll = () => {
    if (queuedRefresh) return queuedRefresh;
    if (!inFlight) return poll();
    // Timer ticks join the pending request; explicit refreshes share one
    // follow-up so a newly queued scan cannot be missed by an older response.
    queuedRefresh = inFlight.then(() => poll()).finally(() => { queuedRefresh = null; });
    return queuedRefresh;
  };
  // Reload/open checks resume existing work without enqueueing a scan.
  statusIntervalId = setInterval(poll, STATUS_POLL_INTERVAL_MS);
  return poll();
}

window.addEventListener('bookoasis:scan-queued', event => {
  startSystemStatusPolling(event?.detail?.type || state.currentLibraryType || 'general');
});
window.addEventListener('bookoasis:system-health-changed', refreshSystemStatus);

// Recover server-owned work after reload; idle pages do not keep polling.
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', () => {
    initScanActivityPopover();
    refreshSystemStatus();
  });
} else {
  initScanActivityPopover();
  refreshSystemStatus();
}
