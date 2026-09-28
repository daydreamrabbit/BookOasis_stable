// 도서 컨텍스트 메뉴의 읽음 상태 액션 결정.
// 진행 정보가 누락된(undefined) 카드를 읽은 책으로 추정하면 미독 도서에
// "읽지 않은 상태로 변경"이 노출되므로, 명시적인 true만 진행 있음으로 취급한다.
export function shouldOfferMarkAsRead({ hasProgress, isMultiSelection, isVideoLibrary }) {
  return !isMultiSelection && !isVideoLibrary && hasProgress !== true;
}
