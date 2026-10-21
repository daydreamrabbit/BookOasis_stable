import { getTxtPageScrollLeft, setTxtPageScrollLeft, isTxtRtlPageFlow } from './txt_page_utils.js?rev=20260922-reader-session-v45';

// Reflow anchors are deliberately separate from persisted/TTS phrase anchors.
// DOM offsets survive column changes and inline annotation wrappers. Hit testing
// cannot be used here: the reader's navigation hotspots cover the text.
const ANCHOR_CHUNKS = '.txt-chunk, .txt-scroll-chunk, .epub-chunk, .txt-flow-chunk';

function anchorCharRect(node, offset) {
  if (offset < 0 || offset >= node.length) return null;
  const range = document.createRange();
  range.setStart(node, offset);
  range.setEnd(node, offset + 1);
  return Array.from(range.getClientRects()).find(r => r.width > 0 && r.height > 0) || null;
}

export function captureTxtPageAnchor({ scrollWrapper, contentArea, mode = 'page' }) {
  if (!scrollWrapper || !contentArea) return null;
  const view = scrollWrapper.getBoundingClientRect();
  if (!view.width || !view.height) return null;
  const rtl = mode === 'page' && isTxtRtlPageFlow();
  const visible = r => r && r.width > 0 && r.height > 0
    && r.bottom > view.top && r.top < view.bottom && r.right > view.left && r.left < view.right;
  for (const chunk of contentArea.querySelectorAll(ANCHOR_CHUNKS)) {
    const chunkIdx = Number(chunk.dataset.idx);
    if (!Number.isInteger(chunkIdx) || chunkIdx < 0) continue;
    // Flow/scroll chunks expose their fragments. Fixed-height EPUB containers
    // do not, so their overflowing text must still be inspected on later pages.
    if (chunk.matches('.txt-flow-chunk, .txt-scroll-chunk')
        && !Array.from(chunk.getClientRects()).some(visible)) continue;
    const walker = document.createTreeWalker(chunk, NodeFilter.SHOW_TEXT);
    let node, offset = 0;
    while ((node = walker.nextNode())) {
      const range = document.createRange();
      range.selectNodeContents(node);
      if (/\S/.test(node.nodeValue) && Array.from(range.getClientRects()).some(visible)) {
        // Search by column (or line in scrolling mode), not paragraph start.
        let lo = 0, hi = node.length - 1;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          const r = anchorCharRect(node, mid);
          const before = !r || (mode === 'scroll' ? r.bottom <= view.top
            : rtl ? r.left >= view.right : r.right <= view.left);
          if (before) lo = mid + 1;
          else hi = mid;
        }
        // Collapsed spaces have no usable box; never anchor invisible text.
        for (let i = lo; i < node.length; i++) {
          const r = anchorCharRect(node, i);
          if (visible(r) && /\S/.test(node.nodeValue[i])) {
            const charOffset = offset + i;
            return { chunkIdx, charOffset,
              probe: chunk.textContent.slice(charOffset, charOffset + 32),
              textLength: chunk.textContent.length, top: r.top - view.top };
          }
          if (r && (mode === 'scroll' ? r.top >= view.bottom
            : rtl ? r.right <= view.left : r.left >= view.right)) break;
        }
      }
      offset += node.length;
    }
  }
  return null;
}

// Returns a logical scroll position, including for negative-scrollLeft 2|1.
export function locateTxtPageAnchor({ scrollWrapper, contentArea, anchor, advanceWidth, mode = 'page' }) {
  if (!anchor || !scrollWrapper || !contentArea || !Number.isInteger(anchor.chunkIdx)
      || !Number.isInteger(anchor.charOffset) || anchor.charOffset < 0) return null;
  const chunk = contentArea.querySelector(ANCHOR_CHUNKS.split(', ')
    .map(selector => `${selector}[data-idx="${anchor.chunkIdx}"]`).join(', '));
  if (!chunk || chunk.textContent.length !== anchor.textLength
      || chunk.textContent.slice(anchor.charOffset, anchor.charOffset + 32) !== anchor.probe) return null;
  const view = scrollWrapper.getBoundingClientRect();
  if (!view.width || !view.height) return null;
  const walker = document.createTreeWalker(chunk, NodeFilter.SHOW_TEXT);
  let node, offset = anchor.charOffset;
  while ((node = walker.nextNode())) {
    if (offset >= node.length) { offset -= node.length; continue; }
    const rect = anchorCharRect(node, offset);
    if (!rect) return null;
    if (mode === 'scroll') return Math.max(0, Math.min(scrollWrapper.scrollHeight - scrollWrapper.clientHeight,
      scrollWrapper.scrollTop + rect.top - view.top - (anchor.top || 0)));
    if (!(advanceWidth > 0)) return null;
    const distance = isTxtRtlPageFlow() ? view.right - rect.right : rect.left - view.left;
    const page = Math.max(0, Math.floor((getTxtPageScrollLeft(scrollWrapper) + distance + 0.5) / advanceWidth));
    return Math.min(Math.max(0, scrollWrapper.scrollWidth - scrollWrapper.clientWidth), page * advanceWidth);
  }
  return null;
}

