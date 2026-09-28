// viewer.js – 미디어 뷰어 라이프사이클 및 단축키 코어 조율기
import { state } from './state.js';
import { restoreViewerPreferences } from './viewer/preference_restore.js';
import { getTapZoneDirection } from './viewer_comic.js';
import { dismissViewerChromeOnContentTap, isViewerTextPoint } from './viewer/input_controller.js?rev=20260927-tts-session-v8';
import { nextComicPage, prevComicPage, setComicFitMode, toggleComicOverlay, markAsCompleted as markComicAsCompleted, getComicReadingDirection, initReadingDirection, toggleComicReadingDirection, toggleComicPageStep, comicJumpToFirstPage, comicJumpToLastPage, setTapZoneDirection, toggleTapZoneDirection, initTapZoneDirection, toggleComicSplitSpread, toggleSpreadShiftOffset, loadComicPage, initPageStep, resetSpreadShiftOffset } from './viewer_comic.js';
import { prevTxtPage, nextTxtPage, applyTxtSettings, txtJumpToFirstPage, txtJumpToLastPage } from './viewer_txt.js?rev=20260927-tts-session-v8';
import { openEpubTocPanel } from './viewer/txt_toc.js?rev=20260922-reader-session-v45';
import { openInlineTts, openInlineTtsSettings } from './viewer/inline_tts.js';
import { initViewerBookmarkController, toggleCurrentPageBookmark } from './viewer/bookmark_controller.js';
import { closeViewerSidePanels, openViewerSearchPanel, openImageReadingNotesPanel } from './viewer/ridi_panels.js';
import { nextPdfPage, prevPdfPage, pdfJumpToFirstPage, pdfJumpToLastPage, renderPdfPage } from './viewer_pdf.js';
import { initFullscreenStateSync, isViewerInFullscreen, toggleFullscreenViewer } from './viewer/fullscreen_controller.js';
import { initViewerSeekBar, rememberViewerPosition, returnToPreviousViewerPosition } from './viewer/seekbar_controller.js?rev=20260927-tts-session-v8';
import {
  configureLifecycleController,
  getActiveViewerInstance,
  openReader,
  closeMediaViewer,
} from './viewer/lifecycle_controller.js?rev=20260927-tts-session-v8';
import {
  configureInputController,
  initKeyboardListener,
  initWheelListener,
  syncHotspotPointerEvents,
  initViewerClickToggle,
} from './viewer/input_controller.js?rev=20260927-tts-session-v8';
import {
  ViewerDisplayMode,
  getViewerDisplayMode,
  saveViewerDisplayMode,
  syncViewerDisplayModeUI,
  initViewerChrome,
  resetViewerChrome,
  toggleViewerChrome,
} from './viewer/display_mode.js?rev=20260922-reader-session-v45';
export { toggleFullscreenViewer };
export { initKeyboardListener, initWheelListener, syncHotspotPointerEvents, initViewerClickToggle };
export { openReader, closeMediaViewer, initViewerSeekBar };

initFullscreenStateSync();

function closeViewerSettingsOverlay() {
  const menu = document.getElementById('comic-overlay-menu');
  if (menu && menu.style.display === 'flex') toggleComicOverlay({ suppressReopen: false });
}

// 보기 설정은 설정 카드 안을 조작할 때만 유지한다. 카드 바깥을 누르면
// 모바일의 합성 click보다 먼저 설정 시트를 닫는다.
document.addEventListener('pointerdown', (event) => {
  const menu = document.getElementById('comic-overlay-menu');
  if (!menu || menu.style.display !== 'flex') return;
  const target = event.target;
  if (target?.closest?.('.ridi-view-settings') || target?.closest?.('.ridi-viewer-toolbar-top')) return;
  toggleComicOverlay({ suppressReopen: false });
}, true);

document.addEventListener('viewer-side-panel-opening', closeViewerSettingsOverlay);
document.addEventListener('viewer-chrome-will-hide', closeViewerSettingsOverlay);

document.addEventListener('viewer-side-panel-state-changed', (event) => {
  const activePanel = event.detail?.panel || null;
  const actionByPanel = {
    toc: 'open-toc',
    notes: 'open-reading-notes',
    search: 'open-viewer-search',
  };
  document.querySelectorAll('.ridi-viewer-tools [data-action]').forEach((button) => {
    const isActive = actionByPanel[activePanel] === button.dataset.action;
    if (['open-toc', 'open-reading-notes', 'open-viewer-search'].includes(button.dataset.action)) {
      button.classList.toggle('is-active', isActive);
      button.setAttribute('aria-pressed', String(isActive));
    }
  });
});

// Unused legacy EPUB functions (stubbed for compatibility)
export async function initEpubViewer(bookId, pagesRead, totalPages) {}
export async function clearEpubViewer() {}
export async function epubPrevPage() {}
export async function epubNextPage() {}
export async function applyEpubSettings(options) {}
export async function changeEpubScrollMode(scrollMode) {}
import { THEMES, getViewerSettings, updateFontSize, toggleTheme, setViewerTheme, updateLineHeight, updateParagraphSpacing } from './viewer_settings.js';
import { fetchUserSettings, updateUserSetting } from './api.js';

