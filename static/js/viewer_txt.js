// viewer_txt.js – 텍스트 리더(TXT) 및 EPUB 뷰어 통합 로직
import { createTxtPaginationEngine } from './viewer/txt_pagination_engine.js';
import { state } from './state.js';
import { viewerStorage } from './viewer/storage.js';

// Route all storage access through a wrapper for safer future refactors.
const localStorage = viewerStorage;

let txtChunks = [];
let txtContentLoading = false;
let currentChunkIdx = 0;
let loadedChunks = { min: 0, max: 0 };
let fullText = '';
let resizeTimeout = null;
let activeResizeHandler = null;
let txtScrollPreloadTriggered = false;
let txtScrollNextEpisodeTriggered = false;
let txtPageSnapTimeout = null;
let txtPageSnapInProgress = false;
let txtPendingRestoreTimer = null;
let txtRestoreToastAt = 0;
let txtRenderGeneration = 0;
let txtSessionGeneration = 0;
const epubChapterFetchInFlight = new Set();
const epubChapterRetryState = new Map();

// Phase-1 runtime state object for incremental modularization.
export const txtRuntimeState = {
  get txtChunks() {
    return txtChunks;
  },
  set txtChunks(value) {
    txtChunks = value;
  },
  get currentChunkIdx() {
    return currentChunkIdx;
  },
  set currentChunkIdx(value) {
    currentChunkIdx = value;
  },
  get loadedChunks() {
    return loadedChunks;
  },
  set loadedChunks(value) {
    loadedChunks = value;
  },
  get fullText() {
    return fullText;
  },
  set fullText(value) {
    fullText = value;
  },
  get txtScrollPreloadTriggered() {
    return txtScrollPreloadTriggered;
  },
  set txtScrollPreloadTriggered(value) {
    txtScrollPreloadTriggered = value;
  },
  get txtScrollNextEpisodeTriggered() {
    return txtScrollNextEpisodeTriggered;
  },
  set txtScrollNextEpisodeTriggered(value) {
    txtScrollNextEpisodeTriggered = value;
  },
  reset() {
    txtContentLoading = false;
    txtChunks = [];
    currentChunkIdx = 0;
    loadedChunks = { min: 0, max: 0 };
    fullText = '';
    txtScrollPreloadTriggered = false;
    txtScrollNextEpisodeTriggered = false;
    epubChapterRetryState.clear();
    // Annotation IDs are only unique within the currently opened book.  Keeping
    // the measured page map across viewer sessions can therefore attach an old
    // book's page number to a newly opened book before its pagination pass ends.
    epubAnnotationLocalPages.clear();
    clearAnnotationState();
  }
};

import { showViewerLoading, hideViewerLoading, showViewerError, showToast, showViewerBoundaryNotice } from './view_manager.js';
import { saveProgress as queueProgress } from './viewer_progress.js?rev=20260927-tts-session-v8';
import { captureTextResume, restoreTextResume, readTextResume } from './viewer/text_resume.js';
import { initPageStep, initReadingDirection, getComicReadingDirection, getSpreadShiftOffset, setSpreadShiftOffset } from './viewer/reader_settings.js';
import { getTxtPageAdvanceWidth, getTxtViewportPageInfo, getTxtPhysicalPageInfo, getTxtPageScrollLeft, setTxtPageScrollLeft, snapTxtPageScrollLeft, isTxtScrollLeftAtMaxPage, getTxtPageMaxScroll, applyTxtTwoPageTrailingSpacer, applyTxtImageMaxHeight } from './viewer/txt_page_utils.js?rev=20260922-reader-session-v45';
import { chunkText, formatTxtToHtml, stripHtml } from './viewer/txt_text_utils.js';
import { renderTxtChunkView, applyTxtParagraphStyles, isEpubImageOnlyHtml } from './viewer/txt_render.js';
import { getTxtAnchorInfoByMode, restoreTxtAnchorInfoByMode } from './viewer/txt_anchor_utils.js';
import { findAnchorOffset, chunkStarts } from './viewer/text_position_utils.js?rev=20260927-tts-session-v8';
import { setReadPositionProvider, reportReadNow, fetchSyncState, listenTargetForTxt, listenTargetForEpub } from './viewer/tts_sync.js?rev=20260927-tts-session-v8';
import { applyTxtSettingsCore, applyFontFamilyToElement as applyTxtFontFamily } from './viewer/txt_settings_apply.js';
import {
  prevTxtPageAction,
  nextTxtPageAction,
  txtJumpToFirstPageAction,
  txtJumpToLastPageAction,
  txtSliderInputAction,
  txtSliderChangeAction,
} from './viewer/txt_navigation.js?rev=20260927-tts-session-v8';
import { renderEpubTocPanel, jumpToTxtTocChapter, highlightEpubTocChapter, updateEpubTocPageNumbers } from './viewer/txt_toc.js?rev=20260922-reader-session-v45';
import { loadAnnotationsForBook, getAnnotations, clearAnnotationState } from './viewer/annotation_state.js';
import { applyAnnotationsToAllRenderedChunks } from './viewer/annotation_render.js';
import { decodeAnchor } from './viewer/annotation_anchor.js';
import { initAnnotationSelectionUI } from './viewer/annotation_ui.js?rev=20260922-reader-session-v45';

import {
  clearEpubChapterRetryState,
  clampNumber,
  pickEpubStartIndex,
  syncActiveEpubToc as syncActiveEpubTocExt,
  preloadEpubChapterImages,
  requestEpubChapterContent as requestEpubChapterContentExt,
  getVisibleEpubPlaceholderIndexes as getVisibleEpubPlaceholderIndexesExt,
  scheduleVisibleEpubPlaceholderRecovery as scheduleVisibleEpubPlaceholderRecoveryExt,
  hydrateEpubChapterWindow as hydrateEpubChapterWindowExt,
  requestEpubChaptersBatch as requestEpubChaptersBatchExt,
  retryVisibleEpubPlaceholders as retryVisibleEpubPlaceholdersExt,
} from './viewer/epub_loader.js';

let epubPagination = null;
let epubPaginationTimer = null;
let epubPaginationGeneration = 0;
const calculateTxtPages = createTxtPaginationEngine();
let txtPagination = null;
let txtPaginationTimer = null;
let txtPaginationGeneration = 0;
let pendingTxtFlowPosition = null;
let textResumeReady = false;

function saveProgress(bookId, pageIdx, totalPages, extraData = null) {
  if (!textResumeReady || txtPageSnapInProgress) return;
  const anchor = captureTextResume(document.getElementById('txt-scroll-wrapper'),
    document.getElementById('txt-content-area'), currentChunkIdx)
    || (state.currentViewerFormat === 'epub' ? { type: 'bookoasis-text-v1', chunkIdx: currentChunkIdx, offset: 0 } : null);
  const extra = { ...extraData, epub_session: { ...extraData?.epub_session,
    index: anchor?.chunkIdx ?? pageIdx, cfi: anchor ? JSON.stringify(anchor) : '' } };
  if (state.currentViewerFormat === 'epub') {
    const wrapper = document.getElementById('txt-scroll-wrapper');
    if (!wrapper) return;
    let fraction;
    if ((localStorage.getItem('viewer_scroll_mode') || 'page') === 'scroll') {
      const extent = wrapper.scrollHeight - wrapper.clientHeight;
      fraction = extent > 0 ? wrapper.scrollTop / extent : 0;
      totalPages = 101;
      pageIdx = Math.round(Math.max(0, Math.min(1, fraction)) * 100);
    } else {
      // A spine is not a page: opening spine 0 of 3 must not mean 33% read.
      // Wait for real pagination instead of committing an estimated chapter ratio.
      if (!epubPagination || epubPagination.bookId !== state.activeBookId) return;
      const first = getTxtPhysicalPageInfo(wrapper).first;
      const start = epubPagination.starts[currentChunkIdx] || 1;
      fraction = (start + first - 2) / Math.max(1, epubPagination.total - 1);
      pageIdx = Math.max(0, Math.min(epubPagination.total - 1, start + first - 2));
      totalPages = epubPagination.total;
    }
    extra.epub_session.percent = Math.max(0, Math.min(100, fraction * 100));
  }
  queueProgress(bookId, state.currentViewerFormat === 'epub' ? pageIdx : anchor?.chunkIdx ?? pageIdx, totalPages, extra);
}

function restoreServerTextPosition(anchor) {
  const wrapper = document.getElementById('txt-scroll-wrapper');
  return restoreTextResume(anchor, wrapper, document.getElementById('txt-content-area'), {
    scroll: (localStorage.getItem('viewer_scroll_mode') || 'page') === 'scroll',
    rtl: document.getElementById('media-viewer-modal')?.dataset.displayMode === 'two-one',
    advance: getTxtPageAdvanceWidth(wrapper),
  });
}
document.fonts?.addEventListener('loadingdone', () => {
  if (state.currentViewerFormat === 'txt' && txtChunks.length) scheduleTxtPagination(120);
});
let epubAnnotationLocalPages = new Map();

function commitEpubPaginationCounts(counts, metrics) {
  const starts = [];
  let total = 0;
  counts.forEach((count) => {
    starts.push(total + 1);
    total += Math.max(1, Number(count) || 1);
  });
  epubPagination = {
    bookId: state.activeBookId,
    mode: metrics.mode,
    step: metrics.step,
    counts,
    starts,
    total: Math.max(1, total),
  };
  updateEpubTocPageNumbers(starts);
  document.dispatchEvent(new CustomEvent('viewer-pagination-changed', {
    detail: { bookId: state.activeBookId, total: epubPagination.total },
  }));
}

function annotationPercentInChunk(item, chapterIdx) {
  if (Number.isFinite(Number(item?.percent))) {
    return Math.max(0, Math.min(100, Number(item.percent)));
  }
  const offset = Number(item?.start_offset);
  if (!Number.isFinite(offset)) return 0;
  if (String(item?.format || '').toLowerCase() === 'txt') {
    let rawStart = 0;
    for (let idx = 0; idx < chapterIdx; idx += 1) rawStart += String(txtChunks[idx] || '').length;
    const length = Math.max(1, String(txtChunks[chapterIdx] || '').length);
    return Math.max(0, Math.min(100, ((offset - rawStart) / length) * 100));
  }
  const textLength = Math.max(1, stripHtml(String(txtChunks[chapterIdx] || '')).length);
  return Math.max(0, Math.min(100, (offset / textLength) * 100));
}

export function resolveStoredTextLocation(item = {}) {
  let chapterIdx = Number(item.chapter_idx);
  if (!Number.isFinite(chapterIdx)) chapterIdx = 0;
  let migratedPercent = null;
  let legacyGlobalPage = null;
  // 이전 구현은 하단의 전체 페이지 숫자를 chapter_idx로 저장하면서 라벨을
  // "10페이지"처럼 남겼다. TOC 제목이 아닌 이 숫자 전용 라벨만 현재 페이지
  // 테이블로 역변환해 기존 잘못 저장된 책갈피도 올바른 곳으로 복구한다.
  const legacyPageMatch = String(item.label || '').trim().match(/^(\d+)페이지$/);
  const currentPagination = state.currentViewerFormat === 'epub' ? epubPagination : txtPagination;
  if (legacyPageMatch && (state.currentViewerFormat === 'epub' || state.currentViewerFormat === 'txt')
      && currentPagination?.bookId === state.activeBookId && currentPagination.mode === 'page') {
    const targetPage = Math.max(1, Math.min(currentPagination.total, Number(legacyPageMatch[1]) || 1));
    legacyGlobalPage = targetPage;
    const resolvedChapter = currentPagination.starts.findLastIndex((start) => start <= targetPage);
    if (resolvedChapter >= 0) {
      chapterIdx = resolvedChapter;
      const localPage = targetPage - currentPagination.starts[chapterIdx] + 1;
      const count = Math.max(1, Number(currentPagination.counts[chapterIdx]) || 1);
      migratedPercent = count <= 1 ? 0 : ((localPage - 1) / (count - 1)) * 100;
    }
  }
  if (String(item.format || '').toLowerCase() === 'txt' && item.chapter_idx == null) {
    const globalOffset = Math.max(0, Number(item.start_offset) || 0);
    let consumed = 0;
    chapterIdx = Math.max(0, txtChunks.length - 1);
    for (let idx = 0; idx < txtChunks.length; idx += 1) {
      const next = consumed + String(txtChunks[idx] || '').length;
      if (globalOffset < next) {
        chapterIdx = idx;
        break;
      }
      consumed = next;
    }
  }
  chapterIdx = Math.max(0, Math.min(Math.max(0, txtChunks.length - 1), chapterIdx));
  const percent = migratedPercent === null ? annotationPercentInChunk(item, chapterIdx) : migratedPercent;
  const mode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (mode === 'scroll') {
    const preceding = txtChunks.slice(0, chapterIdx).reduce((sum, chunk) => sum + Math.max(1, stripHtml(String(chunk || '')).length), 0);
    const currentLength = Math.max(1, stripHtml(String(txtChunks[chapterIdx] || '')).length);
    const totalLength = Math.max(1, txtChunks.reduce((sum, chunk) => sum + Math.max(1, stripHtml(String(chunk || '')).length), 0));
    const overallPercent = Math.max(0, Math.min(100, Math.round(((preceding + currentLength * percent / 100) / totalLength) * 100)));
    return { chapterIdx, percent, page: null, label: `${overallPercent}%` };
  }
  const pagination = state.currentViewerFormat === 'epub' ? epubPagination : txtPagination;
  if ((state.currentViewerFormat === 'epub' || state.currentViewerFormat === 'txt')
      && pagination?.bookId === state.activeBookId && pagination.mode === 'page') {
    const count = Math.max(1, Number(pagination.counts[chapterIdx]) || 1);
    const measuredAnnotationPage = state.currentViewerFormat === 'epub' && item.id != null
      ? epubAnnotationLocalPages.get(String(item.id))
      : null;
    const localPage = Number.isFinite(measuredAnnotationPage)
      ? Math.max(1, Math.min(count, measuredAnnotationPage))
      : Math.min(count, Math.floor((percent / 100) * count) + 1);
    let page = Math.min(pagination.total, pagination.starts[chapterIdx] + localPage - 1);
    if (pagination.continuous && item.id != null && item.start_offset != null) {
      const mark = document.querySelector(`mark.annotation-highlight[data-annotation-id="${CSS.escape(String(item.id))}"]`);
      if (mark) page = continuousTxtElementPage(mark);
    }
    return { chapterIdx, percent, page, globalPage: legacyGlobalPage ?? page, label: `${legacyGlobalPage ?? page}페이지` };
  }
  return { chapterIdx, percent, page: chapterIdx + 1, label: `${chapterIdx + 1}페이지` };
}

