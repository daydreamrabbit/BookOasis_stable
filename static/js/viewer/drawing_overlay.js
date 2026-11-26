// Image viewer drawing layer.
// The source image is never changed; each user's page strokes are rendered on a
// transparent canvas and stored as normalized vector data.
import { state } from '../state.js';
import { getStroke } from '../../lib/perfect-freehand/index.mjs';

const IMAGE_FORMATS = new Set(['zip', 'cbz', 'imgdir']);
const DEFAULT_COLOR = '#000000';
const DEFAULT_SETTINGS = Object.freeze({
  penType: 'pen',
  brushType: 'round',
  shape: 'freehand',
  size: 6,
  color: DEFAULT_COLOR,
  eraser: false,
});

const drawingsByPage = new Map();
const dirtyPages = new Set();
const surfaces = new Map();
const saveTimers = new Map();
const saveChains = new Map();
let currentBookId = null;
let drawingsLoaded = false;
let drawingMode = false;
let activeSurface = null;
let mutationObserver = null;
let resizeObserver = null;
let surfaceIntersectionObserver = null;
let surfaceObserverRoot = null;
let initialized = false;
let loadSequence = 0;
let drawingsLoadPromise = null;
let drawingsLoadBookId = null;
let drawingSettings = { ...DEFAULT_SETTINGS };

function byId(id) {
  return document.getElementById(id);
}

function isImageFormat(format = state.currentViewerFormat) {
  return IMAGE_FORMATS.has(String(format || '').toLowerCase());
}

function dbType() {
  return ['general', 'adult'].includes(String(state.currentLibraryType || '').toLowerCase())
    ? String(state.currentLibraryType).toLowerCase()
    : 'general';
}

function showDrawingToast(message, type = 'error') {
  if (typeof window.showToast === 'function') {
    window.showToast(message, type);
  } else {
    console.warn(`[Viewer-Drawing] ${message}`);
  }
}

function setButtonText(active) {
  const button = byId('btn-viewer-drawing');
  if (!button) return;
  const label = button.querySelector('span');
  if (label) label.textContent = active ? '그리기 종료' : '그리기';
  button.title = active ? '그리기 모드 종료' : '그리기';
  button.setAttribute('aria-label', active ? '그리기 모드 종료' : '그리기 모드');
  button.setAttribute('aria-pressed', String(active));
  button.classList.toggle('is-active', active);
}

function setToolbarCollapsed(collapsed) {
  const toolbar = byId('drawing-toolbar');
  if (!toolbar) return;
  toolbar.classList.toggle('is-collapsed', Boolean(collapsed));
  toolbar.dataset.collapsed = collapsed ? '1' : '0';
  const handle = byId('drawing-toolbar-handle');
  if (handle) {
    handle.title = collapsed ? '그리기 도구 표시' : '그리기 도구 숨기기';
    const icon = handle.querySelector('i');
    if (icon) icon.className = collapsed ? 'fa-solid fa-chevron-up' : 'fa-solid fa-chevron-down';
  }
}

function setEraser(active) {
  drawingSettings.eraser = Boolean(active);
  const button = byId('drawing-eraser');
  if (!button) return;
  button.classList.toggle('is-active', drawingSettings.eraser);
  button.setAttribute('aria-pressed', String(drawingSettings.eraser));
  button.title = drawingSettings.eraser ? '지우개 모드 해제' : '지우개 모드';
}

function syncUndoButton() {
  const button = byId('drawing-undo');
  if (!button) return;
  const key = activeSurface?.pageKey;
  button.disabled = !key || !(drawingsByPage.get(key)?.length);
}

function setModeUi(active) {
  drawingMode = Boolean(active);
  const modal = byId('media-viewer-modal');
  const toolbar = byId('drawing-toolbar');
  const hotspot = byId('common-viewer-hotspot');
  if (modal) modal.classList.toggle('viewer-drawing-mode', drawingMode);
  if (toolbar) toolbar.hidden = !drawingMode;
  if (!drawingMode) setToolbarCollapsed(false);
  setButtonText(drawingMode);
  window.__viewerDrawingModeActive = drawingMode;
  if (hotspot) {
    hotspot.style.pointerEvents = drawingMode ? 'none' : '';
  }
  surfaces.forEach((surface) => {
    surface.canvas.style.pointerEvents = drawingMode ? 'auto' : 'none';
  });
  document.dispatchEvent(new CustomEvent('viewer-drawing-mode-changed', {
    detail: { active: drawingMode },
  }));
}

