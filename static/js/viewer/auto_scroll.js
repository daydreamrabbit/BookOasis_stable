// Timed native scrolling: existing scroll listeners retain progress/lazy loading.
import { state } from '../state.js';
import { nextPage } from '../reader_loader.js';

const modal = document.getElementById('media-viewer-modal');
const button = document.getElementById('viewer-auto-scroll-toggle');
const speedInput = document.getElementById('viewer-auto-scroll-speed');
const output = document.getElementById('viewer-auto-scroll-value');
const status = document.getElementById('viewer-auto-scroll-status');
const normalizeSpeed = value => Math.max(10, Math.min(200, Number(value) || 40));
let speed = 40;
try { speed = normalizeSpeed(localStorage.getItem('viewer_auto_scroll_speed')); } catch {}
let running = false;
let frame = 0;
let lastTime = null;
let position = 0;
let bookId = null;
let scrollTarget = null;
let activeMode = 'scroll';
let pageElapsed = 0;
let lastTurnPosition = null;
let interval = 5;
let displayMode = '';
try { interval = Math.max(2, Math.min(120, Number(localStorage.getItem('viewer_auto_page_interval')) || 5)); } catch {}
const pageMode = () => localStorage.getItem('viewer_scroll_mode') !== 'scroll';

function available() {
  return modal && getComputedStyle(modal).display !== 'none'
    && ['zip','cbz','imgdir','txt','epub','pdf'].includes(String(state.currentViewerFormat || '').toLowerCase());
}

function getTarget() {
  if (!modal || getComputedStyle(modal).display === 'none'
      || localStorage.getItem('viewer_scroll_mode') !== 'scroll') return null;
  const format = String(state.currentViewerFormat || '').toLowerCase();
  const selector = ['zip', 'cbz', 'imgdir'].includes(format) ? '.comic-image-wrapper'
    : ['txt', 'epub'].includes(format) ? '#txt-scroll-wrapper'
    : format === 'pdf' ? '#pdf-render-area' : null;
  const target = selector && modal.querySelector(selector);
  return target && target.getClientRects().length ? target : null;
}

function syncUI(message) {
  const enabled = pageMode() ? available() : !!getTarget();
  button.closest('.viewer-auto-scroll-settings').hidden = !enabled;
  button.disabled = !enabled;
  document.getElementById('viewer-auto-move-title').textContent = pageMode() ? '자동 페이지 넘김' : '자동 스크롤';
  document.getElementById('viewer-auto-move-label').textContent = pageMode() ? '넘김 간격' : '이동 속도';
  speedInput.min = pageMode() ? '2' : '10';
  speedInput.max = pageMode() ? '120' : '200';
  speedInput.step = pageMode() ? '1' : '10';
  speedInput.value = String(pageMode() ? interval : speed);
  button.textContent = running ? '일시정지' : '시작';
  button.setAttribute('aria-pressed', String(running));
  output.textContent = pageMode() ? `${interval}초` : `${speed} px/초`;
  if (message) status.textContent = message;
  else status.textContent = running ? '자동 이동 중 · 본문을 터치하거나 휠을 움직이면 정지합니다.' : '원하는 간격·속도를 선택한 뒤 시작하세요.';
}

function stop(message) {
  running = false;
  cancelAnimationFrame(frame);
  frame = 0;
  lastTime = null;
  scrollTarget = null;
  syncUI(message);
}