function reconcileRenderedEpubPageCount(wrapper, renderedSpan = 1) {
  if (!wrapper || !epubPagination || epubPagination.bookId !== state.activeBookId || epubPagination.mode !== 'page') return;
  const physical = getTxtPhysicalPageInfo(wrapper);
  let changed = false;
  if (renderedSpan > 1) {
    for (let offset = 0; offset < renderedSpan && currentChunkIdx + offset < epubPagination.counts.length; offset += 1) {
      if (epubPagination.counts[currentChunkIdx + offset] !== 1) {
        epubPagination.counts[currentChunkIdx + offset] = 1;
        changed = true;
      }
    }
  } else if (epubPagination.counts[currentChunkIdx] !== physical.total) {
    epubPagination.counts[currentChunkIdx] = physical.total;
    changed = true;
  }
  if (changed) {
    const counts = [...epubPagination.counts];
    const protectedEnd = Math.min(counts.length - 1, currentChunkIdx + renderedSpan - 1);
    // 이미 화면에 들어온 챕터의 실측값을 반영하되 전체 페이지 수는 마지막 미방문
    // 챕터가 남아 있는 동안 고정한다. 그렇지 않으면 챕터에 들어갈 때마다 분모가
    // 220→221처럼 흔들린다. 남은 오차는 아직 읽지 않은 마지막 챕터가 흡수하고,
    // 실제 마지막 챕터에 도달했을 때만 최종 실측값으로 확정된다.
    if (protectedEnd < counts.length - 1) {
      let balance = epubPagination.total - counts.reduce((sum, count) => sum + Math.max(1, Number(count) || 1), 0);
      if (balance > 0) {
        counts[counts.length - 1] += balance;
      } else if (balance < 0) {
        for (let idx = counts.length - 1; idx > protectedEnd && balance < 0; idx -= 1) {
          const removable = Math.min(counts[idx] - 1, -balance);
          counts[idx] -= removable;
          balance += removable;
        }
      }
    }
    commitEpubPaginationCounts(counts, epubPagination);
  }
}

function paginationMetrics() {
  const wrapper = document.getElementById('txt-scroll-wrapper');
  const content = document.getElementById('txt-content-area');
  if (!wrapper || !content) return null;
  const style = getComputedStyle(content);
  const mode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const step = localStorage.getItem('comic_page_step') === '2' && mode === 'page' ? 2 : 1;
  const gap = step === 2 ? (parseFloat(style.columnGap) || 0) : 0;
  const width = mode === 'page'
    ? (parseFloat(style.columnWidth) || Math.max(1, (wrapper.clientWidth - gap) / step))
    : Math.max(260, Math.min(850, wrapper.clientWidth));
  return {
    mode, step, gap, width,
    containerWidth: Math.max(1, wrapper.clientWidth),
    height: Math.max(240, content.clientHeight || wrapper.clientHeight),
    viewportHeight: Math.max(240, wrapper.clientHeight),
    fontSize: style.fontSize,
    fontFamily: style.fontFamily,
    lineHeight: style.lineHeight,
    letterSpacing: style.letterSpacing,
    paragraphSpacing: localStorage.getItem('viewer_paragraph_spacing') || '1.0',
  };
}

async function measureEpubChapter(html, metrics, chapterAnnotations = []) {
  if (!html || html === 'LOADING_PENDING') return { pages: 1, annotationPages: [] };
  if (isEpubImageOnlyHtml(html)) return { pages: 1, annotationPages: [] };
  const probe = document.createElement('div');
  probe.className = 'txt-content epub-pagination-probe';
  probe.style.cssText = `position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;box-sizing:border-box;width:${metrics.containerWidth}px;font-size:${metrics.fontSize};font-family:${metrics.fontFamily};line-height:${metrics.lineHeight};letter-spacing:${metrics.letterSpacing};white-space:normal;word-break:break-word;`;
  if (metrics.mode === 'page') {
    probe.style.height = `${metrics.height}px`;
    probe.style.columnWidth = `${metrics.width}px`;
    probe.style.columnGap = `${metrics.gap}px`;
    probe.style.columnFill = 'auto';
    probe.style.overflow = 'visible';
  }
  probe.innerHTML = `<div class="txt-chunk epub-chunk" style="height:100%;box-sizing:border-box">${html}</div>`;
  applyTxtParagraphStyles({ contentArea: probe, localStorage, currentViewerFormat: 'epub' });
  probe.querySelectorAll('img').forEach((img) => {
    img.style.display = 'block';
    img.style.margin = '1.2rem auto';
    img.style.maxWidth = '100%';
    img.style.height = 'auto';
    img.style.maxHeight = metrics.mode === 'page' ? `${Math.max(80, metrics.height - 56)}px` : '85vh';
    img.style.objectFit = 'contain';
    img.style.contentVisibility = 'visible';
  });
  // 실제 래퍼의 자식으로 붙여 #txt-scroll-wrapper ... 하위 선택자까지 동일하게
  // 적용한다. body 직속 숨은 DOM은 실제 뷰어 CSS를 받지 않아 챕터당 수십 페이지의
  // 오차를 만들었다. fixed/offscreen이므로 실제 scrollWidth에는 관여하지 않는다.
  const measurementHost = document.getElementById('txt-scroll-wrapper') || document.body;
  measurementHost.appendChild(probe);
  const images = [...probe.querySelectorAll('img')].filter((img) => !img.complete);
  if (images.length) {
    await Promise.race([
      Promise.all(images.map((img) => new Promise((resolve) => {
        img.addEventListener('load', resolve, { once: true });
        img.addEventListener('error', resolve, { once: true });
      }))),
      new Promise((resolve) => setTimeout(resolve, 1500)),
    ]);
  }
  await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
  let pages;
  if (metrics.mode === 'page') {
    pages = Math.max(1, Math.round((probe.scrollWidth + metrics.gap) / Math.max(1, metrics.width + metrics.gap)));
    // 두 장 보기에서 홀수 컬럼 챕터는 실제 렌더러가 마지막 빈 잎을 하나 추가해
    // 펼침면을 완성한다. 숨은 사전 계산도 같은 규칙을 써야 총 페이지 수가 챕터
    // 진입 시 1씩 늘어나지 않는다.
    if (metrics.step === 2 && pages > 1 && pages % 2 === 1) pages += 1;
  } else {
    pages = Math.max(1, Math.ceil(probe.scrollHeight / metrics.viewportHeight));
  }
  const annotationPages = [];
  if (metrics.mode === 'page' && chapterAnnotations.length) {
    const chunkEl = probe.querySelector('.txt-chunk');
    const probeRect = probe.getBoundingClientRect();
    const unit = Math.max(1, metrics.width + metrics.gap);
    chapterAnnotations.forEach((annotation) => {
      const decoded = decodeAnchor(chunkEl, annotation);
      const rect = decoded.range?.getBoundingClientRect();
      if (!rect || !Number.isFinite(rect.left)) return;
      const localPage = Math.max(1, Math.min(pages,
        Math.floor(Math.max(0, rect.left - probeRect.left) / unit) + 1));
      annotationPages.push([String(annotation.id), localPage]);
    });
  }
  probe.remove();
  return { pages, annotationPages };
}

function createTxtMeasurementProbe(rawText, metrics) {
  if (!rawText) return null;

  const probe = document.createElement('div');
  probe.className = 'txt-content txt-pagination-probe';
  probe.style.cssText = `position:fixed;left:-100000px;top:0;visibility:hidden;pointer-events:none;box-sizing:border-box;width:${metrics.containerWidth}px;font-size:${metrics.fontSize};font-family:${metrics.fontFamily};line-height:${metrics.lineHeight};letter-spacing:${metrics.letterSpacing};white-space:normal;word-break:break-all;`;
  if (metrics.mode === 'page') {
    probe.style.height = `${metrics.height}px`;
    probe.style.columnWidth = `${metrics.width}px`;
    probe.style.columnGap = `${metrics.gap}px`;
    probe.style.columnFill = 'auto';
    probe.style.overflow = 'visible';
  }
  probe.innerHTML = `<div class="txt-chunk" style="height:100%;box-sizing:border-box">${formatTxtToHtml(String(rawText))}</div>`;
  applyTxtParagraphStyles({ contentArea: probe, localStorage, currentViewerFormat: 'txt' });

  const measurementHost = document.getElementById('txt-scroll-wrapper') || document.body;
  measurementHost.appendChild(probe);
  return probe;
}

function readTxtMeasurementProbe(probe, metrics) {
  if (!probe) return 1;
  let pages;
  if (metrics.mode === 'page') {
    pages = Math.max(1, Math.round((probe.scrollWidth + metrics.gap) / Math.max(1, metrics.width + metrics.gap)));
    if (metrics.step === 2 && pages > 1 && pages % 2 === 1) pages += 1;
  } else {
    pages = Math.max(1, Math.ceil(probe.scrollHeight / metrics.viewportHeight));
  }
  return pages;
}

async function recalculateEpubPagination(generation) {
  if (state.currentViewerFormat !== 'epub' || !txtChunks.length) return;
  const bookId = state.activeBookId;
  // 최초 오픈 직후 주변 챕터 프리패치가 이미 진행 중일 수 있다. 그 요청을 기다리지 않고
  // LOADING_PENDING을 1페이지로 계산하면 잠시 17/35페이지처럼 보였다가 모드 전환 후
  // 수백 페이지로 튀는 현상이 생긴다. 진행 중인 배치가 끝날 때까지 기다린 뒤 계산한다.
  for (let attempt = 0; attempt < 150 && txtChunks.some((value) => value === 'LOADING_PENDING'); attempt += 1) {
    await new Promise((resolve) => setTimeout(resolve, 100));
    if (generation !== epubPaginationGeneration || state.activeBookId !== bookId) return;
  }
  if (txtChunks.some((value) => value === 'LOADING_PENDING')) {
    scheduleEpubPagination(500);
    return;
  }
  const missing = txtChunks.map((value, idx) => (value === null ? idx : -1)).filter((idx) => idx >= 0);
  if (missing.length) await requestEpubChaptersBatchExt(txtChunks, missing);
  if (generation !== epubPaginationGeneration || state.activeBookId !== bookId) return;
  if (document.fonts?.ready) await document.fonts.ready.catch(() => {});
  const metrics = paginationMetrics();
  if (!metrics) return;
  await loadAnnotationsForBook(bookId, state.currentLibraryType);
  const annotationsByChapter = new Map();
  getAnnotations().forEach((annotation) => {
    if (String(annotation.format || '').toLowerCase() !== 'epub') return;
    const idx = Number(annotation.chapter_idx);
    if (!Number.isFinite(idx)) return;
    if (!annotationsByChapter.has(idx)) annotationsByChapter.set(idx, []);
    annotationsByChapter.get(idx).push(annotation);
  });
  // 챕터를 순차 측정하면 깨진 이미지 하나당 timeout을 누적해 모드 전환 뒤 오래도록
  // 이전 모드 페이지 수가 남는다. 독립된 숨은 DOM이므로 병렬 측정하고 한 번에 확정한다.
  const measured = [];
  const chunks = txtChunks;
  // Limit live measurement DOM and yield between batches so mode switches and
  // navigation are still handled on long books. Cancel obsolete layouts early.
  for (let start = 0; start < chunks.length; start += 6) {
    if (generation !== epubPaginationGeneration || state.activeBookId !== bookId) return;
    measured.push(...await Promise.all(chunks.slice(start, start + 6).map((html, offset) =>
      measureEpubChapter(html, metrics, annotationsByChapter.get(start + offset) || []))));
    await new Promise(resolve => setTimeout(resolve, 0));
  }
  if (generation !== epubPaginationGeneration || state.activeBookId !== bookId) return;
  const counts = measured.map((entry) => entry.pages);
  epubAnnotationLocalPages = new Map(measured.flatMap((entry) => entry.annotationPages));
  commitEpubPaginationCounts(counts, metrics);
  updateTxtSeekBar();
}

