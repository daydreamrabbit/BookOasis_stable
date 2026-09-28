import sqlite3
from unittest.mock import patch

from repositories.sqlite.reading_progress_repository import ReadingProgressRepository
from services.reading_progress_service import ReadingProgressService


def test_get_book_ids_by_series_is_read_only_and_scoped(tmp_path, monkeypatch):
    db_path = tmp_path / "progress.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            series_name TEXT,
            library_id INTEGER,
            is_deleted INTEGER DEFAULT 0
        );
        INSERT INTO books (id, series_name, library_id) VALUES
            (1, 'Target', 10),
            (2, 'Target', 10),
            (3, 'Other', 10),
            (4, 'Target', 10);
        UPDATE books SET is_deleted = 1 WHERE id = 4;
        """
    )
    conn.commit()
    conn.close()

    def get_connection(_db_type):
        connection = sqlite3.connect(db_path)
        connection.row_factory = sqlite3.Row
        return connection

    monkeypatch.setattr(
        "repositories.sqlite.reading_progress_repository.database.connection",
        lambda _db_type: get_connection(_db_type),
    )

    book_ids = ReadingProgressRepository.get_book_ids_by_series("general", "Target", 10)

    assert book_ids == [1, 2]

    # 읽기 전용이어야 하므로 books 테이블이 그대로 남아있는지 확인
    conn = get_connection("general")
    remaining = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    conn.close()
    assert remaining == 4


def test_mark_read_book_scope_uses_single_book_id():
    with patch.object(
        ReadingProgressService, 'mark_books_completed', return_value=1
    ) as mark_completed:
        affected = ReadingProgressService.mark_read('general', 5, user_id=7)

    assert affected == 1
    mark_completed.assert_called_once_with('general', [5], user_id=7)


def test_mark_read_series_scope_resolves_book_ids_first():
    with patch.object(
        ReadingProgressRepository, 'get_book_ids_by_series', return_value=[1, 2, 3]
    ) as resolve_ids, patch.object(
        ReadingProgressService, 'mark_books_completed', return_value=3
    ) as mark_completed:
        affected = ReadingProgressService.mark_read(
            'general', 1, user_id=7, series_name='Target', library_id=10
        )

    assert affected == 3
    resolve_ids.assert_called_once_with('general', 'Target', 10)
    mark_completed.assert_called_once_with('general', [1, 2, 3], user_id=7)


def test_mark_read_audiobook_loops_mark_audiobook_completed():
    with patch.object(
        ReadingProgressRepository, 'get_book_ids_by_series', return_value=[11, 12]
    ), patch.object(
        ReadingProgressService, 'mark_audiobook_completed', side_effect=[1, 1]
    ) as mark_audiobook:
        affected = ReadingProgressService.mark_read(
            'audiobook', 11, user_id=7, series_name='Target', library_id=10
        )

    assert affected == 2
    assert mark_audiobook.call_count == 2
    mark_audiobook.assert_any_call(11, user_id=7, track_ids=[])
    mark_audiobook.assert_any_call(12, user_id=7, track_ids=[])
