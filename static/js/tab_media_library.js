// tab_media_library.js – 도서관 코어 엔트리 오케스트레이터 및 메인 라우터
import { state } from './state.js';
import * as api from './api.js';
import { openBookDetail, goBackToList } from './modal.js';
import { matchesRetainedDetailHistory, restoreBehindDetail } from './detail/history_navigation.js?rev=20260927-detail-back-v2';
import { updateCurrentCategoryIndicator } from './category_indicator.js';
import { openReader, closeMediaViewer, toggleFullscreenViewer, setComicFitMode, changeFontSize, toggleReaderTheme, initKeyboardListener, nextComicPage, prevComicPage, nextPdfPage, prevPdfPage, epubPrevPage, epubNextPage, prevTxtPage, nextTxtPage } from './viewer.js?rev=20260927-tts-session-v8';
import { switchActiveView } from './view_manager.js?rev=20260921-theme-mobile-v3';
import { flushProgress } from './viewer_progress.js?rev=20260927-tts-session-v8';
import './header_scroll_behavior.js';

// category.js CRUD 임포트
import { loadLibraries, triggerAddLibrary, triggerEditLibrary, triggerDeleteLibrary, closeLibraryModal, submitLibraryForm, triggerScanLibrary, triggerScanLibraryCovers, triggerCancelScanLibrary } from './category.js?rev=20260922-library-kinds-v5';
import { applySidebarShowMore, expandGroupContainingCategory } from './category/index.js?rev=20260922-library-kinds-v5';

// scheduler.js 임포트
import { loadLibrarySchedules, saveLibrarySchedule, runLibraryScanNow } from './scheduler.js';

// 서브 모듈 임포트
import { invalidateDashboardData, loadDashboardData, loadDashboardPlugins, switchPluginsViewTab } from './dashboard.js?v=20260926-home-layout-type-cache-v1';
import { initScrollableRowNavDelegation } from './scrollable_row_nav.js';
import { initInfiniteScrollObserver } from './infinite_scroll.js';
import { showBookContextMenu, triggerScanSingleBookAction, triggerSearchAladinMetadataAction, triggerMarkAsUnreadAction } from './book_context_menu.js?rev=20260927-tts-session-v8';
import { openMetadataSearchModal, closeMetadataSearchModal, performMetadataSearch } from './metadata_search.js?rev=20260927-metadata-scroll-v1';
import { getLoadedPageRange } from './book_list_refresh_state.js';

// book_list.js 임포트
import {
  loadBooksList,
  cancelPendingBookListRequests,
  restoreBookListPosition,
  invalidateBookListAfterScan,
  refreshBooksListIfStale,
  loadReadingHistory,
  filterBooks,
  toggleLibrarySort,
  resumeSeries,
  updateSortButtonUI,
  clearLibrarySearchQuery,
  restoreLibrarySearchQuery,
} from './book_list.js?rev=20260921-global-search-v1';
import { clearBookSelection } from './book_selection.js';

// plugin_custom_view.js 임포트
import { mountCategoryPluginUI } from './plugin_custom_view.js?rev=20260921-theme-mobile-v3';
import { switchSettingsTab, getPreferredSettingsTab, loadInitialSystemSettings, loadGeneralSettings, submitGeneralSettings, initReportsTab, loadReportList, loadReportDetail, loadViewerSettings, submitViewerSettings, applySettingsTabAccessControl } from './settings_tab.js?rev=20260921-plugin-settings-account-sync-v6';

// 장르/태그 및 사이드바 제어 모듈
import { initFloatingFilter, toggleFilterModal, refreshFilterCategory } from './genre_tag_filter.js?rev=20260926-filter-chip-click-stays-open-v1';
import { initSidebarInteractions, restoreDesktopSidebarState, toggleDesktopSidebar, syncSidebarResponsiveControls, runAfterMobileSidebarClose } from './sidebar_manager.js?rev=20260921-mobile-header-v6';
import { decodeDetailParams } from './url_obfuscator.js';

// 모듈화로 분리한 미디어 타입 토글 및 검색 단축키 제어부 임포트
import { canAccessLibraryType, applyLibraryTypeToggleVisibility, applyLibraryTypeButtonState, switchLibraryType, initLibraryTypeCollapse, toggleLibraryTypeCollapse } from './library_type_toggle.js?rev=20260921-mobile-header-v7';
import { applyGroupModeButtonState, switchGroupMode, restoreGroupModeView } from './author_group_toggle.js';
import { focusLibrarySearchInput, applySearchShortcutSetting, initLibrarySearchShortcut, handleLibrarySearchAction, handleLibrarySearchKeydown, initLibraryTypeHotkeys } from './search_shortcut_manager.js?rev=20260921-mobile-header-v6';
import { handleLibrarySearchDraft, initLibrarySearchPreview } from './library_search_preview.js?rev=20260921-search-preview-v1';
import { setSelectCategoryHandler } from './category_navigation.js?rev=20260920-library-content-kind-v2';
import { initUserProfile, loadUserProfile } from './user_profile.js?rev=20260922-profile-image-v2';

import './viewer/viewer_padding.js';
import './audio_player.js';
import './video_library.js';
import './author_group_context_menu.js';
import './video_player.js';
import './plugin_webview_api.js?rev=20260923-access-v1';

// 새로고침/뒤로가기 시 브라우저가 이전 스크롤 위치(내부 스크롤 컨테이너 포함)를
// 되살리면서 .library-main-content가 scrollTop 0이 아닌 채로 시작해 상단 검색창이
// 화면 밖으로 밀리는 경우가 있어(안드로이드 Chrome), 자동 복원을 끄고
// sidebar_manager.js의 resetScrollIfHeaderHidden()이 항상 0에서 시작하게 한다.
if ('scrollRestoration' in history) {
  history.scrollRestoration = 'manual';
}