async function recalculateTxtPagination(generation) {
  if (state.currentViewerFormat !== 'txt' || !txtChunks.length) return;
  const bookId = state.activeBookId;
  const chunks = txtChunks;
  const isCurrent = () => generation === txtPaginationGeneration && state.activeBookId === bookId
    && state.currentViewerFormat === 'txt' && txtChunks === chunks;
  if (!isCurrent()) return;
  if (document.fonts?.ready) await document.fonts.ready.catch(() => {});
  if (!isCurrent()) return;
  const metrics = paginationMetrics();
  if (!metrics) return;
  const style = getComputedStyle(document.getElementById('txt-content-area'));
  if (metrics.mode === 'page' && document.querySelector('#txt-content-area .txt-flow-chunk')) {
    const wrapper = document.getElementById('txt-scroll-wrapper');
    const content = document.getElementById('txt-content-area');
    const rect = content.getBoundingClientRect();
    const rtl = document.getElementById('media-viewer-modal')?.dataset.displayMode === 'two-one';
    const unit = metrics.width + metrics.gap;
    const starts = Array.from(content.querySelectorAll('.txt-flow-chunk'), chunk => {
      const range = document.createRange();
      const node = document.createTreeWalker(chunk, NodeFilter.SHOW_TEXT).nextNode();
      if (!node) return 1;
      range.setStart(node, 0); range.setEnd(node, Math.min(1, node.length));
      const r = range.getBoundingClientRect();
      return Math.max(1, Math.floor(((rtl ? rect.right - r.right : r.left - rect.left) + 1) / unit) + 1);
    });
    const total = getTxtPhysicalPageInfo(wrapper).total;
    txtPagination = { bookId, mode: 'page', step: metrics.step, continuous: true, starts,
      counts: starts.map((start, idx) => Math.max(1, (starts[idx + 1] || total) - start + 1)), total };
    if (pendingTxtFlowPosition) {
      const pos = pendingTxtFlowPosition;
      pendingTxtFlowPosition = null;
      const base = pos.flowVersion === 1 ? 0 : Math.floor(((starts[pos.chunkIdx] || 1) - 1) / metrics.step) * getTxtPageAdvanceWidth(wrapper);
      setTxtPageScrollLeft(wrapper, base + (Number(pos.scrollLeft) || 0));
      if (pos.anchor) restoreTxtAnchorInfo(pos.anchor);
      if (pos.serverAnchor) restoreServerTextPosition(pos.serverAnchor);
    }
    textResumeReady = true;
    document.dispatchEvent(new CustomEvent('viewer-pagination-changed', {detail:{bookId,format:'txt',total}}));
    updateTxtSeekBar();
    return;
  }
  const key = JSON.stringify([state.currentLibraryType, bookId, metrics,
    getComputedStyle(document.documentElement).fontSize,
    style.fontWeight, style.fontStyle, style.fontStretch, style.wordSpacing,
    style.fontFeatureSettings, style.fontVariationSettings,
    Array.from(document.fonts || [], font => [font.family, font.style, font.weight, font.status])]);
  const counts = await calculateTxtPages({ key, chunks, isCurrent,
    createProbe: chunk => createTxtMeasurementProbe(chunk, metrics),
    readProbe: probe => readTxtMeasurementProbe(probe, metrics),
  });
  if (!counts || !isCurrent()) return;
  const starts = [];
  let total = 0;
  counts.forEach((count) => {
    starts.push(total + 1);
    total += Math.max(1, Number(count) || 1);
  });
  txtPagination = {
    bookId,
    mode: metrics.mode,
    step: metrics.step,
    counts,
    starts,
    total: Math.max(1, total),
  };
  if (pendingTxtFlowPosition) {
    const pos = pendingTxtFlowPosition;
    pendingTxtFlowPosition = null;
    const wrapper = document.getElementById('txt-scroll-wrapper');
    const chunk = document.querySelector(`#txt-content-area [data-idx="${pos.chunkIdx}"]`);
    if (wrapper) wrapper.scrollTop = chunk?.offsetTop || pos.scrollTop || 0;
    if (pos.serverAnchor) restoreServerTextPosition(pos.serverAnchor);
  }
  textResumeReady = true;
  document.dispatchEvent(new CustomEvent('viewer-pagination-changed', {
    detail: { bookId, format: 'txt', total: txtPagination.total },
  }));
  updateTxtSeekBar();
}

function scheduleEpubPagination(delay = 120) {
  clearTimeout(epubPaginationTimer);
  // 모드/크기 변경 즉시 이미 실행 중인 이전 측정을 무효화한다. 타이머가 실제로
  // 시작될 때까지 기다리면 한 장 보기 측정값이 두 장 보기에 뒤늦게 덮어써서
  // 챕터 진입 시 총 페이지가 변한다.
  const generation = ++epubPaginationGeneration;
  // 새 뷰포트/보기 모드의 계산이 끝나기 전에는 이전 계산값이나 챕터 수를
  // 전체 페이지처럼 보여주지 않는다. 그 값이 4/17 -> 4/249처럼 깜빡이는 원인이 된다.
  epubPagination = null;
  if ((localStorage.getItem('viewer_scroll_mode') || 'page') === 'page') updateTxtSeekBar();
  epubPaginationTimer = setTimeout(() => recalculateEpubPagination(generation).catch((error) => {
    console.warn('[Viewer-EPUB] 페이지 계산 실패:', error);
  }), delay);
}

function scheduleTxtPagination(delay = 120) {
  clearTimeout(txtPaginationTimer);
  const generation = ++txtPaginationGeneration;
  txtPagination = null;
  if ((localStorage.getItem('viewer_scroll_mode') || 'page') === 'page') updateTxtSeekBar();
  txtPaginationTimer = setTimeout(() => recalculateTxtPagination(generation).catch((error) => {
    console.warn('[Viewer-TXT] 페이지 계산 실패:', error);
  }), delay);
}

function syncActiveEpubToc(scrollIntoView = false) {
  syncActiveEpubTocExt(currentChunkIdx, scrollIntoView);
}

function requestEpubChapterContent(chapterIdx, options = {}) {
  return requestEpubChapterContentExt(txtChunks, chapterIdx, options);
}

function getVisibleEpubPlaceholderIndexes(maxCount = 10) {
  return getVisibleEpubPlaceholderIndexesExt(txtChunks, maxCount);
}

function scheduleVisibleEpubPlaceholderRecovery(delays = [50, 180, 450]) {
  scheduleVisibleEpubPlaceholderRecoveryExt(txtChunks, delays);
}

function hydrateEpubChapterWindow(centerIdx, radius = 10) {
  hydrateEpubChapterWindowExt(txtChunks, centerIdx, radius);
}

function retryVisibleEpubPlaceholders(maxCount = 8) {
  retryVisibleEpubPlaceholdersExt(txtChunks, maxCount);
}