const viewerPreferenceSaveTimers = new Map();

function persistViewerPreference(key, value) {
  state.systemSettings[key] = String(value);
  clearTimeout(viewerPreferenceSaveTimers.get(key));
  viewerPreferenceSaveTimers.set(key, setTimeout(() => {
    updateUserSetting(key, String(value)).then((result) => {
      if (result?.success) state.systemSettings[key] = String(value);
    }).catch((error) => console.warn(`[Viewer-Settings] ${key} 저장 실패:`, error));
  }, 250));
}

function addFontOption(select, value, label = value) {
  if (!select || !value || [...select.options].some((option) => option.value === value)) return;
  const option = document.createElement('option');
  option.value = value;
  option.textContent = label;
  select.appendChild(option);
}

export function syncViewerSettingsUI() {
  const settings = getViewerSettings();
  const fontSizePx = Math.round(settings.fontSize * 16);
  const controls = {
    'ridi-font-size-value': `${fontSizePx}px`,
    'ridi-line-height-value': settings.lineHeight.toFixed(1),
    'ridi-paragraph-spacing-value': `${settings.paragraphSpacing.toFixed(1)}em`,
  };
  Object.entries(controls).forEach(([id, value]) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  });
  const settingsFontSize = document.getElementById('my-setting-viewer-font-size');
  if (settingsFontSize) settingsFontSize.value = String(fontSizePx);

  ['viewer-font-select', 'ridi-viewer-font-select', 'my-setting-viewer-font-family'].forEach((id) => {
    const select = document.getElementById(id);
    if (!select) return;
    addFontOption(select, settings.fontFamily, settings.fontFamily);
    select.value = settings.fontFamily;
  });
  const lineSelect = document.getElementById('viewer-line-height-select');
  const paragraphSelect = document.getElementById('viewer-paragraph-spacing-select');
  if (lineSelect) lineSelect.value = settings.lineHeight.toFixed(1);
  if (paragraphSelect) paragraphSelect.value = settings.paragraphSpacing.toFixed(1);

  document.querySelectorAll('.ridi-theme-options [data-action="viewer-theme"]').forEach((button) => {
    const active = button.dataset.value === settings.theme.name;
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
  });

  const modal = document.getElementById('media-viewer-modal');
  if (modal) {
    const dark = ['dark', 'black', 'navy'].includes(settings.theme.name);
    modal.dataset.viewerTheme = settings.theme.name;
    [modal, document.documentElement].forEach((target) => {
      target.style.setProperty('--viewer-theme-bg', settings.theme.background);
      target.style.setProperty('--viewer-theme-text', settings.theme.text);
      target.style.setProperty('--viewer-panel-bg', `color-mix(in srgb, ${settings.theme.background} ${dark ? 84 : 92}%, ${dark ? '#ffffff' : '#000000'})`);
      target.style.setProperty('--viewer-panel-soft', `color-mix(in srgb, ${settings.theme.background} ${dark ? 72 : 84}%, ${dark ? '#ffffff' : '#000000'})`);
      target.style.setProperty('--viewer-panel-border', `color-mix(in srgb, ${settings.theme.text} 20%, transparent)`);
      target.style.setProperty('--viewer-panel-muted', `color-mix(in srgb, ${settings.theme.text} 68%, transparent)`);
    });
  }
  syncViewerSpreadSettingsUI();
}

export function syncViewerSpreadSettingsUI() {
  const spread = document.getElementById('ridi-spread-settings');
  const twoPage = (localStorage.getItem('comic_page_step') === '2')
    && (localStorage.getItem('viewer_scroll_mode') || 'page') === 'page';
  if (spread) spread.hidden = !twoPage;
  const gapButton = document.getElementById('ridi-center-gap-button');
  const gapRemoved = localStorage.getItem('remove_2page_center_gap') === '1';
  if (gapButton) {
    gapButton.classList.toggle('is-active', gapRemoved);
    const label = gapButton.querySelector('span');
    if (label) label.textContent = gapRemoved ? '가운데 여백 복원' : '가운데 여백 제거';
  }
  const shiftButton = document.getElementById('ridi-spread-shift-button');
  if (shiftButton) shiftButton.classList.toggle('is-active', localStorage.getItem('viewer_spread_cover_alone') === '0');
}

async function hydrateViewerPreferences() {
  try {
    const result = await fetchUserSettings();
    if (!result?.success || !result.settings) return;
    const settings = result.settings;
    const effective = restoreViewerPreferences(settings);
    state.systemSettings = { ...state.systemSettings, ...settings, ...effective };
    syncViewerThemeUI();
    syncViewerSettingsUI();
    getActiveViewerInstance()?.applySettings?.({ skipSavedPositionRestore: true });
  } catch (error) {
    console.warn('[Viewer-Settings] 계정 설정 동기화 실패:', error);
  }
}