/**
 * startIndex 주변에서 실제 내용(비공백 5자 이상)이 포함된 30자 앵커 텍스트를 탐색.
 * 앞에서 실패하면 뒤(startIndex+1 방향)로 최대 100자까지 탐색 후 반환.
 * @param {string} text - 정제된 전체 텍스트
 * @param {number} startIndex - 탐색 시작 인덱스
 * @param {number} length - 앵커 길이 (기본 30)
 * @returns {string|null}
 */
function _findMeaningfulAnchor(text, startIndex, length = 30) {
  if (!text || text.length === 0) return null;

  // 앞뒤로 탐색 (최대 ±200자 범위)
  const searchRange = 200;
  const lo = Math.max(0, startIndex - searchRange);
  const hi = Math.min(text.length - length, startIndex + searchRange);

  // 먼저 startIndex 부근 → 앞 방향으로 탐색
  for (let i = startIndex; i <= hi; i++) {
    const slice = text.substring(i, i + length);
    if (slice.replace(/\s/g, '').length >= 5) return slice.trim();
  }
  // 그다음 startIndex 이전 방향으로 탐색
  for (let i = startIndex - 1; i >= lo; i--) {
    const slice = text.substring(i, i + length);
    if (slice.replace(/\s/g, '').length >= 5) return slice.trim();
  }
  return null;
}

export function getTxtAnchorInfoByMode({
  scrollWrapper,
  contentArea,
  forcedMode,
  storage,
  isEpub,
  fullText,
  txtChunks,
  currentChunkIdx,
  stripHtml,
}) {
  if (!scrollWrapper || !contentArea) return null;

  const scrollMode = forcedMode || storage.getItem('viewer_scroll_mode') || 'page';

  if (scrollMode === 'scroll') {
    const rawChunk = (Array.isArray(txtChunks) && txtChunks[currentChunkIdx]) ? txtChunks[currentChunkIdx] : '';
    const cleanText = isEpub ? stripHtml(rawChunk) : (rawChunk || fullText || '').replace(/\s+/g, ' ').trim();
    if (cleanText.length === 0) return null;

    const targetChunk = contentArea.querySelector(`.txt-scroll-chunk[data-idx="${currentChunkIdx}"]`);
    let ratio = 0;
    if (targetChunk && targetChunk.offsetHeight > 0) {
      const chunkRelativeScroll = Math.max(0, scrollWrapper.scrollTop - targetChunk.offsetTop);
      ratio = Math.min(1, chunkRelativeScroll / targetChunk.offsetHeight);
    } else {
      const maxScroll = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
      ratio = maxScroll > 0 ? scrollWrapper.scrollTop / maxScroll : 0;
    }

    const startIndex = Math.floor(cleanText.length * ratio);
    // 공백/특수문자만 있는 구간을 피해 실제 의미있는 텍스트가 나오는 위치를 앞뒤로 탐색
    const anchorText = _findMeaningfulAnchor(cleanText, startIndex, 30);
    if (!anchorText) return null;

    return {
      chunkIdx: currentChunkIdx,
      anchorText,
    };
  }

  const rawChunk = txtChunks[currentChunkIdx] || '';
  const cleanText = isEpub ? stripHtml(rawChunk) : rawChunk.replace(/\s+/g, ' ').trim();
  if (cleanText.length === 0) return null;

  // 1순위: 화면 뷰포트 내 실제 가시 엘리먼트 텍스트 캡처 (iOS Safari scrollLeft 읽기 오류 방어)
  try {
    const rect = scrollWrapper.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const centerY = rect.top + rect.height / 3;
    const elemAtPoint = document.elementFromPoint(centerX, centerY);
    if (elemAtPoint && contentArea.contains(elemAtPoint)) {
      const visibleTxt = (elemAtPoint.textContent || '').replace(/\s+/g, ' ').trim();
      const meaningful = _findMeaningfulAnchor(visibleTxt, 0, 30);
      if (meaningful && meaningful.replace(/\s/g, '').length >= 5) {
        return {
          chunkIdx: currentChunkIdx,
          anchorText: meaningful,
        };
      }
    }
  } catch (e) {}

  const maxScroll = scrollWrapper.scrollWidth - scrollWrapper.clientWidth;
  const ratio = maxScroll > 0 ? getTxtPageScrollLeft(scrollWrapper) / maxScroll : 0;
  const startIndex = Math.floor(cleanText.length * ratio);
  // 공백/특수문자만 있는 구간을 피해 실제 의미있는 텍스트가 나오는 위치를 앞뒤로 탐색
  const anchorText = _findMeaningfulAnchor(cleanText, startIndex, 30);
  if (!anchorText) return null;

  return {
    chunkIdx: currentChunkIdx,
    anchorText,
  };
}