// 스크롤/터치/리사이즈 런타임 리스너를 등록한다. EPUB과 일반 TXT 두 로딩 경로
// 모두에서 호출되어야 한다 — 예전에는 TXT 경로에만 있어서 EPUB 책은 브라우저
// 리사이즈 시 컬럼 폭이 갱신되지 않아 2페이지 모드가 1페이지처럼 깨지는 버그가 있었다.
function setupTxtViewerRuntimeListeners() {
  const contentArea = document.getElementById('txt-content-area');
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  if (scrollWrapper) {
    if (scrollWrapper.__txtScrollHandler) {
      scrollWrapper.removeEventListener('scroll', scrollWrapper.__txtScrollHandler);
    }
    if (scrollWrapper.__txtTouchHandler) {
      scrollWrapper.removeEventListener('touchend', scrollWrapper.__txtTouchHandler);
      scrollWrapper.removeEventListener('touchcancel', scrollWrapper.__txtTouchHandler);
    }

    const triggerNextEpisodeIfNeeded = () => {
      const mode = localStorage.getItem('viewer_scroll_mode') || 'page';
      if (mode !== 'scroll') return;

      const scrollHeight = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
      if (scrollHeight <= 0) return;

      const ratio = scrollWrapper.scrollTop / scrollHeight;
      const newIdx = Math.min(txtChunks.length - 1, Math.max(0, Math.floor(ratio * txtChunks.length)));
      const isAtAbsoluteEnd = scrollWrapper.scrollTop + scrollWrapper.clientHeight >= scrollWrapper.scrollHeight - 15;
      if (!isAtAbsoluteEnd || isTransitioning || txtScrollNextEpisodeTriggered || newIdx < txtChunks.length - 1) return;

      isTransitioning = true;
      txtScrollNextEpisodeTriggered = true;
      import('./viewer_next_episode.js').then(m => {
        m.handleNextEpisodeDirect(state.activeBookId);
        setTimeout(() => { isTransitioning = false; }, 300);
      });
    };

    // 스크롤 모드 시 이전 진척도 스크롤 위치 복구
    const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
    if (textResumeReady && scrollMode === 'scroll' && currentChunkIdx > 0 && txtChunks.length > 0) {
      txtPendingRestoreTimer = setTimeout(() => {
        const ratio = currentChunkIdx / txtChunks.length;
        scrollWrapper.scrollTop = scrollWrapper.scrollHeight * ratio;
        txtPendingRestoreTimer = null;
      }, 150);
    }

    let isTransitioning = false;
    let rAfPending = false;
    let scrollDebounceTimeout = null;

    const processScroll = () => {
      rAfPending = false;
      const mode = localStorage.getItem('viewer_scroll_mode') || 'page';
      if (mode === 'page') {
        if (txtPageSnapInProgress) return;
        clearTimeout(txtPageSnapTimeout);
        txtPageSnapTimeout = setTimeout(() => {
          txtPageSnapInProgress = true;
          snapTxtPageScrollLeft(scrollWrapper);
          txtPageSnapInProgress = false;
          updateTxtSeekBar();
          logActiveViewportText();
          saveDetailPosition();
        }, 90);
        return;
      }

      if (mode !== 'scroll') return;

      const scrollHeight = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
      if (scrollHeight <= 0) return;

      const currentScroll = scrollWrapper.scrollTop;
      const chunks = contentArea.querySelectorAll('.txt-scroll-chunk');
      let detectedIdx = 0;

      for (let chunk of chunks) {
        const idx = parseInt(chunk.getAttribute('data-idx'));
        if (currentScroll >= chunk.offsetTop - 120) {
          detectedIdx = idx;
        } else {
          break;
        }
      }

      const newIdx = Math.min(txtChunks.length - 1, Math.max(0, detectedIdx));
      const ratio = scrollHeight > 0 ? scrollWrapper.scrollTop / scrollHeight : 0;
      const isEpubMode = (state.currentViewerFormat === 'epub');

      // EPUB 스크롤 모드: 현재 화면 뷰포트 인근(전후 10개 챕터) null 챕터 선제 동적 로드
      if (isEpubMode) {
        hydrateEpubChapterWindow(newIdx, 10);
      }

      if (!txtScrollPreloadTriggered && ratio >= 0.9 && txtChunks.length > 1) {
        txtScrollPreloadTriggered = true;
        saveProgress(
          state.activeBookId,
          Math.min(txtChunks.length - 1, newIdx),
          txtChunks.length,
          isEpubMode ? { epub_session: { index: newIdx, percent: Math.round(ratio * 100) } } : null
        );
      }

      if (newIdx !== currentChunkIdx) {
        currentChunkIdx = newIdx;
        const pageInfo = document.getElementById('comic-overlay-page-info');
        if (pageInfo) {
          pageInfo.textContent = i18n.t('viewer.txt_chunk_info', {current: currentChunkIdx + 1, total: txtChunks.length});
        }
        syncActiveEpubToc();

        // EPUB 모드: 현재 감지된 챕터 및 이전/다음 챕터가 null이면 동적 로드
        if (isEpubMode) {
          const fetchList = [newIdx, newIdx - 1, newIdx + 1].filter(i => i >= 0 && i < txtChunks.length && (txtChunks[i] === null || txtChunks[i] === 'LOADING_PENDING'));
          fetchList.forEach(fIdx => {
            requestEpubChapterContent(fIdx);
          });
        }

        const targetChunk = contentArea.querySelector(`.txt-scroll-chunk[data-idx="${newIdx}"]`);
        let fingerprint = '';
        if (targetChunk) {
          fingerprint = String(targetChunk.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180);
        }
        const epubSessionPayload = isEpubMode
          ? {
              epub_session: {
                index: newIdx,
                percent: Math.max(0, Math.min(100, Math.round(ratio * 100))),
                fingerprint: fingerprint || undefined
              }
            }
          : null;
        saveProgress(state.activeBookId, currentChunkIdx, txtChunks.length, epubSessionPayload);
      }

      updateTxtSeekBar();

      triggerNextEpisodeIfNeeded();

      // Debounce heavy operations (logActiveViewportText, saveDetailPosition, fine-grained progress)
      clearTimeout(scrollDebounceTimeout);
      scrollDebounceTimeout = setTimeout(() => {
        logActiveViewportText();
        saveDetailPosition();
        if (isEpubMode) {
          const targetChunk = contentArea.querySelector(`.txt-scroll-chunk[data-idx="${currentChunkIdx}"]`);
          let fingerprint = '';
          if (targetChunk) {
            fingerprint = String(targetChunk.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180);
          }
          const epubSessionPayload = {
            epub_session: {
              index: currentChunkIdx,
              percent: Math.max(0, Math.min(100, Math.round(ratio * 100))),
              fingerprint: fingerprint || undefined
            }
          };
          saveProgress(state.activeBookId, currentChunkIdx, txtChunks.length, epubSessionPayload);
        }
      }, 150);
    };

    const scrollHandler = () => {
      if (!rAfPending) {
        rAfPending = true;
        requestAnimationFrame(processScroll);
      }
    };
    scrollWrapper.addEventListener('scroll', scrollHandler, { passive: true });
    scrollWrapper.__txtScrollHandler = scrollHandler;

    const touchHandler = () => {
      triggerNextEpisodeIfNeeded();
    };
    scrollWrapper.__txtTouchHandler = touchHandler;
    scrollWrapper.addEventListener('touchend', touchHandler, { passive: true });
    scrollWrapper.addEventListener('touchcancel', touchHandler, { passive: true });
  }

  let lastWindowWidth = window.innerWidth;
  const handleResize = () => {
    const wrapper = document.getElementById('txt-scroll-wrapper');
    if (!wrapper) return;
    const mode = localStorage.getItem('viewer_scroll_mode') || 'page';

    const currentWidth = window.innerWidth;
    const widthChanged = Math.abs(currentWidth - lastWindowWidth) > 5;
    lastWindowWidth = currentWidth;
    if (state.currentViewerFormat === 'epub') scheduleEpubPagination(260);
    if (state.currentViewerFormat === 'txt') scheduleTxtPagination(260);

    if (mode === 'page') {
      const prevStepWidth = getTxtPageAdvanceWidth(wrapper);
      // 챕터 마지막의 짧은 페이지(스프레드)에 있을 때는 stepWidth 배수 기반 인덱스
      // 계산이 부정확할 수 있으므로(snapTxtPageScrollLeft와 동일한 문제), 그 경우
      // 인덱스 재구성 대신 "마지막 페이지였다"는 사실 자체를 보존한다.
      const wasAtLastPage = isTxtScrollLeftAtMaxPage(wrapper);
      const currentColumnIdx = Math.round(getTxtPageScrollLeft(wrapper) / prevStepWidth);
      // Resize relayout should preserve current visual page, not stale saved localStorage position.
      applyTxtSettings({ previousMode: mode, skipSavedPositionRestore: true });
      const contentArea = document.getElementById('txt-content-area');
      applyTxtImageMaxHeight(wrapper, contentArea);
      applyTxtTwoPageTrailingSpacer(wrapper, contentArea);
      const newStepWidth = getTxtPageAdvanceWidth(wrapper);
      setTxtPageScrollLeft(wrapper, wasAtLastPage ? getTxtPageMaxScroll(wrapper) : currentColumnIdx * newStepWidth);
      snapTxtPageScrollLeft(wrapper);
      logActiveViewportText();
    } else {
      // In scroll mode, mobile address bar toggles change height only. Skip DOM re-render if width hasn't changed.
      if (!widthChanged) return;

      const beforeHeight = wrapper.scrollHeight - wrapper.clientHeight;
      const ratio = beforeHeight > 0 ? wrapper.scrollTop / beforeHeight : 0;
      // Scroll mode resize also preserves ratio instead of restoring stale saved position.
      applyTxtSettings({ previousMode: mode, skipSavedPositionRestore: true });
      const afterHeight = wrapper.scrollHeight - wrapper.clientHeight;
      if (afterHeight > 0) {
        wrapper.scrollTop = afterHeight * ratio;
      }
      logActiveViewportText();
    }
  };

  if (activeResizeHandler) {
    window.removeEventListener('resize', activeResizeHandler);
  }
  activeResizeHandler = () => {
    clearTimeout(resizeTimeout);
    resizeTimeout = setTimeout(handleResize, 100);
  };
  window.addEventListener('resize', activeResizeHandler, { passive: true });
}

export function initTxtViewer(bookId, initialPageIdx = 0) {
  console.log(`[Viewer-Txt] initTxtViewer - 콘텐츠 요청 중: bookId=${bookId}, initialPageIdx=${initialPageIdx}, format=${state.currentViewerFormat}`);
  const pane = document.getElementById('txt-viewer-container');
  const contentArea = document.getElementById('txt-content-area');
  if (!pane || !contentArea) return;
  const sessionId = ++txtSessionGeneration;
  textResumeReady = false;
  const isCurrentSession = () => sessionId === txtSessionGeneration && state.activeBookId === bookId;
  contentArea.dataset.viewerBookId = String(bookId);
  contentArea.dataset.viewerSession = String(sessionId);
  txtContentLoading = state.currentViewerFormat === 'txt';
  if (txtContentLoading) contentArea.textContent = '현재 로딩중입니다.';
  pane.style.display = 'block';
  epubChapterRetryState.clear();

  loadAnnotationsForBook(bookId, state.currentLibraryType).then(() => {
    if (!isCurrentSession()) return;
    const contentArea = document.getElementById('txt-content-area');
    applyAnnotationsToAllRenderedChunks({
      contentArea,
      format: state.currentViewerFormat === 'epub' ? 'epub' : 'txt',
      txtChunks,
    });
  });
  initAnnotationSelectionUI(() => txtChunks);

  // 뷰어 여백(Padding) 설정 동적 적용
  import('./viewer/viewer_padding.js').then(m => {
    const padTop = localStorage.getItem('viewer_padding_top') || '40';
    const padBottom = localStorage.getItem('viewer_padding_bottom') || '60';
    const padLeft = localStorage.getItem('viewer_padding_left') || '20';
    const padRight = localStorage.getItem('viewer_padding_right') || '20';
    m.applyViewerPaddingRealtime('novel', 'top', padTop);
    m.applyViewerPaddingRealtime('novel', 'bottom', padBottom);
    m.applyViewerPaddingRealtime('novel', 'left', padLeft);
    m.applyViewerPaddingRealtime('novel', 'right', padRight);
  }).catch(e => {
    console.error('[Viewer-Txt] Failed to dynamically load viewer_padding.js:', e);
  });
  
  const txtCtrl = document.getElementById('txt-controls');
  if (txtCtrl) txtCtrl.style.display = 'none';
  
  showViewerLoading(i18n.t("viewer.loading_txt_title"), i18n.t("viewer.loading_txt_sub"));
  
  const isEpub = (state.currentViewerFormat === 'epub');
  const ttsSyncPromise = fetchSyncState(state.currentLibraryType, bookId);
  setReadPositionProvider(currentReadPosition);
  
  if (isEpub) {
    // ─── EPUB 초고속 렌더링: 1단계 /api/media/epub/meta 요청 (50ms) ───
    fetch(`/api/media/epub/meta?db_type=${state.currentLibraryType}&book_id=${bookId}`)
      .then(res => {
        if (!res.ok) throw new Error(i18n.t('viewer.error_txt_load'));
        return res.json();
      })
      .then(async meta => {
        if (!isCurrentSession()) return;
        const totalChapters = Number(meta?.total_chapters);
        if (!Number.isInteger(totalChapters) || totalChapters <= 0) {
          throw new Error(meta?.error || 'EPUB 목차에서 챕터를 찾지 못했습니다.');
        }
        txtChunks = new Array(totalChapters).fill(null);
        
        const tocList = meta.toc || [];
        renderEpubToc(tocList);

        let startIdx = pickEpubStartIndex(totalChapters, initialPageIdx, null);

        let serverEpubSession = null;
        try {
          const stateRes = await fetch(`/api/media/progress-state?db_type=${state.currentLibraryType}&book_id=${bookId}&_ts=${Date.now()}`, {
            cache: 'no-store'
          });
          if (stateRes.ok) {
            const stateData = await stateRes.json();
            if (!isCurrentSession()) return;
            if (stateData && stateData.success && stateData.state && stateData.state.epub_session) {
              serverEpubSession = stateData.state.epub_session;
            }
          }
        } catch (_) {}

        if (serverEpubSession) {
          startIdx = pickEpubStartIndex(totalChapters, initialPageIdx, serverEpubSession);
        } else {
          const savedPosStr = localStorage.getItem(`viewer_last_pos_${bookId}`);
          if (savedPosStr) {
            try {
              const pos = JSON.parse(savedPosStr);
              if (pos && pos.chunkIdx !== undefined && pos.chunkIdx < totalChapters) {
                startIdx = pos.chunkIdx;
              }
            } catch(e) {}
          }
        }

        const ttsTarget = listenTargetForEpub(await ttsSyncPromise, totalChapters);
        if (ttsTarget) startIdx = ttsTarget.chunkIdx;

        startIdx = Math.max(0, Math.min(totalChapters - 1, parseInt(startIdx, 10) || 0));
        currentChunkIdx = startIdx;

        // ─── 2단계: 현재 읽고 있는 챕터만 즉시 청크 스트리밍 렌더링 (0.01초) ───
        fetch(`/api/media/epub/chapter?db_type=${state.currentLibraryType}&book_id=${bookId}&chapter_idx=${startIdx}`)
          .then(cRes => {
            if (!cRes.ok) throw new Error(`EPUB 챕터 요청 실패 (HTTP ${cRes.status})`);
            return cRes.json();
          })
          .then(async cData => {
            if (!isCurrentSession()) return;
            if (!cData || typeof cData.content !== 'string') {
              throw new Error(cData?.error || 'EPUB 챕터 내용이 비어 있습니다.');
            }
            hideViewerLoading();
            txtChunks[startIdx] = cData.content || '<p>내용이 없습니다.</p>';
            
            initReadingDirection();
            initPageStep();
            renderCurrentChunk(true);
            // scrollWrapper에 아직 scroll-mode-page 클래스가 안 붙어 있는 최초 오픈 시점이라,
            // previousMode를 안 넘기면 실제 설정이 '페이지(2장)' 모드여도 내부적으로
            // "scroll → page 모드 전환"으로 오판해 더블 rAF로 지연 적용된다. 그 사이
            // 컬럼 미설정 상태로 첫 페인트가 되어 1페이지 폭처럼 보이는 원인이 되므로,
            // 최초 렌더링임을 명시해 동기적으로 바로 적용되게 한다.
            applyTxtSettings({ previousMode: getViewerSettings().scrollMode, skipSavedPositionRestore: !!serverEpubSession, resumePending: true });
            setupTxtViewerRuntimeListeners();
            await document.fonts?.ready;
            await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
            if (!isCurrentSession()) return;
            const serverAnchor = readTextResume(serverEpubSession);
            if (serverAnchor) restoreServerTextPosition(serverAnchor);
            else if (getViewerSettings().scrollMode === 'scroll') {
              const chunk = contentArea.querySelector(`[data-idx="${startIdx}"]`);
              document.getElementById('txt-scroll-wrapper').scrollTop = chunk?.offsetTop || 0;
            }
            if (ttsTarget) applyListenTarget(ttsTarget);
            textResumeReady = true;
            updateTxtSeekBar();

            // ─── 3단계: 이전/다음 챕터 백그라운드 프리패치 (전후 10개 챕터 확장) ───
            // hydrateEpubChapterWindow는 이제 반경 내 미로드 챕터를 배치 API 1회 호출로
            // 묶어서 요청하므로(서버에서 zip을 1번만 오픈), 반경을 키워도 zip 재오픈 부담이 없다.
            hydrateEpubChapterWindow(startIdx, 10);
            scheduleEpubPagination(180);
          })
          .catch(err => {
            if (!isCurrentSession()) return;
            hideViewerLoading();
            showViewerError(i18n.t('viewer.error_txt_load'));
          });
      })
      .catch(err => {
        if (!isCurrentSession()) return;
        hideViewerLoading();
        showViewerError(i18n.t('viewer.error_txt_load'));
      });
    return;
  }

  const url = `/api/media/txt?db_type=${state.currentLibraryType}&book_id=${bookId}`;
  fetch(url)
    .then(res => {
      if (!res.ok) throw new Error(i18n.t('viewer.error_txt_load'));
      return res.text();
    })
    .then(async data => {
      if (!isCurrentSession()) return;
      hideViewerLoading();
      txtScrollPreloadTriggered = false;
      txtScrollNextEpisodeTriggered = false;

      fullText = data;
      txtChunks = chunkText(data, 4000);
      txtContentLoading = false;
      // TXT는 실제 목차(TOC)가 없지만, renderEpubToc([])의 폴백 경로(챕터 번호 나열)로
      // 여전히 패널을 띄운다 — 북마크 탭이 이 패널에 얹혀 있어서, 패널 자체를 없애면
      // TXT에서는 북마크 기능을 아예 쓸 수 없게 된다.
      renderEpubToc([]);

      let startIdx = initialPageIdx;

      // Cross-device resume: prefer server pointer / pages_read when available for both TXT and EPUB
      let serverEpubSession = null;
      let serverPagesRead = 0;
      try {
        const stateRes = await fetch(`/api/media/progress-state?db_type=${state.currentLibraryType}&book_id=${bookId}&_ts=${Date.now()}`, {
          cache: 'no-store'
        });
        if (stateRes.ok) {
          const stateData = await stateRes.json();
          if (!isCurrentSession()) return;
          if (stateData && stateData.success && stateData.state) {
            if (stateData.state.epub_session) {
              serverEpubSession = stateData.state.epub_session;
            }
            if (typeof stateData.state.pages_read === 'number' && stateData.state.pages_read > 0) {
              serverPagesRead = stateData.state.pages_read;
            }
          }
        }
      } catch (_) {}

      const savedPosStr = localStorage.getItem(`viewer_last_pos_${bookId}`);
      if (savedPosStr) {
        try {
          const pos = JSON.parse(savedPosStr);
          if (pos && pos.chunkIdx !== undefined) {
            startIdx = pos.chunkIdx;
            console.log(`[Viewer-Txt] 로컬 저장소에서 챕터 인덱스 감지: ${startIdx}`);
          }
        } catch(e) {}
      }

      if (serverPagesRead > 0) {
        startIdx = Math.max(0, serverPagesRead - 1);
        console.log(`[Viewer-Txt] Server progress-state fetched: chunk ${startIdx + 1}`);
      }

      if (isEpub && serverEpubSession) {
        startIdx = pickEpubStartIndex(txtChunks.length, serverPagesRead > 0 ? serverPagesRead : startIdx, serverEpubSession);

        // Fallback backup pointer: text fingerprint match.
        const fp = String(serverEpubSession.fingerprint || '').trim();
        if (fp) {
          const matchedIdx = txtChunks.findIndex(ch => stripHtml(ch).includes(fp));
          if (matchedIdx >= 0) {
            startIdx = matchedIdx;
          }
        }
      }

      if (isEpub && txtChunks.length > 0) {
        startIdx = Math.max(0, Math.min(txtChunks.length - 1, parseInt(startIdx, 10) || 0));
      }

      const ttsTarget = isEpub ? null : listenTargetForTxt(await ttsSyncPromise, fullText, txtChunks);
      if (ttsTarget) startIdx = ttsTarget.chunkIdx;

      currentChunkIdx = startIdx;

      pendingTxtFlowPosition = { chunkIdx: startIdx, scrollLeft: 0 };
      if (!ttsTarget && savedPosStr && serverPagesRead === 0) {
        try { pendingTxtFlowPosition = JSON.parse(savedPosStr); } catch (_) {}
      }
      const serverAnchor = readTextResume(serverEpubSession);
      if (!ttsTarget && serverAnchor && serverAnchor.chunkIdx < txtChunks.length) {
        currentChunkIdx = serverAnchor.chunkIdx;
        pendingTxtFlowPosition = { chunkIdx: currentChunkIdx, serverAnchor };
      }

      initReadingDirection();
      initPageStep();
      renderCurrentChunk(true);
      // 최초 오픈 시 previousMode 오판 방지 (위 스트리밍 경로와 동일한 이유)
      applyTxtSettings({ previousMode: getViewerSettings().scrollMode, skipSavedPositionRestore: true, resumePending: true });

      setupTxtViewerRuntimeListeners();
      if (ttsTarget) applyListenTarget(ttsTarget);
      scheduleTxtPagination(180);
    })
    .catch((err) => {
      if (!isCurrentSession()) return;
      console.error('[Viewer-Txt] 로딩 에러 발생:', err);
      txtContentLoading = false;
      hideViewerLoading();
      showViewerError(i18n.t("viewer.error_txt_title"), i18n.t("viewer.error_txt_sub"));
    });
}

