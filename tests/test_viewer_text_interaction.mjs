import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const annotationSource = await readFile(new URL('../static/js/viewer/annotation_ui.js', import.meta.url), 'utf8');
const inputSource = await readFile(new URL('../static/js/viewer/input_controller.js', import.meta.url), 'utf8');
const cssSource = await readFile(new URL('../static/css/tab_media_library_viewer.css', import.meta.url), 'utf8');
const annotationStateSource = await readFile(new URL('../static/js/viewer/annotation_state.js', import.meta.url), 'utf8');
const tocSource = await readFile(new URL('../static/js/viewer/txt_toc.js', import.meta.url), 'utf8');
const panelSource = await readFile(new URL('../static/js/viewer/ridi_panels.js', import.meta.url), 'utf8');
const displayModeSource = await readFile(new URL('../static/js/viewer/display_mode.js', import.meta.url), 'utf8');
const mobileCssSource = await readFile(new URL('../static/css/mobile.css', import.meta.url), 'utf8');
const viewerSource = await readFile(new URL('../static/js/viewer.js', import.meta.url), 'utf8');
const txtViewerSource = await readFile(new URL('../static/js/viewer_txt.js', import.meta.url), 'utf8');
const navigationSource = await readFile(new URL('../static/js/viewer/navigation.js', import.meta.url), 'utf8');
const viewerTemplate = await readFile(new URL('../templates/components/media_viewer.html', import.meta.url), 'utf8');
const comicNavigationSource = await readFile(new URL('../static/js/viewer/navigation.js', import.meta.url), 'utf8');
const comicRendererSource = await readFile(new URL('../static/js/viewer/renderer.js', import.meta.url), 'utf8');
const pdfSource = await readFile(new URL('../static/js/viewer_pdf.js', import.meta.url), 'utf8');
const librarySource = await readFile(new URL('../static/js/tab_media_library.js', import.meta.url), 'utf8');
const detailInteractionsSource = await readFile(new URL('../static/js/detail/interactions.js', import.meta.url), 'utf8');
const bookmarkSource = await readFile(new URL('../static/js/viewer/bookmark_controller.js', import.meta.url), 'utf8');
const seekbarSource = await readFile(new URL('../static/js/viewer/seekbar_controller.js', import.meta.url), 'utf8');
const pageUtilsSource = await readFile(new URL('../static/js/viewer/txt_page_utils.js', import.meta.url), 'utf8');
const txtNavigationSource = await readFile(new URL('../static/js/viewer/txt_navigation.js', import.meta.url), 'utf8');
const epubLoaderSource = await readFile(new URL('../static/js/viewer/epub_loader.js', import.meta.url), 'utf8');

