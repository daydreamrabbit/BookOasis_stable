# -*- coding: utf-8 -*-
"""
mcp_admin_tools_service.py – MCP 서버(tools/mcp_server.py)용 범용 읽기전용 SQL 쿼리 및
서버 로그 조회. 진단 항목마다 전용 리포지토리/서비스 메서드를 새로 만들어야 했던
library_diagnostics_service.py의 한계를 보완한다 - Claude가 스키마만 알면 즉석에서
새 조건으로 직접 조회할 수 있다.
"""
import os
import re
from collections import deque

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS_DIR = os.path.join(BASE_DIR, 'logs')

_VALID_DB_TYPES = ('general', 'adult', 'audiobook', 'video')

_ALLOWED_LEADING_KEYWORDS = ('select', 'with', 'explain', 'pragma')
_BANNED_KEYWORDS = (
    'insert', 'update', 'delete', 'drop', 'alter', 'create', 'attach', 'detach',
    'replace', 'truncate', 'grant', 'revoke', 'vacuum',
)
# PRAGMA는 시작 키워드로는 허용한다(table_info/index_list 등 스키마 조회에 필요) - 값을
# 바꾸는 PRAGMA(journal_mode=DELETE 등)가 섞여 들어와도 sqlite는 읽기전용(mode=ro)
# 커넥션, MariaDB는 SESSION READ ONLY 세션에서 실행되므로 DB 레벨에서 실제로 막힌다.

_ALLOWED_LOG_FILES = ('media_server.log', 'scanner.log', 'lazy_scanner.log', 'scan_history.log')


def _validate_readonly_sql(sql):
    """SELECT/WITH/EXPLAIN 단일 구문만 허용 (앱 레벨 1차 방어 - DB 레벨 방어가 진짜 안전판)"""
    stripped = (sql or '').strip().rstrip(';').strip()
    if not stripped:
        raise ValueError('sql이 비어있습니다.')
    if ';' in stripped:
        raise ValueError('세미콜론으로 구분된 다중 쿼리는 허용되지 않습니다.')

    first_word = stripped.split(None, 1)[0].lower()
    if first_word not in _ALLOWED_LEADING_KEYWORDS:
        raise ValueError(f"SELECT/WITH/EXPLAIN 쿼리만 허용됩니다 (시작 키워드: {first_word})")

    lowered = stripped.lower()
    for kw in _BANNED_KEYWORDS:
        if re.search(rf'\b{kw}\b', lowered):
            raise ValueError(f'허용되지 않는 키워드가 포함되어 있습니다: {kw}')

    return stripped


def _validate_db_type(db_type):
    db_type = (db_type or 'general').strip().lower()
    if db_type not in _VALID_DB_TYPES:
        raise ValueError(f"지원하지 않는 db_type입니다: {db_type} (허용값: {', '.join(_VALID_DB_TYPES)})")
    return db_type


class McpAdminToolsService:
    @staticmethod
    def run_readonly_query(db_type, sql, max_rows=200):
        db_type = _validate_db_type(db_type)
        sql = _validate_readonly_sql(sql)
        max_rows = max(1, min(int(max_rows or 200), 1000))

        import database
        if database.is_mariadb_mode():
            rows, columns = McpAdminToolsService._run_mariadb_readonly(db_type, sql, max_rows)
        else:
            rows, columns = McpAdminToolsService._run_sqlite_readonly(db_type, sql, max_rows)

        truncated = len(rows) > max_rows
        return {
            'db_type': db_type,
            'columns': columns,
            'rows': rows[:max_rows],
            'row_count': min(len(rows), max_rows),
            'truncated': truncated,
        }

    @staticmethod
    def _run_sqlite_readonly(db_type, sql, max_rows):
        """전용 read-only URI 커넥션 - 풀을 쓰지 않고, OS 레벨에서 물리적으로 쓰기가
        불가능한 별도 연결을 매번 새로 열고 닫는다 (진짜 안전판)."""
        import sqlite3
        import database
        db_path = database.get_db_path(db_type)
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=30.0)
        try:
            conn.row_factory = sqlite3.Row
            conn.execute(f"PRAGMA busy_timeout = {database.SQLITE_BUSY_TIMEOUT_MS}")
            cursor = conn.execute(sql)
            fetched = cursor.fetchmany(max_rows + 1)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(row) for row in fetched]
            return rows, columns
        finally:
            conn.close()

    @staticmethod
    def _run_mariadb_readonly(db_type, sql, max_rows):
        """풀 커넥션을 빌리되 세션을 READ ONLY로 걸었다가 반드시 READ WRITE로 원복 후
        반납한다 - 세션 상태이므로 그대로 반납하면 다음 사용자가 쓰기를 못 하게 되는
        사고가 나기 때문."""
        import database
        conn = database.get_connection(db_type)
        cursor = conn.cursor()
        try:
            cursor.execute("SET SESSION TRANSACTION READ ONLY")
            cursor.execute(sql)
            fetched = cursor.fetchmany(max_rows + 1)
            columns = [d[0] for d in cursor.description] if cursor.description else []
            rows = [dict(row) for row in fetched]
            return rows, columns
        finally:
            try:
                cursor.execute("SET SESSION TRANSACTION READ WRITE")
            except Exception:
                pass
            conn.close()

    @staticmethod
    def read_log_file(log_name, lines=200, search=None):
        if log_name not in _ALLOWED_LOG_FILES:
            raise ValueError(f"허용되지 않는 로그 파일입니다. 허용 목록: {', '.join(_ALLOWED_LOG_FILES)}")

        lines = max(1, min(int(lines or 200), 1000))
        log_path = os.path.join(LOGS_DIR, log_name)
        if not os.path.exists(log_path):
            return {'exists': False, 'file': log_name, 'lines': []}

        search_lower = (search or '').strip().lower()
        matched = deque(maxlen=lines)
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if search_lower and search_lower not in line.lower():
                    continue
                matched.append(line.rstrip('\n'))

        return {
            'exists': True,
            'file': log_name,
            'returned_lines': len(matched),
            'lines': list(matched),
        }