// 사용자 정의 폰트 목록 로드 및 드롭다운 바인딩
export function loadCustomFontsList() {
  fetch('/api/media/fonts')
    .then(res => res.json())
    .then(data => {
      if (data.success && data.fonts) {
        window.customFonts = data.fonts;
        console.log("[Viewer-Fonts] Custom fonts loaded: ", window.customFonts);

        let styleContent = '';
        data.fonts.forEach(f => {
            const fontFaceName = `CustomFont_${f.name.replace(/\s+/g, '_')}`;
            styleContent += `@font-face { font-family: '${fontFaceName}'; src: url("${f.url}"); }\n`;
        });
        if (styleContent) {
            let styleEl = document.getElementById('viewer-custom-fonts-style');
            if (!styleEl) {
                styleEl = document.createElement('style');
                styleEl.id = 'viewer-custom-fonts-style';
                document.head.appendChild(styleEl);
            }
            styleEl.innerHTML = styleContent;
        }

        const selects = ['viewer-font-select', 'ridi-viewer-font-select', 'my-setting-viewer-font-family']
          .map((id) => document.getElementById(id)).filter(Boolean);
        if (selects.length) {
          const sortedFontsDesc = [...data.fonts].sort((a, b) =>
            String(b.name || '').localeCompare(String(a.name || ''), undefined, { sensitivity: 'base' })
          );
          selects.forEach((select) => {
            sortedFontsDesc.forEach((font) => addFontOption(select, font.name, font.name));
            select.value = getViewerSettings().fontFamily;
          });
        }
        syncViewerSettingsUI();
      }
    })
    .catch(err => {
      console.error("[Viewer-Fonts] Failed to fetch custom fonts list:", err);
      syncViewerThemeUI();
    });
}

// 이전 페이지 통합 조율
export function prevPage() {
  console.log('[Viewer-Core] prevPage() called');
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.prevPage === 'function') {
    activeViewerInstance.prevPage();
    return;
  }
  const isRtl = localStorage.getItem('comic_reading_direction') === 'rtl';
  if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    if (getComicReadingDirection() === 'rtl') {
      nextComicPage();
    } else {
      prevComicPage();
    }
  } else if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    prevPdfPage();
  // TODO(삭제 대상, 향후 재검토): #epub-viewer-container는 EPUB이 지금은 #txt-viewer-container를
  // 공유해서 쓰므로 실제로 존재하지 않는 ID다. 위 activeViewerInstance.prevPage 분기가 EPUB/TXT를
  // 항상 먼저 가로채기 때문에 지금은 이 분기에 절대 도달하지 않지만(도달하면 null.style에서 즉시
  // 크래시), 그 가로채기 로직이 바뀌면 조용한 시한폭탄이 될 수 있어 지우기 전에 한 번 더 확인 필요.
  } else if (document.getElementById('epub-viewer-container').style.display !== 'none') {
    if (isRtl) {
      epubNextPage();
    } else {
      epubPrevPage();
    }
  } else if (document.getElementById('txt-viewer-container').style.display !== 'none') {
    prevTxtPage();
  }
}

// 다음 페이지 통합 조율
export function nextPage() {
  console.log('[Viewer-Core] nextPage() called');
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.nextPage === 'function') {
    activeViewerInstance.nextPage();
    return;
  }
  const isRtl = localStorage.getItem('comic_reading_direction') === 'rtl';
  if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    if (getComicReadingDirection() === 'rtl') {
      prevComicPage();
    } else {
      nextComicPage();
    }
  } else if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    nextPdfPage();
  // TODO(삭제 대상, 향후 재검토): prevPage()와 동일한 사유로 도달 불가능한 #epub-viewer-container
  // 분기(null 참조 크래시 위험 포함) — activeViewerInstance.nextPage 가로채기가 바뀌면 재검토.
  } else if (document.getElementById('epub-viewer-container').style.display !== 'none') {
    if (isRtl) {
      epubPrevPage();
    } else {
      epubNextPage();
    }
  } else if (document.getElementById('txt-viewer-container').style.display !== 'none') {
    nextTxtPage();
  }
}

export function movePageByOne(direction) {
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.moveByOne === 'function') {
    activeViewerInstance.moveByOne(direction === 'prev' ? 'prev' : 'next');
    return;
  }
  if (direction === 'prev') prevPage();
  else nextPage();
}

// 2쪽보기 정렬 "한 장 밀기" 통합 조율 - 예: (9,10)(11,12)로 짝지어지던 스프레드를
// (10,11)로 볼 수 있도록 한 장 밀어서 보정한다. comic/pdf 뷰어에서만 의미가 있다
// 이미지 중심 EPUB도 두 spine 항목을 한 펼침면으로 사용하므로 같은 정렬을 적용한다.
export function shiftSpreadByOne() {
  console.log('[Viewer-Core] shiftSpreadByOne() called');
  toggleSpreadShiftOffset();
  if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    loadComicPage();
  } else if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    renderPdfPage();
  } else if (document.getElementById('txt-viewer-container').style.display !== 'none'
      && String(state.currentViewerFormat || '').toLowerCase() === 'epub') {
    applyTxtSettings({ skipSavedPositionRestore: true });
  }
}

configureInputController({
  toggleFullscreenViewer,
  isViewerInFullscreen,
  closeMediaViewer,
  nextPage,
  prevPage,
  toggleComicOverlay,
  toggleViewerChrome,
  shiftSpreadByOne,
  movePageByOne,
});

