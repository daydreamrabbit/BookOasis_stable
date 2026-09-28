import { state } from '../state.js';

let cachedBookId = null;
let bookmarks = [];
let bound = false;

function currentPosition() {
  const slider = document.getElementById('viewer-page-slider');
  const format = String(state.currentViewerFormat || '').toLowerCase();
  if (!slider || !state.activeBookId || !format) return null;
  // EPUB/TXT의 하단 숫자는 현재 레이아웃에서 계산된 "전체 표시 페이지"다.
  // 이를 chapter_idx로 저장하면 10페이지를 10번째 spine으로 해석해 전혀 다른
  // 위치로 점프한다. 텍스트 뷰어가 range dataset에 기록한 canonical 위치를 쓴다.
  let chapterIdx = Math.max(0, Number.parseInt(slider.value || '1', 10) - 1);
  if (format === 'epub' || format === 'txt') {
    const canonicalChapter = Number.parseInt(slider.dataset.chapterIdx || '', 10);
    if (Number.isFinite(canonicalChapter)) chapterIdx = Math.max(0, canonicalChapter);
  }
  const max = Math.max(1, Number.parseInt(slider.max || '1', 10));
  const canonicalPercent = Number.parseInt(slider.dataset.chapterPercent || '', 10);
  const percent = (format === 'epub' || format === 'txt') && Number.isFinite(canonicalPercent)
    ? Math.max(0, Math.min(100, canonicalPercent))
    : slider.dataset.seekMode === 'scroll-progress'
      ? Math.max(0, Math.min(100, Number.parseInt(slider.value || '0', 10)))
      : Math.round(((chapterIdx + 1) / max) * 100);
  const visibleLabel = String(document.getElementById('seekbar-start-label')?.textContent || '').trim();
  const globalPage = Number.parseInt(visibleLabel.match(/^\d+/)?.[0] || '', 10);
  return { format, chapterIdx, percent, label: visibleLabel || `${chapterIdx + 1}페이지`, globalPage };
}

async function loadBookmarks(force = false) {
  const bookId = Number(state.activeBookId);
  if (!bookId) return [];
  if (!force && cachedBookId === bookId) return bookmarks;
  const response = await fetch(`/api/v1/books/${bookId}/bookmarks?db_type=${encodeURIComponent(state.currentLibraryType || 'general')}`);
  const data = await response.json();
  bookmarks = response.ok && data.success && Array.isArray(data.bookmarks) ? data.bookmarks : [];
  cachedBookId = bookId;
  return bookmarks;
}

function matchingBookmark(position) {
  return bookmarks.find((item) => String(item.format).toLowerCase() === position.format
    && (Number(item.chapter_idx) === position.chapterIdx
      || (Number.isFinite(position.globalPage)
        && String(item.label || '').trim() === `${position.globalPage}페이지`)));
}

export async function syncCurrentBookmarkButton({ force = false } = {}) {
  const button = document.getElementById('btn-add-bookmark');
  const position = currentPosition();
  if (!button || !position) return;
  try {
    await loadBookmarks(force);
    const active = Boolean(matchingBookmark(position));
    button.classList.toggle('is-active', active);
    button.setAttribute('aria-pressed', String(active));
    button.title = active ? '현재 페이지 책갈피 삭제' : '현재 페이지 책갈피 추가';
    const icon = button.querySelector('i');
    if (icon) icon.className = active ? 'fa-solid fa-bookmark' : 'fa-regular fa-bookmark';
  } catch (error) {
    console.warn('[Viewer-Bookmark] 상태 확인 실패:', error);
  }
}

export async function toggleCurrentPageBookmark() {
  const position = currentPosition();
  if (!position) return;
  await loadBookmarks(true);
  const current = matchingBookmark(position);
  const dbType = encodeURIComponent(state.currentLibraryType || 'general');
  let response;
  if (current) {
    response = await fetch(`/api/v1/bookmarks/${current.id}?db_type=${dbType}`, { method: 'DELETE' });
  } else {
    response = await fetch(`/api/v1/books/${state.activeBookId}/bookmarks?db_type=${dbType}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        format: position.format,
        chapter_idx: position.chapterIdx,
        percent: position.percent,
        label: position.label,
      }),
    });
  }
  const data = await response.json();
  if (!response.ok || !data.success) throw new Error(data.error || '책갈피를 저장하지 못했습니다.');
  await syncCurrentBookmarkButton({ force: true });
  window.showToast?.(current ? '책갈피를 삭제했습니다.' : '책갈피를 저장했습니다.', 'success');
  document.dispatchEvent(new CustomEvent('viewer-bookmarks-changed'));
}

export function initViewerBookmarkController() {
  if (bound) return;
  bound = true;
  document.addEventListener('viewer-position-sync', () => syncCurrentBookmarkButton());
  document.addEventListener('viewer-book-opened', () => {
    cachedBookId = null;
    bookmarks = [];
    syncCurrentBookmarkButton({ force: true });
  });
}
