import sqlite3

from repositories.sqlite import reading_progress_repository as repository_module


def _make_recent_books_db():
    connection = sqlite3.connect(':memory:')
    connection.row_factory = sqlite3.Row
    connection.executescript("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            library_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            title_alias TEXT,
            series_name TEXT,
            series_alias TEXT,
            cover_image TEXT,
            cover_updated_at TEXT,
            file_format TEXT,
            total_pages INTEGER,
            created_at TEXT NOT NULL,
            metadata_locked INTEGER DEFAULT 0,
            is_deleted INTEGER DEFAULT 0
        );
        CREATE TABLE user_favorites (
            user_id INTEGER NOT NULL,
            book_id INTEGER NOT NULL,
            PRIMARY KEY (user_id, book_id)
        );
        CREATE TABLE user_category_permissions (
            user_id INTEGER NOT NULL,
            library_id INTEGER NOT NULL,
            has_access INTEGER NOT NULL
        );
    """)
    return connection


def _insert_book(connection, book_id, library_id, title, series_name, created_at):
    connection.execute("""
        INSERT INTO books (
            id, library_id, title, title_alias, series_name, series_alias,
            cover_image, cover_updated_at, file_format, total_pages, created_at,
            metadata_locked, is_deleted
        ) VALUES (?, ?, ?, '', ?, '', 'cover.webp', NULL, 'cbz', 100, ?, 0, 0)
    """, (book_id, library_id, title, series_name, created_at))


def test_recently_added_uses_latest_added_volume_per_library(monkeypatch):
    connection = _make_recent_books_db()
    # ID 순서와 추가 시각이 다른 경우에도 최신 추가 권을 골라야 한다.
    _insert_book(connection, 50, 1, 'Series Vol 1', 'Series', '2026-09-16 12:00:00')
    _insert_book(connection, 10, 1, 'Series Vol 2', 'Series', '2026-09-17 12:00:00')
    # 같은 시리즈명이 다른 라이브러리에 있으면 별도 항목으로 유지한다.
    _insert_book(connection, 5, 2, 'Series Copy', 'Series', '2026-09-17 13:00:00')
    _insert_book(connection, 6, 1, 'Standalone', None, '2026-09-17 11:00:00')
    monkeypatch.setattr(repository_module.database, 'get_connection', lambda _db_type, **_kwargs: connection)

    rows = repository_module.ReadingProgressRepository.fetch_recently_added_all('general', user_id=1)

    assert {(row['library_id'], row['id']) for row in rows} == {(1, 10), (2, 5), (1, 6)}


def test_recently_added_user_filter_does_not_hide_accessible_same_named_series(monkeypatch):
    connection = _make_recent_books_db()
    _insert_book(connection, 10, 1, 'Accessible Series', 'Shared Name', '2026-09-16 12:00:00')
    _insert_book(connection, 20, 2, 'Restricted Series', 'Shared Name', '2026-09-17 12:00:00')
    connection.execute(
        'INSERT INTO user_category_permissions (user_id, library_id, has_access) VALUES (7, 1, 1)'
    )
    monkeypatch.setattr(repository_module.database, 'get_connection', lambda _db_type, **_kwargs: connection)

    rows = repository_module.ReadingProgressRepository.fetch_recently_added_by_user('general', user_id=7)

    assert [row['id'] for row in rows] == [10]