configureLifecycleController({
  initViewerSeekBar,
  syncHotspotPointerEvents,
  clearEpubViewer,
});

// 공통 환경 설정 트리거 함수
export function changeFontSize(dir) {
  const size = updateFontSize(dir);
  persistViewerPreference('VIEWER_FONT_SIZE', Math.round(size * 16));
  syncViewerSettingsUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
}

export function syncViewerThemeUI() {
  const currentTheme = localStorage.getItem('viewer_theme') || 'dark';
  const themeObj = THEMES[currentTheme] || THEMES.dark;

  const select = document.getElementById('viewer-theme-select');
  if (select) {
    select.value = currentTheme;
  }

  const label = document.getElementById('viewer-theme-label');
  if (label) {
    label.textContent = themeObj.label || '다크';
  }
  syncViewerSettingsUI();
}

export function toggleReaderTheme() {
  toggleTheme();
  syncViewerThemeUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
}

// HTML 인라인 이벤트 연동을 위해 글로벌 윈도우 객체에 바인딩
window.toggleTheme = toggleReaderTheme;

window.onViewerThemeChange = function (value) {
  console.log(`[Viewer-Core] Background theme changed to: ${value}`);
  setViewerTheme(value);
  persistViewerPreference('VIEWER_THEME', value);
  syncViewerThemeUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
};

window.onViewerFontChange = function (value) {
  console.log(`[Viewer-Core] Font family changed to: ${value}`);
  localStorage.setItem('viewer_font_family', value);
  persistViewerPreference('VIEWER_FONT_FAMILY', value);
  syncViewerSettingsUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
};

window.onViewerLineHeightChange = function (value) {
  console.log(`[Viewer-Core] Line height changed to: ${value}`);
  updateLineHeight(value);
  persistViewerPreference('VIEWER_LINE_HEIGHT', value);
  syncViewerSettingsUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
};

window.onViewerParagraphSpacingChange = function (value) {
  console.log(`[Viewer-Core] Paragraph spacing changed to: ${value}`);
  updateParagraphSpacing(value);
  persistViewerPreference('VIEWER_PARAGRAPH_SPACING', value);
  syncViewerSettingsUI();
  const activeViewerInstance = getActiveViewerInstance();
  if (activeViewerInstance && typeof activeViewerInstance.applySettings === 'function') {
    activeViewerInstance.applySettings();
  } else {
    applyTxtSettings();
    applyEpubSettings();
  }
};

window.setScrollMode = function (mode) {
  console.log(`[Viewer-Core] Scroll mode changed to: ${mode}`);
  const previousMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (previousMode === mode) return; // 동일 모드 클릭 시 무시
  localStorage.setItem('viewer_scroll_mode', mode);
  if (mode === 'scroll') {
    localStorage.setItem('viewer_display_mode', ViewerDisplayMode.SCROLL);
  } else if (localStorage.getItem('viewer_display_mode') === ViewerDisplayMode.SCROLL) {
    const restoredMode = (localStorage.getItem('comic_page_step') || '1') === '2'
      ? (localStorage.getItem('comic_reading_direction') === 'rtl' ? ViewerDisplayMode.TWO_ONE : ViewerDisplayMode.ONE_TWO)
      : ViewerDisplayMode.ONE;
    localStorage.setItem('viewer_display_mode', restoredMode);
  }
  syncViewerDisplayModeUI(getViewerDisplayMode());

  const btnPage = document.getElementById('btn-scroll-page');
  const btnScroll = document.getElementById('btn-scroll-continuous');
  if (mode === 'page') {
    if (btnPage) btnPage.classList.add('active');
    if (btnScroll) btnScroll.classList.remove('active');
  } else {
    if (btnPage) btnPage.classList.remove('active');
    if (btnScroll) btnScroll.classList.add('active');
  }

  const activeFormat = String(state.currentViewerFormat || '').toLowerCase();
  if (typeof window.syncViewerControlsForFormat === 'function') {
    window.syncViewerControlsForFormat(activeFormat);
  }

  // ── 보기 모드 전환 중 즉시 피드백 오버레이 ──────────────────────
  // 전체 뷰어를 덮는 반투명 블러 배경 + 중앙 알림 라벨
  // pointer-events: all → 터치/클릭 완전 차단
  const viewerBody = document.getElementById('viewer-body-container');
  const existingBanner = document.getElementById('viewer-mode-switch-banner');
  if (existingBanner) existingBanner.remove();

  const banner = document.createElement('div');
  banner.id = 'viewer-mode-switch-banner';
  banner.style.cssText = `
    position: absolute;
    inset: 0;
    background: rgba(0, 0, 0, 0.55);
    backdrop-filter: blur(6px);
    -webkit-backdrop-filter: blur(6px);
    z-index: 20000;
    pointer-events: all;
    display: flex;
    align-items: center;
    justify-content: center;
    cursor: wait;
  `;
  banner.innerHTML = `
    <div style="
      background: rgba(var(--app-panel-rgb), 0.95);
      border: 1px solid rgba(168, 85, 247, 0.6);
      color: var(--app-text-primary);
      padding: 0.9rem 2rem;
      border-radius: 50px;
      font-size: 1rem;
      font-weight: 600;
      white-space: nowrap;
      box-shadow: 0 8px 32px rgba(0,0,0,0.6), 0 0 20px rgba(168,85,247,0.2);
      display: flex;
      align-items: center;
      gap: 0.5rem;
    ">
      <i class="fa-solid fa-arrows-rotate" style="color:var(--app-accent); font-size:1rem;"></i>
      보기 모드 전환 중...
    </div>
  `;
  if (viewerBody) viewerBody.appendChild(banner);

  // 다음 프레임에서 실제 렌더링 (banner가 화면에 그려진 뒤 실행)
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      if (['zip', 'cbz', 'imgdir'].includes(activeFormat)) {
        import('./viewer_comic.js').then(m => {
          if (mode === 'page' && typeof m.initPageStep === 'function') m.initPageStep();
          if (typeof m.syncSplitSpreadModeForScrollMode === 'function') {
            m.syncSplitSpreadModeForScrollMode(mode === 'scroll');
          }
          const apply = m.applyComicFitMode || m.setComicFitMode || window.setComicFitMode;
          if (typeof apply === 'function') apply();
          if (typeof m.loadComicPage === 'function') m.loadComicPage();
        }).catch(err => console.warn('[Viewer-Core] Failed to import viewer_comic:', err));
      } else if (activeFormat === 'pdf') {
        import('./viewer_pdf.js').then(m => {
          if (typeof m.renderPdfPage === 'function') m.renderPdfPage();
        }).catch(err => console.warn('[Viewer-Core] Failed to import viewer_pdf:', err));
      } else if (activeFormat === 'txt' || activeFormat === 'epub') {
        applyTxtSettings({ previousMode });
      }
      syncHotspotPointerEvents();
      // 전환 완료 후 배너 제거
      setTimeout(() => {
        const b = document.getElementById('viewer-mode-switch-banner');
        if (b) b.remove();
      }, 400);
    });
  });
};