function currentPageStrokes(pageKey) {
  if (!drawingsByPage.has(pageKey)) drawingsByPage.set(pageKey, []);
  return drawingsByPage.get(pageKey);
}

function normalizePoint(event, canvas) {
  const rect = canvas.getBoundingClientRect();
  const width = Math.max(1, rect.width);
  const height = Math.max(1, rect.height);
  const x = Math.max(0, Math.min(1, (event.clientX - rect.left) / width));
  const y = Math.max(0, Math.min(1, (event.clientY - rect.top) / height));
  const pressure = Number.isFinite(event.pressure) && event.pressure > 0
    ? Math.max(0, Math.min(1, event.pressure))
    : 0.5;
  return [Number(x.toFixed(6)), Number(y.toFixed(6)), Number(pressure.toFixed(4))];
}

function colorAlpha(penType) {
  return penType === 'highlighter' ? 0.34 : (penType === 'pencil' ? 0.72 : 0.95);
}

function getStrokeOptions(stroke) {
  const soft = stroke.brush_type === 'soft';
  const pencil = stroke.pen_type === 'pencil';
  return {
    size: Number(stroke.size) || DEFAULT_SETTINGS.size,
    thinning: stroke.pen_type === 'highlighter' ? 0 : (pencil ? -0.2 : 0.35),
    smoothing: soft ? 0.86 : (pencil ? 0.35 : 0.62),
    streamline: soft ? 0.72 : 0.48,
    simulatePressure: true,
    last: true,
  };
}

function canvasPoint(point, width, height) {
  return [point[0] * width, point[1] * height];
}

function renderShape(ctx, stroke, width, height) {
  const points = stroke.points || [];
  if (!points.length) return;
  const start = canvasPoint(points[0], width, height);
  const end = canvasPoint(points[points.length - 1], width, height);
  const size = Number(stroke.size) || DEFAULT_SETTINGS.size;
  ctx.save();
  ctx.globalCompositeOperation = stroke.eraser ? 'destination-out' : 'source-over';
  ctx.globalAlpha = stroke.eraser ? 1 : colorAlpha(stroke.pen_type);
  ctx.strokeStyle = stroke.color || DEFAULT_COLOR;
  ctx.lineWidth = size;
  ctx.lineCap = stroke.brush_type === 'square' ? 'butt' : 'round';
  ctx.lineJoin = stroke.brush_type === 'square' ? 'miter' : 'round';
  ctx.beginPath();
  if (stroke.shape === 'line') {
    ctx.moveTo(start[0], start[1]);
    ctx.lineTo(end[0], end[1]);
  } else if (stroke.shape === 'rect') {
    ctx.rect(start[0], start[1], end[0] - start[0], end[1] - start[1]);
  } else {
    const centerX = (start[0] + end[0]) / 2;
    const centerY = (start[1] + end[1]) / 2;
    const radiusX = Math.abs(end[0] - start[0]) / 2;
    const radiusY = Math.abs(end[1] - start[1]) / 2;
    ctx.ellipse(centerX, centerY, Math.max(0.5, radiusX), Math.max(0.5, radiusY), 0, 0, Math.PI * 2);
  }
  ctx.stroke();
  ctx.restore();
}

function renderFreehand(ctx, stroke, width, height) {
  const points = stroke.points || [];
  if (!points.length) return;
  const inputPoints = points.map((point) => [point[0] * width, point[1] * height, point[2]]);
  const outline = getStroke(inputPoints, getStrokeOptions(stroke));
  if (!outline?.length) return;
  ctx.save();
  ctx.globalCompositeOperation = stroke.eraser ? 'destination-out' : 'source-over';
  ctx.globalAlpha = stroke.eraser ? 1 : colorAlpha(stroke.pen_type);
  ctx.fillStyle = stroke.color || DEFAULT_COLOR;
  ctx.beginPath();
  outline.forEach((point, index) => {
    const [x, y] = point;
    if (index === 0) ctx.moveTo(x, y);
    else ctx.lineTo(x, y);
  });
  ctx.closePath();
  ctx.fill();
  ctx.restore();
}

function renderStroke(ctx, stroke, width, height) {
  if (stroke.shape === 'freehand') renderFreehand(ctx, stroke, width, height);
  else renderShape(ctx, stroke, width, height);
}

