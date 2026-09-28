import { getTxtPageScrollLeft, setTxtPageScrollLeft } from './txt_page_utils.js?rev=20260922-reader-session-v45';

export function prevTxtPageAction(ctx) {
  const scrollWrapper = ctx.getScrollWrapper();
  if (!scrollWrapper) return;

  ctx.cancelPendingRestore();
  const scrollMode = ctx.getScrollMode();

  if (scrollMode === 'page') {
    // 챕터 경계를 넘는 전환(위 분기)은 기존에 이 가드를 전혀 쓰지 않았다.
    // 짧은 챕터(스크롤 폭이 좁아 maxScrollLeft가 거의 0)에 진입한 직후
    // 빠르게 다시 탭하면, 아직 innerHTML/scrollLeft 리셋이 끝나기 전(20ms
    // 타이머 대기 중) 상태로 재진입해 옛 scrollLeft 값을 새 챕터의(짧은)
    // scrollWidth 기준으로 판정 → 챕터를 건너뛰거나 같은 내용이 반복
    // 표시되는 원인이었다. 페이지 모드 전환 전체를 이 가드로 감싼다.
    if (ctx.getTxtPageSnapInProgress && ctx.getTxtPageSnapInProgress()) return;
    ctx.setTxtPageSnapInProgress(true);
    ctx.snapTxtPageScrollLeft(scrollWrapper);
    if (getTxtPageScrollLeft(scrollWrapper) <= 10) {
      if (ctx.getCurrentChunkIdx() > 0) {
        const previousIdx = ctx.getPreviousChunkIdx
          ? ctx.getPreviousChunkIdx(ctx.getCurrentChunkIdx())
          : ctx.getCurrentChunkIdx() - 1;
        ctx.setCurrentChunkIdx(previousIdx);
        scrollWrapper.style.scrollBehavior = 'auto';
        scrollWrapper.style.visibility = 'hidden';
        let chapterEndJumpDone = false;
        const finishJumpToChapterEnd = () => {
          if (chapterEndJumpDone) return;
          chapterEndJumpDone = true;
          setTxtPageScrollLeft(scrollWrapper, Math.max(0, scrollWrapper.scrollWidth - scrollWrapper.clientWidth));
          ctx.snapTxtPageScrollLeft(scrollWrapper);
          scrollWrapper.style.scrollBehavior = '';
          ctx.saveDetailPosition();
          ctx.setTxtPageSnapInProgress(false);
          ctx.updatePageInfo?.();
          scrollWrapper.style.visibility = '';
        };
        ctx.renderCurrentChunk(false, finishJumpToChapterEnd);
      } else {
        ctx.setTxtPageSnapInProgress(false);
        ctx.showBoundaryNotice?.('start');
      }
    } else {
      const pageStepWidth = ctx.getTxtPageAdvanceWidth(scrollWrapper);
      const currentPageIdx = Math.round(getTxtPageScrollLeft(scrollWrapper) / pageStepWidth);
      const targetScrollLeft = Math.max(0, (currentPageIdx - 1) * pageStepWidth);
      setTxtPageScrollLeft(scrollWrapper, targetScrollLeft);
      ctx.snapTxtPageScrollLeft(scrollWrapper);
      ctx.logActiveViewportText();
      ctx.saveDetailPosition();
      ctx.updatePageInfo?.();
      ctx.setTxtPageSnapInProgress(false);
    }
    return;
  }

  if (scrollWrapper.scrollTop <= 10) {
    if (ctx.getCurrentChunkIdx() > 0) {
      ctx.setCurrentChunkIdx(ctx.getCurrentChunkIdx() - 1);
      scrollWrapper.style.scrollBehavior = 'auto';
      ctx.renderCurrentChunk();

      setTimeout(() => {
        scrollWrapper.scrollTop = scrollWrapper.scrollHeight;
      }, 20);

      setTimeout(() => {
        scrollWrapper.style.scrollBehavior = '';
        ctx.logActiveViewportText();
        ctx.saveDetailPosition();
      }, 80);
    } else {
      ctx.showBoundaryNotice?.('start');
    }
  } else {
    scrollWrapper.scrollBy({ top: -scrollWrapper.clientHeight * 0.9, behavior: 'smooth' });
    setTimeout(() => {
      ctx.logActiveViewportText();
      ctx.saveDetailPosition();
    }, 350);
  }
}