function cancelPendingTxtRestore() {
  clearTimeout(txtPageSnapTimeout);
  if (txtPendingRestoreTimer) {
    clearTimeout(txtPendingRestoreTimer);
    txtPendingRestoreTimer = null;
  }
}

function showTxtRestoreLoadingToast(msg = null) {
  const now = Date.now();
  if (now - txtRestoreToastAt < 300) return;
  txtRestoreToastAt = now;
  if (typeof showToast === 'function') {
    showToast(typeof msg === 'string' ? msg : '로딩중입니다', 'info');
  }
}

function renderCurrentChunk(initMode = false, onSettled) {
  const contentArea = document.getElementById('txt-content-area');
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  if (!contentArea) return;
  // An explicit seek/TOC/settings render supersedes a pending chapter turn.
  if (txtPageSnapInProgress && typeof onSettled !== 'function') {
    txtPageSnapInProgress = false;
    if (scrollWrapper) scrollWrapper.style.visibility = '';
  }
  const renderGeneration = ++txtRenderGeneration;

  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const isEpub = (state.currentViewerFormat === 'epub');

  // EPUB 메타 응답 전에 보기 방식/글자 설정이 바뀌면 렌더가 먼저 호출될 수 있다.
  // 이때 빈 txtChunks를 실제 빈 책으로 표시하지 말고 로딩 상태를 유지한다.
  if (isEpub && txtChunks.length === 0) {
    contentArea.innerHTML = '<div class="epub-ch-loading" style="padding:2rem;text-align:center;opacity:.55;">챕터 불러오는 중...</div>';
    return;
  }
  if (!isEpub && txtContentLoading) {
    contentArea.textContent = '현재 로딩중입니다.';
    return;
  }

  // 이미지형 EPUB의 2장 보기에서는 슬라이더/진행률 복원으로 펼침면의 두 번째
  // 항목을 직접 가리켜도 그 항목만 단독 렌더링하지 않고 올바른 펼침면 시작점으로
  // 되돌린다. 표지 단독이면 0, (1,2), (3,4)… 순서가 된다.
  if (isEpub
      && scrollMode === 'page'
      && (localStorage.getItem('comic_page_step') || '1') === '2') {
    const coverAlone = getSpreadShiftOffset() === 1;
    const spreadStartIdx = currentChunkIdx <= 0
      ? 0
      : (coverAlone
        ? 1 + Math.floor((currentChunkIdx - 1) / 2) * 2
        : Math.floor(currentChunkIdx / 2) * 2);
    const currentHtml = txtChunks[currentChunkIdx];
    if (spreadStartIdx < currentChunkIdx && isEpubImageOnlyHtml(currentHtml)) {
      const startHtml = txtChunks[spreadStartIdx];
      if (startHtml === null || startHtml === 'LOADING_PENDING') {
        if (!epubChapterFetchInFlight.has(spreadStartIdx)) {
          epubChapterFetchInFlight.add(spreadStartIdx);
          requestEpubChapterContent(spreadStartIdx, { force: true, updateDom: false })
            .then(data => {
              if (typeof data === 'string') txtChunks[spreadStartIdx] = data;
              if (isEpubImageOnlyHtml(txtChunks[spreadStartIdx])) {
                currentChunkIdx = spreadStartIdx;
              }
              renderCurrentChunk(initMode, onSettled);
            })
            .finally(() => epubChapterFetchInFlight.delete(spreadStartIdx));
        }
        return;
      }
      if (isEpubImageOnlyHtml(startHtml)) {
        currentChunkIdx = spreadStartIdx;
      }
    }
  }

  // 2장 보기에서 이미지 전용 EPUB spine의 다음 장이 아직 지연 로딩 상태라면,
  // 현재 장을 먼저 보여주되 다음 장을 받아온 직후 같은 펼침면으로 다시 렌더링한다.
  const wantsImagePair = isEpub
    && scrollMode === 'page'
    && (localStorage.getItem('comic_page_step') || '1') === '2'
    && !(getSpreadShiftOffset() === 1 && currentChunkIdx === 0)
    && isEpubImageOnlyHtml(txtChunks[currentChunkIdx]);
  const pairNextIdx = currentChunkIdx + 1;
  if (wantsImagePair
      && pairNextIdx < txtChunks.length
      && (txtChunks[pairNextIdx] === null || txtChunks[pairNextIdx] === 'LOADING_PENDING')
      && !epubChapterFetchInFlight.has(pairNextIdx)) {
    epubChapterFetchInFlight.add(pairNextIdx);
    requestEpubChapterContent(pairNextIdx, { force: true, updateDom: false })
      .then(data => {
        if (typeof data === 'string') txtChunks[pairNextIdx] = data;
        if (renderGeneration === txtRenderGeneration && currentChunkIdx === pairNextIdx - 1) renderCurrentChunk(initMode, onSettled);
      })
      .finally(() => epubChapterFetchInFlight.delete(pairNextIdx));
  }

  if (isEpub && (txtChunks[currentChunkIdx] === null || txtChunks[currentChunkIdx] === 'LOADING_PENDING')) {
    // 요청 시점의 챕터 번호를 고정 캡처합니다. currentChunkIdx는 이후 빠른 연속 페이지
    // 넘김으로 계속 바뀔 수 있는 가변 변수라, 응답을 그 변수로 다시 참조해서 쓰면
    // 엉뚱한(현재의) 슬롯에 데이터를 덮어쓰는 레이스가 발생합니다.
    const requestedIdx = currentChunkIdx;
    showViewerLoading(i18n.t("viewer.loading_txt_title"), i18n.t("viewer.loading_txt_sub"));

    const awaitChapter = (retriesLeft, isFirstAttempt) => {
      requestEpubChapterContent(requestedIdx, { force: isFirstAttempt, updateDom: false })
        .then(data => {
          if (data && typeof data === 'string') {
            txtChunks[requestedIdx] = data;
          } else if (retriesLeft > 0) {
            // null 응답은 같은 챕터를 이미 다른 호출이 fetch 중이라는 뜻(in-flight 중복 방지).
            // 빈 내용으로 성급하게 덮어쓰지 말고, 그 fetch가 채워줄 때까지 짧게 재확인한다.
            setTimeout(() => awaitChapter(retriesLeft - 1, false), 200);
            return;
          } else {
            txtChunks[requestedIdx] = '<p>내용이 없습니다.</p>';
          }
          hideViewerLoading();
          if (renderGeneration === txtRenderGeneration && currentChunkIdx === requestedIdx) {
            renderCurrentChunk(initMode, onSettled);
          }
        })
        .catch(err => {
          hideViewerLoading();
          showViewerError(i18n.t('viewer.error_txt_load'));
          if (renderGeneration === txtRenderGeneration) onSettled?.();
        });
    };

    awaitChapter(10, true);
    return;
  }

  // Render the ready chapter immediately. Scroll placeholders are hydrated below;
  // unrelated chapters must not keep the entire reader behind a loading overlay.

  const reusedTxtFlow = !isEpub && scrollMode === 'page' && contentArea.__txtFlowChunks === txtChunks
    && !!contentArea.querySelector('.txt-flow-chunk');
  const rendered = renderTxtChunkView({
    contentArea,
    txtChunks,
    currentChunkIdx,
    scrollMode,
    isEpub,
    initMode,
    formatTxtToHtml,
    emptyText: i18n.t('viewer.txt_empty'),
    pageStep: parseInt(localStorage.getItem('comic_page_step') || '1', 10),
    coverAlone: getSpreadShiftOffset() === 1
  });
  if (!rendered) return;

  if (!reusedTxtFlow) applyAnnotationsToAllRenderedChunks({ contentArea, format: isEpub ? 'epub' : 'txt', txtChunks });
  applyDynamicParagraphStyles();
  applyTxtImageMaxHeight(scrollWrapper, contentArea);
  applyTxtTwoPageTrailingSpacer(scrollWrapper, contentArea);

  // 이미지가 로드되기 전에 위 계산이 끝나면(짧은 챕터에서 흔함) 홀/짝 판정이
  // 최종 레이아웃과 어긋난 채 고정될 수 있어, 이미지 로드 완료 후 재계산한다.
  const pendingImages = Array.from(contentArea.querySelectorAll('img')).filter(img => !img.complete);
  if (pendingImages.length) {
    let settled = false;
    let remaining = pendingImages.length;
    const recomputeWhenReady = () => {
      if (settled || renderGeneration !== txtRenderGeneration) return;
      remaining -= 1;
      if (remaining <= 0) {
        settled = true;
        applyTxtTwoPageTrailingSpacer(scrollWrapper, contentArea);
        updateTxtSeekBar();
        if (typeof onSettled === 'function') onSettled();
      }
    };
    pendingImages.forEach(img => {
      img.addEventListener('load', recomputeWhenReady, { once: true });
      img.addEventListener('error', recomputeWhenReady, { once: true });
    });
    // 네트워크 문제 등으로 일부 이미지가 load/error 이벤트를 끝내 발생시키지
    // 않는 경우를 대비한 안전장치 — 무한 대기 방지.
    setTimeout(() => {
      if (!settled && renderGeneration === txtRenderGeneration) {
        settled = true;
        applyTxtTwoPageTrailingSpacer(scrollWrapper, contentArea);
        updateTxtSeekBar();
        if (typeof onSettled === 'function') onSettled();
      }
    }, 3000);
  } else if (typeof onSettled === 'function') {
    // 대기할 이미지가 없으면 이 시점에 이미 레이아웃이 최종 상태이므로 바로 콜백한다.
    onSettled();
  }

  // 모드 재전환 시 placeholder가 남아도 가시 범위 챕터를 즉시 재요청해 자동 복구한다.
  if (isEpub && scrollMode === 'scroll') {
    hydrateEpubChapterWindow(currentChunkIdx, 12);
    scheduleVisibleEpubPlaceholderRecovery();
  }

  updateTxtSeekBar();
  syncActiveEpubToc();
  saveProgress(state.activeBookId, currentChunkIdx, txtChunks.length);
}

