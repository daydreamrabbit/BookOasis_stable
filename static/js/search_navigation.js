// search_navigation.js – 검색어를 입력했을 때 화면을 이동해야 하는지, 어디로 이동할지 판단하는 순수 함수
//
// 상단 자료 검색은 현재 선택된 카테고리와 무관하게 항상 전체보기에서 실행한다.
// 시리즈 상세 화면에서는 검색 결과로 이동하되 히스토리에 상세를 남기고, 그 외 카테고리에서는
// 원래 카테고리와 스크롤 상태를 남겨 브라우저 뒤로가기로 복원할 수 있게 한다.

/**
 * @returns {null | {categoryId: string, options: object}} 전체보기에 이미 있으면 이동 없이 현재 목록을 검색한다.
 */
export function resolveSearchNavigation({ query, rawQuery, libraryId, detailVisible }) {
  if (!String(query || '').trim()) return null;
  const currentId = String(libraryId ?? '');

  if (detailVisible) {
    return {
      categoryId: 'all',
      options: { preserveSearch: true, searchNavigation: true, searchQuery: rawQuery },
    };
  }
  if (currentId !== 'all') {
    return {
      categoryId: 'all',
      options: { preserveSearch: true, searchNavigationFrom: currentId, searchQuery: rawQuery },
    };
  }
  return null;
}
