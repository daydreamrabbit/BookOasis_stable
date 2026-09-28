// 전역 검색 미리보기: 입력 중인 초안은 현재 목록에 적용하지 않고 작은 결과 패널로만 보여준다.
import { state } from './state.js';
import * as api from './api.js?rev=20260920-scan-response-v1';
import { getBookCoverSrc } from './cover_fallback.js';

let previewTimer = null;
let previewController = null;
let previewSerial = 0;

function panel() {
  return document.getElementById('library-search-preview');
}

function escapeText(value) {
  return String(value ?? '').replace(/[&<>'"]/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;'
  })[char]);
}

export function closeLibrarySearchPreview() {
  if (previewTimer) clearTimeout(previewTimer);
  previewTimer = null;
  previewController?.abort();
  previewController = null;
  const target = panel();
  if (target) {
    target.hidden = true;
    target.innerHTML = '';
  }
}

function renderPreview(query, rows) {
  const target = panel();
  if (!target) return;
  if (!rows.length) {
    target.innerHTML = '<div class="library-search-preview-empty">검색 결과가 없습니다.</div>';
    target.hidden = false;
    return;
  }

  const items = rows.map(item => {
    const seriesName = item.series_name || item.title || '';
    const displayTitle = item.series_alias || item.title_alias || seriesName;
    const bookId = item.representative_book_id || item.id || '';
    const cover = getBookCoverSrc({
      coverImage: item.cover_image,
      title: displayTitle,
      format: item.file_format,
      seed: bookId,
    });
    return `
      <button type="button" class="library-search-preview-item" data-search-preview-result
          data-series-name="${escapeText(seriesName)}" data-display-title="${escapeText(displayTitle)}"
          data-library-id="${escapeText(item.library_id)}" data-book-id="${escapeText(bookId)}">
        <img class="library-search-preview-cover" src="${escapeText(cover)}" alt="" loading="lazy">
        <span class="library-search-preview-text">
          <span class="library-search-preview-title">${escapeText(displayTitle)}</span>
          <span class="library-search-preview-author">${escapeText(item.author || '')}</span>
        </span>
      </button>`;
  }).join('');

  target.innerHTML = `${items}<button type="button" class="library-search-preview-more" data-search-preview-more>“${escapeText(query)}” 전체 검색 결과 보기</button>`;
  target.hidden = false;
}

async function loadPreview(query, serial) {
  previewController?.abort();
  const controller = new AbortController();
  previewController = controller;
  const target = panel();
  if (target) {
    target.innerHTML = '<div class="library-search-preview-status"><i class="fa-solid fa-circle-notch fa-spin"></i> 검색 중...</div>';
    target.hidden = false;
  }

  try {
    const data = await api.fetchBooksList({
      type: state.currentLibraryType,
      libraryId: 'all',
      page: 1,
      limit: 8,
      append: false,
      search: query,
      sort: 'asc',
      genres: [],
      tags: [],
      groupBy: 'default',
      signal: controller.signal,
    });
    if (serial !== previewSerial || controller.signal.aborted) return;
    renderPreview(query, data.success ? (data.series || []) : []);
  } catch (error) {
    if (error.name === 'AbortError' || serial !== previewSerial) return;
    if (target) {
      target.innerHTML = '<div class="library-search-preview-empty">검색 결과를 불러오지 못했습니다.</div>';
      target.hidden = false;
    }
  }
}

export function handleLibrarySearchDraft(value) {
  const query = String(value || '').trim();
  const action = document.getElementById('btn-library-search-action');
  if (action) {
    const isCommitted = !!state.searchQuery && (!query || query.toLowerCase() === String(state.searchQuery).toLowerCase());
    action.innerHTML = isCommitted
      ? '<i class="fa-solid fa-xmark" aria-hidden="true"></i><span class="sr-only">검색 초기화</span>'
      : '<i class="fa-solid fa-magnifying-glass" aria-hidden="true"></i><span class="sr-only">검색</span>';
    action.title = isCommitted ? '검색 초기화' : '검색';
  }
  previewSerial += 1;
  const serial = previewSerial;
  if (previewTimer) clearTimeout(previewTimer);
  previewController?.abort();
  if (!query) {
    closeLibrarySearchPreview();
    return;
  }
  previewTimer = setTimeout(() => loadPreview(query, serial), 240);
}

export function initLibrarySearchPreview(onCommit) {
  if (window.__librarySearchPreviewBound) return;
  document.addEventListener('click', event => {
    const result = event.target.closest?.('[data-search-preview-result]');
    if (result) {
      event.preventDefault();
      closeLibrarySearchPreview();
      const input = document.getElementById('library-search');
      if (input) input.value = result.dataset.displayTitle || result.dataset.seriesName || '';
      if (typeof window.openBookDetail === 'function') {
        window.openBookDetail(
          null,
          result.dataset.seriesName || '',
          result.dataset.libraryId || 'all',
          result.dataset.bookId || null,
          result.dataset.displayTitle || ''
        );
      }
      return;
    }

    if (event.target.closest?.('[data-search-preview-more]')) {
      event.preventDefault();
      closeLibrarySearchPreview();
      onCommit?.();
      return;
    }

    const target = panel();
    if (target && !target.hidden && !event.target.closest?.('.library-search-center')) {
      closeLibrarySearchPreview();
    }
  }, true);
  window.__librarySearchPreviewBound = true;
}