function applyDynamicParagraphStyles() {
  const contentArea = document.getElementById('txt-content-area');
  if (!contentArea) return;
  applyTxtParagraphStyles({
    contentArea,
    localStorage,
    currentViewerFormat: state.currentViewerFormat
  });
}

function persistTxtProgressSnapshot() {
  if (!state.activeBookId || !Array.isArray(txtChunks) || txtChunks.length === 0) return;

  // TXT는 첫 청크/첫 퍼센트 구간에서는 서버 progress가 0으로 남을 수 있으므로,
  // 같은 기기 재오픈용 세부 스크롤/페이지 위치를 닫기 직전에 반드시 갱신합니다.
  saveDetailPosition();

  const totalChunks = txtChunks.length;
  const safeChunkIdx = Math.max(0, Math.min(totalChunks - 1, currentChunkIdx));
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const isEpub = (state.currentViewerFormat === 'epub');

  if (!isEpub) {
    saveProgress(state.activeBookId, safeChunkIdx, totalChunks);
    return;
  }

  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  const contentArea = document.getElementById('txt-content-area');
  let snapshotIdx = safeChunkIdx;
  let snapshotPercent = totalChunks > 0 ? Math.round((safeChunkIdx / totalChunks) * 100) : 0;

  if (scrollMode === 'scroll' && scrollWrapper && contentArea) {
    const scrollHeight = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
    const ratio = scrollHeight > 0 ? scrollWrapper.scrollTop / scrollHeight : 0;
    const chunks = contentArea.querySelectorAll('.txt-scroll-chunk');
    for (const chunk of chunks) {
      const idx = parseInt(chunk.getAttribute('data-idx'), 10);
      if (Number.isFinite(idx) && scrollWrapper.scrollTop >= chunk.offsetTop - 120) {
        snapshotIdx = idx;
      } else {
        break;
      }
    }
    snapshotPercent = Math.max(0, Math.min(100, Math.round(ratio * 100)));
  }

  let fingerprint = '';
  if (contentArea) {
    const currentChunk = contentArea.querySelector(`.txt-scroll-chunk[data-idx="${snapshotIdx}"]`) || contentArea.querySelector('.txt-chunk, .epub-chunk');
    if (currentChunk) {
      fingerprint = String(currentChunk.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 180);
    }
  }

  saveProgress(state.activeBookId, snapshotIdx, totalChunks, {
    epub_session: {
      index: snapshotIdx,
      percent: snapshotPercent,
      fingerprint: fingerprint || undefined
    }
  });
}

import { getViewerSettings } from './viewer_settings.js';

export function logActiveViewportText() {
  try {
    const anchor = getTxtAnchorInfo();
    if (anchor && anchor.anchorText) {
      console.log(`[Viewer-Active-Text] 현재 화면 첫줄 감지: "${anchor.anchorText.trim()}" (챕터: ${anchor.chunkIdx})`);
    } else {
      console.log(`[Viewer-Active-Text] 현재 화면 첫줄 감지 실패 (null)`);
    }
  } catch (e) {
    console.error(`[Viewer-Active-Text] 감지 중 예외 발생:`, e);
  }
}

export function getTxtAnchorInfo(forcedMode = null) {
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  const contentArea = document.getElementById('txt-content-area');
  const isEpub = (state.currentViewerFormat === 'epub');
  return getTxtAnchorInfoByMode({
    scrollWrapper,
    contentArea,
    forcedMode,
    storage: localStorage,
    isEpub,
    fullText,
    txtChunks,
    currentChunkIdx,
    stripHtml
  });
}

function applyListenTarget(target) {
  requestAnimationFrame(() => requestAnimationFrame(() => {
    if (target?.anchorText) restoreTxtAnchorInfo({ chunkIdx: target.chunkIdx, anchorText: target.anchorText });
    showToast(i18n.t('viewer.tts_moved_to_listen'), 'info');
  }));
}

// 기존 뷰어 위치(user_progress)는 페이지/구간 단위로 계속 저장하고, TTS 동기화 테이블에는
// 해당 구간에서 보이는 문장 앵커만 별도로 보고한다.
function currentReadPosition() {
  if (!Array.isArray(txtChunks) || txtChunks.length === 0) return null;
  const content = document.getElementById('txt-content-area');
  const visible = captureTextResume(document.getElementById('txt-scroll-wrapper'), content, currentChunkIdx);
  const root = visible && content?.querySelector(`[data-idx="${visible.chunkIdx}"]`);
  const info = root ? { chunkIdx: visible.chunkIdx,
    anchorText: String(root.textContent || '').slice(visible.offset, visible.offset + 120).replace(/\s+/g, ' ').trim().slice(0, 40) } : null;
  if (!info?.anchorText) {
    if (state.currentViewerFormat === 'epub' && textResumeReady) {
      return { chapter_idx: currentChunkIdx, char_offset: 0, text_len: 0, anchor: '' };
    }
    return null;
  }
  const chapterIdx = Math.max(0, Math.min(txtChunks.length - 1, Number(info.chunkIdx) || currentChunkIdx));
  const chunkText = state.currentViewerFormat === 'epub'
    ? stripHtml(String(txtChunks[chapterIdx] || ''))
    : String(txtChunks[chapterIdx] || '');
  const inChunk = findAnchorOffset(chunkText, info.anchorText, visible?.offset || 0) ?? 0;
  if (state.currentViewerFormat === 'epub') {
    return { chapter_idx: chapterIdx, char_offset: inChunk, text_len: chunkText.length, anchor: info.anchorText };
  }
  const starts = chunkStarts(txtChunks);
  return {
    chapter_idx: 0,
    char_offset: (starts[chapterIdx] || 0) + inChunk,
    text_len: String(fullText || '').length,
    anchor: info.anchorText,
  };
}

export function restoreTxtAnchorInfo(anchorInfo) {
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  const contentArea = document.getElementById('txt-content-area');
  const isEpub = (state.currentViewerFormat === 'epub');
  const restored = restoreTxtAnchorInfoByMode({
    anchorInfo,
    scrollWrapper,
    contentArea,
    storage: localStorage,
    currentChunkIdx,
    getPageAdvanceWidth: getTxtPageAdvanceWidth,
    isEpub,
    fullText,
    txtChunks,
    stripHtml
  });

  if (restored) {
    const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
    if (scrollMode === 'scroll') {
      console.log(`[Viewer-Txt] 앵커 복원 성공 (세로 scrollTop = ${scrollWrapper ? scrollWrapper.scrollTop : 0})`);
    } else {
      console.log(`[Viewer-Txt] 앵커 복원 성공 (가로 scrollLeft = ${scrollWrapper ? scrollWrapper.scrollLeft : 0})`);
    }
  }

  return restored;
}

export function saveDetailPosition() {
  if (!textResumeReady) return;
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  if (scrollWrapper && state.activeBookId) {
    const pos = {
      flowVersion: state.currentViewerFormat === 'txt' && document.querySelector('#txt-content-area .txt-flow-chunk') ? 1 : undefined,
      anchor: state.currentViewerFormat === 'txt' ? getTxtAnchorInfo() : undefined,
      chunkIdx: currentChunkIdx,
      scrollLeft: getTxtPageScrollLeft(scrollWrapper),
      scrollTop: scrollWrapper.scrollTop
    };
    localStorage.setItem(`viewer_last_pos_${state.activeBookId}`, JSON.stringify(pos));
    saveProgress(state.activeBookId, currentChunkIdx, txtChunks.length);
  }
}

export function applyTxtSettings(options = {}) {
  const container = document.getElementById('txt-viewer-container');
  const scrollWrapper = document.getElementById('txt-scroll-wrapper');
  const contentArea = document.getElementById('txt-content-area');
  if (!container || !scrollWrapper || !contentArea) return;

  clearTimeout(txtPageSnapTimeout);
  txtPageSnapInProgress = false;
  cancelPendingTxtRestore();

  applyTxtSettingsCore({
    options,
    container,
    scrollWrapper,
    contentArea,
    localStorage,
    getViewerSettings,
    getCurrentChunkIdx: () => currentChunkIdx,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getChunkCount: () => txtChunks.length,
    getActiveBookId: () => state.activeBookId,
    getTxtAnchorInfo,
    restoreTxtAnchorInfo,
    renderCurrentChunk,
    snapTxtPageScrollLeft,
    saveDetailPosition,
    showRestoreLoadingToast: showTxtRestoreLoadingToast,
    setPendingRestoreTimer: value => {
      txtPendingRestoreTimer = value;
    },
    applyFontFamily: (element, fontKey) => {
      applyTxtFontFamily(
        element,
        fontKey,
        window.customFonts || [],
        (name, url, target, fallbackFamily) => {
          import('./viewer_settings.js').then(m => {
            m.loadAndApplyCustomFont(name, url, target, fallbackFamily);
          });
        }
      );
    }
  });
  if (state.currentViewerFormat === 'epub') {
    if (epubPagination?.bookId !== state.activeBookId) epubPagination = null;
    scheduleEpubPagination(260);
  }
  if (state.currentViewerFormat === 'txt') {
    if (txtPagination?.bookId !== state.activeBookId) txtPagination = null;
    scheduleTxtPagination(260);
  }
}

