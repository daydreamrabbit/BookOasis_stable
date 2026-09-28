# 리디형 이미지 뷰어 구현 메모

이 폴더의 코드는 특정 프레임워크에 종속되지 않는 ES 모듈입니다. 리디 PC 뷰어의 페이지 묶음 규칙을 재현하되, HTML 클래스명과 디자인 자산은 독립적으로 작성했습니다.

## 사용법

```html
<link rel="stylesheet" href="/ridi-viewer.css">
<div id="viewer"></div>
<script type="module">
  import { RidiStyleViewer, ViewerMode } from '/ridi-viewer.js';

  const viewer = new RidiStyleViewer({
    root: '#viewer',
    title: '작품명 1권',
    pages: pageUrls,
    initialPage: 1,
    initialMode: ViewerMode.TWO_ONE,
    readingDirection: 'rtl',
  });

  viewer.addEventListener('pagechange', ({ detail }) => {
    // detail.currentPage, detail.visiblePages, detail.totalPages
    saveReadingProgress(detail);
  });

  viewer.addEventListener('close', () => viewer.destroy());
</script>
```

## 페이지 묶음 규칙

총 10페이지라고 가정합니다.

| 모드 | 화면 묶음 | 하단 대표 페이지 변화 |
|---|---|---|
| 한쪽 | `[1] [2] [3] ... [10]` | `1, 2, 3 ... 10` |
| 왼쪽→오른쪽 두쪽 | `[빈칸,1] [2,3] ... [10,빈칸]` | `1, 2, 4, 6, 8, 10` |
| 오른쪽→왼쪽 두쪽 | 위와 같은 묶음을 반대 순서로 배치 | `1, 2, 4, 6, 8, 10` |
| 스크롤(웹툰) | 1~10을 세로로 연속 배치 | 가장 많이 보이는 이미지 기준 `1 ... 10` |

총 페이지가 홀수일 때도 빈칸을 넣어 펼침 정렬을 유지합니다. 빈칸은 실제 페이지 수에 포함하지 않습니다.

## 버튼 동작

- 첫 페이지: 모든 모드에서 논리 페이지 1로 이동하며 두 쪽 보기는 표지를 단독 표시합니다.
- 마지막 페이지: 현재 모드의 마지막 묶음으로 이동합니다.
- 이전/다음: 한쪽은 1페이지, 두쪽 모드는 한 묶음씩 이동합니다. 스크롤은 인접 이미지로 스크롤합니다.
- 한쪽: 현재 보고 있던 실제 페이지를 한 장으로 표시합니다.
- 1→2: 표지를 단독으로 두고 다음 장부터 왼쪽에서 오른쪽 순서로 표시합니다.
- 2←1: 같은 묶음을 오른쪽에서 왼쪽 순서로 표시합니다.
- 스크롤: 모든 이미지를 위에서 아래로 붙입니다. 원본 페이지 수는 변하지 않습니다.

## 키보드와 마우스

- `→`, `Space`, `PageDown`: 다음
- `←`, `PageUp`: 이전
- `Home` / `End`: 첫 / 마지막
- `Enter`: 메뉴 표시/숨김
- `Esc`: 화면 맞춤(배율 100%)
- `Ctrl + 휠`: 확대/축소

화면 탭존은 `왼쪽 28% / 중앙 44% / 오른쪽 28%`로 구성되어 있습니다. 중앙은 메뉴 토글, 양쪽은 이전/다음입니다.