function initLibraryShellDelegation() {
  if (window.__libraryShellDelegationBound) return;

  document.addEventListener('click', (event) => {
    const target = event && event.target && typeof event.target.closest === 'function'
      ? event.target.closest('[data-role="mobile-brand-home"], [data-role="sidebar-category-static"], [data-role="desktop-sidebar-toggle"], [data-role="library-search-action"], [data-role="library-open-filter"], [data-role="library-sort-toggle"], [data-role="library-type-collapse"], [data-role="library-type-toggle"], [data-role="grouping-mode-toggle"], [data-role="library-filter-reset"], [data-role="detail-back-to-list"]')
      : null;
    if (!target) return;

    event.preventDefault();

    const role = target.getAttribute('data-role');
    if (role === 'mobile-brand-home') {
      return runAfterMobileSidebarClose(() => selectCategory('home'));
    }
    if (role === 'sidebar-category-static') {
      const categoryId = target.getAttribute('data-category-id') || 'home';
      return runAfterMobileSidebarClose(() => selectCategory(categoryId));
    }
    if (role === 'desktop-sidebar-toggle') {
      return toggleDesktopSidebar();
    }
    if (role === 'library-search-action') {
      return handleLibrarySearchAction();
    }
    if (role === 'library-open-filter') {
      return toggleFilterModal();
    }
    if (role === 'library-sort-toggle') {
      return toggleLibrarySort();
    }
    if (role === 'library-type-collapse') {
      return toggleLibraryTypeCollapse();
    }
    if (role === 'library-type-toggle') {
      return switchLibraryType(target.getAttribute('data-library-type') || 'general');
    }
    if (role === 'grouping-mode-toggle') {
      return switchGroupMode(target.getAttribute('data-group-mode') || 'default');
    }
    if (role === 'library-filter-reset') {
      return window.resetAllFilters?.();
    }
    if (role === 'detail-back-to-list') {
      return goBackToList();
    }
  }, true);

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    const target = event.target?.closest?.('[data-role="mobile-brand-home"]');
    if (!target) return;
    event.preventDefault();
    selectCategory('home');
  });

  document.addEventListener('input', (event) => {
    const target = event && event.target;
    if (!target) return;
    if (target.matches && target.matches('[data-role="library-search-input"]')) {
      handleLibrarySearchDraft(target.value);
    }
  }, true);

  document.addEventListener('keydown', (event) => {
    const target = event && event.target;
    if (!target) return;
    if (target.matches && target.matches('[data-role="library-search-input"]')) {
      handleLibrarySearchKeydown(event);
    }
  }, true);

  window.__libraryShellDelegationBound = true;
  initLibrarySearchPreview(() => handleLibrarySearchAction());
}

function recoverTopCategoryUiAfterBack() {
  const isMobileLayout = window.matchMedia('(max-width: 1200px)').matches;
  if (!isMobileLayout) return;

  const libraryHeader = document.querySelector('.library-header');
  const searchCenter = document.querySelector('.library-search-center');
  const libraryControls = document.querySelector('.library-controls');
  const groupModeToggle = document.getElementById('group-mode-toggle-group');
  const libraryTypeToggle = document.getElementById('library-type-toggle-group');
  const sidebarCollapsible = document.getElementById('sidebar-collapsible-content');

  if (libraryHeader) libraryHeader.style.display = 'grid';
  if (searchCenter) searchCenter.style.display = 'block';
  if (libraryControls) libraryControls.style.display = 'flex';
  if (groupModeToggle) groupModeToggle.style.display = 'flex';
  if (libraryTypeToggle) libraryTypeToggle.style.display = 'flex';

  applyLibraryTypeToggleVisibility();
  initLibraryTypeCollapse();
  applyGroupModeButtonState(state.groupMode);
  // 뷰어 전체화면 종료 등으로 상단 사이드바(햄버거 메뉴)의 표시 상태가
  // 어긋난 채로 남는 경우를 대비해 back 복귀 시점에 항상 강제 재동기화한다.
  syncSidebarResponsiveControls();

  if (sidebarCollapsible) {
    const isOpen = sidebarCollapsible.classList.contains('show');
    sidebarCollapsible.hidden = !isOpen;
  }

  // 스크롤 복구 판정을 .library-header(검색/필터 카드) 하나만으로 하면, 그보다 더 위에
  // 있는 .sidebar-header-wrapper(BookOasis 로고+햄버거)가 화면 밖으로 스크롤됐어도
  // .library-header 자체는 아직 화면 안에 남아있어 복구 조건을 못 만족하는 경우가
  // 있었다(실사용자 리포트로 확인: headerRect.top이 -30~-59까지 나가는데도 복구가
  // 트리거 안 됨). html/body가 overflow:hidden이라도 iOS Safari는 키보드 표시/숨김,
  // 주소창 접힘 등으로 여전히 창을 스크롤시킬 수 있다 - 두 헤더 중 더 위에 있는
  // sidebarHeader 기준으로 판정하고, 임계값도 완화한다.
  const mainContent = document.querySelector('.library-main-content');
  const sidebarHeader = document.querySelector('.sidebar-header-wrapper');
  const rectsOutOfView = [libraryHeader, sidebarHeader].some((el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    return rect.bottom <= 0 || rect.top < -4;
  });
  if (rectsOutOfView) {
    if (mainContent) mainContent.scrollTop = 0;
    // y=0 대신 y=1: iOS Safari는 스크롤 위치가 정확히 0일 때 주소창을 펼치며
    // 페이지 콘텐츠 위에 겹쳐 그리는 버그가 있다.
    window.scrollTo(0, 1);
  }

  requestAnimationFrame(() => {
    window.dispatchEvent(new Event('resize'));
  });
}