test('wheel navigation is bound to the real viewer body instead of only the transparent hotspot', () => {
  assert.match(inputSource, /viewerBody\.addEventListener\(\s*['"]wheel['"]/);
  assert.doesNotMatch(inputSource, /hotspot\.addEventListener\(\s*['"]wheel['"]/);
});

test('desktop wheel responds quickly and preserves native continuous-scroll momentum', () => {
  assert.match(inputSource, /const threshold = e\.deltaMode === WheelEvent\.DOM_DELTA_PIXEL \? 14 : 1/);
  assert.match(inputSource, /Math\.max\(145, 220 - wheelRepeatCount \* 15\)/);
  assert.match(inputSource, /isComicScroll \|\| isComicWidth \|\| \(isTxt && scrollMode === 'scroll'\)\) \{\s*return;/);
  assert.doesNotMatch(inputSource, /targetScrollEl\.scrollBy/);
  assert.match(pageUtilsSource, /behavior === 'smooth'[\s\S]*scrollWrapper\.scrollTo/);
  assert.match(txtNavigationSource, /setTxtPageScrollLeft\(scrollWrapper, targetScrollLeft\);/);
});

test('text drag never becomes a page swipe and paged text moves immediately', () => {
  assert.match(inputSource, /startedInSelectableText && Math\.max\(absX, absY\) >= TAP_THRESHOLD/);
  assert.match(inputSource, /mouseStartedOnSelectableText = \(format === 'epub' \|\| format === 'txt'\)/);
  assert.match(inputSource, /mouseMoved \|\| mouseStartedOnSelectableText \|\| isPointOnSelectableText/);
  assert.match(txtNavigationSource, /setTxtPageScrollLeft\(scrollWrapper, targetScrollLeft\);/);
  assert.doesNotMatch(txtNavigationSource, /setTxtPageScrollLeft\(scrollWrapper, targetScrollLeft, 'smooth'\)/);
  assert.match(txtNavigationSource, /ctx\.snapTxtPageScrollLeft\(scrollWrapper\);[\s\S]*ctx\.updatePageInfo\?\.\(\);[\s\S]*ctx\.setTxtPageSnapInProgress\(false\);/);
});

test('selected text menu contains five highlight colors, memo and body search without dictionary search', () => {
  const colors = annotationSource.match(/\['#[0-9a-f]{6}',\s*'[^']+'\]/gi) || [];
  assert.equal(colors.length, 5);
  assert.match(annotationSource, />메모 추가</);
  assert.match(annotationSource, />본문 검색</);
  assert.doesNotMatch(annotationSource, /사전 검색/);
});

test('only rendered text chunks are selectable and viewer images are not selectable or draggable', () => {
  assert.match(cssSource, /#media-viewer-modal \.viewer-body[\s\S]*user-select: auto !important/);
  assert.match(cssSource, /#media-viewer-modal #txt-content-area \.txt-chunk[\s\S]*user-select: text !important/);
  assert.match(cssSource, /#media-viewer-modal img[\s\S]*user-select: none !important[\s\S]*-webkit-user-drag: none/);
  assert.match(annotationSource, /isPointOnChunkText/);
});

test('text selection does not depend on opening the viewer chrome', () => {
  assert.match(cssSource, /data-viewer-format="epub"[\s\S]*#common-viewer-hotspot[\s\S]*pointer-events: none !important/);
  assert.match(inputSource, /startedInSelectableText[\s\S]*return/);
  assert.match(inputSource, /isPointOnSelectableText/);
  assert.match(inputSource, /removeAllRanges/);
  assert.doesNotMatch(annotationSource, /addEventListener\('selectstart'/);
  assert.match(annotationSource, /const startedOnText = selectionGestureStartedOnText/);
});

test('mobile swipe and edge taps use one unified non-passive handler', () => {
  assert.doesNotMatch(inputSource, /androidTapBound/);
  assert.match(inputSource, /SWIPE_MIN_DISTANCE = 18/);
  assert.match(inputSource, /EDGE_ZONE_RATIO = 0\.35/);
  assert.match(inputSource, /const tapConfig = getTapDirection\(\)/);
  assert.match(inputSource, /tapDirection === 'horizontal'/);
  assert.match(inputSource, /tapDirection === 'vertical'/);
  assert.match(inputSource, /callDep\('movePageByOne'/);
  assert.match(inputSource, /__viewerSuppressClickUntil/);
  assert.match(inputSource, /\{ passive: false \}/);
});

test('mobile viewer panels stay compact, search input remains interactive and settings close outside', () => {
  assert.match(panelSource, /panel\.addEventListener\('pointerdown'/);
  assert.match(panelSource, /function handleViewerSidePanelOutside/);
  assert.match(panelSource, /document\.addEventListener\('pointerdown', handleViewerSidePanelOutside, true\)/);
  assert.match(panelSource, /input\.focus\(\{ preventScroll: true \}\)/);
  assert.match(viewerSource, /document\.addEventListener\('pointerdown'/);
  assert.match(viewerSource, /target\?\.closest\?\.\('\.ridi-view-settings'\)/);
  assert.match(cssSource, /\.viewer-side-panel[\s\S]*max-height: min\(68dvh, 560px\)/);
  assert.match(cssSource, /bottom: auto !important/);
});

test('detail-card drag preserves selection and suppresses the synthetic open click', () => {
  assert.match(detailInteractionsSource, /suppressDetailClickUntil/);
  assert.match(detailInteractionsSource, /Math\.hypot\(dx, dy\) >= 8/);
  assert.match(detailInteractionsSource, /draggedTarget/);
});

test('explicit tap direction overrides page layout and stale comic pages remain hidden', () => {
  assert.match(inputSource, /function isViewerRtlFlowActive/);
  assert.match(inputSource, /const isRtl = isViewerRtlFlowActive\(\)/);
  assert.match(viewerSource, /getTapZoneDirection\(\)\)\.endsWith\('-reverse'\)/);
  assert.match(viewerSource, /isRtlFlow && \(action === 'prev-page' \|\| action === 'next-page'\)/);
  assert.match(comicRendererSource, /previousPair\.style\.visibility = 'hidden'/);
  assert.match(comicRendererSource, /let comicRenderSeq = 0/);
  assert.match(comicRendererSource, /if \(!isCurrentRender\(\)\) return/);
});

test('viewer sessions reject stale comic and EPUB responses', () => {
  assert.match(comicRendererSource, /let rendererSessionSeq = 0/);
  assert.match(comicRendererSource, /const isCurrentSession = \(\) =>/);
  assert.match(txtViewerSource, /let txtSessionGeneration = 0/);
  assert.match(txtViewerSource, /dataset\.viewerSession/);
  assert.match(epubLoaderSource, /const requestedSession/);
  assert.match(epubLoaderSource, /if \(!isCurrentViewer\(\)\) return null/);
  assert.match(txtViewerSource, /페이지 계산 중…/);
  assert.match(txtViewerSource, /epubPagination = null/);
});

test('TXT paged mode measures physical pages instead of chunk count', () => {
  assert.match(txtViewerSource, /let txtPagination = null/);
  assert.match(txtViewerSource, /createTxtPaginationEngine/);
  assert.match(txtViewerSource, /async function recalculateTxtPagination/);
  assert.match(txtViewerSource, /scheduleTxtPagination\(180\)/);
  assert.match(txtViewerSource, /hasTxtPages/);
  assert.match(txtViewerSource, /const pagination = state\.currentViewerFormat === 'epub' \? epubPagination : txtPagination/);
});

test('desktop blank-area navigation follows the selected horizontal or vertical zones', () => {
  assert.match(inputSource, /isPointOnSelectableText\(e\.clientX, e\.clientY\)/);
  assert.match(inputSource, /direction === 'vertical'[\s\S]*e\.clientY \/ Math\.max\(1, window\.innerHeight\)/);
});

test('each paged viewer exposes one-physical-page mobile movement', () => {
  assert.match(comicNavigationSource, /export function moveComicPageByOne/);
  assert.match(pdfSource, /export function movePdfPageByOne/);
  assert.match(txtViewerSource, /export function moveTxtPageByOne/);
});

test('viewer back restores the retained series detail without requiring the source library id to match', () => {
  const restoreBlock = librarySource.match(/const canRestoreRetainedDetail =[\s\S]*?;\n/)?.[0] || '';
  assert.match(restoreBlock, /retainedDetailMatchesHistory/);
  assert.doesNotMatch(restoreBlock, /detailLibraryId/);
});

test('open reading notes refresh immediately and use each saved highlight color', () => {
  assert.match(annotationStateSource, /viewer-annotations-changed/);
  assert.match(tocSource, /addEventListener\('viewer-annotations-changed', refreshOpenReadingNotes\)/);
  assert.match(tocSource, /addEventListener\('viewer-bookmarks-changed', refreshOpenReadingNotes\)/);
  assert.match(tocSource, /savedColor = String\(item\.color[\s\S]*icon\.style\.color =/);
});

test('right panels leave both viewer toolbars visible and epub images have no blur shadow', () => {
  assert.match(cssSource, /#epub-toc-container \{[\s\S]*top: 64px !important;[\s\S]*bottom: 62px !important;[\s\S]*height: auto !important/);
  assert.match(cssSource, /\.epub-chunk img,[\s\S]*\.epub-full-content img[\s\S]*box-shadow: none !important;[\s\S]*filter: none !important/);
});

test('toc, reading notes and search panels switch exclusively without auto-hiding viewer chrome', () => {
  assert.match(tocSource, /viewer-side-panel-opening/);
  assert.match(tocSource, /source: 'toc-side-panel'/);
  assert.match(panelSource, /viewer-side-panel-opening/);
  assert.match(panelSource, /source: 'search-side-panel'/);
  assert.match(cssSource, /\.viewer-side-panel \{[\s\S]*box-sizing: border-box/);
  assert.match(displayModeSource, /resetViewerChrome\(\)[\s\S]*autoHide: false/);
  assert.doesNotMatch(displayModeSource, /setViewerChromeVisible\(true, \{ autoHide: !chromeLockedOpen \}\)/);
  assert.match(panelSource, /if \(openPanel\)[\s\S]*closePanel\(\)/);
  assert.match(tocSource, /isTocPanelOpen && activeTocTab === tab[\s\S]*_closeEpubTocPanel\(\)/);
  assert.match(viewerSource, /viewer-side-panel-state-changed[\s\S]*classList\.toggle\('is-active', isActive\)/);
  assert.match(displayModeSource, /viewer-chrome-will-hide/);
  assert.match(displayModeSource, /viewer-request-chrome-hide/);
  assert.match(panelSource, /target\?\.closest\?\.\('\.viewer-side-panel, #epub-toc-container, \.ridi-viewer-toolbar-top'\)/);
  assert.match(panelSource, /document\.dispatchEvent\(new CustomEvent\('viewer-request-chrome-hide'\)/);
});

test('mobile viewer removes horizontal safe-area shade and sticky hotspot shading', () => {
  assert.match(mobileCssSource, /padding-left: 0;[\s\S]*padding-right: 0;/);
  assert.match(cssSource, /\.hotspot-zone:hover > i \{ opacity: 0; \}/);
  assert.match(cssSource, /\.comic-hotspot-layer:not\(\.tap-zone-preview\) \.hotspot-zone \{ background: transparent !important; \}/);
});

test('viewer settings close with other panels or chrome and the remaining seek track stays visible', () => {
  assert.match(viewerSource, /viewer-side-panel-opening', closeViewerSettingsOverlay/);
  assert.match(viewerSource, /viewer-chrome-will-hide', closeViewerSettingsOverlay/);
  assert.match(viewerSource, /toggleComicOverlay\(\{ suppressReopen: false \}\)/);
  assert.match(navigationSource, /settingsButton\.classList\.toggle\('is-active', isOpening\)/);
  assert.match(inputSource, /overlay-blank-tap'[\s\S]*toggleViewerChrome/);
  assert.match(cssSource, /seekbar-input \{[\s\S]*height: 28px;[\s\S]*#8f9aa2/);
});

test('TOC requests made while EPUB is loading are queued for the active book', () => {
  assert.match(tocSource, /pendingTocTab = tab/);
  assert.match(tocSource, /Number\(tocPanelBookId\) !== Number\(state\.activeBookId\)/);
  assert.match(tocSource, /queueMicrotask\(\(\) => openEpubTocPanel\(queuedTab\)\)/);
});

test('the common loading overlay remains below the viewer toolbar', () => {
  assert.match(viewerTemplate, /id="viewer-common-overlay"[^>]+z-index: 10003/);
});

test('EPUB does not render a false empty-content message before metadata arrives', () => {
  assert.match(txtViewerSource, /isEpub && txtChunks\.length === 0[\s\S]*epub-ch-loading[\s\S]*return;/);
});

test('text bookmarks store canonical chapter and in-chapter position instead of the displayed global page', () => {
  assert.match(txtViewerSource, /slider\.dataset\.chapterIdx = String\(currentChunkIdx\)/);
  assert.match(txtViewerSource, /slider\.dataset\.chapterPercent = String/);
  assert.match(bookmarkSource, /slider\.dataset\.chapterIdx/);
  assert.match(bookmarkSource, /slider\.dataset\.chapterPercent/);
  assert.match(txtViewerSource, /legacyPageMatch[\s\S]*findLastIndex/);
});

test('toc, notes and search result navigation keep their side panel open', () => {
  assert.doesNotMatch(panelSource, /jumpToTextSearchResult\(match\.chapterIdx\);\s*closePanel\(\)/);
  assert.doesNotMatch(tocSource, /jump-chapter-close-toc/);
  assert.match(tocSource, /annotationId: item\.kind === 'bookmark' \? null : item\.id/);
  assert.match(tocSource, /viewer-pagination-changed/);
  assert.match(txtViewerSource, /options\?\.globalPage != null/);
});

test('scroll progress seekbar navigates live while its thumb is dragged', () => {
  assert.match(seekbarSource, /seekMode === 'scroll-progress'[\s\S]*txtSliderChange/);
  assert.match(txtViewerSource, /wrapper\.scrollTop \/ maxScroll/);
});

test('seekbar click and drag map pointer coordinates without relying on the native range track', () => {
  assert.match(seekbarSource, /function updateSliderFromPointer/);
  assert.match(seekbarSource, /setPointerCapture/);
  assert.match(seekbarSource, /slider\.dispatchEvent\(new Event\('input'/);
  assert.match(seekbarSource, /slider\.dispatchEvent\(new Event\('change'/);
});

test('two-one text spreads use rtl columns with normalized scrolling instead of a width-breaking transform', () => {
  assert.doesNotMatch(cssSource, /data-display-mode="two-one"[^}]*transform:\s*scaleX/);
  assert.match(cssSource, /data-display-mode="two-one"[^}]*#txt-scroll-wrapper[\s\S]*direction:\s*rtl/);
  assert.match(pageUtilsSource, /getTxtPageScrollLeft/);
  assert.match(pageUtilsSource, /isTxtRtlPageFlow\(\)[\s\S]*-scrollWrapper\.scrollLeft/);
});

test('annotation page labels are measured from the rendered range rather than estimated by text ratio', () => {
  assert.match(txtViewerSource, /decodeAnchor\(chunkEl, annotation\)/);
  assert.match(txtViewerSource, /epubAnnotationLocalPages/);
  assert.match(txtViewerSource, /measuredAnnotationPage/);
});

test('mobile viewer gestures never consume interactions inside the search side panel', () => {
  assert.match(inputSource, /touchTarget\.closest\('\.viewer-side-panel'\)/);
  assert.match(inputSource, /target\.closest\('\.viewer-side-panel'\)/);
});

test('desktop hotspot clicks are suppressed after a mouse drag', () => {
  assert.match(inputSource, /__viewerMouseDraggedUntil = Date\.now\(\) \+ 350/);
  assert.match(viewerSource, /__viewerMouseDraggedUntil/);
});

test('mobile controls own the whole gesture and long text gestures remain selections', () => {
  assert.match(inputSource, /touchStartedOnControl = !!onControl/);
  assert.match(inputSource, /if \(startedOnControl\)/);
  assert.match(inputSource, /startedInSelectableText && duration >= 350/);
  assert.match(annotationSource, /isMobileDevice \? 180 : 10/);
});

test('comic readers hide toc and search while exposing bookmark-only reading notes', () => {
  assert.match(navigationSource, /tocButton\.style\.display = capabilities\.toc/);
  assert.match(panelSource, /openImageReadingNotesPanel/);
  assert.match(panelSource, /viewer-note-card--bookmark/);
  assert.match(viewerSource, /isComicFormat \? openImageReadingNotesPanel\(\)/);
});
