const COMIC_FORMATS = new Set(['zip', 'cbz', 'imgdir']);
const TEXT_FORMATS = new Set(['txt', 'epub']);

export function getViewerControlCapabilities(format, scrollMode = 'page') {
  const normalized = String(format || '').toLowerCase();
  const isComic = COMIC_FORMATS.has(normalized);
  const isText = TEXT_FORMATS.has(normalized);
  const isPdf = normalized === 'pdf';

  return {
    toc: isText,
    readingNotes: isText || isComic,
    search: isText,
    bookmark: isText || isComic || isPdf,
    styleTab: isText,
    marginTab: isText,
    comicFit: isComic || isPdf,
    pageStep: (isComic || isText || isPdf) && scrollMode !== 'scroll',
    spreadShift: (isComic || normalized === 'epub') && scrollMode !== 'scroll',
    splitSpread: false,
    centerGap: (isComic || isText || isPdf) && scrollMode !== 'scroll',
    readingDirection: isComic && scrollMode !== 'scroll',
    // EPUB/TXT는 현재 스크롤 보기여도 좌우/상하 선호를 바꿀 수 있게 유지한다.
    // 이미지/PDF 연속 스크롤에서만 페이지 탭 방향을 숨긴다.
    tapZoneDirection: isText || ((isComic || isPdf) && scrollMode !== 'scroll'),
    widthRow: isPdf && scrollMode === 'scroll',
    annotation: isText,
  };
}

export function normalizeViewerOverlayTab(format, tabName) {
  const allowed = new Set(['nav', 'layout', 'style', 'margin']);
  const requested = allowed.has(tabName) ? tabName : 'nav';
  const capabilities = getViewerControlCapabilities(format);
  if (requested === 'style' && !capabilities.styleTab) return 'nav';
  if (requested === 'margin' && !capabilities.marginTab) return 'nav';
  return requested;
}
