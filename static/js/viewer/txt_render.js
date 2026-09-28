export function isEpubImageOnlyHtml(html) {
  if (typeof html !== 'string' || !html.includes('<img')) return false;
  const probe = document.createElement('div');
  probe.innerHTML = html;
  return !!probe.querySelector('img') && !probe.textContent.trim();
}

export function renderTxtChunkView({
  contentArea,
  txtChunks,
  currentChunkIdx,
  scrollMode,
  isEpub,
  initMode,
  formatTxtToHtml,
  emptyText,
  pageStep = 1,
  coverAlone = false,
}) {
  if (!contentArea) return false;

  if (!Array.isArray(txtChunks) || txtChunks.length === 0) {
    contentArea.textContent = emptyText || '';
    return false;
  }

  if (isEpub) {
    contentArea.style.whiteSpace = 'normal';
    contentArea.style.wordBreak = 'break-word';
  } else {
    contentArea.style.whiteSpace = 'normal';
    contentArea.style.wordBreak = 'break-all';
  }

  if (scrollMode === 'page') {
    if (isEpub) {
      const currentHtml = txtChunks[currentChunkIdx];
      const nextHtml = txtChunks[currentChunkIdx + 1];
      const pairImageChapters = pageStep === 2
        && !(coverAlone && currentChunkIdx === 0)
        && isEpubImageOnlyHtml(currentHtml)
        && isEpubImageOnlyHtml(nextHtml);
      contentArea.classList.toggle('epub-image-spread', pairImageChapters);
      contentArea.dataset.renderedChunkSpan = pairImageChapters ? '2' : '1';
      contentArea.innerHTML = pairImageChapters
        ? `<div class="txt-chunk epub-chunk epub-image-only-chunk" data-idx="${currentChunkIdx}">${currentHtml}</div><div class="txt-chunk epub-chunk epub-image-only-chunk" data-idx="${currentChunkIdx + 1}">${nextHtml}</div>`
        : `<div class="txt-chunk epub-chunk" data-idx="${currentChunkIdx}" style="height: 100%; box-sizing: border-box;">${currentHtml}</div>`;
      // 표지·속표지처럼 이미지밖에 없는 EPUB 챕터는 래퍼 자체를 컬럼 높이(100%)로
      // 고정하면 Chromium의 multi-column 레이아웃이 래퍼 뒤에 빈 컬럼을 하나 더
      // 만든다. 그 결과 첫 페이지 넘김은 빈 컬럼만 통과하고 두 번째 넘김에서야
      // 다음 spine 항목으로 이동한다. 이미지 크기 제한은 별도로 적용되므로 이 경우에만
      // 래퍼 높이를 내용 기준으로 풀어 실제 이미지 한 장을 한 페이지로 계산한다.
      const epubChunk = contentArea.querySelector('.epub-chunk');
      if (epubChunk && !epubChunk.textContent.trim() && epubChunk.querySelector('img')) {
        epubChunk.style.height = 'auto';
        epubChunk.classList.add('epub-image-only-chunk');
      }
    } else {
      contentArea.classList.remove('epub-image-spread');
      contentArea.dataset.renderedChunkSpan = '1';
      // Keep stable chunk IDs for existing annotations, but let columns flow
      // through their boundaries instead of ending a page every 4000 chars.
      if (contentArea.__txtFlowChunks !== txtChunks || !contentArea.querySelector('.txt-flow-chunk')) {
        contentArea.innerHTML = txtChunks.map((text, idx) =>
          `<div class="txt-chunk txt-flow-chunk" data-idx="${idx}" style="height:auto;break-inside:auto;box-sizing:border-box">${formatTxtToHtml(text)}</div>`).join('');
        contentArea.__txtFlowChunks = txtChunks;
      }
    }
  } else if (initMode || !contentArea.querySelector('.txt-full-content')) {
    contentArea.classList.remove('epub-image-spread');
    contentArea.dataset.renderedChunkSpan = '1';
    if (isEpub) {
      const wrapped = txtChunks
        .map((ch, idx) => {
          const isPending = (ch === null || ch === 'LOADING_PENDING');
          return `<div class="txt-scroll-chunk" data-idx="${idx}" style="margin-bottom: 3rem;">${!isPending ? ch : '<div class="epub-ch-loading" style="padding: 2rem; text-align: center; opacity: 0.5;">챕터 불러오는 중...</div>'}</div>`;
        })
        .join('');
      contentArea.innerHTML = `<div class="txt-full-content epub-full-content">${wrapped}</div>`;
    } else {
      const wrapped = txtChunks
        .map((ch, idx) => `<div class="txt-scroll-chunk" data-idx="${idx}">${formatTxtToHtml(ch)}</div>`)
        .join('');
      contentArea.innerHTML = `<div class="txt-full-content">${wrapped}</div>`;
    }
  }

  return true;
}

export function applyTxtParagraphStyles({ contentArea, localStorage, currentViewerFormat }) {
  if (!contentArea) return;

  const savedParagraphSpacing = localStorage.getItem('viewer_paragraph_spacing') || '1.0';
  const pSpacingRem = parseFloat(savedParagraphSpacing);
  const scrollMode = localStorage.getItem('viewer_scroll_mode') || 'page';

  if (currentViewerFormat === 'epub') {
    contentArea.querySelectorAll('img').forEach(img => {
      img.style.maxHeight = scrollMode === 'page' ? '70vh' : '85vh';
      img.style.maxWidth = '100%';
      img.style.objectFit = 'contain';
    });
  }

  contentArea
    .querySelectorAll('p, div.txt-chunk > div, div.txt-full-content > div, h1, h2, h3, h4, h5, h6, blockquote, ul, ol, li, hr, ruby, rt, rp, sup, sub')
    .forEach(el => {
      const tag = el.tagName.toLowerCase();
      if (tag.startsWith('h')) {
        el.style.marginBottom = `${pSpacingRem * 1.5}rem`;
        el.style.marginTop = '1.5rem';
        el.style.fontWeight = 'bold';
      } else if (tag === 'ul' || tag === 'ol') {
        el.style.marginTop = '0';
        el.style.marginBottom = `${pSpacingRem}rem`;
        el.style.paddingLeft = '1.4rem';
      } else if (tag === 'li') {
        el.style.marginTop = '0';
        el.style.marginBottom = `${Math.max(0.2, pSpacingRem * 0.45)}rem`;
      } else if (tag === 'blockquote') {
        el.style.marginTop = '0';
        el.style.marginBottom = `${pSpacingRem}rem`;
        el.style.paddingLeft = '0.9rem';
        el.style.borderLeft = '3px solid rgba(148, 163, 184, 0.45)';
        el.style.opacity = '0.95';
      } else if (tag === 'hr') {
        el.style.marginTop = `${pSpacingRem}rem`;
        el.style.marginBottom = `${pSpacingRem}rem`;
      } else {
        el.style.marginBottom = `${pSpacingRem}rem`;
        el.style.marginTop = '0';
      }
    });
}
