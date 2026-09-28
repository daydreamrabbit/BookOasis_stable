// input_controller.js - keyboard/wheel/hotspot/click input handlers for viewer
import { state } from '../state.js';
import { getTapDirection } from './tap_direction.js';

let _deps = {
  toggleFullscreenViewer: null,
  isViewerInFullscreen: null,
  closeMediaViewer: null,
  nextPage: null,
  prevPage: null,
  toggleComicOverlay: null,
  toggleViewerChrome: null,
  shiftSpreadByOne: null,
  movePageByOne: null,
};

let keyboardListenerInitialized = false;
let wheelLock = false;
let wheelRepeatCount = 0;
let wheelLastDirection = 0;
let wheelLastTurnAt = 0;
let wheelDeltaAccumulator = 0;
let viewerClickToggleInited = false;

export function configureInputController(deps = {}) {
  _deps = { ..._deps, ...deps };
}

function callDep(name, ...args) {
  const fn = _deps[name];
  if (typeof fn === 'function') {
    return fn(...args);
  }
  return undefined;
}

function isPointOnSelectableText(clientX, clientY) {
  // Caret APIs can snap to clipped text in an adjacent CSS column even when
  // the user clicked the reader margin. Only the actually hit text is selectable.
  const hitChunk = document.elementFromPoint(clientX, clientY)
    ?.closest?.('.txt-chunk[data-idx], .txt-scroll-chunk[data-idx]');
  if (!hitChunk) return false;
  const caret = document.caretRangeFromPoint?.(clientX, clientY)
    || document.caretPositionFromPoint?.(clientX, clientY);
  const node = caret?.startContainer || caret?.offsetNode;
  if (!node) return false;
  const element = node.nodeType === Node.TEXT_NODE ? node.parentElement : node;
  if (element?.closest?.('.txt-chunk[data-idx], .txt-scroll-chunk[data-idx]') !== hitChunk) return false;
  if (node.nodeType !== Node.TEXT_NODE || !node.textContent?.trim()) return false;
  const range = document.createRange();
  range.selectNodeContents(node);
  return Array.from(range.getClientRects()).some((rect) => (
    clientX >= rect.left - 2 && clientX <= rect.right + 2
    && clientY >= rect.top - 2 && clientY <= rect.bottom + 2
  ));
}

// 페이지 배치(1|2/2|1)와 입력 방향은 별개 설정이다.
function isViewerRtlFlowActive() {
  const { vertical, reverse } = getTapDirection();
  return !vertical && reverse;
}

// 높이맞춤 + 1장 보기에서 너비가 화면보다 커져(좌우가 가려짐) 롱프레스+드래그로 팬이 가능한
// 상태인지 확인한다. 팬 대상이 없으면(너비맞춤 모드, 스크롤 모드, 페이지가 이미 화면 안에
// 다 들어오는 경우 등) null을 반환해 롱프레스가 그냥 평범한 탭/스와이프로 흘러가게 둔다.
function getPannableComicImage() {
  const isComicFormat = ['zip', 'cbz', 'imgdir'].includes((state.currentViewerFormat || '').toLowerCase());
  if (!isComicFormat) return null;

  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  if (scrollMode !== 'page') return null;

  const fitMode = (typeof window.Settings !== 'undefined' && typeof window.Settings.getFitMode === 'function')
    ? window.Settings.getFitMode()
    : 'height';
  if (fitMode !== 'height') return null;

  const pair = document.querySelector('.comic-image-wrapper .comic-page-pair.single-page');
  if (!pair) return null;
  const img = pair.querySelector('img');
  const wrapper = document.querySelector('.comic-image-wrapper');
  if (!img || !wrapper || !img.naturalWidth) return null;

  const renderedWidth = img.getBoundingClientRect().width;
  const wrapperWidth = wrapper.getBoundingClientRect().width;
  const maxPan = (renderedWidth - wrapperWidth) / 2;
  if (maxPan <= 1) return null; // 이미 화면 안에 다 들어와 있어 팬 할 여지가 없음

  return { img, maxPan };
}

