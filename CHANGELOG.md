# CHANGELOG
## v2.7.2
- (fix) 최신 추가순 카테고리 로딩이 느린 이슈 수정 (목록의 has_metadata 계산 제거, `include_has_metadata=1`로 선택 계산) | fix slow category loading on newest-first sort (drop has_metadata from list queries; opt-in via `include_has_metadata=1`)
- (fix) MariaDB에서 MCP `run_readonly_query`가 동작하지 않던 이슈 수정 | fix MCP `run_readonly_query` failing on MariaDB
- (improvement) MCP 툴 추가/개선 (`get_version`, `SHOW`/`DESCRIBE` 쿼리 허용) | add MCP `get_version` and allow `SHOW`/`DESCRIBE` queries

## v2.7.1
- (fix) 카테고리 로딩이 권한체크 이슈로 느려지는 이슈 수정 | fix category loading slowdown caused by permission-check issue
- (improvement) 사용자 권한 기능 개선 (권한 복사 기능 추가) | improve user permission features (add permission copy feature)
- (improvement) 컨텍스트 메뉴에서 미독/완독 상태에 따라 노출되는 메뉴(상태 변경) 항목 변경 | change context menu items shown based on unread/completed status

## v2.7.0
- (fix,Emergency) lazyscanner 버그 픽스 (이미지 축소 백필 한계 증량) | lazyscanner bug fix
- (improvement) 도서 카드 그리드의 "메타데이터 미연결" 표시를 제거하고 상세화면 헤더로 이동 | remove the "no metadata" indicator from the book card grid and move it to the detail page header

