# -*- coding: utf-8 -*-
"""
mcp_server.py – BookOasis 서재 데이터를 Claude Code/Desktop 등 MCP 클라이언트에
읽기 전용 진단 툴로 노출하는 로컬 stdio MCP 서버.

tools/scanner_worker.py와 동일하게 Flask 앱과 분리된 별도 OS 프로세스로 실행되며,
services/repositories 레이어를 직접 import해서 쓴다. Claude Code에 등록하는 방법은
docs/guide_mcp_server.md 참고.

⚠️ stdout 보호: MCP stdio 전송 규약은 stdout을 오직 JSON-RPC 메시지 전용으로만
써야 한다. 이 코드베이스는 곳곳에서(예: database.py, series_service.py) 로그용
plain print()를 stdout에 쓰고 있어, 그대로 두면 서재 조회 한 번에 프로토콜 스트림이
깨질 수 있다. 그래서 각 툴 함수 본문 실행 동안만 sys.stdout을 stderr로 리다이렉트해
어떤 내부 print()도 실제 stdout(MCP 프로토콜 채널)을 건드리지 못하게 막는다.
"""
import os
import sys
import contextlib

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from utils.encoding_helper import force_utf8_stdio
force_utf8_stdio()

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(BASE_DIR, '.env'))
except Exception as env_err:
    print(f"[MCP-Server] .env 로드 실패: {env_err}", file=sys.stderr)

from mcp.server.mcpserver import MCPServer

mcp = MCPServer("bookoasis")


def _quiet(fn, *args, **kwargs):
    """내부 서비스 호출 동안 stdout을 stderr로 돌려 MCP 프로토콜 스트림을 보호한다."""
    with contextlib.redirect_stdout(sys.stderr):
        return fn(*args, **kwargs)


@mcp.tool()
def search_books(query: str, db_type: str = "general", library_id: str = "all",
                  genre: str = "", tags: str = "", limit: int = 20) -> dict:
    """서재에서 제목/시리즈명으로 시리즈를 검색합니다(단행본이 아니라 시리즈 단위로 묶여 반환됨).
    db_type: general(일반 도서) / adult(성인 서재) / audiobook(오디오북).
    genre/tags는 콤마로 구분된 필터 문자열입니다(선택)."""
    def _run():
        from services.series_service import SeriesService
        genre_filters = [g.strip() for g in genre.split(',') if g.strip()] if genre else None
        tag_filters = [t.strip() for t in tags.split(',') if t.strip()] if tags else None
        results = SeriesService.get_books_list(
            db_type, library_id, page=1, limit=limit, search_query=query,
            genre_filters=genre_filters, tag_filters=tag_filters,
        )
        return {'total_returned': len(results), 'series': results}
    return _quiet(_run)


@mcp.tool()
def get_library_stats(db_type: str = "general") -> dict:
    """서재 전체 통계(총 시리즈 수/총 도서 권수) 및 카테고리별 세부 통계를 반환합니다."""
    def _run():
        from services.library_diagnostics_service import LibraryDiagnosticsService
        return LibraryDiagnosticsService.get_stats(db_type)
    return _quiet(_run)


@mcp.tool()
def find_missing_cover(db_type: str = "general", library_id: int = None,
                        limit: int = 50, offset: int = 0) -> dict:
    """표지 이미지가 없는 도서 목록을 페이지네이션으로 조회합니다. library_id를 지정하면
    해당 카테고리로 범위를 좁힙니다."""
    def _run():
        from services.library_diagnostics_service import LibraryDiagnosticsService
        return LibraryDiagnosticsService.find_missing_cover(db_type, library_id=library_id, limit=limit, offset=offset)
    return _quiet(_run)


@mcp.tool()
def find_missing_genre_and_tags(db_type: str = "general", library_id: int = None,
                                 limit: int = 50, offset: int = 0) -> dict:
    """장르와 태그가 둘 다 비어있는 도서 목록을 페이지네이션으로 조회합니다."""
    def _run():
        from services.library_diagnostics_service import LibraryDiagnosticsService
        return LibraryDiagnosticsService.find_missing_genre_and_tags(db_type, library_id=library_id, limit=limit, offset=offset)
    return _quiet(_run)


