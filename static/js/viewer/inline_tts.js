import { state } from '../state.js';
import { getActiveViewerInstance } from './lifecycle_controller.js?rev=20260927-tts-session-v8';
import { reportReadNow, getCurrentReadPosition } from './tts_sync.js?rev=20260927-tts-session-v8';
import {
  getTxtPageAdvanceWidth,
  getTxtPageMaxScroll,
  getTxtPageScrollLeft,
  setTxtPageScrollLeft,
} from './txt_page_utils.js?rev=20260922-reader-session-v45';

const HOST_ID = 'viewer-tts-host';
let host = null;
let frame = null;
let settingsRequested = false;
let positionSequence = 0;
let activeHighlight = null;
let playerGeneration = 0;
let playerOpening = false;
let lastTtsViewport = '';
let themeObserver = null;
let settingsPanel = null;
let playerPaused = true;
let backgroundPosition = null;
function syncReaderProgress() {
  const slider = document.getElementById('viewer-page-slider');
  if (!slider || !frame) return;
  postToPlayer({ type: 'reader-progress', min: slider.min, max: slider.max,
    value: slider.value, disabled: slider.disabled,
    label: document.getElementById('seekbar-start-label')?.textContent || '',
    percent: parseFloat(slider.style.getPropertyValue('--seek-progress')) || 0 });
}
function showSettingsPanel(open) {
  if (open && !settingsPanel) {
    const sheet = frame?.contentDocument?.getElementById('settingsSheet');
    if (!sheet) return;
    settingsPanel = document.createElement('div');
    settingsPanel.id = 'viewer-tts-settings-panel';
    settingsPanel.className = 'ridi-view-settings';
    const shadow = settingsPanel.attachShadow({ mode: 'open' });
    for (const style of frame.contentDocument.querySelectorAll('style')) shadow.append(style.cloneNode(true));
    const style = document.createElement('style');
    style.textContent = ':host{display:block;font:14px system-ui;color:var(--text)}#settingsSheet{position:relative;inset:auto;max-height:none;padding:0;border-radius:0;box-shadow:none;background:var(--surface)}.grabber,.tts-display-options,#devBtn{display:none!important}.field{padding:14px 16px;margin:0;border-bottom:1px solid var(--line)}';
    shadow.append(style, sheet);
    document.getElementById('media-viewer-modal')?.append(settingsPanel);
  }
  if (settingsPanel) settingsPanel.hidden = !open;
  syncPlayerTheme();
}
function viewportKey(position) { return position ? `${position.chapter_idx}:${position.anchor}` : ''; }
function syncPlayerTheme() {
  const modal = document.getElementById('media-viewer-modal');
  const root = frame?.contentDocument?.documentElement;
  if (!modal || !root) return;
  const style = getComputedStyle(modal);
  for (const [target, source] of Object.entries({ '--bg':'--viewer-theme-bg', '--surface':'--viewer-panel-bg',
    '--surface-2':'--viewer-panel-soft', '--text':'--viewer-theme-text', '--strong':'--viewer-theme-text',
    '--line':'--viewer-panel-border', '--muted':'--viewer-panel-muted' })) {
    const color = style.getPropertyValue(source).trim();
    if (color) root.style.setProperty(target, color);
    if (color && settingsPanel) settingsPanel.style.setProperty(target, color);
  }
  root.style.colorScheme = ['dark','black','navy'].includes(modal.dataset.viewerTheme) ? 'dark' : 'light';
}

function postToPlayer(message) {
  if (!frame?.contentWindow) return false;
  frame.contentWindow.postMessage({ source: 'bookoasis-viewer', ...message }, window.location.origin);
  return true;
}

function clearHighlight() {
  try { window.CSS?.highlights?.delete('bookoasis-tts-current'); } catch (_) { /* CSS Highlights 미지원 */ }
  activeHighlight = null;
}

function normalizedTextMap(root) {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const chars = [];
  const points = [];
  let node;
  let previousWasSpace = true;
  while ((node = walker.nextNode())) {
    const value = node.nodeValue || '';
    for (let offset = 0; offset < value.length; offset += 1) {
      const char = value[offset];
      if (/[\s\u00a0\u3000]/u.test(char)) {
        if (!previousWasSpace) {
          chars.push(' ');
          points.push({ node, offset });
        }
        previousWasSpace = true;
      } else {
        chars.push(char);
        points.push({ node, offset });
        previousWasSpace = false;
      }
    }
  }
  if (chars.at(-1) === ' ') { chars.pop(); points.pop(); }
  return { text: chars.join(''), points };
}

