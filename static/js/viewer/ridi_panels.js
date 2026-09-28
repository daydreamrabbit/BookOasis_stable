import { state } from '../state.js';

function closePanel({ notify = true } = {}) {
  const panel = document.getElementById('viewer-search-panel');
  if (!panel) return false;
  panel.remove();
  if (notify) {
    document.dispatchEvent(new CustomEvent('viewer-overlay-visibility-changed', {
      detail: { isOpen: false, source: 'search-side-panel' },
    }));
    document.dispatchEvent(new CustomEvent('viewer-side-panel-state-changed', {
      detail: { panel: null },
    }));
  }
  return true;
}

function closeImageNotesPanel({ notify = true } = {}) {
  const panel = document.getElementById('viewer-image-notes-panel');
  if (!panel) return false;
  panel.remove();
  if (notify) {
    document.dispatchEvent(new CustomEvent('viewer-overlay-visibility-changed', {
      detail: { isOpen: false, source: 'image-notes-side-panel' },
    }));
    document.dispatchEvent(new CustomEvent('viewer-side-panel-state-changed', {
      detail: { panel: null },
    }));
  }
  return true;
}

async function renderImageBookmarks(panel) {
  const list = panel?.querySelector('.viewer-note-list');
  if (!list || !state.activeBookId) return;
  list.innerHTML = '<p class="viewer-panel-empty">책갈피를 불러오는 중...</p>';
  try {
    const response = await fetch(`/api/v1/books/${state.activeBookId}/bookmarks?db_type=${encodeURIComponent(state.currentLibraryType || 'general')}`);
    const data = await response.json();
    if (!panel.isConnected) return;
    const format = String(state.currentViewerFormat || '').toLowerCase();
    const bookmarks = response.ok && data.success && Array.isArray(data.bookmarks)
      ? data.bookmarks.filter((item) => String(item.format || '').toLowerCase() === format)
      : [];
    list.innerHTML = '';
    if (!bookmarks.length) {
      list.innerHTML = '<p class="viewer-panel-empty">저장된 책갈피가 없습니다.</p>';
      return;
    }
    bookmarks.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'viewer-note-card viewer-note-card--bookmark';
      const icon = document.createElement('i');
      icon.className = 'fa-solid fa-bookmark';
      const body = document.createElement('span');
      const title = document.createElement('strong');
      const location = document.createElement('small');
      const label = item.label || `${Number(item.chapter_idx || 0) + 1}페이지`;
      title.textContent = label;
      location.textContent = label;
      body.append(title, location);
      button.append(icon, body);
      button.addEventListener('click', () => {
        const slider = document.getElementById('viewer-page-slider');
        if (!slider) return;
        slider.value = String(Math.max(Number(slider.min || 1), Math.min(Number(slider.max || 1), Number(item.chapter_idx || 0) + 1)));
        slider.dispatchEvent(new Event('input', { bubbles: true }));
        slider.dispatchEvent(new Event('change', { bubbles: true }));
      });
      list.appendChild(button);
    });
  } catch (error) {
    if (panel.isConnected) list.innerHTML = '<p class="viewer-panel-empty">책갈피를 불러오지 못했습니다.</p>';
  }
}

export async function openImageReadingNotesPanel() {
  const openPanel = document.getElementById('viewer-image-notes-panel');
  if (openPanel) {
    closeImageNotesPanel();
    return;
  }
  document.dispatchEvent(new CustomEvent('viewer-side-panel-opening', {
    detail: { source: 'image-notes-side-panel' },
  }));
  const panel = document.createElement('aside');
  panel.id = 'viewer-image-notes-panel';
  panel.className = 'viewer-side-panel';
  panel.innerHTML = `
    <header><strong>독서노트</strong><button type="button" data-close-viewer-panel aria-label="닫기"><i class="fa-solid fa-xmark"></i></button></header>
    <div class="viewer-note-filters"><button type="button" class="active">책갈피</button></div>
    <div class="viewer-note-list"></div>`;
  document.body.appendChild(panel);
  // 패널 안의 입력/결과를 누를 때 뷰어 본문 제스처나 전역 닫기 핸들러가
  // 이벤트를 가로채지 않도록 패널에서 이벤트 전파를 끝낸다.
  panel.addEventListener('pointerdown', (event) => event.stopPropagation());
  panel.addEventListener('click', (event) => event.stopPropagation());
  panel.querySelector('[data-close-viewer-panel]').addEventListener('click', closeImageNotesPanel);
  document.dispatchEvent(new CustomEvent('viewer-overlay-visibility-changed', {
    detail: { isOpen: true, source: 'image-notes-side-panel' },
  }));
  document.dispatchEvent(new CustomEvent('viewer-side-panel-state-changed', {
    detail: { panel: 'notes' },
  }));
  await renderImageBookmarks(panel);
}