function continuousTxtElementPage(element) {
  const content = document.getElementById('txt-content-area');
  const style = getComputedStyle(content);
  const range = document.createRange(); range.selectNodeContents(element);
  const rect = range.getClientRects()[0] || element.getBoundingClientRect();
  const base = content.getBoundingClientRect();
  const rtl = document.getElementById('media-viewer-modal')?.dataset.displayMode === 'two-one';
  return Math.max(1, Math.floor(((rtl ? base.right - rect.right : rect.left - base.left) + 1)
    / ((parseFloat(style.columnWidth) || content.clientWidth) + (parseFloat(style.columnGap) || 0))) + 1);
}

function moveContinuousTxtPage(direction) {
  if (state.currentViewerFormat !== 'txt' || !document.querySelector('#txt-content-area .txt-flow-chunk')
      || (localStorage.getItem('viewer_scroll_mode') || 'page') !== 'page') return false;
  const wrapper = document.getElementById('txt-scroll-wrapper');
  cancelPendingTxtRestore();
  const advance = getTxtPageAdvanceWidth(wrapper);
  if (direction > 0 && getTxtPageScrollLeft(wrapper) >= getTxtPageMaxScroll(wrapper) - 1) {
    import('./viewer_next_episode.js').then(m => m.handleNextEpisodeDirect(state.activeBookId));
    return true;
  }
  if (direction < 0 && getTxtPageScrollLeft(wrapper) <= 1) { showViewerBoundaryNotice('start'); return true; }
  setTxtPageScrollLeft(wrapper, Math.max(0, Math.min(getTxtPageMaxScroll(wrapper),
    (Math.round(getTxtPageScrollLeft(wrapper) / advance) + direction) * advance)));
  updateTxtSeekBar(); saveDetailPosition();
  return true;
}

export function prevTxtPage() {
  if (moveContinuousTxtPage(-1)) return;
  prevTxtPageAction({
    getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
    getContentArea: () => document.getElementById('txt-content-area'),
    cancelPendingRestore: cancelPendingTxtRestore,
    getScrollMode: () => localStorage.getItem('viewer_scroll_mode') || 'page',
    snapTxtPageScrollLeft,
    getTxtPageAdvanceWidth,
    getCurrentChunkIdx: () => currentChunkIdx,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getChunkCount: () => txtChunks.length,
    getPreviousChunkIdx: index => {
      if ((localStorage.getItem('viewer_scroll_mode') || 'page') !== 'page'
          || (localStorage.getItem('comic_page_step') || '1') !== '2') {
        return Math.max(0, index - 1);
      }
      const pairStart = index - 2;
      if (pairStart >= 0
          && isEpubImageOnlyHtml(txtChunks[pairStart])
          && isEpubImageOnlyHtml(txtChunks[pairStart + 1])) {
        return pairStart;
      }
      return Math.max(0, index - 1);
    },
    renderCurrentChunk,
    saveDetailPosition,
    updatePageInfo: updateTxtSeekBar,
    logActiveViewportText,
    getTxtPageSnapInProgress: () => txtPageSnapInProgress,
    setTxtPageSnapInProgress: value => {
      txtPageSnapInProgress = value;
    },
    showBoundaryNotice: showViewerBoundaryNotice,
    handleNextEpisode: () => {
      import('./viewer_next_episode.js').then(m => {
        m.handleNextEpisodeDirect(state.activeBookId);
      });
    },
    setTxtScrollPreloadTriggered: value => {
      txtScrollPreloadTriggered = value;
    },
    setTxtScrollNextEpisodeTriggered: value => {
      txtScrollNextEpisodeTriggered = value;
    }
  });
}

export function nextTxtPage() {
  if (moveContinuousTxtPage(1)) return;
  nextTxtPageAction({
    getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
    cancelPendingRestore: cancelPendingTxtRestore,
    getScrollMode: () => localStorage.getItem('viewer_scroll_mode') || 'page',
    snapTxtPageScrollLeft,
    getTxtPageAdvanceWidth,
    getCurrentChunkIdx: () => currentChunkIdx,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getChunkCount: () => txtChunks.length,
    getChunkAdvance: () => Math.max(1, parseInt(
      document.getElementById('txt-content-area')?.dataset.renderedChunkSpan || '1',
      10
    )),
    renderCurrentChunk,
    saveDetailPosition,
    updatePageInfo: updateTxtSeekBar,
    logActiveViewportText,
    getTxtPageSnapInProgress: () => txtPageSnapInProgress,
    setTxtPageSnapInProgress: value => {
      txtPageSnapInProgress = value;
    },
    handleNextEpisode: () => {
      import('./viewer_next_episode.js').then(m => {
        m.handleNextEpisodeDirect(state.activeBookId);
      });
    },
    setTxtScrollPreloadTriggered: value => {
      txtScrollPreloadTriggered = value;
    },
    setTxtScrollNextEpisodeTriggered: value => {
      txtScrollNextEpisodeTriggered = value;
    }
  });
}

export function moveTxtPageByOne(direction) {
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const twoPage = (localStorage.getItem('comic_page_step') || '1') === '2';
  const imageSpread = state.currentViewerFormat === 'epub'
    && scrollMode === 'page'
    && twoPage
    && isEpubImageOnlyHtml(txtChunks[currentChunkIdx]);
  if (!imageSpread) return direction === 'prev' ? prevTxtPage() : nextTxtPage();

  const target = currentChunkIdx + (direction === 'prev' ? -1 : 1);
  if (target < 0) return showViewerBoundaryNotice('start');
  if (target >= txtChunks.length) {
    import('./viewer_next_episode.js').then(m => m.handleNextEpisodeDirect(state.activeBookId));
    return;
  }
  setSpreadShiftOffset(target % 2 === 1 ? 1 : 0);
  currentChunkIdx = target;
  renderCurrentChunk(false);
  saveDetailPosition();
  updateTxtSeekBar();
}

export function txtJumpToFirstPage() {
  if (state.currentViewerFormat === 'txt' && txtPagination?.continuous) { txtSliderChange(null, 1); return; }
  txtJumpToFirstPageAction({
    getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
    cancelPendingRestore: cancelPendingTxtRestore,
    getCurrentChunkIdx: () => currentChunkIdx,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getChunkCount: () => txtChunks.length,
    renderCurrentChunk,
    updateSeekBar: updateTxtSeekBar,
    setTxtScrollPreloadTriggered: value => {
      txtScrollPreloadTriggered = value;
    },
    setTxtScrollNextEpisodeTriggered: value => {
      txtScrollNextEpisodeTriggered = value;
    }
  });
}

export function txtJumpToLastPage() {
  if (state.currentViewerFormat === 'txt' && txtPagination?.continuous) { txtSliderChange(null, txtPagination.total); return; }
  txtJumpToLastPageAction({
    getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
    cancelPendingRestore: cancelPendingTxtRestore,
    getCurrentChunkIdx: () => currentChunkIdx,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getChunkCount: () => txtChunks.length,
    renderCurrentChunk,
    updateSeekBar: updateTxtSeekBar,
    setTxtScrollPreloadTriggered: value => {
      txtScrollPreloadTriggered = value;
    },
    setTxtScrollNextEpisodeTriggered: value => {
      txtScrollNextEpisodeTriggered = value;
    }
  });
}

export function updateTxtSeekBar() {
  if (txtPageSnapInProgress) return;
  const slider = document.getElementById('viewer-page-slider');
  const startLabel = document.getElementById('seekbar-start-label');
  const pageInfo = document.getElementById('comic-overlay-page-info');

  if (!slider || txtChunks.length === 0) return;

  const mode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const wrapper = document.getElementById('txt-scroll-wrapper');
  if (mode === 'scroll' && wrapper) {
    const maxScroll = Math.max(0, wrapper.scrollHeight - wrapper.clientHeight);
    const percent = maxScroll > 0
      ? Math.max(0, Math.min(100, Math.round((wrapper.scrollTop / maxScroll) * 100)))
      : 0;
    slider.min = '0';
    slider.max = '100';
    slider.value = String(percent);
    slider.dataset.seekMode = 'scroll-progress';
    const chunkEl = document.getElementById('txt-content-area')
      ?.querySelector(`.txt-scroll-chunk[data-idx="${currentChunkIdx}"]`);
    const withinChunk = chunkEl?.clientHeight
      ? Math.max(0, Math.min(100, Math.round(((wrapper.scrollTop - chunkEl.offsetTop) / chunkEl.clientHeight) * 100)))
      : 0;
    slider.dataset.chapterIdx = String(currentChunkIdx);
    slider.dataset.chapterPercent = String(withinChunk);
    slider.disabled = false;
    if (startLabel) startLabel.textContent = `${percent}%`;
    if (pageInfo) pageInfo.textContent = `${percent}% · 구간 ${currentChunkIdx + 1}/${txtChunks.length}`;
    slider.style.setProperty('--seek-progress', `${percent}%`);
    slider.dispatchEvent(new CustomEvent('viewer-position-sync', { bubbles: true }));
    return;
  }

  if ((state.currentViewerFormat === 'epub' && !epubPagination)
      || (state.currentViewerFormat === 'txt' && !txtPagination)) {
    slider.min = '1';
    slider.max = '1';
    slider.value = '1';
    slider.disabled = true;
    slider.dataset.seekMode = 'page';
    slider.style.setProperty('--seek-progress', '0%');
    if (startLabel) startLabel.textContent = '페이지 계산 중…';
    if (pageInfo) pageInfo.textContent = '페이지 계산 중…';
    slider.dispatchEvent(new CustomEvent('viewer-position-sync', { bubbles: true }));
    return;
  }

  slider.dataset.seekMode = 'page';
  slider.dataset.chapterIdx = String(currentChunkIdx);
  slider.min = "1";
  const contentArea = document.getElementById('txt-content-area');
  const renderedSpan = Math.max(1, parseInt(contentArea?.dataset.renderedChunkSpan || '1', 10));
  const visibleEndIdx = Math.min(txtChunks.length - 1, currentChunkIdx + renderedSpan - 1);
  const hasEpubPages = state.currentViewerFormat === 'epub'
    && epubPagination
    && epubPagination.bookId === state.activeBookId
    && epubPagination.mode === 'page';
  const hasTxtPages = state.currentViewerFormat === 'txt'
    && txtPagination
    && txtPagination.bookId === state.activeBookId
    && txtPagination.mode === 'page';
  slider.disabled = false;

  if ((hasEpubPages || hasTxtPages) && wrapper) {
    const pagination = hasEpubPages ? epubPagination : txtPagination;
    if (hasEpubPages) reconcileRenderedEpubPageCount(wrapper, renderedSpan);
    const physical = getTxtPhysicalPageInfo(wrapper);
    const first = pagination.continuous ? physical.first : renderedSpan > 1
      ? pagination.starts[currentChunkIdx]
      : pagination.starts[currentChunkIdx] + physical.first - 1;
    const last = pagination.continuous ? physical.last : renderedSpan > 1
      ? pagination.starts[visibleEndIdx]
      : Math.min(pagination.total, pagination.starts[currentChunkIdx] + physical.last - 1);
    slider.max = String(pagination.total);
    slider.value = String(Math.max(1, first));
    if (pagination.continuous) {
      currentChunkIdx = Math.max(0, pagination.starts.findLastIndex(start => start <= first));
      slider.dataset.chapterIdx = String(currentChunkIdx);
      syncActiveEpubToc();
    }
    if (startLabel) startLabel.textContent = `${first === last ? first : `${first}-${last}`} / ${pagination.total}`;
    if (pageInfo) pageInfo.textContent = startLabel?.textContent || `${first} / ${pagination.total}`;
  } else {
    slider.max = String(txtChunks.length);
    slider.value = String(visibleEndIdx + 1);
    if (startLabel) startLabel.textContent = `${currentChunkIdx + 1}${visibleEndIdx > currentChunkIdx ? `-${visibleEndIdx + 1}` : ''} / ${txtChunks.length}`;
    if (pageInfo) {
      const inner = wrapper ? getTxtViewportPageInfo(wrapper) : { current: 1, total: 1 };
      const chapterLabel = renderedSpan > 1 ? `${currentChunkIdx + 1}-${visibleEndIdx + 1}` : `${currentChunkIdx + 1}`;
      pageInfo.textContent = `${chapterLabel} / ${txtChunks.length} · 화면 ${inner.current} / ${inner.total}`;
    }
  }

  const chapterMaxScroll = wrapper ? getTxtPageMaxScroll(wrapper) : 0;
  slider.dataset.chapterPercent = String(chapterMaxScroll > 0
    ? Math.max(0, Math.min(100, Math.round((getTxtPageScrollLeft(wrapper) / chapterMaxScroll) * 100)))
    : 0);
  if (hasTxtPages && txtPagination.continuous) {
    slider.dataset.chapterPercent = String(Math.max(0, Math.min(100,
      (Number(slider.value) - txtPagination.starts[currentChunkIdx]) / Math.max(1, txtPagination.counts[currentChunkIdx] - 1) * 100)));
  }

  const ratio = (Number(slider.value) - 1) / Math.max(1, Number(slider.max) - 1);
  slider.style.setProperty('--seek-progress', `${Math.max(0, Math.min(100, ratio * 100))}%`);
  slider.dispatchEvent(new CustomEvent('viewer-position-sync', { bubbles: true }));
}