function renderSurface(surface, draft = null) {
  const width = Math.max(1, surface.width || surface.canvas.clientWidth || 1);
  const height = Math.max(1, surface.height || surface.canvas.clientHeight || 1);
  const dpr = surface.dpr || 1;
  const ctx = surface.ctx;
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, width, height);
  currentPageStrokes(surface.pageKey).forEach((stroke) => renderStroke(ctx, stroke, width, height));
  if (draft) renderStroke(ctx, draft, width, height);
}

function syncSurfaceGeometry(surface) {
  if (!surface.img.isConnected || !surface.host.isConnected) return;
  const imageRect = surface.img.getBoundingClientRect();
  const hostRect = surface.host.getBoundingClientRect();
  if (imageRect.width < 1 || imageRect.height < 1) return;
  const scrollLeft = surface.host === document.querySelector('.comic-image-wrapper') ? surface.host.scrollLeft : 0;
  const scrollTop = surface.host === document.querySelector('.comic-image-wrapper') ? surface.host.scrollTop : 0;
  const left = imageRect.left - hostRect.left + scrollLeft;
  const top = imageRect.top - hostRect.top + scrollTop;
  surface.canvas.style.left = `${left}px`;
  surface.canvas.style.top = `${top}px`;
  surface.canvas.style.width = `${imageRect.width}px`;
  surface.canvas.style.height = `${imageRect.height}px`;
  surface.width = imageRect.width;
  surface.height = imageRect.height;
  surface.dpr = Math.min(3, window.devicePixelRatio || 1);
  surface.canvas.width = Math.max(1, Math.round(imageRect.width * surface.dpr));
  surface.canvas.height = Math.max(1, Math.round(imageRect.height * surface.dpr));
  renderSurface(surface);
}

function finishStroke(surface, pointerId, commit = true) {
  if (!surface || surface.pointerId !== pointerId) return;
  const draft = surface.draft;
  surface.draft = null;
  surface.pointerId = null;
  try { surface.canvas.releasePointerCapture(pointerId); } catch (_) { /* already released */ }
  if (commit && draft?.points?.length) {
    currentPageStrokes(surface.pageKey).push(draft);
    dirtyPages.add(surface.pageKey);
    renderSurface(surface);
    queueSave(surface.pageKey);
    activeSurface = surface;
    syncUndoButton();
  } else {
    renderSurface(surface);
  }
}

