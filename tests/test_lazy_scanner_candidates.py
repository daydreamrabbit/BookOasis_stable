import sqlite3
from unittest.mock import patch

from tools.lazy_scanner import (
    _fetch_lazy_scan_candidates,
    _fetch_lazy_scan_series_books,
    _open_database_connection,
)


def test_mariadb_connection_does_not_require_local_database_file():
    expected_connection = object()

    with patch('tools.lazy_scanner.database.is_mariadb_mode', return_value=True), patch(
        'tools.lazy_scanner.database.get_connection', return_value=expected_connection
    ) as get_connection, patch('tools.lazy_scanner.os.path.exists') as path_exists:
        connection = _open_database_connection('general')

    assert connection is expected_connection
    get_connection.assert_called_once_with('general', wait_timeout=60.0)
    path_exists.assert_not_called()


def test_sqlite_connection_is_skipped_when_database_file_is_missing():
    with patch('tools.lazy_scanner.database.is_mariadb_mode', return_value=False), patch(
        'tools.lazy_scanner.database.get_db_path', return_value='missing.db'
    ), patch('tools.lazy_scanner.os.path.exists', return_value=False), patch(
        'tools.lazy_scanner.database.get_connection'
    ) as get_connection:
        connection = _open_database_connection('general')

    assert connection is None
    get_connection.assert_not_called()


def test_failed_cover_is_retried_on_next_lazy_scan():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE books (
            id INTEGER,
            file_path TEXT,
            series_name TEXT,
            file_format TEXT,
            cover_image TEXT,
            library_id INTEGER,
            total_pages INTEGER,
            has_offsets INTEGER,
            metadata_locked INTEGER
        )
    """)
    connection.executemany(
        'INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (1, 'missing.pdf', 'Missing', 'pdf', None, 1, 1, 1, 0),
            (2, 'failed.pdf', 'Failed', 'pdf', 'NO_COVER', 1, 1, 1, 0),
            (3, 'ready.pdf', 'Ready', 'pdf', 'ready.webp', 1, 1, 1, 0),
            (4, 'text.txt', 'Text', 'txt', None, 1, 1, 1, 0),
            (5, 'invalid.cbz', 'Invalid', 'cbz', 'NO_COVER', 1, 0, -1, 0),
            (6, 'offset-failed.cbz', 'Offset failed', 'cbz', 'ready.webp', 1, 0, -1, 0),
        ],
    )

    candidates = _fetch_lazy_scan_candidates(connection.cursor())

    assert [book['id'] for book in candidates] == [1, 2, 5]


def test_manual_library_scan_inspects_all_rows_and_bypasses_no_cover_cooldown():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE books (
            id INTEGER,
            file_path TEXT,
            series_name TEXT,
            file_format TEXT,
            cover_image TEXT,
            library_id INTEGER,
            total_pages INTEGER,
            has_offsets INTEGER,
            metadata_locked INTEGER
        )
    """)
    connection.executemany(
        'INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (1, '/books/one.cbz', 'Series', 'cbz', 'NO_COVER', 7, 180, 1, 0),
            (2, '/books/two.cbz', 'Series', 'cbz', '7/stale-cover.webp', 7, 200, 1, 0),
            (3, '/books/ready.cbz', 'Ready', 'cbz', '7/ready.webp', 7, 190, 1, 0),
            (4, '/books/notes.txt', 'Notes', 'txt', None, 7, 0, 0, 0),
            (5, '/other-library/book.cbz', 'Other', 'cbz', None, 8, 0, 0, 0),
        ],
    )

    candidates = _fetch_lazy_scan_candidates(
        connection.cursor(),
        no_cover_retry_days=7,
        library_id=7,
        include_all_library_books=True,
    )

    # 실제 파일이 남아 있는 커버는 뒤 단계의 물리 점검에서 제외되고, NO_COVER의
    # 7일 재시도 대기나 stale 경로는 라이브러리 수동 실행에서 후보에 포함된다.
    assert [book['id'] for book in candidates] == [1, 2, 3]


def test_series_lazy_scan_fetches_every_volume_in_only_that_library():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.execute("""
        CREATE TABLE books (
            id INTEGER,
            file_path TEXT,
            series_name TEXT,
            file_format TEXT,
            cover_image TEXT,
            library_id INTEGER,
            total_pages INTEGER,
            has_offsets INTEGER,
            metadata_locked INTEGER
        )
    """)
    connection.executemany(
        'INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
        [
            (1, '/books/boruto-01.cbz', 'Boruto', 'cbz', '2/volume-01.webp', 2, 180, 1, 0),
            (2, '/books/boruto-02.cbz', 'Boruto', 'cbz', 'NO_COVER', 2, 0, 0, 0),
            (3, '/other-library/boruto-03.cbz', 'Boruto', 'cbz', None, 3, 0, 0, 0),
            (4, '/books/other-01.cbz', 'Other Series', 'cbz', None, 2, 0, 0, 0),
        ],
    )

    books = _fetch_lazy_scan_series_books(connection.cursor(), 2, 'Boruto')

    # 1권의 정상 커버 여부로 2권이 시리즈 조회에서 누락되지 않아야 한다.
    assert [book['id'] for book in books] == [1, 2]
