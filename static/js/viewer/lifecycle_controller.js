// lifecycle_controller.js - open/close orchestration for viewer modal
import { state } from '../state.js';
import { ComicViewer, clearComicViewer } from '../viewer_comic.js';
import { TxtViewer } from '../viewer_txt.js?rev=20260927-tts-session-v8';
import { PdfViewer, clearPdfViewer } from '../viewer_pdf.js';
import { tryAutoFullscreenOnOpen, exitFullscreenIfNeeded } from './fullscreen_controller.js';
import { shouldAutoFullscreenForFormat } from './platform_profile.js';
import { flushProgress, resetPreloadState, setProgressSnapshotProvider } from '../viewer_progress.js?rev=20260927-tts-session-v8';
import { setAnnotationUiEnabled } from './annotation_ui.js?rev=20260922-reader-session-v45';

let deps = {
  initViewerSeekBar: () => {},
  syncHotspotPointerEvents: () => {},
  clearEpubViewer: () => {},
};

let activeViewerInstance = null;
setProgressSnapshotProvider(() => activeViewerInstance?.prepareForClose?.());

function resetViewerSeekbarForOpen() {
  const slider = document.getElementById('viewer-page-slider');
  const label = document.getElementById('seekbar-start-label');
  const tooltip = document.getElementById('seekbar-tooltip');
  if (slider) {
    slider.min = '1';
    slider.max = '1';
    slider.value = '1';
    slider.style.setProperty('--seek-progress', '0%');
    slider.dataset.seekMode = 'page';
  }
  if (label) label.textContent = '– / –';
  if (tooltip) tooltip.classList.remove('visible');
}

export function configureLifecycleController(nextDeps = {}) {
  deps = { ...deps, ...nextDeps };
}

export function getActiveViewerInstance() {
  return activeViewerInstance;
}

