// 라이브러리 도서 카드 선택 상태와 Ctrl/Shift 다중 선택을 관리합니다.
import { state } from './state.js';

const selectedCards = new Map();
let selectionScope = '';
let selectionAnchor = null;
let toolbar = null;
let rangeRequest = null;
let selectionVersion = 0;

function getScope() {
  return JSON.stringify([state.currentLibraryType || 'general', state.currentLibraryId ?? '',
    state.searchQuery || '', state.currentSortDirection || 'asc', state.filterGenres || [],
    state.filterTags || [], state.groupMode || '', state.authorKeyFilter || '']);
}

function getSelectableCard(target) {
  const card = target && typeof target.closest === 'function'
    ? target.closest('.book-card')
    : null;
  return card && card.querySelector('[data-role="book-card-select-toggle"]')
    ? card
    : null;
}

function targetFromCard(card) {
  const id = Number.parseInt(card.dataset.bookId || '', 10);
  if (!Number.isFinite(id) || id <= 0) return null;

  const rawLibraryId = card.dataset.libraryId || '';
  const parsedLibraryId = Number.parseInt(rawLibraryId, 10);
  return {
    id,
    title: String(card.dataset.title || '도서'),
    markUnreadScope: card.dataset.markUnreadScope || 'book',
    seriesName: String(card.dataset.seriesName || '').trim(),
    libraryId: Number.isFinite(parsedLibraryId) ? parsedLibraryId : null,
    fileFormat: String(card.dataset.fileFormat || '').toLowerCase(),
    coverAlign: card.dataset.coverAlign || 'center',
    isVolumeDetail: false,
    selectionKey: `${getScope()}:${parsedLibraryId || ''}:${id}`,
  };
}

function setCardSelected(card, selected) {
  card.classList.toggle('book-card--selected', selected);
  const button = card.querySelector('[data-role="book-card-select-toggle"]');
  if (button) {
    button.setAttribute('aria-pressed', selected ? 'true' : 'false');
    button.setAttribute('aria-label', selected ? '선택 해제' : '작품 선택');
  }
}

function ensureToolbar() {
  if (toolbar && toolbar.isConnected) return toolbar;

  toolbar = document.createElement('div');
  toolbar.id = 'book-selection-toolbar';
  toolbar.className = 'book-selection-toolbar';
  toolbar.setAttribute('role', 'status');
  toolbar.setAttribute('aria-live', 'polite');

  const summary = document.createElement('span');
  summary.className = 'book-selection-toolbar-summary';
  summary.dataset.role = 'book-selection-summary';

  const hint = document.createElement('span');
  hint.className = 'book-selection-toolbar-hint';
  hint.textContent = '선택한 작품을 우클릭해 일괄 작업';

  const clearButton = document.createElement('button');
  clearButton.type = 'button';
  clearButton.className = 'book-selection-clear';
  clearButton.dataset.role = 'book-selection-clear';
  clearButton.innerHTML = '<i class="fa-solid fa-xmark" aria-hidden="true"></i><span>선택 해제</span>';

  toolbar.append(summary, hint, clearButton);
  document.body.append(toolbar);
  return toolbar;
}

function updateToolbar() {
  const count = selectedCards.size;
  const element = ensureToolbar();
  element.hidden = count === 0;
  const summary = element.querySelector('[data-role="book-selection-summary"]');
  if (summary) summary.textContent = rangeRequest ? '범위 선택 중…' : `${count}개 선택`;
}

function setSelected(card, selected) {
  const target = targetFromCard(card);
  if (!target) return;

  if (selected) {
    selectedCards.set(target.selectionKey, { ...target, card });
  } else {
    selectedCards.delete(target.selectionKey);
  }
  setCardSelected(card, selected);
  updateToolbar();
}

function ensureCurrentScope() {
  const scope = getScope();
  if (selectionScope && selectionScope !== scope) clearBookSelection();
  selectionScope = scope;
}

