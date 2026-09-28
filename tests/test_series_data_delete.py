import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

# 호스트의 최소 테스트 환경에는 선택 의존성 redis가 없을 수 있다. 이 테스트에서는
# Redis 호출을 모두 mock하므로 import 시 필요한 모듈 이름만 제공한다.
sys.modules.setdefault('redis', types.SimpleNamespace())

from repositories.series_delete_repository_shared import delete_series_by_anchor
from services.series_delete_service import SeriesDeleteService


DEPENDENT_TABLES = (
    'user_progress', 'user_reading_log', 'user_favorites', 'book_offsets',
    'book_annotations', 'epub_bookmarks', 'collection_items', 'gdrive_book_copies',
)


def _connection_factory(db_path):
    def get_connection(_db_type):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        return conn
    return get_connection


class SeriesDataDeleteTests(unittest.TestCase):
    def test_delete_is_scoped_and_preserves_sources_and_shared_media(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            db_path = temp_path / 'series-delete.db'
            source_dir = temp_path / 'source' / 'Target'
            source_dir.mkdir(parents=True)
            first_source = source_dir / 'Target 01.cbz'
            second_source = source_dir / 'Target 02.cbz'
            first_source.write_bytes(b'first-source')
            second_source.write_bytes(b'second-source')

            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY, library_id INTEGER, title TEXT, series_name TEXT,
                    file_path TEXT, cover_image TEXT, banner_image TEXT, is_deleted INTEGER DEFAULT 0
                );
                CREATE TABLE user_progress (book_id INTEGER);
                CREATE TABLE user_reading_log (book_id INTEGER);
                CREATE TABLE user_favorites (book_id INTEGER);
                CREATE TABLE book_offsets (book_id INTEGER);
                CREATE TABLE book_annotations (book_id INTEGER);
                CREATE TABLE epub_bookmarks (book_id INTEGER);
                CREATE TABLE collection_items (book_id INTEGER);
                CREATE TABLE gdrive_book_copies (book_id INTEGER);
                CREATE TABLE folder_mtimes (folder_path TEXT PRIMARY KEY);
                CREATE TABLE series_summary (library_id INTEGER, series_key TEXT);
                CREATE TABLE collections (cover_image TEXT);
                """
            )
            conn.executemany(
                'INSERT INTO books VALUES (?, ?, ?, ?, ?, ?, ?, 0)',
                [
                    (1, 10, 'Target 01', 'Target', str(first_source), '10/shared.webp', '10/banner.webp'),
                    (2, 10, 'Target 02', 'Target', str(second_source), '10/orphan.webp', None),
                    (3, 10, 'Other', 'Other', '/source/Other.cbz', '10/shared.webp', None),
                    (4, 20, 'Target 01', 'Target', '/other-library/Target.cbz', '20/target.webp', None),
                ],
            )
            for table in DEPENDENT_TABLES:
                conn.executemany(f'INSERT INTO {table} (book_id) VALUES (?)', [(1,), (2,), (3,), (4,)])
            conn.executemany(
                'INSERT INTO folder_mtimes (folder_path) VALUES (?)',
                [(str(source_dir),), ('/source',), ('/other-library',)],
            )
            conn.executemany(
                'INSERT INTO series_summary VALUES (?, ?)',
                [(10, 'Target'), (10, 'Other'), (20, 'Target')],
            )
            conn.commit()
            conn.close()

            get_connection = _connection_factory(db_path)
            with patch(
                'repositories.series_delete_repository_shared.database.get_connection',
                side_effect=get_connection,
            ):
                result = delete_series_by_anchor('general', 1, 10, '?')

            self.assertEqual(result['deleted_count'], 2)
            self.assertEqual(result['series_name'], 'Target')
            self.assertEqual(set(result['unreferenced_media']), {'10/banner.webp', '10/orphan.webp'})
            self.assertEqual(first_source.read_bytes(), b'first-source')
            self.assertEqual(second_source.read_bytes(), b'second-source')

            conn = get_connection('general')
            self.assertEqual([row['id'] for row in conn.execute('SELECT id FROM books ORDER BY id')], [3, 4])
            for table in DEPENDENT_TABLES:
                self.assertEqual(
                    [row['book_id'] for row in conn.execute(f'SELECT book_id FROM {table} ORDER BY book_id')],
                    [3, 4],
                )
            self.assertEqual(
                [tuple(row) for row in conn.execute(
                    'SELECT library_id, series_key FROM series_summary ORDER BY library_id, series_key'
                )],
                [(10, 'Other'), (20, 'Target')],
            )
            self.assertEqual(
                [row['folder_path'] for row in conn.execute(
                    'SELECT folder_path FROM folder_mtimes ORDER BY folder_path'
                )],
                ['/other-library', '/source'],
            )
            conn.close()

    def test_service_removes_only_files_inside_cover_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            covers_root = temp_path / 'covers'
            inside = covers_root / '10' / 'cover.webp'
            outside = temp_path / 'outside.webp'
            inside.parent.mkdir(parents=True)
            inside.write_bytes(b'cover')
            outside.write_bytes(b'original')

            repository_result = {
                'library_id': 10,
                'series_name': 'Target',
                'deleted_count': 2,
                'unreferenced_media': ['10/cover.webp', '../outside.webp'],
            }
            with patch('services.series_delete_service.get_covers_dir', return_value=str(covers_root)), \
                 patch('services.series_delete_service.redis_acquire_lock', return_value='lock-token'), \
                 patch('services.series_delete_service.redis_release_lock'), \
                 patch(
                     'services.series_delete_service.SeriesDeleteRepository.delete_series_by_anchor',
                     return_value=repository_result,
                 ), \
                 patch('services.series_delete_service.SeriesService.invalidate_all_books_cache'), \
                 patch('services.series_delete_service.redis_delete_pattern'):
                result = SeriesDeleteService.delete_series_data('general', 1, 10)

            self.assertFalse(inside.exists())
            self.assertEqual(outside.read_bytes(), b'original')
            self.assertEqual(result['deleted_media_count'], 1)
            self.assertEqual(len(result['warnings']), 1)


if __name__ == '__main__':
    unittest.main()