@mcp.tool()
def find_missing_offsets(db_type: str = "general", library_id: int = None,
                          limit: int = 50, offset: int = 0) -> dict:
    """zip/cbz 만화책 중 페이지 오프셋 캐시가 없어 재스캔이 필요한 도서 목록을 조회합니다.
    rclone/GDrive 등 원격 마운트 파일은 이 진단 대상에서 자동 제외됩니다."""
    def _run():
        from services.library_diagnostics_service import LibraryDiagnosticsService
        return LibraryDiagnosticsService.find_missing_offsets(db_type, library_id=library_id, limit=limit, offset=offset)
    return _quiet(_run)


@mcp.tool()
def find_duplicate_series(db_type: str = "general") -> dict:
    """동일한 시리즈명이 서로 다른 카테고리 2곳 이상에 흩어져 등록된 케이스를 찾습니다
    (오타/유사명까지는 잡지 못합니다 - 그런 경우는 search_books로 직접 탐색해 판단하세요)."""
    def _run():
        from services.library_diagnostics_service import LibraryDiagnosticsService
        return LibraryDiagnosticsService.find_duplicate_series(db_type)
    return _quiet(_run)


@mcp.tool()
def run_readonly_query(db_type: str = "general", sql: str = "", max_rows: int = 200) -> dict:
    """서재 DB에 읽기 전용(SELECT/WITH/EXPLAIN) SQL을 직접 실행합니다.
    db_type: general(일반 도서) / adult(성인 서재) / audiobook(오디오북) / video(영상 강좌).
    INSERT/UPDATE/DELETE/DROP 등 쓰기 구문은 앱 레벨과 DB 레벨(읽기전용 커넥션/세션) 양쪽에서
    거부됩니다. 미리 만들어진 진단 툴로 커버되지 않는 새로운 조건을 즉석에서 조회할 때 쓰세요.
    스키마를 모르면 먼저 `PRAGMA table_info(books)` 같은 쿼리로 컬럼을 확인하세요."""
    def _run():
        from services.mcp_admin_tools_service import McpAdminToolsService
        return McpAdminToolsService.run_readonly_query(db_type, sql, max_rows=max_rows)
    return _quiet(_run)


@mcp.tool()
def read_logs(log_name: str = "media_server.log", lines: int = 200, search: str = "") -> dict:
    """logs/ 폴더의 서버 로그를 끝에서부터 최근 N줄 조회합니다.
    log_name: media_server.log(웹 프로세스) / scanner.log(스캐너 워커) / lazy_scanner.log /
    scan_history.log(스캔 요약, 회전 없음) 중 하나만 허용됩니다.
    search를 주면 해당 문자열이 포함된 줄만(대소문자 무시) 필터링합니다."""
    def _run():
        from services.mcp_admin_tools_service import McpAdminToolsService
        return McpAdminToolsService.read_log_file(log_name, lines=lines, search=search or None)
    return _quiet(_run)


@mcp.tool()
def call_api(path: str, query_params: dict = None, max_response_chars: int = 20000) -> dict:
    """BookOasis의 기존 GET REST API를 그대로 호출합니다 (사용 가능한 경로 목록은
    docs/api_endpoints.md 참고). 예: path="/api/media/list", query_params={"type": "general",
    "library_id": "all", "limit": 5}. 진단 툴이 커버하지 못하는 기존 기능(상세정보, 장르/태그
    목록, 스캔 상태, 플러그인 목록 등)을 새 코드 없이 그대로 재사용할 때 쓰세요.
    GET만 가능합니다 - 이 툴 자체가 다른 HTTP 메서드를 호출할 방법을 제공하지 않습니다.
    내부적으로 관리자 세션으로 인증되어 호출되므로 성인 서재/admin_only 플러그인 데이터도
    조회됩니다."""
    def _run():
        from services.mcp_admin_tools_service import McpAdminToolsService
        return McpAdminToolsService.call_api(path, query_params=query_params, max_response_chars=max_response_chars)
    return _quiet(_run)