function tick(time) {
  if (!running) return;
  const target = getTarget();
  if (document.hidden || !available() || (modal.dataset.displayMode || '') !== displayMode || (pageMode() ? 'page' : 'scroll') !== activeMode
      || (!pageMode() && (!target || target !== scrollTarget)) || state.activeBookId !== bookId) {
    stop(); return;
  }
  const elapsed = lastTime === null ? 0 : Math.min(100, Math.max(0, time - lastTime));
  lastTime = time;
  if (pageMode()) {
    const overlay = document.getElementById('viewer-common-overlay');
    const pair = modal.querySelector('.comic-page-pair');
    const busy = (overlay && getComputedStyle(overlay).display !== 'none')
      || (pair && pair.style.visibility === 'hidden');
    if (busy) pageElapsed = 0;
    else pageElapsed += elapsed;
    if (pageElapsed >= interval * 1000) {
      pageElapsed = 0;
      const slider = document.getElementById('viewer-page-slider');
      const positionKey = slider ? `${slider.value}/${slider.max}` : null;
      const lastImage = pair && [...pair.querySelectorAll('img[data-index]')]
        .some(img => Number(img.dataset.index) + 1 >= Number(slider?.max));
      const atEnd = slider && Number(slider.max) > 0 && (Number(slider.value) >= Number(slider.max)
        || (['zip','cbz','imgdir'].includes(state.currentViewerFormat) && lastImage));
      if (atEnd || (positionKey && positionKey === lastTurnPosition)) {
        stop('마지막 페이지이거나 이동할 수 없어 자동 넘김을 정지했습니다.'); return;
      }
      lastTurnPosition = positionKey;
      try { nextPage(); } catch { stop('페이지 이동 중 오류가 발생해 정지했습니다.'); return; }
    }
    frame = requestAnimationFrame(tick);
    return;
  }
  const max = Math.max(0, target.scrollHeight - target.clientHeight);
  if (max <= 0 || target.scrollTop >= max - 1) {
    stop('맨 아래에 도착해 자동 스크롤을 정지했습니다.'); return;
  }
  // Keep fractional movement across frames, but respect layout/lazy image shifts.
  if (Math.abs(target.scrollTop - position) > 2) position = target.scrollTop;
  position = Math.min(max, position + speed * elapsed / 1000);
  target.scrollTo({top: position, behavior: 'instant'});
  frame = requestAnimationFrame(tick);
}

if (modal && button && speedInput && output && status) {
  speedInput.value = String(speed);
  button.addEventListener('click', () => {
    if (running) { stop('자동 스크롤을 일시정지했습니다.'); return; }
    scrollTarget = getTarget();
    if (!(pageMode() ? available() : scrollTarget) || document.hidden) return;
    running = true;
    bookId = state.activeBookId;
    activeMode = pageMode() ? 'page' : 'scroll';
    displayMode = modal.dataset.displayMode || '';
    position = scrollTarget?.scrollTop || 0;
    pageElapsed = 0;
    lastTurnPosition = null;
    lastTime = null;
    syncUI();
    frame = requestAnimationFrame(tick);
  });
  speedInput.addEventListener('input', () => {
    if (pageMode()) {
      interval = Math.max(2, Math.min(120, Number(speedInput.value) || 5));
      pageElapsed = 0;
      try { localStorage.setItem('viewer_auto_page_interval', String(interval)); } catch {}
    } else {
      speed = normalizeSpeed(speedInput.value);
      try { localStorage.setItem('viewer_auto_scroll_speed', String(speed)); } catch {}
    }
    syncUI();
  });
  const manualInput = event => {
    if (!running || event.target.closest?.('.ridi-view-settings')) return;
    stop('직접 조작하여 자동 스크롤을 일시정지했습니다.');
  };
  modal.addEventListener('wheel', manualInput, {passive: true, capture: true});
  modal.addEventListener('pointerdown', manualInput, {passive: true, capture: true});
  document.addEventListener('keydown', event => {
    if (running && ['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'PageUp', 'PageDown', 'Home', 'End', 'Escape', ' '].includes(event.key)) manualInput(event);
  }, true);
  document.addEventListener('viewer-closed', () => stop());
  document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
  window.addEventListener('pagehide', () => stop());
  const observer = new MutationObserver(() => {
    if (running && (!available() || (pageMode() ? 'page' : 'scroll') !== activeMode || state.activeBookId !== bookId)) stop();
    else syncUI();
  });
  observer.observe(modal, {attributes: true, attributeFilter: ['style', 'data-display-mode', 'data-viewer-format']});
  const menu = document.getElementById('comic-overlay-menu');
  if (menu) observer.observe(menu, {attributes: true, attributeFilter: ['style']});
  syncUI();
}
