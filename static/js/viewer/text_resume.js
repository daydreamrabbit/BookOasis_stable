// A DOM text offset within the canonical chunk is independent of viewport size.
export function readTextResume(session) {
  try {
    const value = JSON.parse(session?.cfi || 'null');
    return value?.type === 'bookoasis-text-v1' && Number.isInteger(value.chunkIdx)
      && value.chunkIdx >= 0 && Number.isInteger(value.offset) && value.offset >= 0 ? value : null;
  } catch { return null; }
}

export function captureTextResume(wrapper, content, chunkIdx) {
  if (!wrapper || !content) return null;
  const viewport = wrapper.getBoundingClientRect();
  const chunks = content.querySelectorAll('.txt-chunk, .txt-scroll-chunk, .epub-chunk');
  // Only inspect chunks intersecting the viewport; do not walk the entire book.
  for (const chunk of chunks) {
    // A fixed-height EPUB column container has a box on its first page only;
    // its overflowing text fragments can still occupy the current later page.
    if (Number(chunk.dataset.idx) !== Number(chunkIdx)
      && ![...chunk.getClientRects()].some(r => r.bottom > viewport.top && r.top < viewport.bottom
      && r.right > viewport.left && r.left < viewport.right)) continue;
    const walker = document.createTreeWalker(chunk, NodeFilter.SHOW_TEXT);
    let node, offset = 0;
    while ((node = walker.nextNode())) {
      const range = document.createRange(); range.selectNodeContents(node);
      for (const rect of range.getClientRects()) {
        if (rect.height < 1 || rect.bottom <= viewport.top + 1 || rect.top >= viewport.bottom
          || rect.right <= viewport.left || rect.left >= viewport.right) continue;
        const x = Math.max(rect.left, viewport.left) + 1;
        const y = Math.max(rect.top, viewport.top) + Math.min(3, rect.height / 2);
        const caret = document.caretRangeFromPoint?.(x, y);
        const position = !caret && document.caretPositionFromPoint?.(x, y);
        const localOffset = caret?.startContainer === node ? caret.startOffset
          : position?.offsetNode === node ? position.offset : 0;
        return { type: 'bookoasis-text-v1', chunkIdx: Number(chunk.dataset.idx ?? chunkIdx),
          offset: offset + localOffset };
      }
      offset += node.length;
    }
  }
  return null;
}

export function restoreTextResume(anchor, wrapper, content, { scroll, rtl, advance }) {
  if (!anchor || !wrapper || !content) return false;
  const chunk = content.querySelector(`[data-idx="${anchor.chunkIdx}"]`);
  if (!chunk) return false;
  const walker = document.createTreeWalker(chunk, NodeFilter.SHOW_TEXT);
  let node, remaining = anchor.offset;
  while ((node = walker.nextNode())) {
    if (remaining >= node.length && node.length > 0) { remaining -= node.length; continue; }
    if (!node.length) continue;
    const range = document.createRange();
    range.setStart(node, remaining); range.setEnd(node, Math.min(node.length, remaining + 1));
    const rect = range.getBoundingClientRect();
    const viewport = wrapper.getBoundingClientRect();
    if (scroll) wrapper.scrollTop += rect.top - viewport.top;
    else {
      const current = rtl ? -wrapper.scrollLeft : wrapper.scrollLeft;
      const distance = rtl ? viewport.right - rect.right : rect.left - viewport.left;
      const page = Math.max(0, Math.floor((current + distance + 1) / advance));
      wrapper.scrollLeft = (rtl ? -1 : 1) * page * advance;
    }
    return true;
  }
  return false;
}