async function selectRange(anchor, endCard) {
  const grid = endCard.closest('#books-list-container');
  if (!grid) return;
  const endTarget = targetFromCard(endCard);
  if (!endTarget) return;
  const scope = getScope();
  cancelRangeRequest();
  const version = selectionVersion;
  // Initial-bar jumps and DOM pruning can leave every intermediate card unloaded.
  // Resolve the inclusive range using the server's initial-bar ordering, not DOM order.
  if (['asc', 'desc'].includes(state.currentSortDirection || 'asc')
      && state.groupMode !== 'author' && !state.authorKeyFilter) {
    const controller = new AbortController();
    rangeRequest = controller;
    updateToolbar();
    try {
      const params = new URLSearchParams({
        type: state.currentLibraryType, library_id: state.currentLibraryId,
        search: state.searchQuery || '', sort: state.currentSortDirection || 'asc',
        genres: (state.filterGenres || []).join(','), tags: (state.filterTags || []).join(','),
        start_id: anchor.id, start_library_id: anchor.libraryId,
        end_id: endTarget.id, end_library_id: endTarget.libraryId,
      });
      const response = await fetch(`/api/media/list/selection-range?${params}`, {
        cache: 'no-store', signal: controller.signal,
      });
      const data = await response.json();
      if (version !== selectionVersion || scope !== getScope()) return;
      if (!response.ok || !data.success || !Array.isArray(data.targets)) {
        throw new Error(data.error || '범위 선택에 실패했습니다. 다시 시도해 주세요.');
      }
      const targets = data.targets.map(target => ({...target,
        selectionKey: `${scope}:${target.libraryId || ''}:${target.id}`}));
      const shouldSelect = !targets.every(target => selectedCards.has(target.selectionKey));
      for (const target of targets) {
        if (shouldSelect) selectedCards.set(target.selectionKey, target);
        else selectedCards.delete(target.selectionKey);
      }
      grid.querySelectorAll('.book-card').forEach(syncBookSelectionCard);
    } catch (error) {
      if (error.name !== 'AbortError' && version === selectionVersion && scope === getScope()) {
        const { showToast } = await import('./view_manager.js');
        showToast(error.message, 'error');
      }
    } finally {
      if (rangeRequest === controller) {
        rangeRequest = null;
        updateToolbar();
      }
    }
    return;
  }
  const cards = Array.from(grid.querySelectorAll('.book-card'))
    .filter(card => card.querySelector('[data-role="book-card-select-toggle"]'));
  const start = cards.findIndex(card => targetFromCard(card)?.selectionKey === anchor.selectionKey);
  const end = cards.indexOf(endCard);
  if (start < 0 || end < 0) {
    setSelected(endCard, true);
    return;
  }

  const first = Math.min(start, end);
  const last = Math.max(start, end);
  const range = cards.slice(first, last + 1);
  const shouldSelect = !range.every(isBookCardSelected);
  for (const card of range) setSelected(card, shouldSelect);
}

export function getSelectedBookTargets() {
  ensureCurrentScope();
  return Array.from(selectedCards.values()).map(({ card, ...target }) => target);
}

export function isBookCardSelected(card) {
  const target = card ? targetFromCard(card) : null;
  return !!target && selectedCards.has(target.selectionKey);
}

export function syncBookSelectionCard(card) {
  if (!card || !card.querySelector('[data-role="book-card-select-toggle"]')) return;
  const target = targetFromCard(card);
  if (target && selectedCards.has(target.selectionKey)) {
    selectedCards.set(target.selectionKey, { ...target, card });
  }
  setCardSelected(card, !!target && selectedCards.has(target.selectionKey));
}

function cancelRangeRequest() {
  selectionVersion += 1;
  rangeRequest?.abort();
  rangeRequest = null;
}

export function clearBookSelection() {
  cancelRangeRequest();
  selectedCards.forEach(({ card }) => {
    if (card) setCardSelected(card, false);
  });
  selectedCards.clear();
  selectionAnchor = null;
  updateToolbar();
}

document.addEventListener('click', (event) => {
  const clearButton = event.target.closest?.('[data-role="book-selection-clear"]');
  if (clearButton) {
    event.preventDefault();
    clearBookSelection();
    return;
  }

  const selectionButton = event.target.closest?.('[data-role="book-card-select-toggle"]');
  if (selectionButton) {
    const card = getSelectableCard(selectionButton);
    if (!card) return;
    event.preventDefault();
    event.stopPropagation();
    ensureCurrentScope();
    const selected = isBookCardSelected(card);
    if (event.shiftKey && selectionAnchor) {
      selectRange(selectionAnchor, card);
    } else {
      cancelRangeRequest();
      setSelected(card, !selected);
      selectionAnchor = targetFromCard(card);
    }
    return;
  }

  const card = getSelectableCard(event.target);
  if (!card || event.button !== 0) return;

  const usesMultiSelect = event.ctrlKey || event.metaKey || event.shiftKey;
  if (usesMultiSelect) {
    event.preventDefault();
    event.stopPropagation();
    ensureCurrentScope();
    if (event.shiftKey && selectionAnchor) {
      selectRange(selectionAnchor, card);
    } else {
      cancelRangeRequest();
      setSelected(card, !isBookCardSelected(card));
      selectionAnchor = targetFromCard(card);
    }
    return;
  }

  if (selectedCards.size > 0) clearBookSelection();
}, true);

document.addEventListener('contextmenu', (event) => {
  const card = getSelectableCard(event.target);
  if (card && selectedCards.size > 0) ensureCurrentScope();
}, true);
