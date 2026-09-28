export const ViewerDisplayMode = Object.freeze({
  ONE: 'one',
  ONE_TWO: 'one-two',
  TWO_ONE: 'two-one',
  SCROLL: 'scroll',
});

const VALID_MODES = new Set(Object.values(ViewerDisplayMode));

export function normalizeViewerDisplayMode(mode) {
  if (mode === 'two-three') return ViewerDisplayMode.TWO_ONE;
  return VALID_MODES.has(mode) ? mode : ViewerDisplayMode.TWO_ONE;
}

export function getViewerDisplayMode(storage = localStorage) {
  const saved = storage.getItem('viewer_display_mode');
  if (saved === 'two-three') return ViewerDisplayMode.TWO_ONE;
  if (VALID_MODES.has(saved)) return saved;

  if ((storage.getItem('viewer_scroll_mode') || 'page') === 'scroll') {
    return ViewerDisplayMode.SCROLL;
  }
  if ((storage.getItem('comic_page_step') || '1') !== '2') {
    return ViewerDisplayMode.ONE;
  }
  return storage.getItem('comic_reading_direction') === 'rtl'
    ? ViewerDisplayMode.TWO_ONE
    : ViewerDisplayMode.ONE_TWO;
}

export function saveViewerDisplayMode(mode, storage = localStorage) {
  const normalized = normalizeViewerDisplayMode(mode);
  storage.setItem('viewer_display_mode', normalized);
  if (normalized === ViewerDisplayMode.SCROLL) return normalized;

  storage.setItem('comic_page_step', normalized === ViewerDisplayMode.ONE ? '1' : '2');
  // 두 쪽 보기에서는 표지를 항상 단독으로 두고, 두 모드의 차이는 읽기 방향뿐이다.
  storage.setItem('viewer_spread_cover_alone', '1');
  if (normalized === ViewerDisplayMode.ONE_TWO) storage.setItem('comic_reading_direction', 'ltr');
  if (normalized === ViewerDisplayMode.TWO_ONE) storage.setItem('comic_reading_direction', 'rtl');
  return normalized;
}

export function syncViewerDisplayModeUI(mode = getViewerDisplayMode()) {
  const normalized = normalizeViewerDisplayMode(mode);
  document.querySelectorAll('[data-viewer-display-mode]').forEach((button) => {
    const active = button.dataset.viewerDisplayMode === normalized;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
  const modal = document.getElementById('media-viewer-modal');
  if (modal) modal.dataset.displayMode = normalized;
  return normalized;
}

let chromeHideTimer = null;
let chromeLockedOpen = false;

function hideViewerChrome() {
  chromeLockedOpen = false;
  document.dispatchEvent(new CustomEvent('viewer-chrome-will-hide'));
  document.dispatchEvent(new CustomEvent('viewer-side-panel-state-changed', {
    detail: { panel: null },
  }));
  setViewerChromeVisible(false, { autoHide: false });
}

export function setViewerChromeVisible(visible, { autoHide = false } = {}) {
  const modal = document.getElementById('media-viewer-modal');
  if (!modal) return;
  modal.classList.toggle('viewer-chrome-hidden', !visible);
  clearTimeout(chromeHideTimer);
  if (visible && autoHide && !chromeLockedOpen) {
    chromeHideTimer = window.setTimeout(() => {
      if (!chromeLockedOpen) modal.classList.add('viewer-chrome-hidden');
    }, 2400);
  }
}

export function toggleViewerChrome() {
  const modal = document.getElementById('media-viewer-modal');
  if (!modal) return;
  const shouldShow = modal.classList.contains('viewer-chrome-hidden');
  if (!shouldShow) {
    hideViewerChrome();
    return;
  }
  setViewerChromeVisible(shouldShow, { autoHide: false });
}

export function resetViewerChrome() {
  chromeLockedOpen = false;
  // RIDI식 도구 모음은 시간이 지나서 자동으로 사라지지 않는다.
  // 사용자가 본문 중앙을 눌렀을 때만 명시적으로 닫는다.
  setViewerChromeVisible(true, { autoHide: false });
}

export function initViewerChrome() {
  const modal = document.getElementById('media-viewer-modal');
  if (!modal || modal.dataset.ridiChromeBound === '1') return;
  modal.dataset.ridiChromeBound = '1';

  document.addEventListener('viewer-overlay-visibility-changed', (event) => {
    chromeLockedOpen = Boolean(event.detail?.isOpen);
    setViewerChromeVisible(true, { autoHide: false });
  });
  document.addEventListener('viewer-request-chrome-hide', hideViewerChrome);
}