export function setViewerDisplayMode(mode) {
  const previousScrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const normalized = saveViewerDisplayMode(mode);
  const nextScrollMode = normalized === ViewerDisplayMode.SCROLL ? 'scroll' : 'page';
  const activeFormat = String(state.currentViewerFormat || '').toLowerCase();
  initPageStep();
  initReadingDirection();
  resetSpreadShiftOffset();
  syncViewerDisplayModeUI(normalized);
  syncViewerSpreadSettingsUI();

  if (previousScrollMode !== nextScrollMode) {
    window.setScrollMode(nextScrollMode);
    return;
  }

  window.syncViewerControlsForFormat?.(activeFormat);
  if (['zip', 'cbz', 'imgdir'].includes(activeFormat)) {
    loadComicPage();
  } else if (activeFormat === 'pdf') {
    renderPdfPage();
  } else if (activeFormat === 'txt' || activeFormat === 'epub') {
    applyTxtSettings({ skipSavedPositionRestore: true });
  }
}

export function viewerJumpToFirst() {
  const fmt = state.currentViewerFormat;
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const overlayMenu = document.getElementById('comic-overlay-menu');
  rememberViewerPosition();
  if (fmt === 'zip' || fmt === 'cbz') {
    if (typeof comicJumpToFirstPage === 'function') comicJumpToFirstPage();
  } else if (fmt === 'epub') {
    // EPUB도 TxtViewer를 사용하므로 txtJumpToFirstPage 호출
    if (typeof txtJumpToFirstPage === 'function') txtJumpToFirstPage();
  } else if (fmt === 'pdf') {
    if (typeof pdfJumpToFirstPage === 'function') pdfJumpToFirstPage();
  } else if (fmt === 'txt') {
    if (typeof txtJumpToFirstPage === 'function') txtJumpToFirstPage();
  }

  // iOS Safari scroll mode: overlay close path can restore stale inner scroll.
  // When user explicitly jumps, skip one-time inner scroll restore.
  if (overlayMenu && scrollMode === 'scroll' && (fmt === 'epub' || fmt === 'txt')) {
    overlayMenu.dataset.skipInnerScrollRestore = 'true';
  }

  if (overlayMenu && overlayMenu.style.display === 'flex') toggleComicOverlay();
}

export function viewerJumpToLast() {
  const fmt = state.currentViewerFormat;
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const overlayMenu = document.getElementById('comic-overlay-menu');
  rememberViewerPosition();
  if (fmt === 'zip' || fmt === 'cbz') {
    if (typeof comicJumpToLastPage === 'function') comicJumpToLastPage();
  } else if (fmt === 'epub') {
    // EPUB도 TxtViewer를 사용하므로 txtJumpToLastPage 호출
    if (typeof txtJumpToLastPage === 'function') txtJumpToLastPage();
  } else if (fmt === 'pdf') {
    if (typeof pdfJumpToLastPage === 'function') pdfJumpToLastPage();
  } else if (fmt === 'txt') {
    if (typeof txtJumpToLastPage === 'function') txtJumpToLastPage();
  }

  // Same guard for explicit jump-to-last in scroll mode.
  if (overlayMenu && scrollMode === 'scroll' && (fmt === 'epub' || fmt === 'txt')) {
    overlayMenu.dataset.skipInnerScrollRestore = 'true';
  }

  if (overlayMenu && overlayMenu.style.display === 'flex') toggleComicOverlay();
}

