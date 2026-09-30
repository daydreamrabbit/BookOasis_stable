import { state } from './state.js';
import { createRevisionTracker } from './library_revision_tracker.js';

const tracker = createRevisionTracker();
let busy = false;
let lastInputAt = 0;
let deferred = null;
let events = null;
let reconnect = null;
document.addEventListener('input', () => { lastInputAt = Date.now(); }, true);

export async function checkLibraryChanges() {
  if (busy || document.hidden) return;
  busy = true;
  try {
    const type = state.currentLibraryType || 'general';
    if (!tracker.has(type)) return;
    const revision = tracker.revision(type);
    const viewer = document.getElementById('media-viewer-modal');
    if (viewer && getComputedStyle(viewer).display !== 'none') return;
    // Do not interrupt typing, text selection, or an open modal dialog.
    if (Date.now() - lastInputAt < 2000 || document.querySelector('dialog[open]')) return;
    const category = String(state.currentLibraryId || '');
    if (['settings', 'plugins'].includes(category) || category.startsWith('plugin_')) return;
    if (typeof window.invalidateBookListAfterScan !== 'function') return;
    const listRefresh = window.invalidateBookListAfterScan();
    window.invalidateDashboardData?.();
    if (category === 'home') {
      await window.loadDashboardData?.({ force: true });
    } else if (category === 'history') {
      await window.loadReadingHistory?.();
    } else {
      const detail = document.getElementById('book-detail-view');
      if (detail && getComputedStyle(detail).display !== 'none' && state.detailSeriesName) {
        await window.openBookDetail?.(null, state.detailSeriesName, state.detailLibraryId,
          state.detailRepresentativeBookId, state.detailDisplayTitle);
      } else if (await listRefresh === false) {
        return; // A busy/failed list must not consume the revision notification.
      }
    }
    if (typeof window.refreshLibraryCounts !== 'function'
        || await window.refreshLibraryCounts(type) === false) return;
    tracker.acknowledge(type, revision);
  } catch (error) {
    // Keep pending changes and retry; never reload the page or steal input focus.
    console.debug('[LibraryRefresh] 변경 확인 재시도 대기', error);
  } finally {
    busy = false;
    clearTimeout(deferred);
    // Retry only a known pending change, locally; never poll the revision API.
    if (!document.hidden && tracker.has(state.currentLibraryType || 'general')) {
      deferred = setTimeout(checkLibraryChanges, 3000);
    }
  }
}

function connectLibraryEvents() {
  if (document.hidden || events) return;
  events = new EventSource('/api/system/library-events');
  events.addEventListener('snapshot', event => {
    tracker.observe(JSON.parse(event.data));
    checkLibraryChanges();
    window.dispatchEvent(new Event('bookoasis:system-health-changed'));
  });
  events.addEventListener('system-health', () => {
    window.dispatchEvent(new Event('bookoasis:system-health-changed'));
  });
  events.addEventListener('changed', event => {
    const change = JSON.parse(event.data);
    tracker.observe({ [change.type]: change.revision });
    checkLibraryChanges();
  });
  events.onerror = () => {
    events?.close(); events = null;
    clearTimeout(reconnect);
    reconnect = setTimeout(connectLibraryEvents, 30000);
  };
}
document.addEventListener('visibilitychange', () => {
  clearTimeout(reconnect);
  if (document.hidden) { events?.close(); events = null; clearTimeout(deferred); }
  else { connectLibraryEvents(); checkLibraryChanges(); }
});
window.addEventListener('focus', checkLibraryChanges);
window.addEventListener('library:categories-rendered', checkLibraryChanges);
connectLibraryEvents();