function bindSurfacePointerEvents(surface) {
  const canvas = surface.canvas;
  canvas.addEventListener('contextmenu', (event) => {
    if (drawingMode) event.preventDefault();
  });
  canvas.addEventListener('pointerdown', (event) => {
    if (!drawingMode || event.button === 2 || surface.pointerId !== null) return;
    event.preventDefault();
    event.stopPropagation();
    surface.pointerId = event.pointerId;
    surface.draft = {
      pen_type: drawingSettings.penType,
      brush_type: drawingSettings.brushType,
      shape: drawingSettings.shape,
      color: drawingSettings.color,
      size: Number(drawingSettings.size),
      eraser: drawingSettings.eraser,
      points: [normalizePoint(event, canvas)],
    };
    activeSurface = surface;
    setToolbarCollapsed(true);
    try { canvas.setPointerCapture(event.pointerId); } catch (_) { /* unsupported */ }
    renderSurface(surface, surface.draft);
    syncUndoButton();
  });
  canvas.addEventListener('pointermove', (event) => {
    if (!drawingMode || surface.pointerId !== event.pointerId || !surface.draft) return;
    event.preventDefault();
    event.stopPropagation();
    surface.draft.points.push(normalizePoint(event, canvas));
    renderSurface(surface, surface.draft);
  });
  canvas.addEventListener('pointerup', (event) => {
    if (!drawingMode || surface.pointerId !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    finishStroke(surface, event.pointerId, true);
  });
  canvas.addEventListener('pointercancel', (event) => finishStroke(surface, event.pointerId, false));
  canvas.addEventListener('pointerleave', (event) => {
    if (surface.pointerId === event.pointerId && event.buttons === 0) finishStroke(surface, event.pointerId, true);
  });
}

function createSurface(img) {
  const host = img.closest('.comic-page-pair') || img.closest('.comic-image-wrapper');
  if (!host || !img.isConnected) return null;
  const pageKey = String(img.dataset.drawingPageKey || `${img.dataset.index || 0}:full`);
  const canvas = document.createElement('canvas');
  canvas.className = 'drawing-canvas-layer';
  canvas.dataset.drawingPageKey = pageKey;
  canvas.setAttribute('aria-hidden', 'true');
  canvas.style.pointerEvents = drawingMode ? 'auto' : 'none';
  host.appendChild(canvas);
  const context = canvas.getContext('2d');
  if (!context) {
    canvas.remove();
    return null;
  }
  const surface = { img, host, canvas, ctx: context, pageKey, width: 0, height: 0, dpr: 1, pointerId: null, draft: null };
  bindSurfacePointerEvents(surface);
  surfaces.set(img, surface);
  if (resizeObserver) resizeObserver.observe(img);
  img.addEventListener('load', () => {
    const current = surfaces.get(img);
    if (current) syncSurfaceGeometry(current);
  });
  syncSurfaceGeometry(surface);
  return surface;
}

function removeSurface(img) {
  const surface = surfaces.get(img);
  if (!surface || activeSurface === surface || surface.pointerId !== null) return;
  if (resizeObserver) resizeObserver.unobserve(img);
  surface.canvas.remove();
  surfaces.delete(img);
}

function ensureSurfaceObserver(wrapper) {
  if (typeof IntersectionObserver !== 'function') return false;
  if (surfaceIntersectionObserver && surfaceObserverRoot === wrapper) return true;
  surfaceIntersectionObserver?.disconnect();
  surfaceObserverRoot = wrapper;
  surfaceIntersectionObserver = new IntersectionObserver((entries) => {
    entries.forEach((entry) => {
      const img = entry.target;
      if (!img.isConnected) return;
      if (entry.isIntersecting) {
        if (!surfaces.has(img)) createSurface(img);
        else syncSurfaceGeometry(surfaces.get(img));
        return;
      }
      if (wrapper.classList.contains('scroll-mode')) removeSurface(img);
    });
  }, { root: wrapper, rootMargin: '900px 0px', threshold: 0.01 });
  return true;
}

function syncSurfaces() {
  // 일반 뷰어에서는 그리기 캔버스를 유지하지 않는다. 캔버스 제거를
  // MutationObserver가 감지해 다시 만드는 경로도 여기서 차단한다.
  if (!drawingMode) {
    if (surfaces.size) clearSurfaces();
    return;
  }
  const wrapper = document.querySelector('#comic-viewer-container .comic-image-wrapper');
  if (!wrapper) return;
  const scrollMode = wrapper.classList.contains('scroll-mode');
  if (!scrollMode && surfaceIntersectionObserver) {
    surfaceIntersectionObserver.disconnect();
    surfaceIntersectionObserver = null;
    surfaceObserverRoot = null;
  }
  const images = [...wrapper.querySelectorAll('img.comic-page-img, img.comic-scroll-img')];
  const imageSet = new Set(images);
  surfaces.forEach((surface, img) => {
    if (!imageSet.has(img) || !img.isConnected) {
      if (resizeObserver) resizeObserver.unobserve(img);
      surface.canvas.remove();
      surfaces.delete(img);
      if (activeSurface === surface) activeSurface = null;
    }
  });
  const hasObserver = scrollMode && ensureSurfaceObserver(wrapper);
  images.forEach((img) => {
    if (hasObserver) {
      surfaceIntersectionObserver.observe(img);
      if (surfaces.has(img)) syncSurfaceGeometry(surfaces.get(img));
    } else if (!surfaces.has(img)) createSurface(img);
    else syncSurfaceGeometry(surfaces.get(img));
  });
  syncUndoButton();
}

function ensureVisibleScrollSurfaces() {
  const wrapper = document.querySelector('#comic-viewer-container .comic-image-wrapper');
  if (!wrapper || !wrapper.classList.contains('scroll-mode')) return;
  const rootRect = wrapper.getBoundingClientRect();
  wrapper.querySelectorAll('img.comic-scroll-img').forEach((img) => {
    if (surfaces.has(img)) return;
    const rect = img.getBoundingClientRect();
    if (rect.bottom >= rootRect.top && rect.top <= rootRect.bottom) createSurface(img);
  });
}

function clearSurfaces() {
  surfaceIntersectionObserver?.disconnect();
  surfaceIntersectionObserver = null;
  surfaceObserverRoot = null;
  surfaces.forEach((surface) => {
    if (resizeObserver) resizeObserver.unobserve(surface.img);
    surface.canvas.remove();
  });
  surfaces.clear();
  activeSurface = null;
}

function queueSave(pageKey) {
  if (!currentBookId || !drawingsLoaded) return;
  const bookId = currentBookId;
  const targetDbType = dbType();
  clearTimeout(saveTimers.get(pageKey));
  saveTimers.set(pageKey, setTimeout(() => {
    saveTimers.delete(pageKey);
    const payload = {
      page_key: pageKey,
      strokes: drawingsByPage.get(pageKey) || [],
    };
    const previous = saveChains.get(pageKey) || Promise.resolve();
    const next = previous.catch(() => {}).then(() => fetch(`/api/v1/books/${encodeURIComponent(bookId)}/drawings?db_type=${encodeURIComponent(targetDbType)}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'same-origin',
      body: JSON.stringify(payload),
    })).then(async (response) => {
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error || '그림 저장에 실패했습니다.');
      }
    }).catch((error) => {
      showDrawingToast(error.message || '그림 저장에 실패했습니다.');
    });
    saveChains.set(pageKey, next);
  }, 280));
}

async function loadDrawingsFromServer(bookId) {
  const sequence = ++loadSequence;
  drawingsLoaded = false;
  drawingsByPage.clear();
  const response = await fetch(`/api/v1/books/${encodeURIComponent(bookId)}/drawings?db_type=${encodeURIComponent(dbType())}`, {
    credentials: 'same-origin',
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.error || '그림 데이터를 불러오지 못했습니다.');
  }
  const data = await response.json();
  if (sequence !== loadSequence || String(currentBookId) !== String(bookId)) return;
  (data.drawings || []).forEach((drawing) => {
    if (drawing?.page_key && Array.isArray(drawing.strokes)) drawingsByPage.set(drawing.page_key, drawing.strokes);
  });
  drawingsLoaded = true;
  syncSurfaces();
}

function loadDrawings(bookId) {
  if (drawingsLoadPromise && String(drawingsLoadBookId) === String(bookId)) {
    return drawingsLoadPromise;
  }
  drawingsLoadBookId = bookId;
  const promise = loadDrawingsFromServer(bookId);
  drawingsLoadPromise = promise;
  return promise.finally(() => {
    if (drawingsLoadPromise === promise) {
      drawingsLoadPromise = null;
      drawingsLoadBookId = null;
    }
  });
}

function undoCurrentSurface() {
  if (!activeSurface) return;
  const strokes = currentPageStrokes(activeSurface.pageKey);
  if (!strokes.length) return;
  strokes.pop();
  dirtyPages.add(activeSurface.pageKey);
  renderSurface(activeSurface);
  queueSave(activeSurface.pageKey);
  syncUndoButton();
}

function setColor(color) {
  if (!/^#[0-9a-fA-F]{6}$/.test(String(color || ''))) return;
  drawingSettings.color = String(color).toLowerCase();
  document.querySelectorAll('.drawing-color-swatch').forEach((button) => {
    button.classList.toggle('is-active', button.dataset.drawingColor?.toLowerCase() === drawingSettings.color);
  });
  const custom = byId('drawing-custom-color');
  if (custom) custom.value = drawingSettings.color;
}

function bindToolbar() {
  if (initialized) return;
  initialized = true;
  byId('drawing-toolbar-handle')?.addEventListener('click', (event) => {
    event.preventDefault();
    setToolbarCollapsed(!byId('drawing-toolbar')?.classList.contains('is-collapsed'));
  });
  byId('drawing-undo')?.addEventListener('click', (event) => {
    event.preventDefault();
    undoCurrentSurface();
  });
  byId('drawing-eraser')?.addEventListener('click', (event) => {
    event.preventDefault();
    setEraser(!drawingSettings.eraser);
  });
  document.querySelectorAll('.drawing-color-swatch').forEach((button) => {
    button.addEventListener('click', () => setColor(button.dataset.drawingColor));
  });
  byId('drawing-custom-color-button')?.addEventListener('click', () => byId('drawing-custom-color')?.click());
  byId('drawing-custom-color')?.addEventListener('input', (event) => setColor(event.target.value));
  byId('drawing-pen-type')?.addEventListener('change', (event) => { drawingSettings.penType = event.target.value; });
  byId('drawing-brush-type')?.addEventListener('change', (event) => { drawingSettings.brushType = event.target.value; });
  byId('drawing-shape')?.addEventListener('change', (event) => { drawingSettings.shape = event.target.value; });
  byId('drawing-size')?.addEventListener('input', (event) => {
    drawingSettings.size = Number(event.target.value) || DEFAULT_SETTINGS.size;
    const output = byId('drawing-size-value');
    if (output) output.textContent = String(drawingSettings.size);
  });
  document.addEventListener('keydown', (event) => {
    if (!drawingMode) return;
    if (event.key === 'Escape') {
      event.preventDefault();
      event.stopImmediatePropagation();
      exitDrawingMode();
      return;
    }
    if (event.target?.matches?.('input, select, textarea, button')) return;
    if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'z') {
      event.preventDefault();
      undoCurrentSurface();
    }
  }, true);
}

async function enterDrawingMode() {
  if (!currentBookId || !isImageFormat() || drawingMode) return;
  const button = byId('btn-viewer-drawing');
  if (button) button.disabled = true;
  try {
    if (!drawingsLoaded) await loadDrawings(currentBookId);
    if (!currentBookId || !isImageFormat()) return;
    setModeUi(true);
    syncSurfaces();
    ensureVisibleScrollSurfaces();
  } catch (error) {
    showDrawingToast(error.message || '그림 데이터를 불러오지 못했습니다.');
  } finally {
    if (button) button.disabled = false;
  }
}

function exitDrawingMode() {
  const bookId = currentBookId;
  const targetDbType = dbType();
  saveTimers.forEach((timer) => clearTimeout(timer));
  saveTimers.clear();
  dirtyPages.forEach((pageKey) => {
    if (bookId && drawingsLoaded) {
      const payload = { page_key: pageKey, strokes: drawingsByPage.get(pageKey) || [] };
      const previous = saveChains.get(pageKey) || Promise.resolve();
      saveChains.set(pageKey, previous.catch(() => {}).then(() => fetch(`/api/v1/books/${encodeURIComponent(bookId)}/drawings?db_type=${encodeURIComponent(targetDbType)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        credentials: 'same-origin',
        body: JSON.stringify(payload),
      })).catch(() => {}));
    }
  });
  setModeUi(false);
  setEraser(false);
  // 일반 뷰어에서는 투명 캔버스 자체를 제거해 그린 흔적이 보이지 않게 한다.
  // 저장된 벡터 데이터는 유지하므로 다시 그리기 모드로 들어가면 복원할 수 있다.
  clearSurfaces();
}