@mcp.tool()
def update_book_metadata(series_name: str, db_type: str = "general", library_id: str = "all",
                          author: str = None, publisher: str = None, summary: str = None,
                          link: str = None, genre: str = None, tags: str = None,
                          isbn: str = None, series_alias: str = None, books_lv: str = None,
                          publication_status: str = None) -> dict:
    """[쓰기 도구] 시리즈의 장르/태그/작가 등 메타데이터를 부분 수정합니다. 지정하지 않은
    필드는 현재 값이 그대로 유지됩니다(부분 업데이트). 관리자가 설정 > 일반 설정에서
    "MCP 쓰기 도구 허용"을 켜야만 동작하며, 꺼져 있으면 에러를 반환합니다.
    이 도구는 기존 REST API가 쓰는 것과 동일한 검증된 서비스 메서드만 호출하고, 코어나
    플러그인 소스 코드/파일은 절대 건드리지 않습니다. 변경 전/후 값은 응답의
    changed_fields와 logs/mcp_write_audit.log에 함께 기록됩니다. 실행 전 search_books로
    대상 시리즈명이 정확한지 먼저 확인하세요."""
    def _run():
        from services.mcp_admin_tools_service import McpAdminToolsService
        fields = {
            'author': author, 'publisher': publisher, 'summary': summary, 'link': link,
            'genre': genre, 'tags': tags, 'isbn': isbn, 'series_alias': series_alias, 'books_lv': books_lv,
            'publication_status': publication_status,
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        return McpAdminToolsService.update_book_metadata(db_type, series_name, library_id=library_id, **fields)
    return _quiet(_run)


@mcp.tool()
def bulk_set_favorite(book_ids: list, is_favorite: bool, db_type: str = "general", user_id: int = 1) -> dict:
    """[쓰기 도구] 도서 id 목록에 대해 즐겨찾기를 일괄 등록/해제합니다. 한 번에 최대 500건까지
    처리 가능합니다(그 이상의 대량 작업은 이 도구로 하지 마세요). 관리자가 설정 > 일반 설정에서
    "MCP 쓰기 도구 허용"을 켜야만 동작합니다. 코어/플러그인 파일은 건드리지 않으며 서재 DB의
    즐겨찾기 상태만 변경합니다."""
    def _run():
        from services.mcp_admin_tools_service import McpAdminToolsService
        return McpAdminToolsService.bulk_set_favorite(db_type, book_ids, is_favorite, user_id)
    return _quiet(_run)


@mcp.tool()
def propose_bulk_book_metadata_update(series_names: list, db_type: str = "general", library_id: str = "all",
                                       author: str = None, publisher: str = None, summary: str = None,
                                       link: str = None, genre: str = None, tags: str = None,
                                       isbn: str = None, series_alias: str = None, books_lv: str = None,
                                       publication_status: str = None) -> dict:
    """[쓰기 도구 - Tier B, 즉시 실행 안 함] 여러 시리즈에 대한 메타데이터 일괄 수정을
    "제안"합니다. update_book_metadata(단일 시리즈)와 달리 이 도구는 DB를 바로 바꾸지
    않고, 변경 전/후 값 미리보기를 만들어 mcp_pending_changes 테이블에 대기시킵니다.
    관리자가 설정 > MCP 승인 대기 화면에서 검토 후 승인해야만 실제로 반영됩니다.
    관리자가 설정 > 일반 설정에서 "MCP 쓰기 도구 허용"을 켜야만 제안 생성이 가능합니다
    (승인/거부 자체는 그 설정과 무관하게 항상 가능). 응답의 change_id를 사용자에게 알려주고
    관리자 승인을 요청하도록 안내하세요. 단일 시리즈만 수정한다면 즉시 반영되는
    update_book_metadata를 대신 쓰는 게 더 간단합니다."""
    def _run():
        from services.mcp_proposal_service import McpProposalService
        fields = {
            'author': author, 'publisher': publisher, 'summary': summary, 'link': link,
            'genre': genre, 'tags': tags, 'isbn': isbn, 'series_alias': series_alias, 'books_lv': books_lv,
            'publication_status': publication_status,
        }
        fields = {k: v for k, v in fields.items() if v is not None}
        return McpProposalService.propose_bulk_book_metadata_update(db_type, series_names, library_id, fields)
    return _quiet(_run)


@mcp.tool()
def propose_bulk_set_favorite(book_ids: list, is_favorite: bool, db_type: str = "general", user_id: int = 1) -> dict:
    """[쓰기 도구 - Tier B, 즉시 실행 안 함] 500건을 초과하는 대량 즐겨찾기 일괄 등록/해제를
    "제안"합니다. bulk_set_favorite(≤500건, 즉시 실행)와 달리 이 도구는 DB를 바로 바꾸지
    않고 mcp_pending_changes 테이블에 제안만 남기며, 관리자가 설정 > MCP 승인 대기 화면에서
    승인해야 실제로 반영됩니다. 500건 이하라면 즉시 반영되는 bulk_set_favorite를 대신
    쓰는 게 더 간단합니다."""
    def _run():
        from services.mcp_proposal_service import McpProposalService
        return McpProposalService.propose_bulk_set_favorite(db_type, book_ids, is_favorite, user_id)
    return _quiet(_run)


if __name__ == '__main__':
    mcp.run()
