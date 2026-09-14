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


if __name__ == '__main__':
    mcp.run()