window.viewerJumpToFirst = viewerJumpToFirst;
window.viewerJumpToLast = viewerJumpToLast;
window.prevPage = prevPage;
window.nextPage = nextPage;
window.toggleTheme = toggleReaderTheme;
window.toggleComicReadingDirection = function () {
  const direction = toggleComicReadingDirection();
  if ((localStorage.getItem('comic_page_step') || '1') === '2'
      && (localStorage.getItem('viewer_scroll_mode') || 'page') !== 'scroll') {
    localStorage.setItem('viewer_display_mode', direction === 'rtl' ? ViewerDisplayMode.TWO_ONE : ViewerDisplayMode.ONE_TWO);
    syncViewerDisplayModeUI(getViewerDisplayMode());
  }
  if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    if (typeof window.applyPdfFitMode === 'function') {
      window.applyPdfFitMode();
    }
  } else if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    import('./viewer_comic.js').then(m => {
      const load = m.loadComicPage;
      if (typeof load === 'function') load();
    });
  }
};

window.toggleComicPageStep = function () {
  toggleComicPageStep();
  if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    if (typeof window.applyPdfFitMode === 'function') {
      window.applyPdfFitMode();
    }
  } else if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    import('./viewer_comic.js').then(m => {
      const load = m.loadComicPage;
      if (typeof load === 'function') load();
    });
  } else if (document.getElementById('txt-viewer-container').style.display !== 'none') {
    applyTxtSettings();
  // TODO(삭제 대상, 향후 재검토): EPUB은 #txt-viewer-container를 공유해서 위 txt 분기가 항상
  // 먼저 걸리므로 이 분기는 도달 불가능하고, applyEpubSettings()도 빈 함수(no-op)라 설령
  // 도달해도 아무 일 안 한다. EPUB/TXT 컨테이너 통합 구조가 바뀌면 재검토.
  } else if (document.getElementById('epub-viewer-container').style.display !== 'none') {
    applyEpubSettings({ preservePagePosition: true });
  }
};

window.toggleComicSplitSpread = function () {
  toggleComicSplitSpread();
  if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    import('./viewer_comic.js').then(m => {
      if (typeof m.syncSplitSpreadMode === 'function') m.syncSplitSpreadMode();
      if (typeof m.loadComicPage === 'function') m.loadComicPage();
    });
  }
};

window.syncComicCenterGapButton = function () {
  const btn = document.getElementById('btn-comic-center-gap');
  const label = document.getElementById('comic-center-gap-label');
  if (!btn) return;

  const isGapRemoved = (localStorage.getItem('remove_2page_center_gap') === '1');
  btn.classList.toggle('active', isGapRemoved);

  if (label) {
    if (isGapRemoved) {
      label.setAttribute('data-i18n', 'viewer.center_gap_hide');
      label.textContent = window.i18n ? window.i18n.t('viewer.center_gap_hide') : '중앙 여백 감춤';
    } else {
      label.setAttribute('data-i18n', 'viewer.center_gap_show');
      label.textContent = window.i18n ? window.i18n.t('viewer.center_gap_show') : '중앙 여백';
    }
  }
  syncViewerSpreadSettingsUI();
};

window.toggleComicCenterGap = function () {
  const current = localStorage.getItem('remove_2page_center_gap') === '1';
  const nextVal = current ? '0' : '1';
  localStorage.setItem('remove_2page_center_gap', nextVal);
  console.log(`[Viewer] Toggled remove_2page_center_gap to ${nextVal}`);

  syncComicCenterGapButton();

  const removeGapInput = document.getElementById('setting-remove-2page-center-gap');
  if (removeGapInput) {
    removeGapInput.checked = (nextVal === '1');
  }

  if (document.getElementById('pdf-viewer-container').style.display !== 'none') {
    if (typeof window.applyPdfFitMode === 'function') {
      window.applyPdfFitMode();
    }
  } else if (document.getElementById('comic-viewer-container').style.display !== 'none') {
    import('./viewer_comic.js').then(m => {
      const load = m.loadComicPage;
      if (typeof load === 'function') load();
    });
  } else if (document.getElementById('txt-viewer-container').style.display !== 'none') {
    applyTxtSettings();
  // TODO(삭제 대상, 향후 재검토): EPUB은 #txt-viewer-container를 공유해서 위 txt 분기가 항상
  // 먼저 걸리므로 이 분기는 도달 불가능하고, applyEpubSettings()도 빈 함수(no-op)라 설령
  // 도달해도 아무 일 안 한다. EPUB/TXT 컨테이너 통합 구조가 바뀌면 재검토.
  } else if (document.getElementById('epub-viewer-container').style.display !== 'none') {
    applyEpubSettings({ preservePagePosition: true });
  }
};

// 최초 로드 시 사용자 폰트 사전 로딩
loadCustomFontsList();

