// genre_tag_filter.js – 장르 및 태그 플로팅 모달창 관리 모듈
import { state } from './state.js';

let genresData = [];
let tagsData = [];
let selectedGenres = new Set();
let selectedTags = new Set();
let currentTab = 'genres'; // 'genres' or 'tags'
let activeDrag = false;
let currentX = 0;
let currentY = 0;
let initialX = 0;
let initialY = 0;
let xOffset = 0;
let yOffset = 0;

function normalizeMetadataToken(token) {
    if (!token) return '';
    return String(token)
        .replace(/^[\s'"\[\],]+|[\s'"\[\],]+$/g, '')
        .replace(/\s{2,}/g, ' ')
        .trim();
}

// genre/tags 값은 DB의 books.genre/books.tags(사용자/플러그인/MCP 쓰기 도구가 채울 수 있는
// 자유 텍스트)에서 온다 - innerHTML로 꽂기 전에 반드시 이스케이프해야 한다.
function escapeHtml(value) {
    return String(value ?? '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

export async function initFloatingFilter() {
    const modal = document.getElementById('floating-filter-modal');
    const header = document.getElementById('filter-modal-header');
    const btnClose = document.getElementById('btn-filter-close');
    const btnReset = document.getElementById('btn-filter-reset');
    const btnApply = document.getElementById('btn-filter-apply');
    const tabGenres = document.getElementById('tab-genres');
    const tabTags = document.getElementById('tab-tags');
    const searchInput = document.getElementById('filter-search-input');

    if (!modal) return;

    // 드래그 앤 드롭 바인딩
    header.addEventListener('mousedown', dragStart);
    document.addEventListener('mouseup', dragEnd);
    document.addEventListener('mousemove', drag);

    // 버튼 이벤트 바인딩
    btnClose.addEventListener('click', toggleFilterModal);
    btnReset.addEventListener('click', resetAllFilters);
    btnApply.addEventListener('click', applyFilters);

    tabGenres.addEventListener('click', () => switchFilterTab('genres'));
    tabTags.addEventListener('click', () => switchFilterTab('tags'));
    searchInput.addEventListener('input', onFilterSearchChange);

    // 필터 창 바깥을 클릭하면 닫는다. 필터 창 내부의 검색/탭/칩 조작과
    // 필터 열기 버튼을 다시 누르는 동작은 외부 클릭으로 처리하지 않는다.
    if (document.body.dataset.floatingFilterOutsideBound !== '1') {
        document.body.dataset.floatingFilterOutsideBound = '1';
        document.addEventListener('click', (event) => {
            const currentModal = document.getElementById('floating-filter-modal');
            const currentAnchor = document.getElementById('btn-open-filter');
            if (!currentModal || currentModal.style.display === 'none') return;

            const target = event.target;
            // Chips rerender their container on selection, which detaches the
            // clicked node before this document-level listener runs. `contains`
            // then incorrectly treats that internal click as an outside click.
            // The event path is captured before dispatch and still includes the
            // modal after its child is replaced.
            const eventPath = typeof event.composedPath === 'function' ? event.composedPath() : [];
            if ((target instanceof Element && (currentModal.contains(target) || currentAnchor?.contains(target))) ||
                eventPath.includes(currentModal) || (currentAnchor && eventPath.includes(currentAnchor))) {
                return;
            }

            currentModal.style.display = 'none';
        });
    }

    if (modal.dataset.positionBound !== '1') {
        modal.dataset.positionBound = '1';
        window.addEventListener('resize', () => {
            if (modal.style.display !== 'none') positionFilterModal();
        });
    }

    // 전역 함수 바인딩 (HTML onclick 바인딩 호환용)
    window.toggleFilterModal = toggleFilterModal;
    window.selectGenreFilter = selectGenreFilter;
    window.selectTagFilter = selectTagFilter;
    window.quickFilterByGenre = quickFilterByGenre;
    window.quickFilterByTag = quickFilterByTag;
    window.removeActiveFilterItem = removeActiveFilterItem;
    window.resetAllFilters = resetAllFilters;
}

function positionFilterModal() {
    const modal = document.getElementById('floating-filter-modal');
    const anchor = document.getElementById('btn-open-filter');
    if (!modal || !anchor) return;

    const margin = 8;
    const anchorRect = anchor.getBoundingClientRect();
    const modalRect = modal.getBoundingClientRect();
    const top = Math.min(Math.max(margin, anchorRect.bottom + margin), Math.max(margin, window.innerHeight - 180));
    const availableHeight = Math.max(0, window.innerHeight - top - margin);
    const maxHeight = Math.min(window.innerHeight * 0.7, availableHeight);
    const left = Math.min(
        Math.max(margin, anchorRect.right - modalRect.width),
        Math.max(margin, window.innerWidth - modalRect.width - margin),
    );

    currentX = 0;
    currentY = 0;
    initialX = 0;
    initialY = 0;
    xOffset = 0;
    yOffset = 0;
    modal.style.top = `${Math.round(top)}px`;
    modal.style.left = `${Math.round(left)}px`;
    modal.style.right = 'auto';
    modal.style.bottom = 'auto';
    modal.style.maxHeight = `${Math.round(maxHeight)}px`;
    modal.style.transform = 'none';
}

function sleep(ms) {
    return new Promise(resolve => setTimeout(resolve, ms));
}

async function ensureBooksReady(timeoutMs = 5000) {
    const started = Date.now();
    while (Date.now() - started < timeoutMs) {
        if (!state.isLoading) {
            return;
        }
        await sleep(60);
    }
}

async function ensureFilterDataLoaded() {
    if (genresData.length === 0 || tagsData.length === 0) {
        await loadGenresAndTagsData();
    }
}

function getCurrentLibraryIdForFilterOptions() {
    // Option scope belongs to the selected category, never the last detail view
    // or the separate "search tags in all libraries" preference.
    return state.currentLibraryId || 'all';
}

export function refreshFilterCategory() {
    genresData = [];
    tagsData = [];
    const modal = document.getElementById('floating-filter-modal');
    if (modal && modal.style.display !== 'none') {
        loadGenresAndTagsData();
    }
}

function getScopedLibraryIdForTagFilter() {
    if (state.tagFilterSearchInAll) {
        return 'all';
    }

    return getCurrentLibraryIdForFilterOptions();
}

async function prepareTargetCategoryForQuickFilter() {
    const targetCategoryId = getScopedLibraryIdForTagFilter();
    const shouldSwitchCategory = String(state.currentLibraryId) !== String(targetCategoryId);
    if (shouldSwitchCategory && typeof window.selectCategory === 'function') {
        // The quick-filter history entry is created by leaveDetailForQuickFilter.
        // Do not add a second category entry or Back would stop there instead of
        // returning to the detail page.
        window.selectCategory(targetCategoryId, true);
        await ensureBooksReady();
        return;
    }

    // 이미 그리드 카테고리라면 로딩이 완료될 때까지 대기
    await ensureBooksReady();
}

async function applySingleFilter(type, value, options = {}) {
    const normalizedValue = normalizeMetadataToken(value);
    if (!normalizedValue) return;

    await prepareTargetCategoryForQuickFilter();

    // 상세 화면의 빠른 태그/장르 검색은 하나의 검색 조건으로 동작한다.
    // 일반 필터 모달의 다중 선택 동작은 그대로 유지한다.
    if (options.replace) {
        selectedGenres.clear();
        selectedTags.clear();
    }
    if (type === 'genre') {
        selectedGenres.add(normalizedValue);
        state.filterGenres = Array.from(selectedGenres);
    } else {
        selectedTags.add(normalizedValue);
        state.filterTags = Array.from(selectedTags);
    }

    await ensureFilterDataLoaded();

    // 현재 탭을 맞춰 두면 사용자가 필터 모달을 열 때 선택 상태를 직관적으로 확인 가능
    currentTab = type === 'genre' ? 'genres' : 'tags';

    renderChips();
    renderSelectedChips();

    if (typeof window.filterBooks === 'function') {
        window.filterBooks();
    }
    
    updateActiveFilterBar();
}

export async function selectGenreFilter(genreName) {
    await applySingleFilter('genre', genreName);
}

export async function selectTagFilter(tagName) {
    await applySingleFilter('tag', tagName);
}

export async function quickFilterByGenre(genreName) {
    await leaveDetailForQuickFilter();
    await applySingleFilter('genre', genreName, { replace: true });
}

export async function quickFilterByTag(tagName) {
    await leaveDetailForQuickFilter();
    await applySingleFilter('tag', tagName, { replace: true });
}

// 상세 화면에서 필터를 누르면 현재 상세 엔트리를 브라우저 히스토리에
// 남긴 채 목록 엔트리를 새로 쌓는다. 따라서 모바일 뒤로가기가 이전 상세로
// 돌아오고, 목록으로 이동할 때는 기존 태그/장르 선택을 비운다.
async function leaveDetailForQuickFilter() {
    const current = history.state;
    if (current?.view === 'detail') {
        const libraryId = current.sourceLibraryId || current.libraryId || state.currentLibraryId || 'all';
        const type = current.type || state.currentLibraryType || 'general';
        const params = new URLSearchParams({ library: String(libraryId), type: String(type) });
        try {
            history.pushState(
                { view: 'list', type, libraryId, scrollTop: current.returnState?.scrollTop || 0 },
                '',
                `${window.location.pathname}${window.location.search}#${params.toString()}`,
            );
        } catch (error) {
            console.warn('[Filter] 상세→목록 히스토리 저장 실패:', error);
        }
    }
    if (typeof window.goBackToList === 'function') window.goBackToList(false);
}

// 모달 토글
export function toggleFilterModal() {
    const modal = document.getElementById('floating-filter-modal');
    if (!modal) return;
    
    if (modal.style.display === 'none') {
        modal.style.display = 'flex';
        positionFilterModal();
        // 카테고리/스코프 변경 시 stale 데이터가 남지 않도록 모달 오픈마다 재조회
        loadGenresAndTagsData();
    } else {
        modal.style.display = 'none';
    }
}

let filterDataRequestId = 0;

// 장르 및 태그 데이터 로드
export async function loadGenresAndTagsData() {
    const requestId = ++filterDataRequestId;
    const libraryId = getCurrentLibraryIdForFilterOptions();
    const dbType = state.currentLibraryType || 'general';
    const isCurrent = () => requestId === filterDataRequestId &&
        String(libraryId) === String(getCurrentLibraryIdForFilterOptions()) &&
        dbType === (state.currentLibraryType || 'general');
    // Do not keep the previous library/account's chips visible during refresh.
    genresData = [];
    tagsData = [];
    renderChips();
    const genresUrl = `/api/media/genres?type=${dbType}&library_id=${libraryId}`;
    const tagsUrl = `/api/media/tags?type=${dbType}&library_id=${libraryId}`;

    try {
        const [genresHttp, tagsHttp] = await Promise.all([
            fetch(genresUrl),
            fetch(tagsUrl),
        ]);

        let genresRes = {};
        let tagsRes = {};
        try {
            genresRes = await genresHttp.json();
        } catch (e) {}
        try {
            tagsRes = await tagsHttp.json();
        } catch (e) {}

        if (!isCurrent()) return;

        if (genresRes.success) {
            genresData = Array.from(new Set((genresRes.genres || []).map(normalizeMetadataToken).filter(Boolean)));
        } else {
            genresData = [];
        }
        if (tagsRes.success) {
            tagsData = Array.from(new Set((tagsRes.tags || []).map(normalizeMetadataToken).filter(Boolean)));
        } else {
            tagsData = [];
        }

        renderChips();
        renderSelectedChips();
    } catch (err) {
        if (!isCurrent()) return;
        genresData = [];
        tagsData = [];
        renderChips();
        console.error("[Filter] 장르 및 태그 목록 로드 실패:", err);
    }
}

// 탭 스위치
function switchFilterTab(tabName) {
    currentTab = tabName;
    
    const tabGenres = document.getElementById('tab-genres');
    const tabTags = document.getElementById('tab-tags');
    
    if (tabName === 'genres') {
        tabGenres.classList.add('active');
        tabTags.classList.remove('active');
    } else {
        tabTags.classList.add('active');
        tabGenres.classList.remove('active');
    }
    
    // 검색창 초기화 및 칩 렌더링
    document.getElementById('filter-search-input').value = '';
    renderChips();
}

// 실시간 검색 매칭
function onFilterSearchChange() {
    renderChips();
}

// 칩 렌더링
function renderChips() {
    const wrapper = document.getElementById('filter-chips-wrapper');
    const searchVal = document.getElementById('filter-search-input').value.trim().toLowerCase();
    
    if (!wrapper) return;
    wrapper.innerHTML = '';

    const list = currentTab === 'genres' ? genresData : tagsData;
    const selectedSet = currentTab === 'genres' ? selectedGenres : selectedTags;

    // 검색어 매칭 필터링
    const filteredList = list.filter(item => item.toLowerCase().includes(searchVal));

    if (filteredList.length === 0) {
        const noResultText = (window.i18n && typeof window.i18n.t === 'function')
            ? window.i18n.t('filter.no_results', '검색 결과가 없습니다.')
            : '검색 결과가 없습니다.';
        wrapper.innerHTML = `<span style="font-size: 0.8rem; color: var(--app-text-muted); margin: 1rem auto;">${noResultText}</span>`;
        return;
    }

    filteredList.forEach(item => {
        const chip = document.createElement('div');
        chip.className = `filter-chip-item ${selectedSet.has(item) ? 'active' : ''}`;
        chip.innerText = item;
        chip.addEventListener('click', () => {
            toggleChipSelection(item);
        });
        wrapper.appendChild(chip);
    });
}

// 칩 선택/해제 토글
function toggleChipSelection(item) {
    const normalizedItem = normalizeMetadataToken(item);
    if (!normalizedItem) return;

    const selectedSet = currentTab === 'genres' ? selectedGenres : selectedTags;
    if (selectedSet.has(normalizedItem)) {
        selectedSet.delete(normalizedItem);
    } else {
        selectedSet.add(normalizedItem);
    }
    renderChips();
    renderSelectedChips();
}

// 선택된 칩 레이아웃 업데이트
function renderSelectedChips() {
    const container = document.getElementById('selected-chips-container');
    if (!container) return;

    container.innerHTML = '';
    
    if (selectedGenres.size === 0 && selectedTags.size === 0) {
        container.style.display = 'none';
        return;
    }

    container.style.display = 'flex';

    selectedGenres.forEach(genre => {
        const chip = createSelectedChipElement('genres', genre);
        container.appendChild(chip);
    });

    selectedTags.forEach(tag => {
        const chip = createSelectedChipElement('tags', tag);
        container.appendChild(chip);
    });
}

function createSelectedChipElement(type, value) {
    const chip = document.createElement('div');
    chip.className = 'filter-chip-selected';
    chip.title = `[${type === 'genres' ? '장르' : '태그'}] ${value}`;
    chip.innerHTML = `<span>[${type === 'genres' ? '장르' : '태그'}] ${escapeHtml(value)}</span> <i class="fa-solid fa-xmark" style="font-size: 0.7rem;"></i>`;
    chip.addEventListener('click', () => {
        if (type === 'genres') {
            selectedGenres.delete(value);
        } else {
            selectedTags.delete(value);
        }
        renderChips();
        renderSelectedChips();
    });
    return chip;
}

// 필터 적용
export async function applyFilters() {
    // 선택된 필터 값을 state 객체에 보관하여 도서 검색과 결합할 수 있도록 전달
    state.filterGenres = Array.from(selectedGenres);
    state.filterTags = Array.from(selectedTags);

    await prepareTargetCategoryForQuickFilter();

    // 필터링 적용을 위해 기존의 도서 검색/렌더링 호출
    if (typeof window.filterBooks === 'function') {
        window.filterBooks();
    }
    
    // 알림 바 UI 업데이트
    updateActiveFilterBar();

    // 모달 닫기
    toggleFilterModal();
}

// 필터 전체 초기화
export function resetAllFilters() {
    clearFilterState();
    
    document.getElementById('filter-search-input').value = '';
    renderChips();
    renderSelectedChips();

    // 필터링 갱신 호출
    if (typeof window.filterBooks === 'function') {
        window.filterBooks();
    }
    
    // 알림 바 UI 업데이트 (숨김 처리)
    updateActiveFilterBar();
}

export function clearFilterState({ render = true } = {}) {
    selectedGenres.clear();
    selectedTags.clear();
    state.filterGenres = [];
    state.filterTags = [];
    if (!render) return;
    const input = document.getElementById('filter-search-input');
    if (input) input.value = '';
    renderChips();
    renderSelectedChips();
    updateActiveFilterBar();
}

// 드래그 앤 드롭 자유 이동
function dragStart(e) {
    const modal = document.getElementById('floating-filter-modal');
    if (e.target.closest('.filter-modal-header-actions')) return; // 닫기/초기화 버튼 클릭 시 드래그 방지

    initialX = e.clientX - xOffset;
    initialY = e.clientY - yOffset;

    if (e.target === document.getElementById('filter-modal-header') || e.target.parentNode === document.getElementById('filter-modal-header')) {
        activeDrag = true;
    }
}

function dragEnd(e) {
    initialX = currentX;
    initialY = currentY;
    activeDrag = false;
}

function drag(e) {
    if (activeDrag) {
        e.preventDefault();
        
        currentX = e.clientX - initialX;
        currentY = e.clientY - initialY;

        xOffset = currentX;
        yOffset = currentY;

        setTranslate(currentX, currentY, document.getElementById('floating-filter-modal'));
    }
}

function setTranslate(xPos, yPos, el) {
    el.style.transform = "translate3d(" + xPos + "px, " + yPos + "px, 0)";
}

if (!document.body.dataset.activeFilterRemoveDelegated) {
    document.body.dataset.activeFilterRemoveDelegated = '1';
    document.addEventListener('click', (event) => {
        const removeButton = event.target.closest('[data-role="active-filter-remove"]');
        if (!removeButton) return;

        event.preventDefault();
        event.stopPropagation();
        removeActiveFilterItem(removeButton.dataset.filterType, removeButton.dataset.filterValue || '');
    });
}

// 기존 사이드바 필터 토글 호환용 스텁 함수
export function updateSidebarFilterActiveStates() {}

// 모듈이 직접 import되는 경로에서도 전역 함수가 필요하므로 안전 바인딩
window.selectGenreFilter = selectGenreFilter;
window.selectTagFilter = selectTagFilter;
window.quickFilterByGenre = quickFilterByGenre;
window.quickFilterByTag = quickFilterByTag;
window.clearMetadataFilters = () => clearFilterState();

// 필터 활성 알림 바 동적 렌더링
export function updateActiveFilterBar() {
    const bar = document.getElementById('active-filter-bar');
    const badgeContainer = document.getElementById('active-filter-badges');
    if (!bar || !badgeContainer) return;

    const totalFilters = selectedGenres.size + selectedTags.size;
    if (totalFilters === 0) {
        bar.style.display = 'none';
        badgeContainer.innerHTML = '';
        return;
    }

    let html = '';
    selectedGenres.forEach(genre => {
        html += `<span class="active-filter-item">
            <i class="fa-solid fa-list-ul"></i> ${escapeHtml(genre)}
            <span class="filter-remove-btn" data-role="active-filter-remove" data-filter-type="genre" data-filter-value="${escapeHtml(genre)}"><i class="fa-solid fa-xmark"></i></span>
        </span>`;
    });
    selectedTags.forEach(tag => {
        html += `<span class="active-filter-item">
            <i class="fa-solid fa-tag"></i> ${escapeHtml(tag)}
            <span class="filter-remove-btn" data-role="active-filter-remove" data-filter-type="tag" data-filter-value="${escapeHtml(tag)}"><i class="fa-solid fa-xmark"></i></span>
        </span>`;
    });

    badgeContainer.innerHTML = html;
    bar.style.display = 'flex';
}

export function removeActiveFilterItem(type, value) {
    if (type === 'genre') {
        selectedGenres.delete(value);
    } else if (type === 'tag') {
        selectedTags.delete(value);
    }
    renderChips();
    renderSelectedChips();
    applyFilters();
}
window.removeActiveFilterItem = removeActiveFilterItem;