function resetForBook() {
  if (drawingMode) setModeUi(false);
  clearSurfaces();
  currentBookId = null;
  drawingsLoaded = false;
  drawingsLoadPromise = null;
  drawingsLoadBookId = null;
  drawingsByPage.clear();
  dirtyPages.clear();
  saveChains.clear();
  saveTimers.forEach((timer) => clearTimeout(timer));
  saveTimers.clear();
  const button = byId('btn-viewer-drawing');
  if (button) button.style.display = 'none';
}

function onBookOpened(event) {
  resetForBook();
  const format = String(event.detail?.format || state.currentViewerFormat || '').toLowerCase();
  currentBookId = event.detail?.bookId || state.activeBookId;
  if (!currentBookId || !IMAGE_FORMATS.has(format)) return;
  const button = byId('btn-viewer-drawing');
  if (button) {
    button.style.display = '';
    button.disabled = false;
  }
  // 페이지 이미지가 비동기로 커밋되므로 데이터는 백그라운드로 먼저 받아 둔다.
  loadDrawings(currentBookId).catch((error) => {
    drawingsLoaded = false;
    showDrawingToast(error.message || '그림 데이터를 불러오지 못했습니다.');
  });
  requestAnimationFrame(syncSurfaces);
}

function onViewerClosed() {
  exitDrawingMode();
  resetForBook();
}

function init() {
  bindToolbar();
  window.toggleDrawingMode = () => (drawingMode ? exitDrawingMode() : enterDrawingMode());
  document.addEventListener('viewer-book-opened', onBookOpened);
  document.addEventListener('viewer-closed', onViewerClosed);
  const wrapper = document.querySelector('#comic-viewer-container .comic-image-wrapper');
  if (wrapper) {
    mutationObserver = new MutationObserver(() => requestAnimationFrame(syncSurfaces));
    mutationObserver.observe(wrapper, { childList: true, subtree: true });
  }
  resizeObserver = typeof ResizeObserver === 'function'
    ? new ResizeObserver(() => requestAnimationFrame(() => surfaces.forEach(syncSurfaceGeometry)))
    : null;
  window.addEventListener('resize', () => requestAnimationFrame(syncSurfaces), { passive: true });
}

if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init, { once: true });
else init();