export function txtSliderInput(slider, val) {
  txtSliderInputAction({
    val,
    chunkCount: Number(slider?.max || txtChunks.length),
    scrollMode: localStorage.getItem('viewer_scroll_mode') || 'page'
  });
}

export function txtSliderChange(slider, val) {
  const pagination = state.currentViewerFormat === 'epub' ? epubPagination : txtPagination;
  if (pagination?.continuous && (localStorage.getItem('viewer_scroll_mode') || 'page') === 'page') {
    const wrapper = document.getElementById('txt-scroll-wrapper');
    const page = Math.max(1, Math.min(pagination.total, Number(val) || 1));
    setTxtPageScrollLeft(wrapper, Math.floor((page - 1) / pagination.step) * getTxtPageAdvanceWidth(wrapper));
    updateTxtSeekBar(); saveDetailPosition(); return;
  }
  if ((state.currentViewerFormat === 'epub' || state.currentViewerFormat === 'txt')
      && (localStorage.getItem('viewer_scroll_mode') || 'page') === 'page'
      && pagination?.bookId === state.activeBookId
      && pagination.mode === 'page') {
    const targetPage = Math.max(1, Math.min(pagination.total, Number(val) || 1));
    let chapterIdx = pagination.starts.findLastIndex((start) => start <= targetPage);
    if (chapterIdx < 0) chapterIdx = 0;
    const localPage = targetPage - pagination.starts[chapterIdx] + 1;
    const jump = () => {
      currentChunkIdx = chapterIdx;
      renderCurrentChunk(false, () => {
        const wrapper = document.getElementById('txt-scroll-wrapper');
        const step = localStorage.getItem('comic_page_step') === '2' ? 2 : 1;
        if (wrapper) setTxtPageScrollLeft(wrapper, Math.floor((localPage - 1) / step) * getTxtPageAdvanceWidth(wrapper));
        updateTxtSeekBar();
        saveDetailPosition();
      });
    };
    if (txtChunks[chapterIdx] === null || txtChunks[chapterIdx] === 'LOADING_PENDING') {
      requestEpubChapterContent(chapterIdx, { force: true, updateDom: false }).then(jump);
    } else {
      jump();
    }
    return;
  }
  txtSliderChangeAction(
    {
      getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
      cancelPendingRestore: cancelPendingTxtRestore,
      getScrollMode: () => localStorage.getItem('viewer_scroll_mode') || 'page',
      getCurrentChunkIdx: () => currentChunkIdx,
      setCurrentChunkIdx: value => {
        currentChunkIdx = value;
      },
      getChunkCount: () => txtChunks.length,
      renderCurrentChunk,
      saveDetailPosition,
      logActiveViewportText
    },
    val
  );
}

export const TxtViewer = {
  async init(bookId, initialPageIdx = 0) {
    return initTxtViewer(bookId, initialPageIdx);
  },
  prepareForClose() {
    persistTxtProgressSnapshot();
    if (textResumeReady) reportReadNow();
  },
  destroy() {
    txtSessionGeneration += 1;
    txtRuntimeState.reset();
    clearTimeout(txtPageSnapTimeout);
    txtPageSnapInProgress = false;
    cancelPendingTxtRestore();
    const contentArea = document.getElementById('txt-content-area');
    if (contentArea) {
      contentArea.textContent = '';
      delete contentArea.__txtFlowChunks;
      delete contentArea.dataset.viewerBookId;
      delete contentArea.dataset.viewerSession;
    }
    const pane = document.getElementById('txt-viewer-container');
    if (pane) pane.style.display = 'none';

    const scrollWrapper = document.getElementById('txt-scroll-wrapper');
    if (scrollWrapper && scrollWrapper.__txtScrollHandler) {
      scrollWrapper.removeEventListener('scroll', scrollWrapper.__txtScrollHandler);
      delete scrollWrapper.__txtScrollHandler;
    }
    if (scrollWrapper && scrollWrapper.__txtTouchHandler) {
      scrollWrapper.removeEventListener('touchend', scrollWrapper.__txtTouchHandler);
      scrollWrapper.removeEventListener('touchcancel', scrollWrapper.__txtTouchHandler);
      delete scrollWrapper.__txtTouchHandler;
    }

    if (activeResizeHandler) {
      window.removeEventListener('resize', activeResizeHandler);
      activeResizeHandler = null;
    }
    clearTimeout(resizeTimeout);
    clearTimeout(epubPaginationTimer);
    clearTimeout(txtPaginationTimer);
    epubPaginationGeneration += 1;
    txtPaginationGeneration += 1;
    txtRenderGeneration += 1;
    epubPagination = null;
    txtPagination = null;
    pendingTxtFlowPosition = null;
    epubAnnotationLocalPages.clear();
    
    const tocBtn = document.getElementById('epub-toc-btn');
    const tocContainer = document.getElementById('epub-toc-container');
    if (tocBtn) tocBtn.remove();
    if (tocContainer) tocContainer.remove();
  },
  prevPage() {
    prevTxtPage();
  },
  nextPage() {
    nextTxtPage();
  },
  moveByOne(direction) {
    moveTxtPageByOne(direction);
  },
  async seekToTtsPosition(position = {}) {
    cancelPendingTxtRestore();
    const session = txtSessionGeneration;
    const bookId = state.activeBookId;
    const isCurrent = () => session === txtSessionGeneration && bookId === state.activeBookId
      && (typeof position.isCurrent !== 'function' || position.isCurrent());
    if (!isCurrent()) return null;
    const format = String(position.format || state.currentViewerFormat || '').toLowerCase();
    const isEpub = state.currentViewerFormat === 'epub';
    if ((isEpub && format !== 'epub') || (!isEpub && !['txt', 'text'].includes(format)) || !txtChunks.length) {
      return null;
    }

    let chunkIdx = 0;
    let offset = Math.max(0, Number(position.char_offset) || 0);
    if (isEpub) {
      chunkIdx = Math.max(0, Math.min(txtChunks.length - 1, Number(position.chapter_idx) || 0));
      if (txtChunks[chunkIdx] === null || txtChunks[chunkIdx] === 'LOADING_PENDING') {
        const loaded = await requestEpubChapterContent(chunkIdx, { force: true, updateDom: false });
        if (!isCurrent()) return null;
        // An ordinary viewer prefetch can already own the request. Wait for that request
        // instead of treating its temporary null return as a permanently empty chapter.
        for (let attempt = 0; !loaded && attempt < 120
            && (txtChunks[chunkIdx] === null || txtChunks[chunkIdx] === 'LOADING_PENDING'); attempt += 1) {
          await new Promise(resolve => setTimeout(resolve, 50));
          if (!isCurrent()) return null;
        }
        if (txtChunks[chunkIdx] === null || txtChunks[chunkIdx] === 'LOADING_PENDING') return null;
      }
      offset = Math.min(offset, stripHtml(String(txtChunks[chunkIdx] || '')).length);
    } else {
      const starts = chunkStarts(txtChunks);
      const safeOffset = Math.min(offset, String(fullText || '').length);
      let low = 0;
      let high = starts.length - 1;
      while (low <= high) {
        const mid = (low + high) >> 1;
        if (starts[mid] <= safeOffset) low = mid + 1;
        else high = mid - 1;
      }
      chunkIdx = Math.max(0, high);
      offset = safeOffset - (starts[chunkIdx] || 0);
    }

    clearTimeout(txtPageSnapTimeout);
    txtPageSnapInProgress = false;
    const wrapper = document.getElementById('txt-scroll-wrapper');
    if (wrapper) wrapper.style.visibility = '';
    const changed = currentChunkIdx !== chunkIdx;
    currentChunkIdx = chunkIdx;
    const contentArea = document.getElementById('txt-content-area');
    const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
    const renderForTts = () => new Promise(resolve => {
      // TTS 위치는 spine 챕터 번호이지 실제 EPUB 페이지 번호가 아니다. 렌더 시 발생하는
      // 일반 진도 저장이 챕터 개수를 페이지 수로 오인하지 않도록 이 한 번만 저장을 막는다.
      const ready = textResumeReady;
      if (isEpub) textResumeReady = false;
      const timer = setTimeout(resolve, 3500);
      try { renderCurrentChunk(true, () => { clearTimeout(timer); resolve(); }); }
      finally { textResumeReady = ready; }
    });
    if (changed && scrollMode === 'page') await renderForTts();
    else if (!contentArea?.querySelector(`[data-idx="${chunkIdx}"]`)) await renderForTts();
    if (!isCurrent()) return null;
    syncActiveEpubToc(false);
    updateTxtSeekBar();
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    if (!isCurrent()) return null;
    return { chunkIdx, offset };
  },
  jumpTo(target) {
    if (target === 'first') {
      txtJumpToFirstPage();
    } else if (target === 'last') {
      txtJumpToLastPage();
    }
  },
  applySettings(options) {
    applyTxtSettings(options || {});
  }
};

function renderEpubToc(tocList) {
  renderEpubTocPanel({
    tocList,
    txtChunks,
    onJumpToChapter: jumpToChapter,
    resolveLocation: resolveStoredTextLocation,
  });
  syncActiveEpubToc(true);
}

function jumpToChapter(chapterIdx, anchor, options = null) {
  if (state.currentViewerFormat === 'txt' && txtPagination?.continuous
      && (localStorage.getItem('viewer_scroll_mode') || 'page') === 'page') {
    const start = txtPagination.starts[chapterIdx] || 1;
    const local = Math.round((txtPagination.counts[chapterIdx] - 1) * (Number(options?.percent) || 0) / 100);
    const mark = options?.annotationId != null
      ? document.querySelector(`mark.annotation-highlight[data-annotation-id="${CSS.escape(String(options.annotationId))}"]`) : null;
    txtSliderChange(null, mark ? continuousTxtElementPage(mark) : options?.globalPage ?? start + local);
    return;
  }
  if (options?.globalPage != null
      && Number.isFinite(Number(options.globalPage))
      && state.currentViewerFormat === 'epub'
      && (localStorage.getItem('viewer_scroll_mode') || 'page') === 'page') {
    txtSliderChange(null, Number(options.globalPage));
    return;
  }
  jumpToTxtTocChapter({
    chapterIdx,
    anchor,
    options,
    chunkCount: txtChunks.length,
    txtChunks,
    cancelPendingRestore: cancelPendingTxtRestore,
    setCurrentChunkIdx: value => {
      currentChunkIdx = value;
    },
    getScrollMode: () => localStorage.getItem('viewer_scroll_mode') || 'page',
    getScrollWrapper: () => document.getElementById('txt-scroll-wrapper'),
    renderCurrentChunk,
    saveProgress,
    activeBookId: state.activeBookId,
    onActiveChapterChange: idx => {
      currentChunkIdx = idx;
      syncActiveEpubToc(true);
    }
  });
}

export function searchTextViewer(query) {
  const needle = String(query || '').trim().toLocaleLowerCase();
  if (!needle) return [];
  const parser = document.createElement('div');
  const results = [];
  txtChunks.forEach((html, chapterIdx) => {
    if (!html || html === 'LOADING_PENDING') return;
    parser.innerHTML = String(html);
    const text = (parser.textContent || '').replace(/\s+/g, ' ').trim();
    const matchAt = text.toLocaleLowerCase().indexOf(needle);
    if (matchAt < 0) return;
    const start = Math.max(0, matchAt - 32);
    const end = Math.min(text.length, matchAt + needle.length + 64);
    const location = resolveStoredTextLocation({ format: state.currentViewerFormat, chapter_idx: chapterIdx, percent: 0 });
    results.push({ chapterIdx, label: location.label, snippet: `${start > 0 ? '…' : ''}${text.slice(start, end)}${end < text.length ? '…' : ''}` });
  });
  return results.slice(0, 100);
}

export function jumpToTextSearchResult(chapterIdx) {
  jumpToChapter(Number(chapterIdx), '', { preferChapterStart: true });
}