function parseMediaTypeFromUrl() {
  try {
    const searchParams = new URLSearchParams(window.location.search);
    const qType = searchParams.get('type') || searchParams.get('media') || searchParams.get('db_type');
    if (qType) {
      const parsed = normalizeMediaType(qType);
      if (parsed) return parsed;
    }
  } catch (e) {}

  try {
    const rawHash = (window.location.hash || '').trim();
    if (rawHash) {
      const cleanHash = rawHash.replace(/^#/, '');
      if (cleanHash.includes('=')) {
        const hashParams = new URLSearchParams(cleanHash);
        const hType = hashParams.get('type') || hashParams.get('media') || hashParams.get('db_type');
        if (hType) {
          const parsed = normalizeMediaType(hType);
          if (parsed) return parsed;
        }
      }
      const lowerHash = cleanHash.toLowerCase();
      if (lowerHash.includes('audiobook') || lowerHash.includes('audio')) return 'audiobook';
      if (lowerHash.includes('adult') || lowerHash.includes('r18')) return 'adult';
      if (lowerHash.includes('general') || lowerHash.includes('book')) return 'general';
    }
  } catch (e) {}

  try {
    const savedType = localStorage.getItem('last_selected_library_type');
    if (savedType) {
      const parsed = normalizeMediaType(savedType);
      if (parsed) return parsed;
    }
  } catch (e) {}

  return null;
}

function parseLibraryIdFromUrl() {
  try {
    const searchParams = new URLSearchParams(window.location.search);
    const qLibrary = searchParams.get('library') || searchParams.get('library_id');
    if (qLibrary) return String(qLibrary).trim();
  } catch (e) {}

  try {
    const rawHash = (window.location.hash || '').trim();
    if (rawHash) {
      const cleanHash = rawHash.replace(/^#/, '');
      if (cleanHash.includes('=')) {
        const hashParams = new URLSearchParams(cleanHash);
        const hLibrary = hashParams.get('library') || hashParams.get('library_id');
        if (hLibrary) return String(hLibrary).trim();
      }
    }
  } catch (e) {}

  try {
    const savedLib = localStorage.getItem('last_selected_library_id');
    if (savedLib) return String(savedLib).trim();
  } catch (e) {}

  return null;
}

function parseKioskParamsFromUrl() {
  try {
    const searchParams = new URLSearchParams(window.location.search);
    if (searchParams.get('kiosk') !== '1') return null;
    const bookId = (searchParams.get('book') || '').trim();
    const pluginId = (searchParams.get('plugin') || '').trim();
    if (!bookId && !pluginId) return null;
    return {
      bookId,
      pluginId,
      type: normalizeMediaType(searchParams.get('type')) || 'general',
      returnUrl: (searchParams.get('return') || '').trim()
    };
  } catch (e) {
    return null;
  }
}

function injectKioskBackButton(returnUrl) {
  if (!returnUrl || document.getElementById('kiosk-back-btn')) return;
  const btn = document.createElement('button');
  btn.id = 'kiosk-back-btn';
  btn.type = 'button';
  btn.className = 'kiosk-back-btn';
  btn.title = '돌아가기';
  btn.innerHTML = '<i class="fa-solid fa-arrow-left"></i>';
  btn.addEventListener('click', () => {
    window.location.href = returnUrl;
  });
  document.body.appendChild(btn);
}

async function bootKioskMode({ bookId, pluginId, type, returnUrl }) {
  document.body.classList.add('kiosk-mode');
  if (returnUrl) {
    window.__kioskReturnUrl = returnUrl;
    injectKioskBackButton(returnUrl);
  }
  state.currentLibraryType = type;
  await loadInitialSystemSettings();

  if (pluginId) {
    mountCategoryPluginUI(pluginId);
    return;
  }

  try {
    const res = await fetch(`/api/media/books/${encodeURIComponent(bookId)}/reader-info?type=${encodeURIComponent(type)}`);
    const data = await res.json();
    if (!data.success) {
      console.error('[Kiosk] 도서 정보를 불러오지 못했습니다:', data.error);
      return;
    }
    const book = data.book;
    openReader(book.id, book.file_format, book.title, book.pages_read, book.total_pages);
  } catch (e) {
    console.error('[Kiosk] 리더 부팅 실패:', e);
  }
}

function normalizeMediaType(val) {
  if (!val) return null;
  val = String(val).toLowerCase().trim();
  if (['audiobook', 'audio', 'sound'].includes(val)) return 'audiobook';
  if (['video', 'course', 'lecture'].includes(val)) return 'video';
  if (['adult', 'r18'].includes(val)) return 'adult';
  if (['general', 'book', 'books', 'normal'].includes(val)) return 'general';
  return null;
}

// 메인 초기화 함수
async function initTabMediaLibrary() {
  // index.html의 i18n 초기화도 DOMContentLoaded에서 비동기로 실행된다. 사전이 준비되기
  // 전에 사이드바를 다시 그리면 번역 키가 그대로 노출됐다가 API 응답 후 또 바뀐다.
  if (!window.i18nReady) {
    await new Promise((resolve) => {
      let settled = false;
      const finish = () => {
        if (settled) return;
        settled = true;
        document.removeEventListener('i18nReady', finish);
        resolve();
      };
      document.addEventListener('i18nReady', finish, { once: true });
      window.setTimeout(finish, 5000);
    });
  }

  const kioskParams = parseKioskParamsFromUrl();
  if (kioskParams) {
    // 킷오스크 모드: 사이드바/설정 등 라이브러리 UI를 전혀 부팅하지 않고 지정된 책의 리더 또는 플러그인 화면만 즉시 연다.
    await bootKioskMode(kioskParams);
    return;
  }

  initLibraryShellDelegation();
  initScrollableRowNavDelegation();
  initUserProfile();

  if (window.currentUser) {
    state.currentUser = window.currentUser;
    const usernameEl = document.getElementById('session-username-display');
    if (usernameEl) usernameEl.innerText = state.currentUser.username;
    
    // 관리자 전용 설정 탭 버튼은 여기서 한 번에 노출/숨김을 결정한다
    // (탭별 개별 onclick 분기 대신 data-settings-tab 기반 공용 함수 사용, settings_tab.js 참고)
    applySettingsTabAccessControl();
  }

  applyLibraryTypeToggleVisibility();
  initLibraryTypeCollapse();
  applyGroupModeButtonState(state.groupMode);

  document.querySelectorAll('.library-modal').forEach(modal => {
    document.body.appendChild(modal);
  });

  await loadInitialSystemSettings();

  restoreDesktopSidebarState();
  initSidebarInteractions();
  initFloatingFilter();
  initInfiniteScrollObserver();
  initKeyboardListener();
  initLibrarySearchShortcut();
  initLibraryTypeHotkeys();

  window.addEventListener('popstate', async (event) => {
    recoverTopCategoryUiAfterBack();
    // 필터 조건은 URL에 포함하지 않는 일시적인 목록 상태다. 브라우저
    // 뒤로가기·다른 화면 이동에서는 이전 상세의 태그 조건을 남기지 않는다.
    if (typeof window.clearMetadataFilters === 'function') {
      window.clearMetadataFilters();
    }

    const viewerModal = document.getElementById('media-viewer-modal');
    let viewerWasOpen = viewerModal?.dataset.pendingHistoryClose === 'true';
    if (viewerModal) delete viewerModal.dataset.pendingHistoryClose;
    let handledDetailNavigation = false;
    if (viewerModal && viewerModal.style.display === 'flex') {
      if (!event.state || event.state.view !== 'viewer') {
        closeMediaViewer(false); 
        viewerWasOpen = true;
      } else {
        return;
      }
    }

    // 상세 화면에서 연 뷰어를 닫을 때는 상세 DOM이 뷰어 아래에 그대로 남아 있다.
    // 예전 로직은 이 경우에도 아래의 detail 분기로 들어가 selectCategory()를 먼저
    // 실행했기 때문에, 상세 API 응답을 기다리는 동안 시리즈 목록이 잠깐 노출됐다.
    // 같은 상세 히스토리로 돌아가는 경우에는 보존된 상세 화면을 즉시 활성화하고,
    // 진행률 반영을 위한 상세 데이터 갱신은 closeMediaViewer()의 백그라운드 작업에 맡긴다.
    const retainedDetailView = document.getElementById('book-detail-view');
    const retainedDetailMatchesHistory = matchesRetainedDetailHistory({
      hasContent: !!retainedDetailView && retainedDetailView.childElementCount > 0,
      series: state.detailSeriesName,
      libraryId: state.detailLibraryId,
      representativeBookId: state.detailRepresentativeBookId,
      libraryType: state.currentLibraryType || 'general',
    }, event.state);
    const canRestoreRetainedDetail = viewerWasOpen && retainedDetailMatchesHistory;

    // A dashboard reader does not need a list/detail detour on its way back.
    if (viewerWasOpen && ['category', 'list'].includes(event.state?.view)
        && String(event.state.libraryId) === String(state.currentLibraryId)
        && ['home', 'history'].includes(String(event.state.libraryId))) {
      switchActiveView(event.state.libraryId === 'home' ? 'dashboard' : 'grid');
      if (event.state.scrollTop !== undefined) restoreNavigationScroll(event.state.scrollTop, event.state.libraryId);
      return;
    }

    if (canRestoreRetainedDetail) {
      switchActiveView('detail');
      handledDetailNavigation = true;
    }
    
    if (handledDetailNavigation) {
      // 보존된 상세 화면을 동기적으로 복원했으므로 목록/상세 재탐색을 생략한다.
    } else if (event.state && event.state.view === 'search') {
      const targetType = event.state.type || state.currentLibraryType || 'general';
      if (state.currentLibraryType !== targetType) {
        applyLibraryTypeButtonState(canAccessLibraryType(targetType) ? targetType : 'general');
        await loadLibraries();
      }
      const searchQuery = String(event.state.searchQuery || '');
      restoreLibrarySearchQuery(searchQuery);
      await selectCategory(event.state.libraryId || 'all', true, {
        preserveSearch: true,
        searchQuery,
      });
      if (event.state.scrollTop !== undefined) {
        restoreNavigationScroll(event.state.scrollTop, event.state.libraryId || 'all');
      }
      handledDetailNavigation = true;
    } else if (event.state && event.state.view === 'group_mode') {
      const targetType = event.state.type || state.currentLibraryType || 'general';
      const typeChanged = state.currentLibraryType !== targetType;
      if (typeChanged) {
        applyLibraryTypeButtonState(targetType);
        await loadLibraries();
      }
      if (event.state.libraryId && (
        typeChanged
        || String(state.currentLibraryId) !== String(event.state.libraryId)
        || !!state.searchQuery
      )) {
        await selectCategory(event.state.libraryId, true);
      }
      restoreGroupModeView(event.state.mode, event.state.authorKey);
      if (event.state.scrollTop !== undefined) {
        restoreNavigationScroll(event.state.scrollTop, event.state.libraryId);
      }
      handledDetailNavigation = true;
    } else if (event.state && event.state.view === 'detail') {
      // 설정/프로필/다른 카테고리에서 상세 기록으로 돌아올 때 원래 카테고리를
      // 먼저 보여주고 상세 API를 기다리면 목록이 잠깐 깜빡인다. 기존 상세가 같은
      // 작품이면 DOM을 유지하고, 아니면 복원 안내를 보여준 채 목록 복원을 뒤에서 한다.
      const detailViewForRestore = document.getElementById('book-detail-view');
      if (detailViewForRestore) {
        if (!retainedDetailMatchesHistory) {
          detailViewForRestore.innerHTML = '<div class="loading-spinner">상세 화면을 복원하는 중입니다.</div>';
        }
        // selectCategory()가 현재 상세를 닫으며 #detail 기록을 목록으로 바꾸지
        // 않도록 먼저 숨긴다. 아래 helper는 목록 전환 직후 상세를 다시 활성화한다.
        detailViewForRestore.style.display = 'none';
      }
      const selectCategoryBehindDetail = (...args) => restoreBehindDetail(
        () => selectCategory(...args),
        () => switchActiveView('detail'),
      );

      const targetType = event.state.type || state.currentLibraryType || 'general';
      if (state.currentLibraryType !== targetType) {
        applyLibraryTypeButtonState(targetType);
        await loadLibraries();
      }

      // 상세 화면에서 작가/그림작가 검색으로 전체보기로 이동했다가 뒤로 오면,
      // 상세 화면을 열기 전 카테고리(또는 검색/작가별 상태)도 먼저 복원한다.
      const returnState = event.state.returnState;
      if (returnState && typeof returnState === 'object') {
        const returnType = returnState.type || targetType;
        const returnTypeChanged = state.currentLibraryType !== returnType;
        if (returnTypeChanged) {
          applyLibraryTypeButtonState(canAccessLibraryType(returnType) ? returnType : 'general');
          await loadLibraries();
        }

        if (returnState.view === 'search') {
          const searchQuery = String(returnState.searchQuery || '');
          await selectCategoryBehindDetail(returnState.libraryId || 'all', true, {
            preserveSearch: true,
            searchQuery,
          });
        } else if (returnState.view === 'group_mode') {
          if (returnState.libraryId && (
            returnTypeChanged
            || String(state.currentLibraryId) !== String(returnState.libraryId)
            || !!state.searchQuery
          )) {
            await selectCategoryBehindDetail(returnState.libraryId, true);
          }
          restoreGroupModeView(returnState.mode, returnState.authorKey);
        } else if (['category', 'list'].includes(returnState.view) && returnState.libraryId) {
          if (
            returnTypeChanged
            || String(state.currentLibraryId) !== String(returnState.libraryId)
            || !!state.searchQuery
          ) {
            await selectCategoryBehindDetail(returnState.libraryId, true);
          }
        } else {
          const fallbackLibraryId = event.state.sourceLibraryId || event.state.libraryId;
          if (fallbackLibraryId) {
            await selectCategoryBehindDetail(fallbackLibraryId, true);
          }
        }
      } else {
        const fallbackLibraryId = event.state.sourceLibraryId || event.state.libraryId;
        if (fallbackLibraryId) {
          await selectCategoryBehindDetail(fallbackLibraryId, true);
        }
      }
      const canReuseRetainedDetail = retainedDetailMatchesHistory
        && matchesRetainedDetailHistory({
          hasContent: !!detailViewForRestore && detailViewForRestore.childElementCount > 0,
          series: state.detailSeriesName,
          libraryId: state.detailLibraryId,
          representativeBookId: state.detailRepresentativeBookId,
          libraryType: state.currentLibraryType || 'general',
        }, event.state);
      switchActiveView('detail');
      if (!canReuseRetainedDetail) {
        if (detailViewForRestore) {
          detailViewForRestore.innerHTML = '<div class="loading-spinner">상세 화면을 복원하는 중입니다.</div>';
        }
        await openBookDetail(null, event.state.series, event.state.libraryId, event.state.repBookId || null, event.state.displayTitle || '');
      }
      if (returnState && returnState.scrollTop !== undefined) {
        rememberNavigationScroll(returnState.scrollTop, returnState.libraryId);
      }
      handledDetailNavigation = true;
    } else if ((!event.state || !event.state.view) && window.location.hash.startsWith('#detail')) {
      const restored = decodeDetailParams(window.location.hash);
      if (restored && restored.type && state.currentLibraryType !== restored.type) {
        applyLibraryTypeButtonState(restored.type);
        await loadLibraries();
      }
      if (restored && restored.series) {
        await openBookDetail(null, restored.series, restored.libraryId || 'all', restored.repBookId || null, restored.displayTitle || '');
        handledDetailNavigation = true;
      }
    }

    if (!handledDetailNavigation) {
      const detailView = document.getElementById('book-detail-view');
      if (detailView && detailView.style.display !== 'none') {
        goBackToList(false);
      }

      if (event.state && ['category', 'list'].includes(event.state.view) && event.state.libraryId) {
        const typeChanged = !!event.state.type && state.currentLibraryType !== event.state.type;
        if (event.state.type) {
          if (!canAccessLibraryType(event.state.type)) {
            applyLibraryTypeButtonState('general');
          } else {
            applyLibraryTypeButtonState(event.state.type);
          }
          await loadLibraries();
        }
        if (
          typeChanged
          || String(state.currentLibraryId) !== String(event.state.libraryId)
          || !!state.searchQuery
        ) {
          await selectCategory(event.state.libraryId, true);
        }
        if (event.state.scrollTop !== undefined) {
          restoreNavigationScroll(event.state.scrollTop, event.state.libraryId);
        }
      } else if (!event.state && (window.location.hash === '' || window.location.hash.startsWith('#library='))) {
        const hashType = parseMediaTypeFromUrl();
        if (hashType) {
          const resolvedType = canAccessLibraryType(hashType) ? hashType : 'general';
          applyLibraryTypeButtonState(resolvedType);
          if (resolvedType === 'video') {
            if (typeof window.loadVideoLibraryView === 'function') window.loadVideoLibraryView();
          } else {
            await loadLibraries();
          }
        }
        if (state.currentLibraryId !== 'home') {
          await selectCategory('home', true);
        }
      }
    }
  });

  const initialHash = window.location.hash || '';
  const isDetailDeepLink = initialHash.startsWith('#detail');
  const targetMediaType = parseMediaTypeFromUrl();

  if (targetMediaType) {
    if (!canAccessLibraryType(targetMediaType)) {
      applyLibraryTypeButtonState('general');
    } else {
      applyLibraryTypeButtonState(targetMediaType);
    }
  } else {
    applyLibraryTypeButtonState(state.currentLibraryType || 'general');
  }

  const targetLibraryId = parseLibraryIdFromUrl();
  const homeLanding = !isDetailDeepLink && (!targetLibraryId || targetLibraryId === 'home');
  let sidebarLoadPromise = null;

  // 초기 라이브러리 로드는 타입 적용 후에 수행한다. 홈 진입이라면 사이드바 플러그인
  // 목록까지 기다리지 않고 홈을 먼저 띄운 뒤, 카테고리 목록은 백그라운드에서 채운다.
  if (state.currentLibraryType === 'video') {
    if (typeof window.loadVideoLibraryView === 'function') await window.loadVideoLibraryView();
  } else if (homeLanding) {
    sidebarLoadPromise = loadLibraries();
  } else {
    await loadLibraries();
  }

  if (isDetailDeepLink) {
    const restoredDetail = decodeDetailParams(initialHash);
    if (restoredDetail && restoredDetail.series) {
      openBookDetail(null, restoredDetail.series, restoredDetail.libraryId || 'all', restoredDetail.repBookId || null, restoredDetail.displayTitle || '');
      return;
    }
  }

  const savedListPosition = history.state
    && ['category', 'list'].includes(history.state.view)
    && String(history.state.libraryId || '') === String(targetLibraryId || '')
    && String(history.state.type || state.currentLibraryType) === String(state.currentLibraryType)
    ? history.state
    : null;
  if (targetLibraryId && targetLibraryId !== 'home') {
    await selectCategory(targetLibraryId, true, { restoreListPosition: savedListPosition });
  } else {
    await selectCategory('home', true);
  }
  if (sidebarLoadPromise) await sidebarLoadPromise;
}

function makeCategoryHistoryState(libraryId, type = state.currentLibraryType) {
  return {
    view: 'category',
    type: type || 'general',
    libraryId: String(libraryId || 'home'),
  };
}

function getCurrentNavigationScrollTop() {
  const mainContent = document.querySelector('.library-main-content');
  const mainContentTop = Number(mainContent?.scrollTop || 0);
  const scrollTop = mainContentTop > 0
    ? mainContentTop
    : (window.pageYOffset || document.documentElement.scrollTop || mainContentTop);
  return Math.max(0, Math.round(Number(scrollTop) || 0));
}

function rememberNavigationScroll(scrollTop, libraryId = state.currentLibraryId) {
  const value = Number(scrollTop);
  if (!Number.isFinite(value) || value < 0) return;
  state.scrollPositions = state.scrollPositions || {};
  state.scrollPositions.last_pos = value;
  if (libraryId !== undefined && libraryId !== null) {
    state.scrollPositions[String(libraryId)] = value;
  }
}

function restoreNavigationScroll(scrollTop, libraryId = state.currentLibraryId) {
  const value = Number(scrollTop);
  if (!Number.isFinite(value) || value < 0) return;
  rememberNavigationScroll(value, libraryId);
  const apply = () => {
    const mainContent = document.querySelector('.library-main-content');
    if (mainContent) mainContent.scrollTop = value;
    const gridView = document.getElementById('books-grid-view');
    const dashboardView = document.getElementById('library-dashboard-view');
    if (gridView) gridView.scrollTop = mainContent ? 0 : value;
    if (dashboardView) dashboardView.scrollTop = mainContent ? 0 : value;
    const documentTop = window.matchMedia('(max-width: 1200px)').matches ? 0 : value;
    window.scrollTo(0, documentTop);
    document.documentElement.scrollTop = documentTop;
    document.body.scrollTop = documentTop;
  };
  requestAnimationFrame(apply);
  setTimeout(apply, 80);
}

function saveNavigationScrollState() {
  const current = history.state;
  if (!current || !['category', 'list'].includes(current.view)) return;
  if (String(current.libraryId || '') !== String(state.currentLibraryId || '')) return;
  if (String(current.type || 'general') !== String(state.currentLibraryType || 'general')) return;

  const mainContent = document.querySelector('.library-main-content');
  const mainTop = Number(mainContent?.scrollTop || 0);
  const documentTop = Number(window.pageYOffset || document.documentElement.scrollTop || document.body.scrollTop || 0);
  const pages = getLoadedPageRange(state.firstLoadedPage, state.currentPage, state.hasMore);
  try {
    history.replaceState({
      ...current,
      scrollTop: mainTop > 0 ? mainTop : documentTop,
      scrollUseDocument: !mainContent || (mainTop === 0 && documentTop > 0),
      firstLoadedPage: pages.firstPage,
      lastLoadedPage: pages.lastPage,
    }, '', window.location.href);
  } catch (error) {
    console.warn('[Navigation-Scroll] 스크롤 위치 저장 실패:', error);
  }
}

let scrollHistoryUpdateTimer = null;
const navigationScrollContainer = document.querySelector('.library-main-content');
navigationScrollContainer?.addEventListener('scroll', () => {
  // 모바일의 모든 document scroll 이벤트에서 history.replaceState를 실행하면
  // 카드 스크롤 중 메인 스레드 작업이 누적될 수 있다. 실제 목록이 멈춘 뒤 한 번만 저장한다.
  if (scrollHistoryUpdateTimer) window.clearTimeout(scrollHistoryUpdateTimer);
  scrollHistoryUpdateTimer = window.setTimeout(() => {
    scrollHistoryUpdateTimer = null;
    saveNavigationScrollState();
  }, 180);
}, { passive: true });
window.addEventListener('beforeunload', saveNavigationScrollState);

function makeCategoryHistoryUrl(libraryId, type = state.currentLibraryType) {
  const hashParams = new URLSearchParams({
    library: String(libraryId || 'home'),
    type: type || 'general',
  });
  return `${window.location.pathname}${window.location.search}#${hashParams.toString()}`;
}

function recordCategoryNavigation(id, skipHistory) {
  const currentLibraryId = String(state.currentLibraryId || 'home');
  const targetLibraryId = String(id || 'home');
  const currentType = state.currentLibraryType || 'general';

  // 앱 최초 진입 등 현재 엔트리에 state가 없을 때 기준 카테고리를 기록한다.
  // popstate에 의해 들어온 이동(skipHistory)은 기존 state를 그대로 둔다.
  if (skipHistory) {
    if (!history.state) {
      try {
        history.replaceState(makeCategoryHistoryState(targetLibraryId, currentType), '', window.location.href);
      } catch (e) {}
    }
    return;
  }

  // 검색 결과에서 다른 사이드바 항목으로 이동하면, 검색 상태를 현재 카테고리의
  // 검색어 없는 상태로 정리한 뒤 새 카테고리 엔트리를 쌓아 뒤로가기를 자연스럽게 한다.
  if (!history.state || history.state.view === 'search') {
    try {
      history.replaceState({
        ...makeCategoryHistoryState(currentLibraryId, currentType),
        scrollTop: getCurrentNavigationScrollTop(),
      }, '', window.location.href);
    } catch (e) {}
  } else if (history.state && history.state.view !== 'detail') {
    try {
      history.replaceState(
        { ...history.state, scrollTop: getCurrentNavigationScrollTop() },
        '',
        window.location.href
      );
    } catch (e) {}
  }

  const activeState = history.state;
  const alreadyAtTarget = targetLibraryId === currentLibraryId
    && ['category', 'list'].includes(activeState?.view)
    && String(activeState.libraryId || currentLibraryId) === targetLibraryId
    && String(activeState.type || currentType) === currentType;

  if (alreadyAtTarget) {
    if (activeState.view === 'list') {
      try {
      history.replaceState({
        ...makeCategoryHistoryState(targetLibraryId, currentType),
        scrollTop: getCurrentNavigationScrollTop(),
        firstLoadedPage: state.firstLoadedPage,
        lastLoadedPage: getLoadedPageRange(state.firstLoadedPage, state.currentPage, state.hasMore).lastPage,
      }, '', window.location.href);
      } catch (e) {}
    }
    return;
  }

  try {
    history.pushState(
      makeCategoryHistoryState(targetLibraryId, currentType),
      '',
      makeCategoryHistoryUrl(targetLibraryId, currentType)
    );
  } catch (e) {
    console.warn('[Category-Navigation] failed to save browser history state', e);
  }
}

let categoryNavigationSerial = 0;

export async function selectCategory(id, skipHistory = false, options = {}) {
  const navigationSerial = ++categoryNavigationSerial;
  cancelPendingBookListRequests();
  if (id === 'smart_rec' && state.smartRecommendEnabled === false) {
    id = 'home';
  }

  // 장르/태그 빠른 검색은 현재 목록에만 적용한다. 다른 카테고리·검색·상세로
  // 이동하면 이전 조건이 다음 목록까지 남지 않도록 화면 상태를 정리한다.
  if (typeof window.clearMetadataFilters === 'function') {
    window.clearMetadataFilters();
  }

  const preserveSearch = options && options.preserveSearch === true;
  if (preserveSearch) {
    const query = Object.prototype.hasOwnProperty.call(options, 'searchQuery')
      ? options.searchQuery
      : state.searchQuery;
    restoreLibrarySearchQuery(query);
  } else {
    clearLibrarySearchQuery();
  }

  if (options && options.searchNavigationFrom) {
    const returnLibraryId = String(options.searchNavigationFrom);
    const searchQuery = String(options.searchQuery || '').trim();
    const currentUrl = window.location.href;
    const returnState = {
      ...makeCategoryHistoryState(returnLibraryId, state.currentLibraryType),
      scrollTop: getCurrentNavigationScrollTop(),
    };
    try {
      history.replaceState(returnState, '', currentUrl);
      history.pushState(
        {
          view: 'search',
          type: state.currentLibraryType,
          libraryId: id,
          returnLibraryId,
          searchQuery,
          returnState,
        },
        '',
        currentUrl
      );
    } catch (e) {
      console.warn('[Search-Navigation] failed to save search history state', e);
    }
  } else if (options && options.searchNavigation === true) {
    const searchQuery = String(options.searchQuery || '').trim();
    const currentUrl = window.location.href;
    let returnState = history.state && typeof history.state === 'object'
      ? history.state
      : {
        ...makeCategoryHistoryState(state.currentLibraryId, state.currentLibraryType),
        scrollTop: getCurrentNavigationScrollTop(),
      };
    try {
      if (!history.state) {
        history.replaceState(returnState, '', currentUrl);
      } else if (returnState.view !== 'detail') {
        returnState = { ...returnState, scrollTop: getCurrentNavigationScrollTop() };
        history.replaceState(returnState, '', currentUrl);
      }
      history.pushState(
        {
          view: 'search',
          type: state.currentLibraryType,
          libraryId: id,
          searchQuery,
          returnState,
        },
        '',
        makeCategoryHistoryUrl(id, state.currentLibraryType)
      );
    } catch (e) {
      console.warn('[Search-Navigation] failed to save search history state', e);
    }
  } else {
    recordCategoryNavigation(id, skipHistory);
  }

  clearBookSelection();

  // 뷰어를 명시적으로 닫지 않고(예: X버튼) 사이드바 "홈"/"최근 읽은 도서" 메뉴를 바로 눌러
  // 나가는 경우, 마지막 페이지 진행률이 아직 디바운스 대기 중(최대 3초)이거나 방금 닫히면서
  // 예약된 저장이 서버에 완전히 반영되기 전에 이 함수의 히스토리 조회가 먼저 나갈 수 있다.
  // 그러면 "최근 읽은 도서" 응답이 1시간 캐시되는 서버 쪽 구조상, 방금 읽은 책이 빠진 스냅샷이
  // 그대로 굳어버려서 대시보드에 마지막으로 보던 책이 한 권 밀려 보이는 문제가 있었다.
  // 대기 중인 진행률이 있으면(없으면 즉시 반환되는 안전한 호출) 조회 전에 먼저 반영한다.
  // 진행률 반영은 화면 전환을 막지 않는다. 모바일에서는 네트워크 응답을
  // 기다리는 동안 메뉴가 멈춘 것처럼 보일 수 있다.
  const progressFlushPromise = (id === 'home' || id === 'history')
    ? Promise.resolve(flushProgress(false, true)).catch(() => null)
    : Promise.resolve(null);
  state.currentLibraryId = id;
  refreshFilterCategory();
  // 카테고리를 새로 선택하면 이전 카테고리에서 남은 작가별 드릴다운 필터를 초기화한다 -
  // 안 그러면 도서가 훨씬 많은 새 카테고리에서도 이전 드릴다운 결과(예: 3개 시리즈)만
  // 남아있어 "이 카테고리엔 도서가 몇 개 없다"고 착각하게 된다. (그룹 모드 자체(기본/작가별)는
  // 유지 - popstate의 group_mode 복원 분기가 이 값을 필요시 다시 채운다.)
  state.authorKeyFilter = '';
  try {
    localStorage.setItem('last_selected_library_id', id);
  } catch (e) {}

  document.querySelectorAll('#sidebar-categories .menu-item').forEach(item => {
    item.classList.remove('active');
  });

  let activeItem = document.querySelector(`#sidebar-categories .menu-item[data-category-id="${id}"]`);
  if (!activeItem) {
    activeItem = document.getElementById(`category-${id}`);
  }
  if (activeItem) {
    activeItem.classList.add('active');
    // 활성 카테고리가 숨겨진 영역에 있는 경우 자동 전개 (그룹 폴더로 접혀있던 경우 포함 -
    // loadLibraries() 렌더 시점엔 currentLibraryId가 아직 갱신 전이라 그룹이 저장된 접힘
    // 상태 그대로 렌더되므로, 여기서 실제 선택된 카테고리를 기준으로 다시 펼쳐준다)
    expandGroupContainingCategory(id);
    const sidebarEl = document.getElementById('sidebar-categories');
    if (sidebarEl) applySidebarShowMore(sidebarEl, id);
  }
  state.currentLibraryHideCovers = !!(activeItem && activeItem.dataset && activeItem.dataset.type === 'custom' && activeItem.dataset.hideCover === '1');
  state.currentLibraryAspectRatio = (activeItem && activeItem.dataset && activeItem.dataset.coverAspectRatio === '16:9') ? '16:9' : '4:3';
  state.currentLibraryHideTitles = !!(activeItem && activeItem.dataset && activeItem.dataset.type === 'custom' && activeItem.dataset.hideTitle === '1');
  updateCurrentCategoryIndicator(id, activeItem);

  // 정렬 버튼 라벨을 실제 상태(state.currentSortDirection)와 동기화.
  // 이전에는 toggleLibrarySort()를 눌러야만 라벨이 갱신되어, 카테고리 전환 시
  // 실제로는 "최신 추가순" 등으로 정렬된 채로 로드되는데도 버튼엔 항상
  // 초기 HTML의 "가나다 오름차순" 텍스트가 그대로 남아있는 문제가 있었다.
  updateSortButtonUI();

  // 상세 화면에서 라이브러리를 바꿀 때만 상세 복귀 처리를 한다. 목록 화면에서
  // 이 함수를 항상 호출하면 상세에서 마지막으로 저장한 last_pos를 다시 적용해
  // 라이브러리 전환 때 현재 스크롤 위치가 위로 튈 수 있다.
  const detailView = document.getElementById('book-detail-view');
  if (detailView && detailView.style.display !== 'none') {
    goBackToList();
  }

  if (id === 'home') {
    // 영상 세션도 오디오북과 동일하게 공용 대시보드(최근 시청/신규 추가)를 그대로 재사용한다.
    // series_repository/reading_progress_repository가 이미 db_type='video' 분기를 갖고 있어
    // 별도 전용 홈 화면 없이도 targetType='video'로 정상 동작한다.
    switchActiveView('dashboard');
    loadDashboardData();
    progressFlushPromise.then((result) => {
      if (!result || navigationSerial !== categoryNavigationSerial || state.currentLibraryId !== 'home') return;
      invalidateDashboardData(state.currentLibraryType);
      loadDashboardData({ force: true });
    });
  } else if (id === 'collection') {
    switchActiveView('grid');
    import('./tab_collections.js').then((colls) => {
      if (navigationSerial === categoryNavigationSerial) colls.renderCollectionsView();
    });
  } else if (id === 'smart_rec') {
    switchActiveView('grid');
    import('./tab_smart_recommend.js').then((mod) => {
      if (navigationSerial === categoryNavigationSerial) mod.renderSmartRecommendView();
    });
  } else if (id === 'settings') {
    switchActiveView('settings');
    // 마지막으로 열어 둔 접근 가능한 설정 탭을 복원한다. schedule 탭 데이터는
    // switchSettingsTab()이 직접 갱신하므로 여기서 중복 호출하지 않는다.
    switchSettingsTab(getPreferredSettingsTab());
  } else if (id === 'profile') {
    switchActiveView('profile');
    loadUserProfile();
  } else if (id === 'plugins') {
    switchActiveView('plugins');
    loadDashboardPlugins();
  } else if (id.startsWith('plugin_')) {
    const pluginId = id.replace('plugin_', '');
    mountCategoryPluginUI(pluginId);
  } else {
    switchActiveView('grid');
    if (state.currentLibraryType === 'video' && !['history', 'all', 'favorite'].includes(id)) {
      const numericId = parseInt(id, 10);
      if (Number.isFinite(numericId) && typeof window.loadVideoCourseGrid === 'function') {
        window.loadVideoCourseGrid(numericId);
      } else {
        const container = document.getElementById('books-list-container');
        if (container) container.innerHTML = '<div class="loading-spinner">좌측에서 영상 강좌 라이브러리를 선택하거나, 없다면 + 버튼으로 추가해 주세요.</div>';
      }
    } else if (id === 'history') {
      loadReadingHistory();
    } else if (options.restoreListPosition) {
      await restoreBookListPosition(options.restoreListPosition);
    } else {
      loadBooksList(false, null, { preserveScroll: !skipHistory });
    }
  }

  if (navigationSerial !== categoryNavigationSerial) return;
  window.dispatchEvent(new CustomEvent('library:category-selected', {
    detail: { id, skipHistory }
  }));
}

// 글로벌 전역 함수 노출
setSelectCategoryHandler(selectCategory);
window.selectCategory = selectCategory;
window.switchLibraryType = switchLibraryType;
window.filterBooks = filterBooks;
// 스캔 완료(scan_activity_status.js)와 상세→목록 복귀(detail/index.js)에서 호출하는 목록 갱신 훅
window.invalidateBookListAfterScan = invalidateBookListAfterScan;
window.refreshBooksListIfStale = refreshBooksListIfStale;
window.openReader = openReader;
window.openBookDetail = openBookDetail;
window.goBackToList = goBackToList;
window.invalidateBookListAfterScan = invalidateBookListAfterScan;
window.refreshBooksListIfStale = refreshBooksListIfStale;
window.setComicFitMode = setComicFitMode;
window.closeMediaViewer = closeMediaViewer;
window.toggleFullscreenViewer = toggleFullscreenViewer;
window.changeFontSize = changeFontSize;
window.toggleReaderTheme = toggleReaderTheme;
window.nextComicPage = nextComicPage;
window.prevComicPage = prevComicPage;
window.nextPdfPage = nextPdfPage;
window.prevPdfPage = prevPdfPage;
window.epubPrevPage = epubPrevPage;
window.epubNextPage = epubNextPage;
window.prevTxtPage = prevTxtPage;
window.nextTxtPage = nextTxtPage;
window.toggleLibrarySort = toggleLibrarySort;
window.resumeSeries = resumeSeries;

document.addEventListener('DOMContentLoaded', () => {
  initTabMediaLibrary()
    .catch((error) => {
      console.error('[Library-Init] 초기 화면 구성 실패:', error);
    })
    .finally(() => {
      document.documentElement.classList.remove('app-booting');
    });
});