// 최초 로드 시 저장된 탭존 방향(좌/우 ↔ 상/하) 복원 (핫스팟 레이어는 모달과 별개로 항상 DOM에 존재)
initTapZoneDirection();

function initMediaViewerDelegation() {
  if (window.__mediaViewerDelegationBound) return;

  document.addEventListener('click', (event) => {
    const target = event && event.target && typeof event.target.closest === 'function'
      ? event.target.closest('[data-role="viewer-action"]')
      : null;
    if (!target) return;

    if ((Date.now() < Number(window.__viewerSuppressClickUntil || 0)
        || Date.now() < Number(window.__viewerMouseDraggedUntil || 0))
        && target.closest('#common-viewer-hotspot')) {
      event.preventDefault();
      event.stopPropagation();
      return;
    }

    if (target.closest('#common-viewer-hotspot') && isViewerTextPoint(event.clientX, event.clientY)) return;
    // The capture handler owns hotspot clicks. Do not let the body handler
    // immediately dismiss chrome that this same click has just opened.
    if (target.closest('#common-viewer-hotspot')) event.stopPropagation();
    event.preventDefault();
    let action = target.getAttribute('data-action');
    const value = target.getAttribute('data-value');
    if (target.closest('#common-viewer-hotspot')
        && dismissViewerChromeOnContentTap(target, event.clientX, event.clientY)) return;

    // 화면 좌/우 핫스팟 존은 물리적 화면 위치를 클릭하는 공간적(spatial) 조작이라,
    // 만화 RTL(우->좌) 읽기 방향에서는 좌/우 클릭 시 넘어가는 스토리 방향도 반대가 되어야 한다.
    // (메뉴의 '이전'/'다음' 버튼처럼 항상 스토리 순서를 가리키는 조작과는 구분됨)
    const isRtlFlow = String(getTapZoneDirection()).endsWith('-reverse');
    if (isRtlFlow && (action === 'prev-page' || action === 'next-page') && target.closest('#common-viewer-hotspot')) {
      if (isRtlFlow) {
        action = action === 'prev-page' ? 'next-page' : 'prev-page';
      }
    }

    const isSidePanelAction = action === 'open-toc' || action === 'open-reading-notes' || action === 'open-viewer-search';
    if (!isSidePanelAction && target.closest('.ridi-viewer-toolbar-top')) closeViewerSidePanels();
    if (action !== 'toggle-overlay' && target.closest('.ridi-viewer-toolbar-top')) closeViewerSettingsOverlay();

    if (action === 'close') return closeMediaViewer();
    if (action === 'font-size') return changeFontSize(Number.parseInt(value || '0', 10) || 0);
    if (action === 'toggle-reader-theme') return toggleReaderTheme();
    if (action === 'comic-fit') return setComicFitMode(value || 'height');
    if (action === 'toggle-fullscreen') return toggleFullscreenViewer();
    if (action === 'prev-page') return prevPage();
    if (action === 'next-page') return nextPage();
    if (action === 'toggle-overlay') return toggleComicOverlay();
    if (action === 'toggle-viewer-controls') return toggleViewerChrome();
    if (action === 'viewer-display-mode') return setViewerDisplayMode(value || ViewerDisplayMode.ONE);
    if (action === 'open-toc') return openEpubTocPanel('toc');
    if (action === 'open-reading-notes') {
      const isComicFormat = ['zip', 'cbz', 'imgdir'].includes(String(state.currentViewerFormat || '').toLowerCase());
      return isComicFormat ? openImageReadingNotesPanel() : openEpubTocPanel('notes');
    }
    if (action === 'open-viewer-search') return openViewerSearchPanel();
    if (action === 'toggle-page-bookmark') return toggleCurrentPageBookmark().catch(error => window.showToast?.(error.message, 'error'));
    if (action === 'viewer-theme') return window.onViewerThemeChange?.(value || 'dark');
    if (action === 'line-height-step') {
      const current = Number.parseFloat(localStorage.getItem('viewer_line_height') || '1.8');
      return window.onViewerLineHeightChange?.(Math.max(1.2, Math.min(2.4, current + Number(value || 0) * 0.2)).toFixed(1));
    }
    if (action === 'paragraph-spacing-step') {
      const current = Number.parseFloat(localStorage.getItem('viewer_paragraph_spacing') || '1.0');
      return window.onViewerParagraphSpacingChange?.(Math.max(0, Math.min(3, current + Number(value || 0) * 0.5)).toFixed(1));
    }
    if (action === 'overlay-tab') return window.switchViewerOverlayTab?.(value || 'nav');
    if (action === 'jump-first') return viewerJumpToFirst();
    if (action === 'jump-last') return viewerJumpToLast();
    if (action === 'return-last-position') return returnToPreviousViewerPosition();
    if (action === 'listen') return openListenFromViewer();
    if (action === 'tts-settings') return openInlineTtsSettings();
    if (action === 'mark-completed') return markAsCompleted();
    if (action === 'toggle-highlight-mode') return window.toggleHighlightMode?.();
    if (action === 'scroll-mode') return window.setScrollMode?.(value || 'page');
    if (action === 'toggle-page-step') return window.toggleComicPageStep?.();
    if (action === 'shift-spread') return shiftSpreadByOne();
    if (action === 'toggle-center-gap') return window.toggleComicCenterGap?.();
    if (action === 'toggle-reading-direction') return window.toggleComicReadingDirection?.();
    if (action === 'toggle-tap-zone-direction') return toggleTapZoneDirection();
    if (action === 'tap-zone-direction') return setTapZoneDirection(value || 'horizontal');
    if (action === 'toggle-split-spread') return window.toggleComicSplitSpread?.();
    if (action === 'toggle-theme-cycle') return window.toggleTheme?.();
    if (action === 'toggle-padding-panel') return window.toggleViewerPaddingPanel?.();
  }, true);

  document.addEventListener('input', (event) => {
    const target = event && event.target;
    if (!target || !(target.matches instanceof Function)) return;
    if (!target.matches('[data-role="viewer-action-input"]')) return;

    const action = target.getAttribute('data-action');
    if (action === 'comic-scroll-width') {
      window.setComicScrollWidth?.(target.value);
    }
  }, true);

  document.addEventListener('change', (event) => {
    const target = event && event.target;
    if (!target || !(target.matches instanceof Function)) return;
    if (!target.matches('[data-role="viewer-action-change"]')) return;

    const action = target.getAttribute('data-action');
    if (action === 'font-family') return window.onViewerFontChange?.(target.value);
    if (action === 'theme') return window.onViewerThemeChange?.(target.value);
    if (action === 'line-height') return window.onViewerLineHeightChange?.(target.value);
    if (action === 'paragraph-spacing') return window.onViewerParagraphSpacingChange?.(target.value);
  }, true);

  window.__mediaViewerDelegationBound = true;
}

