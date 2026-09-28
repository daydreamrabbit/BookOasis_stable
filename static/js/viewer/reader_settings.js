// reader_settings.js — 읽기 방향, 페이지 스텝, fit 모드, 스크롤 너비 관리
import { showViewerLoading, hideViewerLoading } from '../view_manager.js';

export let comicReadingDirection = 'ltr';
export let tapZoneDirection = 'horizontal';
export let comicPageStep = 1;
export let comicSplitSpread = false;
const VALID_FIT_MODES = new Set(['width', 'height']);
export let comicFitMode = VALID_FIT_MODES.has(localStorage.getItem('comic_fit_mode'))
  ? localStorage.getItem('comic_fit_mode')
  : 'height';
export let comicScrollWidth = 800; // 스크롤 모드 이미지 너비 (px, 600~900, 50단위)

function getStoredComicReadingDirection() {
  const saved = localStorage.getItem('comic_reading_direction');
  return saved === 'rtl' ? 'rtl' : 'ltr';
}

export function setComicReadingDirection(direction) {
  comicReadingDirection = direction === 'rtl' ? 'rtl' : 'ltr';
  localStorage.setItem('comic_reading_direction', comicReadingDirection);
  syncComicReadingDirectionUI();
  return comicReadingDirection;
}

export function getComicReadingDirection() {
  return comicReadingDirection;
}

export function toggleComicReadingDirection() {
  const nextDirection = comicReadingDirection === 'rtl' ? 'ltr' : 'rtl';
  return setComicReadingDirection(nextDirection);
}

function getStoredComicPageStep() {
  const saved = parseInt(localStorage.getItem('comic_page_step'), 10);
  return saved === 2 ? 2 : 1;
}

export function setComicPageStep(step) {
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const safeStep = step === 2 ? 2 : 1;
  if (scrollMode === 'scroll' || comicSplitSpread) {
    // 연속 스크롤에서는 화면상 한 장씩 렌더링하지만, 사용자가 선택한 페이지 모드
    // 장수 설정까지 1장으로 덮어쓰면 페이지 모드 복귀/재진입 때 2장 설정이 사라진다.
    // 유효 장수만 1장으로 취급하고 저장된 선호값은 그대로 보존한다.
    comicPageStep = getStoredComicPageStep();
    syncComicPageStepUI();
    window.syncViewerControlsForFormat?.();
    return 1;
  }

  comicPageStep = safeStep;
  localStorage.setItem('comic_page_step', String(comicPageStep));
  syncComicPageStepUI();
  window.syncViewerControlsForFormat?.();
  return comicPageStep;
}

export function getComicPageStep() {
  return comicPageStep;
}

export function toggleComicPageStep() {
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (scrollMode === 'scroll' || comicSplitSpread) {
    return setComicPageStep(1);
  }

  // Use persisted value as source of truth because this module can be loaded
  // before EPUB initializes page-step state, causing first-click no-op.
  const currentStep = getStoredComicPageStep();
  return setComicPageStep(currentStep === 2 ? 1 : 2);
}

function syncComicReadingDirectionUI() {
  const modal = document.getElementById('media-viewer-modal');
  if (modal) modal.dataset.readingDirection = comicReadingDirection;
  const btn = document.getElementById('btn-comic-reading-direction');
  const label = document.getElementById('comic-reading-direction-label');
  if (btn) {
    btn.classList.toggle('active', comicReadingDirection === 'rtl');
    btn.setAttribute('data-direction', comicReadingDirection);
    btn.title = comicReadingDirection === 'rtl' ? '오른쪽→왼쪽 읽기' : '왼쪽→오른쪽 읽기';
  }
  if (label) {
    label.textContent = comicReadingDirection === 'rtl' ? '오른쪽→왼쪽' : '왼쪽→오른쪽';
  }
}

// ──────────────────────────────────────────────────
// 화면 탭존 방향 (좌/우 넘기기 ↔ 상/하 넘기기, 한손 파지 대응)
// ──────────────────────────────────────────────────