export function openReader(bookId, format, title, pagesRead, totalPages) {
  const existingModal = document.getElementById('media-viewer-modal');
  if (existingModal?.style.display === 'flex' && String(state.activeBookId) === String(bookId)) return;
  console.log(`[Viewer-Core] openReader 시작 - Book ID: ${bookId}, Format: ${format}, Title: ${title}`);

  const fmt = String(format || '').toLowerCase();
  const audioFormats = ['mp3', 'm4b', 'm4a', 'flac', 'aac', 'wav', 'ogg', 'opus', 'audiobook'];
  if (audioFormats.includes(fmt) || state.currentLibraryType === 'audiobook') {
    if (typeof window.openAudioPlayer === 'function') {
      // 오디오북 공통 진입점에서는 전달받은 bookId를 작품 ID로 취급한다.
      // (트랙 단위 재생 진입은 상세/이어보기에서 openAudioPlayer를 직접 호출)
      window.openAudioPlayer(bookId, null, pagesRead);
      return;
    }
  }

  if (fmt === 'video' || state.currentLibraryType === 'video') {
    if (typeof window.openVideoPlayer === 'function') {
      // 강좌(작품) ID를 전달받아 이어보기 위치(episode/time)는 플레이어 내부에서 진도 조회로 복원한다.
      window.openVideoPlayer(bookId);
      return;
    }
  }

  import('../viewer_next_episode.js').then((m) => {
    if (m.clearNextEpisodeArm) {
      console.log('[Viewer-Core] Resetting next episode arming state for new reader session');
      m.clearNextEpisodeArm();
    }
  }).catch(() => {});

  state.activeBookId = bookId;
  const viewerModal = document.getElementById('media-viewer-modal');
  if (!viewerModal) return;
  // 텍스트 뷰어는 도구 모음 표시 여부와 무관하게 첫 입력부터 본문이 직접 포인터를 받는다.
  viewerModal.dataset.viewerFormat = fmt;

  if (viewerModal.parentNode !== document.body) {
    document.body.appendChild(viewerModal);
  }

  viewerModal.style.display = 'flex';
  const viewerTitle = document.getElementById('viewer-title-text');
  if (viewerTitle) {
    // 실제 작품명을 넣은 뒤 전역 i18n 재적용이 기본 문구("독서 중…")로 다시
    // 덮어쓰지 않도록 번역 마커를 제거한다.
    viewerTitle.removeAttribute('data-i18n');
    viewerTitle.textContent = title;
  }
  window.syncViewerDisplayModeUI?.();
  window.resetViewerChrome?.();

  // 플랫폼/포맷 정책 기반 자동 전체화면 분기 (수동 전체화면 버튼은 별도로 유지)
  if (shouldAutoFullscreenForFormat(fmt)) {
    tryAutoFullscreenOnOpen();
  }

  if (window.location.hash !== '#viewer') {
    history.pushState({ view: 'viewer', bookId, libraryId: state.currentLibraryId }, '', '#viewer');
  }

  document.body.style.setProperty('overflow', 'hidden', 'important');
  document.documentElement.style.setProperty('overflow', 'hidden', 'important');

  const overlayMenu = document.getElementById('comic-overlay-menu');
  if (overlayMenu) overlayMenu.style.display = 'none';

  const floatingCloseBtn = document.querySelector('.floating-close-btn');
  if (floatingCloseBtn) floatingCloseBtn.style.display = 'none';

  document.querySelectorAll('.viewer-pane').forEach((p) => {
    p.style.display = 'none';
  });
  document.getElementById('txt-controls').style.display = 'none';
  document.getElementById('comic-fit-controls').style.display = 'none';

  const overlayComicFit = document.getElementById('overlay-comic-fit-group');
  const overlayTxtControls = document.getElementById('overlay-txt-controls-row');
  if (overlayComicFit) overlayComicFit.style.display = 'none';
  if (overlayTxtControls) overlayTxtControls.style.display = 'none';

  // 폰트 목록은 관리자가 업로드할 때만 바뀌는 정적 정보라 페이지 최초 로드 시(viewer.js) 한 번만
  // 받아오면 충분하다 — 예전엔 여기서 책을 열 때마다 매번 /api/media/fonts를 다시 호출하고
  // <style>/<select>를 통째로 재빌드했는데, 하필 현재 페이지 fetch와 같은 타이밍이라 대역폭까지
  // 나눠 먹는 완전히 불필요한 낭비였다.
  const savedFont = localStorage.getItem('viewer_font_family') || 'gothic';
  const select = document.getElementById('viewer-font-select');
  if (select) select.value = savedFont;

  const savedLineHeight = localStorage.getItem('viewer_line_height') || '1.8';
  const selectLineHeight = document.getElementById('viewer-line-height-select');
  if (selectLineHeight) selectLineHeight.value = savedLineHeight;

  const savedParagraphSpacing = localStorage.getItem('viewer_paragraph_spacing') || '1.0';
  const selectParagraphSpacing = document.getElementById('viewer-paragraph-spacing-select');
  if (selectParagraphSpacing) selectParagraphSpacing.value = savedParagraphSpacing;

  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const btnPage = document.getElementById('btn-scroll-page');
  const btnScroll = document.getElementById('btn-scroll-continuous');
  if (scrollMode === 'page') {
    if (btnPage) btnPage.classList.add('active');
    if (btnScroll) btnScroll.classList.remove('active');
  } else {
    if (btnPage) btnPage.classList.remove('active');
    if (btnScroll) btnScroll.classList.add('active');
  }

  const widthRow = document.getElementById('overlay-width-row');
  if (widthRow) widthRow.classList.toggle('visible', scrollMode === 'scroll');

  const savedScrollWidth = parseInt(localStorage.getItem('comic_scroll_width'), 10) || 800;
  const widthSlider = document.getElementById('comic-scroll-width-slider');
  const widthLabel = document.getElementById('comic-scroll-width-label');
  if (widthSlider) widthSlider.value = savedScrollWidth;
  if (widthLabel) widthLabel.textContent = `${savedScrollWidth}px`;

  state.currentViewerFormat = fmt;
  // 이전 책의 4/17 같은 값이 새 책의 실제 페이지 수를 가져오기 전 잠깐 보이지 않게 한다.
  resetViewerSeekbarForOpen();
  if (typeof window.syncViewerControlsForFormat === 'function') {
    window.syncViewerControlsForFormat(fmt);
  }
  setAnnotationUiEnabled(fmt === 'txt' || fmt === 'epub');

  if (activeViewerInstance && typeof activeViewerInstance.destroy === 'function') {
    try {
      console.log(`[Viewer-Core] 기존 활성 뷰어 정리: ${state.currentViewerFormat}`);
      activeViewerInstance.destroy();
    } catch (e) {
      console.warn('[Viewer-Core] Failed to destroy active viewer:', e);
    }
  }
  activeViewerInstance = null;

  if (fmt === 'zip' || fmt === 'cbz' || fmt === 'imgdir') {
    if (overlayComicFit) overlayComicFit.style.display = 'flex';
    activeViewerInstance = ComicViewer;
    activeViewerInstance.init(bookId, pagesRead, totalPages).then(() => {
      deps.initViewerSeekBar();
    });
  } else if (fmt === 'txt') {
    if (overlayTxtControls) overlayTxtControls.style.display = 'flex';
    document.getElementById('comic-overlay-page-info').textContent = i18n.t('viewer.view_text') || '텍스트 보기';
    activeViewerInstance = TxtViewer;
    activeViewerInstance.init(bookId, pagesRead);
    deps.initViewerSeekBar();
  } else if (fmt === 'pdf') {
    activeViewerInstance = PdfViewer;
    activeViewerInstance.init(bookId, pagesRead, totalPages);
    deps.initViewerSeekBar();
  } else if (fmt === 'epub') {
    if (overlayTxtControls) overlayTxtControls.style.display = 'flex';
    document.getElementById('comic-overlay-page-info').textContent = i18n.t('viewer.view_epub') || 'EPUB 보기';
    activeViewerInstance = TxtViewer;
    activeViewerInstance.init(bookId, pagesRead);
    deps.initViewerSeekBar();
  } else {
    alert(i18n.t('viewer.unsupported_format'));
    closeMediaViewer();
  }

  deps.syncHotspotPointerEvents();
  document.dispatchEvent(new CustomEvent('viewer-book-opened', {
    detail: { bookId, format: fmt }
  }));
}