export function nextTxtPageAction(ctx) {
  const scrollWrapper = ctx.getScrollWrapper();
  if (!scrollWrapper) return;

  ctx.cancelPendingRestore();
  const scrollMode = ctx.getScrollMode();

  if (scrollMode === 'page') {
    if (ctx.getTxtPageSnapInProgress && ctx.getTxtPageSnapInProgress()) return;
    ctx.setTxtPageSnapInProgress(true);
    ctx.snapTxtPageScrollLeft(scrollWrapper);
    const pageStepWidth = ctx.getTxtPageAdvanceWidth(scrollWrapper);
    const maxScrollLeft = Math.max(0, scrollWrapper.scrollWidth - scrollWrapper.clientWidth);
    const snapTolerance = Math.max(30, pageStepWidth * 0.4);

    if (getTxtPageScrollLeft(scrollWrapper) + snapTolerance >= maxScrollLeft) {
      if (ctx.getCurrentChunkIdx() < ctx.getChunkCount() - 1) {
        const advance = ctx.getChunkAdvance ? ctx.getChunkAdvance(ctx.getCurrentChunkIdx()) : 1;
        ctx.setCurrentChunkIdx(Math.min(ctx.getChunkCount() - 1, ctx.getCurrentChunkIdx() + advance));
        scrollWrapper.style.scrollBehavior = 'auto';
        scrollWrapper.style.visibility = 'hidden';
        let transitionDone = false;
        const finishChapterTransition = () => {
          if (transitionDone) return;
          transitionDone = true;
          setTxtPageScrollLeft(scrollWrapper, 0);
          scrollWrapper.scrollTop = 0;
          scrollWrapper.style.scrollBehavior = '';
          ctx.saveDetailPosition();
          ctx.setTxtPageSnapInProgress(false);
          ctx.updatePageInfo?.();
          scrollWrapper.style.visibility = '';
        };
        ctx.renderCurrentChunk(false, finishChapterTransition);
      } else {
        ctx.setTxtPageSnapInProgress(false);
        ctx.handleNextEpisode();
      }
    } else {
      const currentPageIdx = Math.round(getTxtPageScrollLeft(scrollWrapper) / pageStepWidth);
      const targetScrollLeft = Math.min(maxScrollLeft, (currentPageIdx + 1) * pageStepWidth);
      setTxtPageScrollLeft(scrollWrapper, targetScrollLeft);
      ctx.snapTxtPageScrollLeft(scrollWrapper);
      ctx.logActiveViewportText();
      ctx.saveDetailPosition();
      ctx.updatePageInfo?.();
      ctx.setTxtPageSnapInProgress(false);
    }
    return;
  }

  const maxScrollTop = scrollWrapper.scrollHeight - scrollWrapper.clientHeight;
  if (scrollWrapper.scrollTop + 10 >= maxScrollTop) {
    if (ctx.getCurrentChunkIdx() < ctx.getChunkCount() - 1) {
      ctx.setCurrentChunkIdx(ctx.getCurrentChunkIdx() + 1);
      scrollWrapper.style.scrollBehavior = 'auto';
      ctx.renderCurrentChunk();

      setTimeout(() => {
        scrollWrapper.scrollTop = 0;
        setTxtPageScrollLeft(scrollWrapper, 0);
      }, 20);

      setTimeout(() => {
        scrollWrapper.style.scrollBehavior = '';
        ctx.logActiveViewportText();
        ctx.saveDetailPosition();
      }, 80);
    } else {
      ctx.handleNextEpisode();
    }
  } else {
    scrollWrapper.scrollBy({ top: scrollWrapper.clientHeight * 0.9, behavior: 'smooth' });
    setTimeout(() => {
      ctx.logActiveViewportText();
      ctx.saveDetailPosition();
    }, 350);
  }
}

export function txtJumpToFirstPageAction(ctx) {
  ctx.cancelPendingRestore();
  const scrollWrapper = ctx.getScrollWrapper();

  if (ctx.getChunkCount() > 0 && ctx.getCurrentChunkIdx() !== 0) {
    ctx.setCurrentChunkIdx(0);
    ctx.setTxtScrollPreloadTriggered(false);
    ctx.setTxtScrollNextEpisodeTriggered(false);
    ctx.renderCurrentChunk();
  }

  // Even if already on chunk 0, reset the in-chapter scroll position.
  if (scrollWrapper) {
    scrollWrapper.scrollTop = 0;
    setTxtPageScrollLeft(scrollWrapper, 0);
  }
  ctx.updateSeekBar?.();
}

export function txtJumpToLastPageAction(ctx) {
  ctx.cancelPendingRestore();
  const lastIdx = Math.max(0, ctx.getChunkCount() - 1);
  if (ctx.getChunkCount() > 0 && ctx.getCurrentChunkIdx() !== lastIdx) {
    ctx.setCurrentChunkIdx(lastIdx);
    ctx.setTxtScrollPreloadTriggered(true);
    ctx.renderCurrentChunk();
    const scrollWrapper = ctx.getScrollWrapper();
    if (scrollWrapper) {
      scrollWrapper.scrollTop = 0;
      setTxtPageScrollLeft(scrollWrapper, 0);
    }
  }
  ctx.updateSeekBar?.();
}

export function txtSliderInputAction({ val, chunkCount, scrollMode = 'page' }) {
  const tooltip = document.getElementById('seekbar-tooltip');
  if (tooltip) {
    tooltip.textContent = scrollMode === 'scroll' ? `${val}%` : val;
    tooltip.style.display = 'block';
  }
  const pageInfo = document.getElementById('comic-overlay-page-info');
  if (pageInfo) {
    pageInfo.textContent = scrollMode === 'scroll' ? `${val}%` : `${val} / ${chunkCount}`;
  }
}

export function txtSliderChangeAction(ctx, val) {
  ctx.cancelPendingRestore();
  const scrollMode = ctx.getScrollMode();
  const scrollWrapper = ctx.getScrollWrapper();
  if (scrollMode === 'scroll') {
    if (scrollWrapper) {
      const percent = Math.max(0, Math.min(100, Number(val) || 0));
      const maxScroll = Math.max(0, scrollWrapper.scrollHeight - scrollWrapper.clientHeight);
      scrollWrapper.scrollTop = maxScroll * (percent / 100);
      setTimeout(ctx.saveDetailPosition, 50);
    }
    return;
  }

  const targetIdx = Math.max(0, Math.min(ctx.getChunkCount() - 1, val - 1));
  if (ctx.getCurrentChunkIdx() !== targetIdx) {
    ctx.setCurrentChunkIdx(targetIdx);

    if (scrollWrapper) {
      setTxtPageScrollLeft(scrollWrapper, 0);
    }
    ctx.renderCurrentChunk();
    ctx.logActiveViewportText();
    ctx.saveDetailPosition();
  }
}
