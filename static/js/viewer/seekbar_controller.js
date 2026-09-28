// seekbar_controller.js - unified seekbar routing for comic/txt/epub/pdf
import { state } from '../state.js';

let viewerSeekbarInited = false;
let seekbarPointerId = null;
let suppressSeekbarClickUntil = 0;
const previousPositions = new Map();
const viewerModules = {
  comic: null,
  txt: null,
  pdf: null,
};

async function getViewerModule(fmt) {
  try {
    if (fmt === 'zip' || fmt === 'cbz' || fmt === 'imgdir') {
      if (!viewerModules.comic) viewerModules.comic = await import('../viewer_comic.js');
      return viewerModules.comic;
    }
    if (fmt === 'epub' || fmt === 'txt') {
      if (!viewerModules.txt) viewerModules.txt = await import('../viewer_txt.js?rev=20260927-tts-session-v8');
      return viewerModules.txt;
    }
    if (fmt === 'pdf') {
      if (!viewerModules.pdf) viewerModules.pdf = await import('../viewer_pdf.js');
      return viewerModules.pdf;
    }
  } catch (err) {
    console.error(`[Viewer-Core] Failed to import module for format ${fmt}:`, err);
  }
  return null;
}

function positionKey() {
  return `${state.currentViewerFormat || ''}:${state.activeBookId || ''}`;
}

function snapshotSlider() {
  const slider = document.getElementById('viewer-page-slider');
  if (!slider) return null;
  return {
    value: Number(slider.value),
    min: Number(slider.min),
    max: Number(slider.max),
    seekMode: slider.dataset.seekMode || 'page',
  };
}

export function rememberViewerPosition() {
  const snapshot = snapshotSlider();
  if (snapshot && Number.isFinite(snapshot.value)) previousPositions.set(positionKey(), snapshot);
}

function syncTooltip(slider) {
  const tooltip = document.getElementById('seekbar-tooltip');
  if (!slider || !tooltip) return;
  const min = Number(slider.min || 0);
  const max = Number(slider.max || 1);
  const value = Number(slider.value || min);
  const ratio = (value - min) / Math.max(1, max - min);
  const thumbHalf = 9;
  const width = Math.max(thumbHalf * 2, slider.offsetWidth || 0);
  tooltip.textContent = slider.dataset.seekMode === 'scroll-progress' ? `${Math.round(value)}%` : `${Math.round(value)}`;
  tooltip.style.left = `${thumbHalf + Math.max(0, Math.min(1, ratio)) * (width - thumbHalf * 2)}px`;
  tooltip.classList.add('visible');
}

function updateSliderFromPointer(slider, clientX) {
  const rect = slider.getBoundingClientRect();
  const min = Number(slider.min || 0);
  const max = Number(slider.max || min + 1);
  const thumbHalf = 9;
  const usableWidth = Math.max(1, rect.width - thumbHalf * 2);
  const ratio = Math.max(0, Math.min(1, (clientX - rect.left - thumbHalf) / usableWidth));
  const next = Math.round(min + ratio * (max - min));
  if (Number(slider.value) === next) return false;
  slider.value = String(next);
  slider.dispatchEvent(new Event('input', { bubbles: true }));
  return true;
}

async function previewSlider(slider) {
  const val = parseInt(slider.value, 10);
  const fmt = state.currentViewerFormat;
  const min = Number(slider.min || 1);
  const max = Number(slider.max || 1);
  const ratio = (val - min) / Math.max(1, max - min);
  slider.style.setProperty('--seek-progress', `${Math.max(0, Math.min(100, ratio * 100))}%`);
  syncTooltip(slider);
  slider.dispatchEvent(new CustomEvent('viewer-position-sync', { bubbles: true }));

  if (fmt === 'zip' || fmt === 'cbz' || fmt === 'imgdir') {
    const m = await getViewerModule(fmt);
    const fn = m && (m.comicSliderInput || window.comicSliderInput);
    if (typeof fn === 'function') fn(slider, val);
  } else if (fmt === 'epub' || fmt === 'txt') {
    const m = await getViewerModule(fmt);
    if (typeof m?.txtSliderInput === 'function') m.txtSliderInput(slider, val);
    // 연속 스크롤은 range를 움직이는 동안 본문도 즉시 따라가야 한다. change만
    // 기다리면 트랙 클릭/모바일 드래그가 브라우저에 따라 이동하지 않은 것처럼 보인다.
    if (slider.dataset.seekMode === 'scroll-progress' && typeof m?.txtSliderChange === 'function') {
      m.txtSliderChange(slider, val, { live: true });
    }
  } else if (fmt === 'pdf') {
    const pageInfo = document.getElementById('comic-overlay-page-info');
    if (pageInfo) pageInfo.textContent = `${val} / ${slider.max}`;
  }
}

