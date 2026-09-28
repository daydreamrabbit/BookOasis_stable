// header_scroll_behavior.js – 상단 헤더(.library-header)를 스크롤 상태에 따라 숨김/노출 + 입체감 부여.
// 커뮤니티에서 계속 논의되던 "스크롤 중에도 검색/세션탭이 보여야 한다" 요청에 따라
// .library-header를 sticky로 고정(static/css/style.css)한 뒤, 아래로 스크롤할 때만 살짝
// 숨겨 좁은 화면에서 그리드 노출 영역을 확보하고 위로 스크롤하면 즉시 다시 보여준다.
// 맨 위에서 조금이라도 스크롤되면 그림자를 키워 플랫하던 헤더가 그리드 위에 "떠 있는"
// 느낌을 주는 효과도 같은 스크롤 리스너에 얹어서 처리한다(추가 리스너/레이아웃 비용 없음).
(function () {
  function init() {
    const scrollEl = document.querySelector('.library-main-content');
    const header = document.querySelector('.library-header');
    if (!scrollEl || !header) return;

    let lastScrollTop = scrollEl.scrollTop;
    const isMobile = window.matchMedia('(max-width: 1200px)').matches;
    const moveThreshold = 8;    // 데스크톱의 미세한 스크롤 변화 무시(떨림 방지)
    const mobileHideDistance = 16;
    const mobileRevealDistance = 80;
    const revealNearTop = 60;   // 맨 위에서 이 거리 이내면 방향과 무관하게 항상 보여줌
    const elevateAfter = 4;     // 이 거리를 넘어서 스크롤되면 그림자를 진하게(입체감)
    let downwardDistance = 0;
    let upwardDistance = 0;
    let ticking = false;

    function onScroll() {
      if (ticking) return;
      ticking = true;
      requestAnimationFrame(() => {
        const st = scrollEl.scrollTop;
        const delta = st - lastScrollTop;

        if (st <= revealNearTop) {
          header.classList.remove('library-header--hidden');
          downwardDistance = 0;
          upwardDistance = 0;
        } else if (delta > 0) {
          downwardDistance += delta;
          upwardDistance = 0;
          if ((!isMobile && downwardDistance >= moveThreshold)
              || (isMobile && downwardDistance >= mobileHideDistance)) {
            header.classList.add('library-header--hidden');
          }
        } else if (delta < 0) {
          upwardDistance += -delta;
          downwardDistance = 0;
          // 모바일에서는 살짝 위로 튕기는 동작만으로 검색바가 다시 내려오지 않게 한다.
          // 충분히 위로 이동했거나 최상단에 가까워졌을 때만 헤더를 복원한다.
          if ((!isMobile && upwardDistance >= moveThreshold)
              || (isMobile && upwardDistance >= mobileRevealDistance)) {
            header.classList.remove('library-header--hidden');
          }
        }

        header.classList.toggle('library-header--elevated', st > elevateAfter);

        lastScrollTop = st;
        ticking = false;
      });
    }

    scrollEl.addEventListener('scroll', onScroll, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