export function restoreTxtAnchorInfoByMode({
  anchorInfo,
  scrollWrapper,
  contentArea,
  storage,
  currentChunkIdx,
  getPageAdvanceWidth,
  isEpub,
  fullText,
  txtChunks,
  stripHtml,
}) {
  if (!anchorInfo || !anchorInfo.anchorText || !scrollWrapper || !contentArea) return false;

  const scrollMode = storage.getItem('viewer_scroll_mode') || 'page';
  const query = anchorInfo.anchorText;
  const targetChunkIdx = anchorInfo.chunkIdx !== undefined ? anchorInfo.chunkIdx : currentChunkIdx;

  let targetArea = contentArea;
  if (scrollMode === 'scroll') {
    const chunkContainer = contentArea.querySelector(`.txt-scroll-chunk[data-idx="${targetChunkIdx}"]`);
    if (chunkContainer) targetArea = chunkContainer;
  } else {
    const chunkContainer = contentArea.querySelector(`.txt-chunk[data-idx="${targetChunkIdx}"]`);
    if (chunkContainer) targetArea = chunkContainer;
  }

  const elements = targetArea.querySelectorAll('p, div, li, blockquote, h1, h2, h3, h4, h5, h6');
  let matchedElem = null;

  for (let el of elements) {
    if (el.children.length === 0 || el.tagName === 'P') {
      const txt = el.textContent.replace(/\s+/g, ' ').trim();
      if (txt.includes(query)) {
        matchedElem = el;
        break;
      }
    }
  }

  if (!matchedElem) {
    for (let el of elements) {
      if (el.textContent.includes(query)) {
        matchedElem = el;
        break;
      }
    }
  }

  if (matchedElem) {
    if (scrollMode === 'scroll') {
      scrollWrapper.scrollTop = Math.max(0, matchedElem.offsetTop - 30);
      return true;
    }

    const colWidth = getPageAdvanceWidth(scrollWrapper);
    const pageIndex = Math.floor(matchedElem.offsetTop / scrollWrapper.clientHeight);
    setTxtPageScrollLeft(scrollWrapper, pageIndex * colWidth);
    return true;
  }

  if (scrollMode === 'scroll') {
    const cleanText = isEpub ? stripHtml(fullText) : fullText.replace(/\s+/g, ' ').trim();

    let charOffset = 0;
    for (let i = 0; i < targetChunkIdx; i++) {
      const chunkText = isEpub ? stripHtml(txtChunks[i]) : txtChunks[i].replace(/\s+/g, ' ').trim();
      charOffset += chunkText.length;
    }

    const matchIndex = cleanText.indexOf(query, charOffset);
    if (matchIndex !== -1) {
      const ratio = matchIndex / cleanText.length;
      const maxScroll = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
      scrollWrapper.scrollTop = maxScroll * ratio;
      return true;
    }
  } else {
    const rawChunk = txtChunks[targetChunkIdx] || '';
    const cleanText = isEpub ? stripHtml(rawChunk) : rawChunk.replace(/\s+/g, ' ').trim();
    const matchIndex = cleanText.indexOf(query);
    if (matchIndex !== -1) {
      const ratio = matchIndex / cleanText.length;
      const colWidth = getPageAdvanceWidth(scrollWrapper);
      const maxScroll = scrollWrapper.scrollWidth - scrollWrapper.clientWidth;
      setTxtPageScrollLeft(scrollWrapper, Math.round((maxScroll * ratio) / colWidth) * colWidth);
      return true;
    }
  }

  return false;
}