export function closeMediaViewer(triggerBack = true, isTransitioning = false) {
  const closingBookId = state.activeBookId;
  const closingLibraryType = state.currentLibraryType;
  const viewerModal = document.getElementById('media-viewer-modal');
  if (!viewerModal) return Promise.resolve();
  if (viewerModal.style.display === 'none' && !activeViewerInstance) return Promise.resolve();
  // The close button hides the modal before popstate fires. Retain that fact so
  // routing can restore the underlying view just as it does for browser Back.
  if (triggerBack && !isTransitioning && window.location.hash === '#viewer') {
    viewerModal.dataset.pendingHistoryClose = 'true';
  }

  if (activeViewerInstance && typeof activeViewerInstance.prepareForClose === 'function') {
    try {
      activeViewerInstance.prepareForClose();
    } catch (e) {
      console.warn('[Viewer-Core] Error preparing viewer for close:', e);
    }
  }

  const fullscreenExitPromise = exitFullscreenIfNeeded();

  if (!isTransitioning) {
    const menu = document.getElementById('comic-overlay-menu');
    let savedScrollY = 0;
    const wasIosBodyLocked = !!(menu && menu.dataset.iosBodyLock === 'true');
    if (wasIosBodyLocked) {
      savedScrollY = parseInt(menu.dataset.savedBodyScrollY || '0', 10);
      delete menu.dataset.savedBodyScrollY;
      delete menu.dataset.iosBodyLock;
    }

    viewerModal.classList.remove('fullscreen-mode');
    viewerModal.style.display = 'none';
    document.dispatchEvent(new CustomEvent('viewer-closed'));
    const fullscreenIcon = document.getElementById('fullscreen-icon');
    if (fullscreenIcon) fullscreenIcon.className = 'fa-solid fa-expand';

    // body 및 documentElement 인라인 스크롤 락 스타일만 안전 소거 (CSS 변수 유실 방지)
    document.body.style.removeProperty('overflow');
    document.documentElement.style.removeProperty('overflow');

    // navigation.js::toggleComicOverlay()가 iOS 스크롤 모드에서 오버레이를 열 때 건
    // position:fixed/top/width 스크롤 락은 오버레이를 다시 닫는 경로에서만 풀린다.
    // 마지막 페이지(다음권 이어보기/닫기 오버레이)처럼 락이 걸린 채로 뷰어 자체가
    // closeMediaViewer()로 바로 닫히면 이 스타일이 지워지지 않아 body가 옛 스크롤
    // 위치에 고정된 채 남고(화면이 예전 상태로 보임), position:fixed라 스크롤/탭도
    // 먹통이 되던 버그가 있었다 - 여기서도 동일하게 정리해준다.
    if (wasIosBodyLocked) {
      document.body.style.removeProperty('position');
      document.body.style.removeProperty('top');
      document.body.style.removeProperty('width');
    }

    if (state.systemSettings) {
      import('../settings/general.js').then(m => {
        if (m.applySettingsToUI) m.applySettingsToUI(state.systemSettings);
      }).catch(() => {});
    }

    if (savedScrollY > 0) {
      window.scrollTo(0, savedScrollY);
    }

    // 모바일 브라우저 뷰포트 레이아웃 재계산 및 카테고리 헤더 리플로우 유도
    const forceLayoutRecovery = () => {
      // 강제 리플로우: 일부 모바일 브라우저는 Fullscreen 종료 직후 safe-area/뷰포트
      // 단위(env(), dvh)를 즉시 재계산하지 않아 상단 사이드바(햄버거 메뉴)가
      // 잘못된 크기로 그려진 채 남는 경우가 있어, 실제 스타일 재계산을 강제한다.
      void document.body.offsetHeight;
      window.dispatchEvent(new Event('resize'));
      import('../sidebar_manager.js').then((m) => {
        if (m.syncSidebarResponsiveControls) m.syncSidebarResponsiveControls();
      }).catch(() => {});
    };

    requestAnimationFrame(forceLayoutRecovery);
    // exitFullscreenIfNeeded()는 비동기로 완료되므로, 전환이 실제로 끝난 뒤
    // 한 번 더 복구를 수행해 Fullscreen 종료 타이밍과의 경쟁 상태를 방지한다.
    Promise.resolve(fullscreenExitPromise)
      .then(() => requestAnimationFrame(forceLayoutRecovery))
      .catch(() => {});
  }

  if (activeViewerInstance && typeof activeViewerInstance.destroy === 'function') {
    try {
      console.log('[Viewer-Core] activeViewerInstance.destroy() 실행');
      activeViewerInstance.destroy();
    } catch (e) {
      console.warn('[Viewer-Core] Error destroying viewer instance:', e);
    }
    activeViewerInstance = null;
  } else {
    clearComicViewer();
    deps.clearEpubViewer();
    clearPdfViewer();
  }

  const flushPromise = flushProgress(false, true);
  resetPreloadState();

  const reloadData = () => {
    if (document.body.classList.contains('kiosk-mode')) {
      // 킷오스크 모드는 사이드바/대시보드가 아예 로드되지 않으므로, 진행도 저장 후
      // 외부(예: my_supporter /tv)에서 넘겨준 복귀 URL로 곧장 이동시킨다.
      if (window.__kioskReturnUrl) {
        window.location.href = window.__kioskReturnUrl;
      }
      return;
    }
    console.log('[Viewer-Core] DB Progress flush 완료. 화면 데이터 갱신을 실행합니다.');
    if (state.currentLibraryId === 'home') {
      import('../dashboard.js?v=20260926-home-layout-type-cache-v1').then((d) => d.loadDashboardData({ force: true }));
    } else if (state.currentLibraryId === 'history') {
      import('../book_list.js?rev=20260920-mobile-request-cancel-v4').then((b) => b.loadReadingHistory());
    }

    const detailView = document.getElementById('book-detail-view');
    if (detailView) {
      // 상세 DOM을 통째로 다시 열면 먼저 목록이 보였다가 상세로 바뀌고, 상세 플러그인의
      // 추천 로딩 문구도 다시 나타난다. 보존된 상세 화면은 그대로 두고 필요한 위젯만
      // 선택적으로 갱신할 수 있도록 완료 이벤트만 전달한다.
      document.dispatchEvent(new CustomEvent('viewer-progress-flushed', {
        detail: { bookId: closingBookId, type: closingLibraryType, seriesName: state.detailSeriesName || '' }
      }));
    }
  };

  flushPromise
    .then(() => reloadData())
    .catch((error) => {
      console.warn('[Viewer-Core] Immediate progress flush failed; retrying view refresh:', error);
      window.setTimeout(reloadData, 2000);
    });

  if (triggerBack && !isTransitioning && window.location.hash === '#viewer') {
    history.back();
  }

  // 다음 책/에피소드 전환처럼 닫자마자 곧바로 새 뷰어를 여는 호출부가
  // Fullscreen 종료 전환이 실제로 끝날 때까지 기다릴 수 있도록 반환한다.
  // (특히 Android는 exitFullscreen이 비동기로 늦게 끝나는데, 이걸 기다리지 않고
  //  바로 다음 책에서 requestFullscreen을 다시 호출하면 브라우저가 두 번째
  //  요청을 조용히 무시해 화면이 멈춘 것처럼 보이는 문제가 있었다.)
  return Promise.resolve(fullscreenExitPromise);
}

export function handleBookDeletedFallback(reason = '해당 도서(카테고리)가 서버에서 삭제되었습니다.') {
  console.warn(`[Viewer-Fallback] 도서 삭제 감지 404: ${reason}`);
  
  // 1. 진행 중인 뷰어 닫기
  try {
    closeMediaViewer(false);
  } catch (e) {}
  
  // 2. 사용자용 알림 표출
  if (typeof window.showToast === 'function') {
    window.showToast(`⚠️ ${reason} 목록 화면으로 이동합니다.`, 'error');
  } else {
    alert(`⚠️ ${reason}\n목록 화면으로 이동합니다.`);
  }

  // 3. 해시 정리 및 목록으로 안전 이동
  if (window.location.hash === '#viewer') {
    window.location.hash = '';
  }
}

window.handleBookDeletedFallback = handleBookDeletedFallback;