function findTtsRange(root, spokenText, approximateOffset) {
  const needle = String(spokenText || '').replace(/[\s\u00a0\u3000]+/gu, ' ').trim();
  if (!root || !needle) return null;
  const mapped = normalizedTextMap(root);
  let searchFrom = 0;
  let best = -1;
  let bestDistance = Infinity;
  while (searchFrom < mapped.text.length) {
    const index = mapped.text.indexOf(needle, searchFrom);
    if (index < 0) break;
    const distance = Number.isFinite(Number(approximateOffset)) ? Math.abs(index - Number(approximateOffset)) : index;
    if (distance < bestDistance) { best = index; bestDistance = distance; }
    searchFrom = index + 1;
  }
  if (best < 0 || !mapped.points[best] || !mapped.points[best + needle.length - 1]) return null;
  const start = mapped.points[best];
  const end = mapped.points[best + needle.length - 1];
  const range = document.createRange();
  range.setStart(start.node, start.offset);
  range.setEnd(end.node, end.offset + 1);
  return range;
}

function showRangeInReader(range) {
  const wrapper = document.getElementById('txt-scroll-wrapper');
  if (!wrapper) return;
  const rect = Array.from(range.getClientRects()).find(rect => rect.width > 0 && rect.height > 0);
  if (!rect || (!rect.width && !rect.height)) return;
  const wrapperRect = wrapper.getBoundingClientRect();
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (scrollMode === 'scroll') {
    if (rect.top < wrapperRect.top || rect.bottom > wrapperRect.bottom) {
      wrapper.scrollTo({
        top: Math.max(0, wrapper.scrollTop + rect.top - wrapperRect.top - wrapper.clientHeight * 0.32),
        behavior: 'auto',
      });
    }
    return isRangeVisible(range, wrapper);
  }
  const advance = getTxtPageAdvanceWidth(wrapper);
  if (!(advance > 0)) return;
  const rtl = document.getElementById('media-viewer-modal')?.dataset.displayMode === 'two-one';
  const pageDelta = rtl ? wrapperRect.right - rect.right : rect.left - wrapperRect.left;
  const logical = Math.max(0, getTxtPageScrollLeft(wrapper) + pageDelta);
  const target = Math.floor((logical + 1) / advance) * advance;
  if (Math.abs(target - getTxtPageScrollLeft(wrapper)) > 1) {
    setTxtPageScrollLeft(wrapper, Math.min(getTxtPageMaxScroll(wrapper), target));
  }
  return isRangeVisible(range, wrapper);
}

function isRangeVisible(range, wrapper) {
  const view = wrapper.getBoundingClientRect();
  const first = Array.from(range.getClientRects()).find(rect => rect.width > 0 && rect.height > 0);
  return !!first && first.right > view.left && first.left < view.right
    && first.bottom > view.top && first.top < view.bottom;
}

async function applyTtsPosition(message) {
  const sequence = ++positionSequence;
  const generation = playerGeneration;
  const viewer = getActiveViewerInstance();
  const location = await viewer?.seekToTtsPosition?.({ ...message,
    isCurrent: () => generation === playerGeneration && sequence === positionSequence && !!host,
  });
  if (sequence !== positionSequence || !location) return;

  const content = document.getElementById('txt-content-area');
  const root = content?.querySelector(`[data-idx="${Number(location.chunkIdx)}"]`)
    || (message.format === 'epub' && content?.querySelector('.epub-chunk'))
    || content;
  if (!root) return;
  const range = findTtsRange(root, message.text, location.offset);
  if (!range) return;

  activeHighlight = range;
  try {
    if (window.CSS?.highlights && typeof window.Highlight === 'function') {
      window.CSS.highlights.set('bookoasis-tts-current', new window.Highlight(range));
    }
  } catch (_) { /* 구형 브라우저에서는 위치 이동만 유지 */ }
  let visible = false;
  for (let attempt = 0; attempt < 3; attempt++) {
    if (sequence !== positionSequence || generation !== playerGeneration || !range.startContainer.isConnected) return false;
    visible = showRangeInReader(range);
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (visible && isRangeVisible(range, document.getElementById('txt-scroll-wrapper'))) break;
    visible = false;
  }
  if (!visible || sequence !== positionSequence || generation !== playerGeneration) return false;
  lastTtsViewport = viewportKey(getCurrentReadPosition());
  return true;
}