export async function openViewerSearchPanel(initialQuery = '') {
  const openPanel = document.getElementById('viewer-search-panel');
  if (openPanel) {
    if (initialQuery) {
      const openInput = openPanel.querySelector('input');
      if (openInput) {
        openInput.value = String(initialQuery).trim();
        openInput.dispatchEvent(new Event('input', { bubbles: true }));
        openInput.focus();
      }
    } else {
      closePanel();
    }
    return;
  }
  document.dispatchEvent(new CustomEvent('viewer-side-panel-opening', {
    detail: { source: 'search-side-panel' },
  }));
  const panel = document.createElement('aside');
  panel.id = 'viewer-search-panel';
  panel.className = 'viewer-side-panel';
  panel.innerHTML = `
    <header><strong>검색</strong><button type="button" data-close-viewer-panel aria-label="닫기"><i class="fa-solid fa-xmark"></i></button></header>
    <label class="viewer-search-field"><i class="fa-solid fa-magnifying-glass"></i><input type="search" placeholder="책에서 검색" autocomplete="off"></label>
    <div class="viewer-search-results"><p class="viewer-panel-empty">검색어를 입력하세요.</p></div>`;
  document.body.appendChild(panel);
  // 검색 입력/결과를 누를 때 본문 제스처나 전역 닫기 핸들러가
  // 입력 이벤트를 가로채지 않도록 패널에서 전파를 끝낸다.
  panel.addEventListener('pointerdown', (event) => event.stopPropagation());
  panel.addEventListener('click', (event) => event.stopPropagation());
  document.dispatchEvent(new CustomEvent('viewer-overlay-visibility-changed', {
    detail: { isOpen: true, source: 'search-side-panel' },
  }));
  document.dispatchEvent(new CustomEvent('viewer-side-panel-state-changed', {
    detail: { panel: 'search' },
  }));
  panel.querySelector('[data-close-viewer-panel]').addEventListener('click', closePanel);
  const input = panel.querySelector('input');
  const results = panel.querySelector('.viewer-search-results');
  const format = String(state.currentViewerFormat || '').toLowerCase();
  let timer = null;
  input.addEventListener('input', () => {
    clearTimeout(timer);
    timer = setTimeout(async () => {
      const query = input.value.trim();
      if (!query) {
        results.innerHTML = '<p class="viewer-panel-empty">검색어를 입력하세요.</p>';
        return;
      }
      if (format !== 'epub' && format !== 'txt') {
        results.innerHTML = '<p class="viewer-panel-empty">텍스트가 포함된 EPUB과 TXT에서 검색할 수 있습니다.</p>';
        return;
      }
      const module = await import('../viewer_txt.js?rev=20260927-tts-session-v8');
      const matches = module.searchTextViewer(query);
      results.innerHTML = '';
      if (!matches.length) {
        results.innerHTML = '<p class="viewer-panel-empty">검색 결과가 없습니다.</p>';
        return;
      }
      matches.forEach((match) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'viewer-search-result';
        const page = document.createElement('small');
        page.textContent = match.label || `${match.chapterIdx + 1}페이지`;
        const snippet = document.createElement('span');
        snippet.textContent = match.snippet;
        button.append(page, snippet);
        button.addEventListener('click', () => {
          module.jumpToTextSearchResult(match.chapterIdx);
        });
        results.appendChild(button);
      });
    }, 180);
  });
  if (initialQuery) {
    input.value = String(initialQuery).trim();
    input.dispatchEvent(new Event('input', { bubbles: true }));
  }
  input.setAttribute('inputmode', 'search');
  input.focus({ preventScroll: true });
}

export function closeViewerSidePanels() {
  closePanel();
  closeImageNotesPanel();
  document.querySelector('.epub-toc-back-btn')?.click();
}

document.addEventListener('viewer-side-panel-opening', (event) => {
  if (event.detail?.source !== 'search-side-panel') closePanel({ notify: false });
  if (event.detail?.source !== 'image-notes-side-panel') closeImageNotesPanel({ notify: false });
});
document.addEventListener('viewer-bookmarks-changed', () => {
  const panel = document.getElementById('viewer-image-notes-panel');
  if (panel) renderImageBookmarks(panel);
});
document.addEventListener('viewer-chrome-will-hide', () => {
  closePanel({ notify: false });
  closeImageNotesPanel({ notify: false });
});
function hasOpenViewerSidePanel() {
  const toc = document.getElementById('epub-toc-container');
  const tocOpen = toc && toc.style.visibility !== 'hidden' && toc.style.pointerEvents !== 'none';
  return Boolean(
    document.getElementById('viewer-search-panel')
    || document.getElementById('viewer-image-notes-panel')
    || tocOpen
  );
}

function handleViewerSidePanelOutside(event) {
  if (!hasOpenViewerSidePanel()) return;
  const target = event.target;
  if (target?.closest?.('.viewer-side-panel, #epub-toc-container, .ridi-viewer-toolbar-top')) return;
  event.preventDefault();
  event.stopPropagation();
  document.dispatchEvent(new CustomEvent('viewer-request-chrome-hide'));
}

// pointerdown을 먼저 처리해야 모바일에서 지연 click/합성 click이 본문 제스처로
// 재해석되기 전에 목차·독서노트·검색 패널을 닫을 수 있다.
document.addEventListener('pointerdown', handleViewerSidePanelOutside, true);
document.addEventListener('click', handleViewerSidePanelOutside, true);
document.addEventListener('viewer-closed', closeViewerSidePanels);