function handleViewerKeydown(e) {
  const viewerModal = document.getElementById('media-viewer-modal');
  if (!viewerModal || viewerModal.style.display !== 'flex') return;

  if (e.target && (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA' || e.target.tagName === 'SELECT' || e.target.isContentEditable)) {
    return;
  }

  // 커스텀 매핑 키 (기본값 + localStorage 커스텀 지정키)
  const customNextKeys = (localStorage.getItem('custom_key_next') || 'ArrowRight,Space,PageDown,VolumeDown,ChannelDown,AudioVolumeDown').split(',').map(k => k.trim().toLowerCase());
  const customPrevKeys = (localStorage.getItem('custom_key_prev') || 'ArrowLeft,PageUp,VolumeUp,ChannelUp,AudioVolumeUp').split(',').map(k => k.trim().toLowerCase());
  const customCloseKeys = (localStorage.getItem('custom_key_close') || 'Escape').split(',').map(k => k.trim().toLowerCase());
  const customDashboardKeys = (localStorage.getItem('custom_key_dashboard') || 'Home').split(',').map(k => k.trim().toLowerCase());

  const rawKey = (e.key || '').toLowerCase();
  const codeKey = (e.code || '').toLowerCase();
  // Explicit bindings win over built-in arrows, F/H and Escape. Keep literal Space.
  if (!e.ctrlKey && !e.altKey && !e.metaKey) {
    for (const [setting, action] of [['next', 'nextPage'], ['prev', 'prevPage'],
      ['close', 'closeMediaViewer'], ['dashboard', 'closeMediaViewer']]) {
      const saved = localStorage.getItem(`custom_key_${setting}`);
      if (saved !== null && saved.split(',').some(key => {
        const normalized = key === ' ' ? 'space' : key.trim().toLowerCase();
        return normalized === rawKey || normalized === codeKey || (normalized === 'space' && rawKey === ' ');
      })) {
        e.preventDefault();
        callDep(action);
        if (setting === 'dashboard') window.showDashboardView?.();
        return;
      }
    }
  }

  // 스페이스바, 화살표, 페이지키, 엔터 등 이중 교차 검증
  const isSpaceKey = rawKey === ' ' || rawKey === 'space' || codeKey === 'space';
  const isArrowRight = rawKey === 'arrowright' || codeKey === 'arrowright';
  const isArrowLeft = rawKey === 'arrowleft' || codeKey === 'arrowleft';
  const isPageDown = rawKey === 'pagedown' || codeKey === 'pagedown';
  const isPageUp = rawKey === 'pageup' || codeKey === 'pageup';
  const isEscapeKey = rawKey === 'escape' || codeKey === 'escape';
  const isEnterKey = rawKey === 'enter' || rawKey === 'return' || codeKey === 'enter';

  // [다음 편 이어서 보기 모달] 노출 중 물리키 및 단축키 핸들링
  const nextModal = document.getElementById('viewer-next-episode-modal');
  if (nextModal && nextModal.style.display !== 'none' && nextModal.style.display !== '') {
    const confirmBtn = document.getElementById('viewer-next-episode-confirm-btn');
    const cancelBtn = document.getElementById('viewer-next-episode-cancel-btn');

    if (isEscapeKey || customCloseKeys.includes(rawKey) || customCloseKeys.includes(codeKey)) {
      e.preventDefault();
      if (cancelBtn) cancelBtn.click();
      return;
    }

    const isNavKeyHit = isEnterKey || isSpaceKey || isArrowRight || isArrowLeft || isPageDown || isPageUp ||
                        customNextKeys.some(k => k === rawKey || k === codeKey || (k === 'space' && isSpaceKey)) ||
                        customPrevKeys.some(k => k === rawKey || k === codeKey || (k === 'space' && isSpaceKey));

    if (isNavKeyHit && confirmBtn) {
      e.preventDefault();
      confirmBtn.click();
      return;
    }
  }

  if (e.key === 'f' || e.key === 'F' || codeKey === 'keyf') {
    e.preventDefault();
    callDep('toggleFullscreenViewer');
    return;
  }

  // 형광펜 모드 토글 (EPUB/TXT 전용). 브라우저가 예약해 쓰는 조합(Ctrl/Alt+H 등)과 겹치지
  // 않도록 아무 보조키 없는 단순 'H'만 쓰고, Ctrl/Alt/Meta가 눌려있으면 무시한다.
  const fmt = (state.currentViewerFormat || '').toLowerCase();
  if ((fmt === 'epub' || fmt === 'txt') && (e.key === 'h' || e.key === 'H' || codeKey === 'keyh')
      && !e.ctrlKey && !e.altKey && !e.metaKey) {
    e.preventDefault();
    window.toggleHighlightMode?.();
    return;
  }

  if (isEscapeKey || customCloseKeys.includes(rawKey) || customCloseKeys.includes(codeKey)) {
    const inFullscreen = !!(
      viewerModal.classList.contains('fullscreen-mode') ||
      (typeof _deps.isViewerInFullscreen === 'function' && _deps.isViewerInFullscreen())
    );
    e.preventDefault();
    if (inFullscreen) {
      callDep('toggleFullscreenViewer');
    } else {
      callDep('closeMediaViewer');
    }
    return;
  }

  if (customDashboardKeys.includes(rawKey) || customDashboardKeys.includes(codeKey) || (e.altKey && (rawKey === 'home' || codeKey === 'home'))) {
    e.preventDefault();
    callDep('closeMediaViewer');
    if (typeof window.showDashboardView === 'function') window.showDashboardView();
    return;
  }

  // Shift + Space/좌우 방향키: 2쪽보기 정렬을 한 장 밀어서 보정 (예: (9,10)(11,12) → (10,11)).
  // 일반 다음/이전 넘김(같은 키, Shift 없음)보다 먼저 가로채야 한다.
  if (e.shiftKey && (isSpaceKey || isArrowRight || isArrowLeft)) {
    e.preventDefault();
    callDep('shiftSpreadByOne');
    return;
  }

  const isRtl = isViewerRtlFlowActive();

  // 화살표 키는 아래 3번에서 읽는 방향(RTL/LTR)에 따라 별도로 분기 처리하므로,
  // 커스텀 Next/Prev 키 기본값에 포함된 ArrowRight/ArrowLeft는 여기서 매칭 대상에서 제외한다.
  // (제외하지 않으면 이 매칭이 먼저 걸려 아래 RTL 분기가 항상 무시됨)
  const isDirectionalArrowKey = (k) => k === 'arrowright' || k === 'arrowleft';

  // 안드로이드 태블릿/e-ink 리더 기종마다 볼륨·채널 키를 반대 방향으로 매핑해서 보내는 경우가 있어
  // (제조사 표준이 없음), "내 설정"에서 켤 수 있는 반전 토글로 여기서만 별도 보정한다.
  // (일반 커스텀 Next/Prev 목록 매칭에서는 제외하고 아래에서 방향을 직접 계산)
  const VOLUME_DOWN_KEYS = ['volumedown', 'channeldown', 'audiovolumedown'];
  const VOLUME_UP_KEYS = ['volumeup', 'channelup', 'audiovolumeup'];
  const isHwVolumeKey = (k) => VOLUME_DOWN_KEYS.includes(k) || VOLUME_UP_KEYS.includes(k);
  const isVolumeDownKey = VOLUME_DOWN_KEYS.includes(rawKey) || VOLUME_DOWN_KEYS.includes(codeKey);
  const isVolumeUpKey = VOLUME_UP_KEYS.includes(rawKey) || VOLUME_UP_KEYS.includes(codeKey);
  const reverseHwNavKeys = localStorage.getItem('viewer_reverse_hw_nav_keys') === '1';

  // 1. 스페이스바, PageDown, 커스텀 Next 키는 읽는 방향에 상관없이 무조건 '다음 스토리 내용(nextPage)'
  const isForwardAction = isSpaceKey || isPageDown ||
                          customNextKeys.some(k => !isDirectionalArrowKey(k) && !isHwVolumeKey(k) && (k === rawKey || k === codeKey || (k === 'space' && isSpaceKey))) ||
                          (reverseHwNavKeys ? isVolumeUpKey : isVolumeDownKey);

  // 2. PageUp, 커스텀 Prev 키는 읽는 방향에 상관없이 무조건 '이전 스토리 내용(prevPage)'
  const isBackwardAction = isPageUp ||
                           customPrevKeys.some(k => !isDirectionalArrowKey(k) && !isHwVolumeKey(k) && (k === rawKey || k === codeKey || (k === 'space' && isSpaceKey))) ||
                           (reverseHwNavKeys ? isVolumeDownKey : isVolumeUpKey);

  if (isForwardAction) {
    e.preventDefault();
    callDep('nextPage');
    return;
  }

  if (isBackwardAction) {
    e.preventDefault();
    callDep('prevPage');
    return;
  }

  // 3. 화살표 키 (LTR / RTL 시각적 책장 방향 분기)
  if (isArrowRight) {
    e.preventDefault();
    if (isRtl) {
      callDep('prevPage'); // RTL(일본만화): 오른쪽 화살표는 이전 내용
    } else {
      callDep('nextPage'); // LTR(일반도서): 오른쪽 화살표는 다음 내용
    }
    return;
  }

  if (isArrowLeft) {
    e.preventDefault();
    if (isRtl) {
      callDep('nextPage'); // RTL(일본만화): 왼쪽 화살표는 다음 내용
    } else {
      callDep('prevPage'); // LTR(일반도서): 왼쪽 화살표는 이전 내용
    }
    return;
  }
}

export function initKeyboardListener() {
  if (keyboardListenerInitialized) return;
  keyboardListenerInitialized = true;

  document.addEventListener('keydown', handleViewerKeydown);

  // Attach keydown listener bridge to iframe document (for EPUB etc)
  document.addEventListener('click', () => {
    const iframe = document.querySelector('#epub-render-area iframe');
    if (iframe && iframe.contentDocument && !iframe.contentDocument.__keyboardBridgeInited) {
      iframe.contentDocument.__keyboardBridgeInited = true;
      iframe.contentDocument.addEventListener('keydown', handleViewerKeydown);
    }
  }, true);

  initWheelListener();
  initViewerClickToggle();
  syncHotspotPointerEvents();
}

export function initWheelListener() {
  const hotspot = document.getElementById('common-viewer-hotspot');
  const viewerBody = document.getElementById('viewer-body-container');
  if (!hotspot || !viewerBody) return;

  hotspot.addEventListener(
    'contextmenu',
    (e) => {
      const viewerModal = document.getElementById('media-viewer-modal');
      if (!viewerModal || viewerModal.style.display !== 'flex') return;

      const fmt = (state.currentViewerFormat || '').toLowerCase();
      const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
      if (fmt === 'epub' && scrollMode === 'page') {
        if (e.cancelable) e.preventDefault();
        e.stopPropagation();
      }
    },
    true
  );

  if (!viewerBody.dataset.viewerWheelBound) {
    viewerBody.dataset.viewerWheelBound = '1';
    viewerBody.addEventListener(
      'wheel',
      (e) => {
      const viewerModal = document.getElementById('media-viewer-modal');
      if (!viewerModal || viewerModal.style.display !== 'flex') return;

      const isComic = document.getElementById('comic-viewer-container').style.display !== 'none';
      const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
      const isComicScroll = isComic && scrollMode === 'scroll';
      const comicImageWrapper = document.querySelector('.comic-image-wrapper');
      const isComicWidth = isComic && comicImageWrapper && comicImageWrapper.classList.contains('fit-width');
      const isTxt = document.getElementById('txt-viewer-container').style.display !== 'none';
      const isPdf = document.getElementById('pdf-viewer-container').style.display !== 'none';

      // 1. 연속 스크롤/폭맞춤은 브라우저의 네이티브 휠 관성에 맡긴다. 여기서
      // scrollBy(auto)로 다시 실행하면 OS/브라우저의 부드러운 스크롤 곡선이 사라져
      // 한 칸씩 끊기는 느낌이 생긴다.
      if (isComicScroll || isComicWidth || (isTxt && scrollMode === 'scroll')) {
        return;
      }

      // 3. Page-turn mode routes wheel events to prev/next actions.
      if (scrollMode === 'page' || (isComic && !isComicWidth)) {
        if (e.cancelable) e.preventDefault();
        if (wheelLock) return;
        const rawDirection = Math.sign(e.deltaY);
        if (!rawDirection) return;
        const now = performance.now();
        if (rawDirection !== Math.sign(wheelDeltaAccumulator) || now - wheelLastTurnAt > 180) {
          wheelDeltaAccumulator = 0;
        }
        wheelDeltaAccumulator += e.deltaY;
        // 일반 휠(delta가 큼)은 첫 이벤트에서 즉시 반응하고, 트랙패드의 작은
        // delta만 짧게 누적한다. 기존 36px 문턱은 저속 휠에서 체감 지연을 만들었다.
        const threshold = e.deltaMode === WheelEvent.DOM_DELTA_PIXEL ? 14 : 1;
        const direction = wheelDeltaAccumulator >= threshold ? 1 : (wheelDeltaAccumulator <= -threshold ? -1 : 0);
        if (!direction) return;
        wheelDeltaAccumulator = 0;
        wheelRepeatCount = direction === wheelLastDirection && now - wheelLastTurnAt < 900
          ? Math.min(5, wheelRepeatCount + 1)
          : 0;
        wheelLastDirection = direction;
        wheelLastTurnAt = now;
        const cooldown = Math.max(145, 220 - wheelRepeatCount * 15);

        if (direction > 0) {
          wheelLock = true;
          callDep('nextPage');
          setTimeout(() => {
            wheelLock = false;
          }, cooldown);
        } else {
          wheelLock = true;
          callDep('prevPage');
          setTimeout(() => {
            wheelLock = false;
          }, cooldown);
        }
      }
      },
      { passive: false, capture: true }
    );
  }
}

export function syncHotspotPointerEvents() {
  const hotspot = document.getElementById('common-viewer-hotspot');
  const viewerModal = document.getElementById('media-viewer-modal');
  if (!hotspot || !viewerModal) {
    console.warn('[syncHotspotPointerEvents] hotspot 또는 viewerModal이 존재하지 않습니다.');
    return;
  }

  if (viewerModal.style.display !== 'flex') {
    console.log('[syncHotspotPointerEvents] 뷰어 모달이 flex 상태가 아님. 생략.');
    return;
  }

  // 형광펜 모드(annotation_ui.js)가 이전 세션(TXT/EPUB)에서 페이지 넘김 핫스팟을
  // 일시적으로 pointer-events:none으로 풀어둔 채 남아있을 수 있으므로, 어떤 포맷이든
  // 뷰어가 새로 열릴 때마다 항상 기본값(auto)으로 되돌린다.
  hotspot.style.pointerEvents = 'auto';

  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
  const fmt = (state.currentViewerFormat || '').toLowerCase();
  const isComic = fmt === 'zip' || fmt === 'cbz';
  const isTxt = fmt === 'txt';
  const isEpub = fmt === 'epub';
  const isPdf = fmt === 'pdf';

  const isScrollActive = scrollMode === 'scroll' && (isComic || isTxt || isEpub || isPdf);

  console.log(
    `[syncHotspotPointerEvents] format=${fmt}, scrollMode=${scrollMode}, isScrollActive=${isScrollActive}, isEpub=${isEpub}`
  );

  if (isEpub) {
    viewerModal.classList.remove('scroll-mode-active');
    document.body.style.overflow = 'hidden';
  } else {
    viewerModal.classList.toggle('scroll-mode-active', isScrollActive);
    document.body.style.overflow = isScrollActive ? 'auto' : 'hidden';
  }

  const shouldHideHotspot = (isEpub && scrollMode === 'scroll') || isScrollActive;
  if (shouldHideHotspot) {
    hotspot.style.display = 'none';
    console.log('[syncHotspotPointerEvents] 핫스팟 비활성화(none) 적용됨.');
  } else {
    hotspot.style.display = 'flex';
    // EPUB/TXT 본문은 드래그 선택과 컨텍스트 메뉴가 콘텐츠에 직접 닿아야 한다.
    // 페이지 이동은 아래 viewerBody 좌표 클릭 처리로 대신한다.
    const isSelectableText = ['epub', 'txt'].includes(String(state.currentViewerFormat || '').toLowerCase());
    hotspot.style.pointerEvents = isSelectableText ? 'none' : 'auto';
    console.log('[syncHotspotPointerEvents] 핫스팟 활성화(flex) 적용됨.');
  }
}

export function initViewerClickToggle() {
  const viewerBody = document.getElementById('viewer-body-container');
  if (!viewerBody || viewerClickToggleInited) return;
  viewerClickToggleInited = true;

  const OVERLAY_INTERACTIVE_SELECTOR = 'button, input, select, textarea, label, a, [role="button"], [data-overlay-keep-open]';

  function handleOverlayBlankTap(target) {
    if (!target || typeof target.closest !== 'function') return false;
    const overlayMenu = document.getElementById('comic-overlay-menu');
    if (!overlayMenu || overlayMenu.style.display !== 'flex') return false;

    const inOverlayMenu = target.closest('#comic-overlay-menu');
    if (!inOverlayMenu) return false;

    const isInteractive = !!target.closest(OVERLAY_INTERACTIVE_SELECTOR);
    if (!isInteractive) {
      callDep('toggleComicOverlay', { source: 'overlay-blank-tap' });
      // 설정 바깥의 본문을 누르는 동작은 설정 시트와 상·하단 도구 모음을 함께 닫는다.
      callDep('toggleViewerChrome');
    }

    // 오버레이 내부 터치는 여기서 모두 소비해 하단 핫스팟 토글과 중복되지 않게 한다.
    return true;
  }

  const TAP_THRESHOLD = 18;
  const SWIPE_MIN_DISTANCE = 18;
  const SWIPE_MAX_TIME = 900;
  const EDGE_ZONE_RATIO = 0.35;
  const LONG_PRESS_MS = 280;
  const LONG_PRESS_JITTER = 10; // 이 문턱값을 넘게 움직이면 롱프레스 팬이 아니라 그냥 스와이프로 간주

  let touchStartX = null;
  let touchStartY = null;
  let touchStartTime = 0;
  let isMultiTouch = false;
  let touchStartedInSelectableText = false;
  let touchStartedOnControl = false;
  let lastTouchEndTime = 0;
  let mouseStartX = null;
  let mouseStartY = null;
  let mouseMoved = false;
  let mouseStartedOnSelectableText = false;

  // 높이맞춤 + 1장 보기에서 좌우로 가려진 부분을 롱프레스+드래그로 살짝씩 이동해서 보는 팬 상태
  let longPressTimer = null;
  let isPanning = false;
  let panImg = null;
  let panMaxOffset = 0;
  let panStartClientX = 0;
  let panStartOffset = 0;
  let panMovedDuringGesture = false;

  function cancelLongPressPan() {
    if (longPressTimer) {
      clearTimeout(longPressTimer);
      longPressTimer = null;
    }
    isPanning = false;
    panImg = null;
  }

  document.addEventListener(
    'touchstart',
    (e) => {
      if (e.touches.length === 1) {
        touchStartX = e.touches[0].clientX;
        touchStartY = e.touches[0].clientY;
        touchStartTime = Date.now();
        isMultiTouch = false;
        panMovedDuringGesture = false;
        touchStartedInSelectableText = ['epub', 'txt'].includes(String(state.currentViewerFormat || '').toLowerCase())
          && !!e.target?.closest?.('.txt-chunk[data-idx], .txt-scroll-chunk[data-idx]');

        cancelLongPressPan();

        // 슬라이더/버튼/오버레이 컨트롤 위에서의 롱프레스는 팬으로 가로채지 않는다
        // (예: 하단 페이지 슬라이더를 느리게 드래그하는 도중 280ms가 지나가는 경우).
        const touchTarget = e.target;
        const onControl = touchTarget && typeof touchTarget.closest === 'function' && (
          touchTarget.closest('button') ||
          touchTarget.closest('input') ||
          touchTarget.closest('select') ||
          touchTarget.closest('.viewer-controls') ||
          touchTarget.closest('.floating-close-btn') ||
          touchTarget.closest('#comic-fit-controls') ||
          touchTarget.closest('#comic-overlay-menu') ||
          touchTarget.closest('#epub-toc-container') ||
          touchTarget.closest('.viewer-side-panel')
        );
        touchStartedOnControl = !!onControl;

        if (!onControl) {
          const startX = touchStartX;
          longPressTimer = setTimeout(() => {
            longPressTimer = null;
            const pannable = getPannableComicImage();
            if (!pannable) return;
            isPanning = true;
            panImg = pannable.img;
            panMaxOffset = pannable.maxPan;
            panStartClientX = startX;
            const existing = parseFloat(panImg.style.getPropertyValue('--comic-pan-x'));
            panStartOffset = Number.isFinite(existing) ? existing : 0;
          }, LONG_PRESS_MS);
        }
      } else {
        isMultiTouch = true;
        touchStartedInSelectableText = false;
        touchStartedOnControl = false;
        touchStartX = null;
        touchStartY = null;
        cancelLongPressPan();
      }
    },
    { passive: true }
  );

  // 팬이 실제로 시작된 뒤의 좌우 이동 처리 - preventDefault로 페이지 넘김/브라우저 스크롤을
  // 막아야 해서 별도의 non-passive 리스너로 분리한다(기존 touchmove 리스너는 passive 유지).
  document.addEventListener(
    'touchmove',
    (e) => {
      if (!isPanning || !panImg || e.touches.length !== 1) return;
      panMovedDuringGesture = true;
      const deltaX = e.touches[0].clientX - panStartClientX;
      let next = panStartOffset + deltaX;
      if (next > panMaxOffset) next = panMaxOffset;
      if (next < -panMaxOffset) next = -panMaxOffset;
      panImg.style.setProperty('--comic-pan-x', `${next}px`);
      e.preventDefault();
    },
    { passive: false }
  );

  document.addEventListener(
    'touchmove',
    (e) => {
      if (e.touches.length > 1) {
        isMultiTouch = true;
        cancelLongPressPan();
        return;
      }

      // 롱프레스 타이머가 아직 대기 중인데 손가락이 문턱값 이상 움직이면 일반 스와이프로 간주하고
      // 팬 진입을 취소한다(롱프레스로 "가만히 누르고" 있어야 팬 모드로 들어간다는 설계 의도).
      if (longPressTimer && touchStartX !== null && touchStartY !== null) {
        const dx = Math.abs(e.touches[0].clientX - touchStartX);
        const dy = Math.abs(e.touches[0].clientY - touchStartY);
        if (dx > LONG_PRESS_JITTER || dy > LONG_PRESS_JITTER) {
          clearTimeout(longPressTimer);
          longPressTimer = null;
        }
      }
    },
    { passive: true }
  );

  document.addEventListener(
    'touchend',
    (e) => {
      if (longPressTimer) {
        clearTimeout(longPressTimer);
        longPressTimer = null;
      }

      if (isPanning) {
        isPanning = false;
        panImg = null;
        const hadMoved = panMovedDuringGesture;
        panMovedDuringGesture = false;
        if (hadMoved) {
          // 실제로 팬 이동이 있었다면 아래의 스와이프(페이지 넘김)/탭(오버레이 토글) 로직으로
          // 이어지지 않게 여기서 끝낸다.
          touchStartX = null;
          touchStartY = null;
          lastTouchEndTime = Date.now();
          return;
        }
        // 팬 모드로 들어갔지만 실제로는 움직이지 않은 롱프레스는 그냥 탭으로 취급해
        // 아래 일반 로직(중앙 탭 시 오버레이 토글 등)으로 흘러가게 둔다.
      }

      if (touchStartX === null || isMultiTouch) return;
      if (!e.changedTouches || e.changedTouches.length === 0) return;

      const endX = e.changedTouches[0].clientX;
      const endY = e.changedTouches[0].clientY;
      const duration = Date.now() - touchStartTime;

      const diffX = touchStartX - endX; // 양수: Swipe Left(👈), 음수: Swipe Right(👉)
      const diffY = touchStartY - endY;

      const startX = touchStartX;
      const startY = touchStartY;
      const startedInSelectableText = touchStartedInSelectableText;
      const startedOnControl = touchStartedOnControl;

      touchStartX = null;
      touchStartY = null;
      touchStartedInSelectableText = false;
      touchStartedOnControl = false;

      const target = e.target || document.elementFromPoint(endX, window.innerHeight / 2);
      if (!target) return;

      const absX = Math.abs(diffX);
      const absY = Math.abs(diffY);

      // EPUB/TXT의 텍스트에서 시작한 가로·세로 드래그는 페이지 제스처가
      // 아니라 네이티브 텍스트 선택이다. 선택 중 손가락을 옆으로 길게 밀어도
      // 페이지가 함께 넘어가면 선택 범위가 끊기고, 손을 뗀 순간 엉뚱한 페이지로
      // 이동한다. 텍스트 제스처는 방향과 속도와 관계없이 페이지 넘김보다 우선한다.
      if (startedInSelectableText && Math.max(absX, absY) >= TAP_THRESHOLD) {
        lastTouchEndTime = Date.now();
        return;
      }

      // 메뉴, 패널, 시크바에서 시작한 드래그는 손가락이 바깥에서 끝나더라도
      // 뷰어 페이지 제스처로 다시 해석하지 않는다.
      if (startedOnControl) {
        lastTouchEndTime = Date.now();
        return;
      }

      if (absX < TAP_THRESHOLD && absY < TAP_THRESHOLD && handleOverlayBlankTap(target)) {
        lastTouchEndTime = Date.now();
        return;
      }

      if (
        target.closest('#epub-toc-container') ||
        target.closest('#epub-toc-btn') ||
        target.closest('.viewer-side-panel') ||
        target.closest('.viewer-controls') ||
        target.closest('.floating-close-btn') ||
        target.closest('button') ||
        target.closest('input') ||
        target.closest('select')
      ) {
        return;
      }

      const viewerModal = document.getElementById('media-viewer-modal');
      if (!viewerModal || viewerModal.style.display !== 'flex') return;

      const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
      const tapConfig = getTapDirection();
      const tapDirection = tapConfig.vertical ? 'vertical' : 'horizontal';

      // 모바일 네이티브 텍스트 선택은 롱프레스 후 드래그로 확정된다. 긴 텍스트
      // 제스처를 먼저 선택기에 넘겨야 touchend가 페이지 스와이프로 소비하지 않는다.
      if (startedInSelectableText && duration >= 350) return;

      // 모바일은 휠 가속도와 무관하게 한 제스처당 정확히 한 번만 이동한다.
      // 텍스트가 아닌 본문 영역에서 시작한 짧고 명확한 스와이프만 페이지 이동으로 해석한다.
      if (scrollMode === 'page' && tapDirection === 'horizontal'
          && absX >= SWIPE_MIN_DISTANCE && absX >= absY * 1.05 && duration <= SWIPE_MAX_TIME) {
        const isRtl = isViewerRtlFlowActive();

        if (e.cancelable) e.preventDefault();
        lastTouchEndTime = Date.now();
        window.__viewerSuppressClickUntil = Date.now() + 700;

        if (diffX > 0) {
          // 👈 Swipe Left (오른쪽에서 왼쪽으로 쓸어넘김)
          console.log(`[Viewer-Touch-Swipe] Swipe Left detected (diffX=${diffX}, isRtl=${isRtl})`);
          if (isRtl) {
            callDep('movePageByOne', 'prev');
          } else {
            callDep('movePageByOne', 'next');
          }
        } else {
          // 👉 Swipe Right (왼쪽에서 오른쪽으로 쓸어넘김)
          console.log(`[Viewer-Touch-Swipe] Swipe Right detected (diffX=${diffX}, isRtl=${isRtl})`);
          if (isRtl) {
            callDep('movePageByOne', 'next');
          } else {
            callDep('movePageByOne', 'prev');
          }
        }
        return;
      }

      // 📱 1-1) 스와이프 제스처 처리 (페이지 모드일 때 수직 스와이프, RTL 무관 상:다음 / 하:이전)
      // 다른 앱(틱톡/릴스/웹툰 세로보기)과 동일하게 "콘텐츠를 끌어올리는" 자연스러운 스크롤 방향을 따름.
      if (scrollMode === 'page' && tapDirection === 'vertical'
          && absY >= SWIPE_MIN_DISTANCE && absY > absX * 1.05 && duration <= SWIPE_MAX_TIME) {
        if (e.cancelable) e.preventDefault();
        lastTouchEndTime = Date.now();
        window.__viewerSuppressClickUntil = Date.now() + 700;

        if (diffY > 0) {
          // 👆 Swipe Up (아래에서 위로 쓸어올림) → 다음 페이지
          console.log(`[Viewer-Touch-Swipe] Swipe Up detected (diffY=${diffY})`);
          callDep('movePageByOne', tapConfig.reverse ? 'prev' : 'next');
        } else {
          // 👇 Swipe Down (위에서 아래로 쓸어내림) → 이전 페이지
          console.log(`[Viewer-Touch-Swipe] Swipe Down detected (diffY=${diffY})`);
          callDep('movePageByOne', tapConfig.reverse ? 'next' : 'prev');
        }
        return;
      }

      // 선택하지 않은 축의 스와이프는 페이지 이동이나 중앙 탭으로 재해석하지 않는다.
      if (scrollMode === 'page' && duration <= SWIPE_MAX_TIME
          && Math.max(absX, absY) >= SWIPE_MIN_DISTANCE) {
        if (e.cancelable) e.preventDefault();
        lastTouchEndTime = Date.now();
        window.__viewerSuppressClickUntil = Date.now() + 700;
        return;
      }

      // 📱 2) 짧은 탭: 설정한 좌우/상하 끝 영역은 페이지 이동, 중앙은 도구 모음 토글.
      // 핫스팟 DOM과 텍스트 선택 가능 여부에 의존하지 않고 같은 좌표 규칙을 쓴다.
      if (absX < TAP_THRESHOLD && absY < TAP_THRESHOLD && duration <= 380) {
        const width = window.innerWidth;
        const height = window.innerHeight;
        const direction = tapConfig.vertical ? 'vertical' : 'horizontal';
        const isRtl = isViewerRtlFlowActive();
        let action = null;
        if (direction === 'vertical') {
          if (endY <= height * EDGE_ZONE_RATIO) action = tapConfig.reverse ? 'nextPage' : 'prevPage';
          else if (endY >= height * (1 - EDGE_ZONE_RATIO)) action = tapConfig.reverse ? 'prevPage' : 'nextPage';
        } else {
          if (endX <= width * EDGE_ZONE_RATIO) action = isRtl ? 'nextPage' : 'prevPage';
          else if (endX >= width * (1 - EDGE_ZONE_RATIO)) action = isRtl ? 'prevPage' : 'nextPage';
        }
        if (e.cancelable) e.preventDefault();
        lastTouchEndTime = Date.now();
        if (action) callDep('movePageByOne', action === 'prevPage' ? 'prev' : 'next');
        else callDep('toggleViewerChrome');
        return;
      }

      // 길게 누르거나 천천히 움직인 텍스트 제스처만 네이티브 선택에 맡긴다.
      if (startedInSelectableText) return;
    },
    { passive: false }
  );

  viewerBody.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (e.target.closest?.('input, textarea, select, button, a, [contenteditable="true"], .viewer-side-panel')) return;
    mouseStartX = e.clientX;
    mouseStartY = e.clientY;
    mouseMoved = false;
    const format = String(state.currentViewerFormat || '').toLowerCase();
    mouseStartedOnSelectableText = (format === 'epub' || format === 'txt')
      && isPointOnSelectableText(e.clientX, e.clientY);
    if ((format === 'epub' || format === 'txt') && !mouseStartedOnSelectableText) {
      window.getSelection?.()?.removeAllRanges?.();
      e.preventDefault();
    }
  });
  viewerBody.addEventListener('mousemove', (e) => {
    if (!(e.buttons & 1)) {
      mouseStartX = null;
      mouseMoved = false;
      return;
    }
    if (mouseStartX === null) return;
    if (Math.hypot(e.clientX - mouseStartX, e.clientY - mouseStartY) > 8) {
      mouseMoved = true;
      // 공통 핫스팟의 document-capture 클릭 디스패처도 같은 드래그를 클릭으로
      // 처리하지 않도록 짧은 전역 억제 시간을 공유한다.
      window.__viewerMouseDraggedUntil = Date.now() + 350;
    }
  });
  window.addEventListener('mouseup', () => {
    window.setTimeout(() => {
      mouseStartX = null;
      mouseStartY = null;
      mouseMoved = false;
      mouseStartedOnSelectableText = false;
    }, 0);
  });

  viewerBody.addEventListener('click', (e) => {
    if (e.sourceCapabilities && e.sourceCapabilities.firesTouchEvents) return;
    if (e.pointerType === 'touch') return;
    if (Date.now() - lastTouchEndTime < 500) return;

    if (handleOverlayBlankTap(e.target)) {
      return;
    }

    console.log('[Viewer-Click-Toggle] Mouse click detected. Target:', e.target);

    if (
      e.target.closest('#epub-toc-container') ||
      e.target.closest('#epub-toc-btn') ||
      e.target.closest('.viewer-controls') ||
      e.target.closest('.floating-close-btn') ||
      e.target.closest('#common-viewer-hotspot') ||
      e.target.closest('button') ||
      e.target.closest('input') ||
      e.target.closest('select')
    ) {
      return;
    }

    const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';
    const format = String(state.currentViewerFormat || '').toLowerCase();
    const isSelectableText = format === 'epub' || format === 'txt';
    if (scrollMode === 'page' && isSelectableText) {
      if (mouseMoved || mouseStartedOnSelectableText || isPointOnSelectableText(e.clientX, e.clientY)) return;
      const tapConfig = getTapDirection();
      const direction = tapConfig.vertical ? 'vertical' : 'horizontal';
      if (direction === 'vertical') {
        const ratio = e.clientY / Math.max(1, window.innerHeight);
        if (ratio < EDGE_ZONE_RATIO) callDep(tapConfig.reverse ? 'nextPage' : 'prevPage');
        else if (ratio > 1 - EDGE_ZONE_RATIO) callDep(tapConfig.reverse ? 'prevPage' : 'nextPage');
        else callDep('toggleViewerChrome');
      } else {
        const ratio = e.clientX / Math.max(1, window.innerWidth);
        const isRtl = isViewerRtlFlowActive();
        if (ratio < EDGE_ZONE_RATIO) callDep(isRtl ? 'nextPage' : 'prevPage');
        else if (ratio > 1 - EDGE_ZONE_RATIO) callDep(isRtl ? 'prevPage' : 'nextPage');
        else callDep('toggleViewerChrome');
      }
      return;
    }
    if (scrollMode === 'scroll') {
      const clickX = e.clientX;
      const width = window.innerWidth;
      if (clickX >= width * 0.3 && clickX <= width * 0.7) {
        console.log('[Viewer-Click-Toggle] Triggering toggleComicOverlay() from mouse click');
        callDep('toggleViewerChrome');
      }
    }
  });
}