function getStoredTapZoneDirection() {
  const saved = localStorage.getItem('viewer_tap_zone_direction');
  return saved === 'vertical' ? 'vertical' : 'horizontal';
}

export function setTapZoneDirection(direction) {
  tapZoneDirection = direction === 'vertical' ? 'vertical' : 'horizontal';
  localStorage.setItem('viewer_tap_zone_direction', tapZoneDirection);
  syncTapZoneDirectionUI();
  showTapZonePreview();
  return tapZoneDirection;
}

export function getTapZoneDirection() {
  return tapZoneDirection;
}

export function toggleTapZoneDirection() {
  return setTapZoneDirection(tapZoneDirection === 'vertical' ? 'horizontal' : 'vertical');
}

export function syncTapZoneDirectionUI() {
  const hotspot = document.getElementById('common-viewer-hotspot');
  if (hotspot) {
    hotspot.classList.toggle('vertical', tapZoneDirection === 'vertical');
  }

  const btn = document.getElementById('btn-tap-zone-direction');
  const label = document.getElementById('tap-zone-direction-label');
  if (btn) {
    btn.classList.toggle('active', tapZoneDirection === 'vertical');
    btn.title = tapZoneDirection === 'vertical' ? '상/하 탭으로 넘기기' : '좌/우 탭으로 넘기기';
    const icon = btn.querySelector('i');
    if (icon) {
      icon.className = tapZoneDirection === 'vertical'
        ? 'fa-solid fa-arrows-up-down'
        : 'fa-solid fa-arrows-left-right';
    }
  }
  if (label) {
    // 언어 변경기가 과거의 고정 "좌/우" 키로 다시 덮어쓰지 않도록 현재 상태에
    // 맞는 키도 함께 갱신한다.
    label.setAttribute('data-i18n', tapZoneDirection === 'vertical'
      ? 'viewer.tap_zone_vertical'
      : 'viewer.tap_zone_horizontal');
    label.textContent = tapZoneDirection === 'vertical' ? '상/하' : '좌/우';
  }
  document.querySelectorAll('[data-tap-zone-direction]').forEach((button) => {
    const active = button.dataset.tapZoneDirection === tapZoneDirection;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

export function initTapZoneDirection() {
  tapZoneDirection = getStoredTapZoneDirection();
  syncTapZoneDirectionUI();
}

let tapZonePreviewTimer = null;
export function showTapZonePreview() {
  const hotspot = document.getElementById('common-viewer-hotspot');
  if (!hotspot) return;
  hotspot.classList.add('tap-zone-preview');
  clearTimeout(tapZonePreviewTimer);
  tapZonePreviewTimer = window.setTimeout(() => hotspot.classList.remove('tap-zone-preview'), 1200);
}

export function syncComicPageStepUI() {
  const btn = document.getElementById('btn-comic-page-step');
  const label = document.getElementById('comic-page-step-label');
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const isTwoPageActive = comicPageStep === 2 && scrollMode !== 'scroll';
  if (btn) {
    btn.classList.toggle('active', isTwoPageActive);
    btn.setAttribute('data-step', String(comicPageStep));
    btn.title = scrollMode === 'scroll' ? '스크롤 모드에서는 1장씩만 적용됩니다' : (comicPageStep === 2 ? '2장씩 보기' : '1장씩 보기');
  }
  if (label) {
    label.textContent = scrollMode === 'scroll' ? '1장' : `${comicPageStep}장`;
  }

  // 2쪽보기가 아니면 버튼만 숨긴다. 정렬 선호까지 지우면 스크롤 모드 왕복 후
  // 표지 단독 정렬이 풀리므로 상태는 보존한다.
  const shiftBtn = document.getElementById('btn-spread-shift');
  if (shiftBtn) shiftBtn.style.display = isTwoPageActive ? '' : 'none';
  window.syncViewerSpreadSettingsUI?.();
}

// ──────────────────────────────────────────────────
// 2쪽보기 정렬 "한 장 밀기" — 예: (9,10)(11,12)로 짝지어지던 스프레드를
// (10,11)로 볼 수 있도록 짝의 기준을 한 장 밀어서 보정한다 (comic/pdf 뷰어 공용).
// 페이지 이동 자체(진행률 저장 기준)는 건드리지 않고 화면에 보여줄 짝만 바꾼다.
// ──────────────────────────────────────────────────

export let spreadShiftOffset = 1; // 0 또는 1, 기본값은 표지 단독

export function getSpreadShiftOffset() {
  return spreadShiftOffset;
}

export function setSpreadShiftOffset(offset) {
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (scrollMode === 'scroll' || comicPageStep !== 2) return spreadShiftOffset;
  spreadShiftOffset = Number(offset) === 1 ? 1 : 0;
  localStorage.setItem('viewer_spread_cover_alone', spreadShiftOffset === 1 ? '1' : '0');
  syncSpreadShiftOffsetUI();
  return spreadShiftOffset;
}

export function toggleSpreadShiftOffset() {
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (scrollMode === 'scroll' || comicPageStep !== 2) return spreadShiftOffset; // 2쪽보기가 아니면 무의미
  return setSpreadShiftOffset(spreadShiftOffset === 0 ? 1 : 0);
}

// 이름은 하위 호환을 위해 유지한다. 실제로는 사용자가 선택한 표지 정렬을 복원한다.
export function resetSpreadShiftOffset() {
  spreadShiftOffset = localStorage.getItem('viewer_spread_cover_alone') === '0' ? 0 : 1;
  syncSpreadShiftOffsetUI();
}

function syncSpreadShiftOffsetUI() {
  const btn = document.getElementById('btn-spread-shift');
  if (!btn) return;
  btn.classList.toggle('active', spreadShiftOffset === 1);
  btn.title = spreadShiftOffset === 1 ? '표지 단독 정렬 끄기' : '첫 표지는 단독으로, 다음 페이지부터 두 장씩 보기';
  window.syncViewerSpreadSettingsUI?.();
}

// ──────────────────────────────────────────────────
// 페이지 좌/우 분할 보기 (스프레드 이미지 1장을 절반씩 2페이지로)
// ──────────────────────────────────────────────────

function getStoredComicSplitSpread() {
  return localStorage.getItem('comic_split_spread') === '1';
}

export function setComicSplitSpread(on) {
  comicSplitSpread = !!on;
  localStorage.setItem('comic_split_spread', comicSplitSpread ? '1' : '0');
  if (comicSplitSpread) {
    // 분할 보기와 2쪽보기를 동시에 켜면 잘린 절반 두 장이 다시 나란히 붙어
    // 원본을 재현해버리는 모순이 생기므로 강제로 1장 보기로 되돌린다.
    setComicPageStep(1);
  }
  syncComicSplitSpreadUI();
  return comicSplitSpread;
}

export function getComicSplitSpread() {
  return comicSplitSpread;
}

export function toggleComicSplitSpread() {
  return setComicSplitSpread(!getStoredComicSplitSpread());
}

function syncComicSplitSpreadUI() {
  const btn = document.getElementById('btn-comic-split-spread');
  const label = document.getElementById('comic-split-spread-label');
  if (btn) {
    btn.classList.toggle('active', comicSplitSpread);
    btn.title = comicSplitSpread ? '분할 보기 끄기 (원본 이미지로 보기)' : '페이지를 좌/우로 분할해서 보기';
  }
  if (label) {
    label.textContent = comicSplitSpread ? '분할 켬' : '분할 끔';
  }
}

export function initSplitSpread() {
  setComicSplitSpread(getStoredComicSplitSpread());
}

export function disableLegacySplitSpread() {
  localStorage.removeItem('comic_split_spread');
  comicSplitSpread = false;
  syncComicSplitSpreadUI();
}

export function initReadingDirection() {
  setComicReadingDirection(getStoredComicReadingDirection());
}

export function initPageStep() {
  setComicPageStep(getStoredComicPageStep());
}

export function syncReaderSettingsUI() {
  comicPageStep = getStoredComicPageStep();
  tapZoneDirection = getStoredTapZoneDirection();
  syncComicPageStepUI();
  syncTapZoneDirectionUI();
  syncSpreadShiftOffsetUI();
  syncFitUI();
}

export function setFitMode(mode) {
  comicFitMode = VALID_FIT_MODES.has(mode) ? mode : 'height';
  localStorage.setItem('comic_fit_mode', comicFitMode);
  syncFitUI();
  return comicFitMode;
}

export function getFitMode() { return comicFitMode; }

function syncFitUI() {
  const btnHeight = document.getElementById('btn-fit-height');
  const btnWidth = document.getElementById('btn-fit-width');
  if (btnHeight) btnHeight.classList.toggle('active', comicFitMode === 'height');
  if (btnWidth) btnWidth.classList.toggle('active', comicFitMode === 'width');

  const btnOverlayHeight = document.getElementById('btn-overlay-fit-height');
  const btnOverlayWidth = document.getElementById('btn-overlay-fit-width');
  if (btnOverlayHeight) btnOverlayHeight.classList.toggle('active', comicFitMode === 'height');
  if (btnOverlayWidth) btnOverlayWidth.classList.toggle('active', comicFitMode === 'width');
  document.querySelectorAll('[data-comic-fit-mode]').forEach((button) => {
    const active = button.dataset.comicFitMode === comicFitMode;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });
}

// ──────────────────────────────────────────────────
// 스크롤 모드 이미지 너비 설정 (600~900px, 50px 단위)
// ──────────────────────────────────────────────────

let pdfRenderDebounceTimer = null;

export function getScrollWidth() {
  return comicScrollWidth;
}

export function setScrollWidth(px) {
  const clamped = Math.round(Math.max(300, Math.min(1600, Number(px))) / 50) * 50;
  comicScrollWidth = clamped;
  localStorage.setItem('comic_scroll_width', String(clamped));
  applyScrollWidth();
  syncScrollWidthUI();

  // PDF 뷰어가 활성화되어 있는 경우
  if (typeof document !== 'undefined') {
    const pdfPane = document.getElementById('pdf-viewer-container');
    if (pdfPane && pdfPane.style.display !== 'none') {
      import('../viewer_pdf.js').then(m => {
        // 1. 실시간 CSS 리사이징 (드래그 중 즉시 60fps)
        if (typeof m.updatePdfCanvasCssWidth === 'function') {
          m.updatePdfCanvasCssWidth(clamped);
        }
        // 2. 디바운스 후 고해상도 PDF.js 재렌더링
        if (pdfRenderDebounceTimer) clearTimeout(pdfRenderDebounceTimer);
        pdfRenderDebounceTimer = setTimeout(() => {
          if (typeof m.renderPdfPage === 'function') {
            m.renderPdfPage();
          }
        }, 300);
      }).catch(err => console.warn('[reader_settings] Failed to trigger PDF re-render:', err));
    }
  }

  return clamped;
}

export function applyScrollWidth() {
  const wrapper = document.querySelector('.comic-image-wrapper');
  if (wrapper) {
    wrapper.style.setProperty('--comic-scroll-width', `${comicScrollWidth}px`);
  }
}

export function initScrollWidth() {
  const saved = parseInt(localStorage.getItem('comic_scroll_width'), 10);
  comicScrollWidth = (saved >= 300 && saved <= 1600) ? Math.round(saved / 50) * 50 : 800;
  applyScrollWidth();
  syncScrollWidthUI();
}

function syncScrollWidthUI() {
  const slider = document.getElementById('comic-scroll-width-slider');
  const label  = document.getElementById('comic-scroll-width-label');
  if (slider) slider.value = comicScrollWidth;
  if (label)  label.textContent = `${comicScrollWidth}px`;
}