function onPlayerMessage(event) {
  if (!frame || event.source !== frame.contentWindow || event.origin !== window.location.origin) return;
  const message = event.data;
  if (!message || message.source !== 'bookoasis-tts') return;
  if (message.type === 'prepare-position') {
    backgroundPosition = message;
    if (document.hidden) {
      postToPlayer({ type: 'position-ready', requestId: message.requestId, ready: true });
      return;
    }
    const source = event.source;
    applyTtsPosition(message).then(applied => {
      if (frame?.contentWindow === source) postToPlayer({ type: 'position-ready', requestId: message.requestId, ready: !!applied });
    }).catch(() => {
      if (frame?.contentWindow === source) postToPlayer({ type: 'position-ready', requestId: message.requestId, ready: false });
    });
    return;
  }
  if (message.type === 'toast') { window.showToast?.(message.text, 'info'); return; }
  if (message.type === 'reader-ready') { syncReaderProgress(); return; }
  if (message.type === 'request-start') {
    const position = getCurrentReadPosition();
    postToPlayer({ type: 'start-position', position });
    lastTtsViewport = viewportKey(position);
    return;
  }
  if (message.type === 'settings-state') {
    syncReaderProgress();
    settingsRequested = !!message.open;
    showSettingsPanel(!!message.open);
    document.getElementById('media-viewer-modal')?.classList.toggle('viewer-tts-settings-open', !!message.open);
    return;
  }
  if (message.type === 'dock-height') {
    return;
  }
  if (message.type === 'playback-state') {
    playerPaused = !!message.paused;
    const button = document.getElementById('viewer-inline-tts-play');
    if (button) {
      button.innerHTML = `<i class="fa-solid fa-${playerPaused ? 'play' : 'pause'}"></i>`;
      button.title = playerPaused ? 'TTS 재생' : 'TTS 일시정지';
      button.setAttribute('aria-label', button.title);
    }
    if (playerPaused) { positionSequence += 1; clearHighlight(); }
    return;
  }
  if (message.type === 'reader-seek') {
    const slider = document.getElementById('viewer-page-slider');
    const value = Number(message.value);
    if (slider && !slider.disabled && Number.isFinite(value)) {
      slider.value = String(Math.max(Number(slider.min), Math.min(Number(slider.max), value)));
      slider.dispatchEvent(new Event('input', { bubbles: true }));
      slider.dispatchEvent(new Event('change', { bubbles: true }));
    }
    return;
  }
  if (message.type === 'close') {
    closeInlineTts();
    return;
  }
  if (message.type === 'position') {
    if (playerPaused && !message.seek) return;
    backgroundPosition = message;
    if (document.hidden) return;
    applyTtsPosition(message).catch((error) => console.warn('[Viewer-TTS] 본문 위치 동기화 실패:', error));
  }
}

async function ensureInlinePlayer({ autoplay = false, openSettings = false } = {}) {
  const bookId = state.activeBookId;
  const dbType = String(state.currentLibraryType || 'general').toLowerCase();
  if (!bookId || !['general', 'adult'].includes(dbType)
      || !['txt', 'text', 'epub'].includes(String(state.currentViewerFormat || '').toLowerCase())) return;
  if (host && autoplay) {
    const position = getCurrentReadPosition();
    postToPlayer({ type: 'start-position', position });
    lastTtsViewport = viewportKey(position);
  }

  if (!host) {
    const startPosition = getCurrentReadPosition();
    lastTtsViewport = viewportKey(startPosition);
    if (playerOpening) return;
    playerOpening = true;
    const generation = ++playerGeneration;
    // 동기화 위치를 먼저 저장해야 iframe이 읽기/듣기 상태를 조회할 때 기존 TTS 위치보다
    // 현재 뷰어 위치를 우선할 수 있다. iframe 생성 후 저장하면 두 요청이 경합한다.
    if (autoplay || openSettings) {
      const save = reportReadNow().catch(() => {});
      await Promise.race([save, new Promise((resolve) => setTimeout(resolve, 500))]);
    }
    if (generation !== playerGeneration || state.activeBookId !== bookId) return;
    playerOpening = false;
    host = document.createElement('div');
    host.id = HOST_ID;
    host.className = 'viewer-tts-host';
    frame = document.createElement('iframe');
    frame.title = 'TTS 음성 재생 컨트롤';
    frame.allow = 'autoplay; clipboard-write';
    frame.src = `/listen?book_id=${encodeURIComponent(bookId)}&db_type=${encodeURIComponent(dbType)}&embed=1&autoplay=${autoplay ? '1' : '0'}`;
    if (startPosition) frame.src += `#start=${encodeURIComponent(JSON.stringify(startPosition))}`;
    frame.addEventListener('load', () => {
      syncPlayerTheme();
      syncReaderProgress();
      if (settingsRequested) postToPlayer({ type: 'open-settings' });
    });
    host.append(frame);
    document.getElementById('media-viewer-modal')?.append(host);
    const play = document.createElement('button');
    play.id = 'viewer-inline-tts-play';
    play.className = 'seekbar-btn';
    play.type = 'button';
    play.title = 'TTS 재생';
    play.setAttribute('aria-label', play.title);
    play.innerHTML = '<i class="fa-solid fa-play"></i>';
    play.onclick = () => postToPlayer({ type: 'toggle-play' });
    document.getElementById('seekbar-btn-first')?.after(play);
    themeObserver = new MutationObserver(syncPlayerTheme);
    themeObserver.observe(document.getElementById('media-viewer-modal'), { attributes: true, attributeFilter: ['style','data-viewer-theme'] });
    window.addEventListener('message', onPlayerMessage);
    document.getElementById('media-viewer-modal')?.classList.add('viewer-tts-open');
  }

  if (openSettings) {
    settingsRequested = true;
    if (frame.contentDocument?.readyState === 'complete') postToPlayer({ type: 'open-settings' });
  }
}