initMediaViewerDelegation();
initViewerBookmarkController();
initViewerChrome();
syncViewerDisplayModeUI(getViewerDisplayMode());
syncViewerSettingsUI();
hydrateViewerPreferences();

function openListenFromViewer() {
  if (!state.activeBookId || !['general', 'adult'].includes(String(state.currentLibraryType || '').toLowerCase())) return;
  return openInlineTts({ autoplay: true });
}
document.addEventListener('viewer-preferences-updated', () => {
  syncViewerThemeUI();
  getActiveViewerInstance()?.applySettings?.({ skipSavedPositionRestore: true });
});

window.setViewerDisplayMode = setViewerDisplayMode;
window.syncViewerDisplayModeUI = () => syncViewerDisplayModeUI(getViewerDisplayMode());
window.syncViewerSettingsUI = syncViewerSettingsUI;
window.syncViewerSpreadSettingsUI = syncViewerSpreadSettingsUI;
window.resetViewerChrome = resetViewerChrome;





// 통합 읽음 완료 처리기 (ZIP, PDF, EPUB, TXT 전체 포맷 완독 조율)
export function markAsCompleted() {
  const fmt = state.currentViewerFormat;
  console.log(`[Viewer-Core] markAsCompleted 수동 호출 - Format: ${fmt}, Book ID: ${state.activeBookId}`);

  if (fmt === 'zip' || fmt === 'cbz') {
    markComicAsCompleted();
  } else if (fmt === 'pdf') {
    const pdfInfo = document.getElementById('pdf-page-info');
    let totalPages = 100;
    if (pdfInfo) {
      const parts = pdfInfo.textContent.split('/');
      if (parts.length === 2) {
        totalPages = parseInt(parts[1].trim(), 10) || 100;
      }
    }
    import('./viewer_progress.js?rev=20260927-tts-session-v8').then(m => {
      m.saveProgress(state.activeBookId, totalPages - 1, totalPages);
      m.flushProgress().then(() => {
        alert(window.i18n.t('viewer.read_completed'));
        toggleComicOverlay();
      });
    });
  } else if (fmt === 'epub') {
    import('./viewer_progress.js?rev=20260927-tts-session-v8').then(m => {
      m.saveProgress(state.activeBookId, 100, 100);
      m.flushProgress().then(() => {
        alert(window.i18n.t('viewer.read_completed'));
        toggleComicOverlay();
      });
    });
  } else if (fmt === 'txt') {
    const pageInfo = document.getElementById('comic-overlay-page-info');
    let totalPages = 100;
    if (pageInfo) {
      const match = pageInfo.textContent.match(/\/.*?(\d+)/);
      if (match && match[1]) {
        totalPages = parseInt(match[1].trim(), 10) || 100;
      }
    }
    import('./viewer_progress.js?rev=20260927-tts-session-v8').then(m => {
      m.saveProgress(state.activeBookId, totalPages - 1, totalPages);
      m.flushProgress().then(() => {
        alert(window.i18n.t('viewer.read_completed'));
        toggleComicOverlay();
      });
    });
  }
}

// 글로벌 핸들러 노출에 사용될 함수 재내보내기 (Re-export)
window.openReader = openReader;
window.markAsCompleted = markAsCompleted;
window.toggleComicOverlay = toggleComicOverlay;
export { toggleComicOverlay, setComicFitMode, nextComicPage, prevComicPage, nextPdfPage, prevPdfPage, prevTxtPage, nextTxtPage };