async function commitSlider(slider) {
  const val = parseInt(slider.value, 10);
  const fmt = state.currentViewerFormat;
  const m = await getViewerModule(fmt);
  if (fmt === 'zip' || fmt === 'cbz' || fmt === 'imgdir') {
    const fn = m && (m.comicSliderChange || window.comicSliderChange);
    if (typeof fn === 'function') fn(slider, val);
  } else if (fmt === 'epub' || fmt === 'txt') {
    if (typeof m?.txtSliderChange === 'function' && slider.dataset.seekMode !== 'scroll-progress') {
      m.txtSliderChange(slider, val);
    }
  } else if (fmt === 'pdf') {
    const fn = m && (m.pdfSliderChange || m.pdfJumpToPage || window.pdfJumpToPage);
    if (typeof fn === 'function') fn(slider, val);
  }
  slider.blur();
}

export async function returnToPreviousViewerPosition() {
  const slider = document.getElementById('viewer-page-slider');
  const key = positionKey();
  const previous = previousPositions.get(key);
  if (!slider || !previous) {
    window.showToast?.('되돌아갈 이전 읽기 위치가 없습니다.', 'info');
    return;
  }
  const current = snapshotSlider();
  slider.value = String(Math.max(Number(slider.min), Math.min(Number(slider.max), previous.value)));
  await previewSlider(slider);
  await commitSlider(slider);
  if (current) previousPositions.set(key, current);
}

export function initViewerSeekBar() {
  const slider = document.getElementById('viewer-page-slider');
  if (!slider) return;

  if (viewerSeekbarInited) return;
  viewerSeekbarInited = true;

  const initialFmt = state.currentViewerFormat;
  if (initialFmt) {
    getViewerModule(initialFmt).catch(() => {});
  }

  slider.addEventListener('pointerdown', (event) => {
    if (event.pointerType === 'mouse' && event.button !== 0) return;
    rememberViewerPosition();
    seekbarPointerId = event.pointerId;
    try { slider.setPointerCapture(event.pointerId); } catch (_) { /* unsupported browser */ }
    updateSliderFromPointer(slider, event.clientX);
    event.preventDefault();
    event.stopPropagation();
  });
  slider.addEventListener('pointermove', (event) => {
    if (seekbarPointerId !== event.pointerId) return;
    updateSliderFromPointer(slider, event.clientX);
    event.preventDefault();
    event.stopPropagation();
  });
  slider.addEventListener('pointerup', (event) => {
    if (seekbarPointerId !== event.pointerId) return;
    updateSliderFromPointer(slider, event.clientX);
    seekbarPointerId = null;
    suppressSeekbarClickUntil = Date.now() + 350;
    slider.dispatchEvent(new Event('change', { bubbles: true }));
    try { slider.releasePointerCapture(event.pointerId); } catch (_) { /* already released */ }
    event.preventDefault();
    event.stopPropagation();
  });
  slider.addEventListener('pointercancel', () => {
    seekbarPointerId = null;
  });
  slider.addEventListener('click', (event) => {
    if (Date.now() >= suppressSeekbarClickUntil) return;
    event.preventDefault();
    event.stopPropagation();
  });
  slider.addEventListener('keydown', (event) => {
    if (['ArrowLeft', 'ArrowRight', 'ArrowUp', 'ArrowDown', 'Home', 'End', 'PageUp', 'PageDown'].includes(event.key)) {
      rememberViewerPosition();
    }
  });

  document.addEventListener('viewer-position-sync', () => syncTooltip(slider));

  slider.addEventListener('input', async (e) => {
    await previewSlider(e.target);
  });

  slider.addEventListener('change', async (e) => {
    await commitSlider(e.target);
  });
}