export function openInlineTts(options = {}) {
  return ensureInlinePlayer({ autoplay: options.autoplay !== false });
}

export function openInlineTtsSettings() {
  if (settingsRequested) { closeInlineTtsSettings(); return; }
  return ensureInlinePlayer({ autoplay: false, openSettings: true });
}

function closeInlineTtsSettings() {
  settingsRequested = false;
  host?.classList.remove('settings-open');
  showSettingsPanel(false);
  document.getElementById('media-viewer-modal')?.classList.remove('viewer-tts-settings-open');
  postToPlayer({ type: 'close-settings' });
}

document.addEventListener('pointerdown', (event) => {
  if (!settingsRequested || host?.contains(event.target) || settingsPanel?.contains(event.target)
      || event.target.closest?.('#btn-viewer-tts-settings')) return;
  closeInlineTtsSettings();
}, true);
document.addEventListener('viewer-chrome-will-hide', closeInlineTtsSettings);
document.addEventListener('viewer-position-sync', syncReaderProgress);
document.addEventListener('visibilitychange', () => {
  // Invalidate pending DOM work; resume only the latest audio position.
  positionSequence += 1;
  if (!document.hidden && frame && !playerPaused && backgroundPosition) {
    applyTtsPosition(backgroundPosition).catch(error => console.warn('[Viewer-TTS] 위치 복원 실패:', error));
  }
});
// Explicit reader input takes ownership of the position before queued audio updates.
function pauseForReaderInput(event) {
  if (!host) return;
  if (event.type === 'keydown' && !['ArrowLeft','ArrowRight','ArrowUp','ArrowDown','PageUp','PageDown','Home','End'].includes(event.key)) return;
  const target = event.target;
  if (!target.closest?.('#txt-viewer-container, #txt-scroll-wrapper, #common-viewer-hotspot, #viewer-page-slider, #seekbar-btn-first, #seekbar-btn-last, [data-action="jump-first"]')) return;
  playerPaused = true;
  backgroundPosition = null;
  positionSequence += 1;
  clearHighlight();
  postToPlayer({ type: 'pause-for-navigation' });
}
for (const type of ['pointerdown', 'wheel', 'keydown']) document.addEventListener(type, pauseForReaderInput, true);
document.addEventListener('keydown', (event) => {
  if (event.key === 'Escape') closeInlineTtsSettings();
});

export function closeInlineTts() {
  backgroundPosition = null;
  themeObserver?.disconnect();
  themeObserver = null;
  lastTtsViewport = '';
  playerGeneration += 1;
  playerOpening = false;
  positionSequence += 1;
  window.removeEventListener('message', onPlayerMessage);
  // Stop synchronously: a postMessage can be discarded when its iframe is removed.
  try { frame?.contentWindow?.dispatchEvent(new Event('bookoasis-tts-dispose')); } catch (_) { /* unloading frame */ }
  const sheet = settingsPanel?.shadowRoot?.getElementById('settingsSheet');
  if (sheet && frame?.contentDocument?.body) frame.contentDocument.body.append(sheet);
  host?.remove();
  document.getElementById('viewer-inline-tts-play')?.remove();
  settingsPanel?.remove();
  settingsPanel = null;
  playerPaused = true;
  host = null;
  frame = null;
  settingsRequested = false;
  document.getElementById('media-viewer-modal')?.classList.remove('viewer-tts-open', 'viewer-tts-settings-open');
  clearHighlight();
}

document.addEventListener('viewer-closed', closeInlineTts);
document.addEventListener('viewer-book-opened', closeInlineTts);
