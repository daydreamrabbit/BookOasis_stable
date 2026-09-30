import os
import sqlite3
import tempfile
import types
import unittest
from unittest.mock import patch

from repositories import recent_additions
from repositories.sqlite.series_repository import SeriesRepository
from services import series_service
from services.series_service import SeriesService


class RecentBadgeTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.path = os.path.join(directory.name, 'books.db')
        conn = self.connect()
        conn.executescript('''
            CREATE TABLE books (id INTEGER PRIMARY KEY, library_id INTEGER,
              series_name TEXT, title TEXT, file_path TEXT, file_format TEXT,
              is_deleted INTEGER DEFAULT 0, created_at TEXT, cover_image TEXT);
            CREATE INDEX idx_books_series_lib_title ON books(series_name, library_id, title);
            CREATE INDEX idx_books_library_id ON books(library_id);
            CREATE TABLE series_summary(library_id INTEGER, series_key TEXT,
              representative_book_id INTEGER, series_book_count INTEGER,
              sort_series_name TEXT, latest_added TEXT NOT NULL);
            CREATE TABLE series_summary_state(id INTEGER PRIMARY KEY, is_ready INTEGER, refreshed_at TEXT);
        ''')
        conn.executemany("INSERT INTO books VALUES(?,1,'old','old',?,'zip',0,datetime('now','-30 days'),NULL)",
                         [(i, f'/old/{i}.zip') for i in range(1, 31)])
        conn.commit()
        conn.close()
        for p in (
            patch.object(recent_additions.database, 'get_connection', side_effect=self.connect),
            patch.object(recent_additions.database, 'is_mariadb_mode', return_value=False),
            patch.object(series_service, '_sync_local_books_cache_with_shared_epoch'),
        ):
            p.start()
            self.addCleanup(p.stop)
        series_service._RECENT_ADDED_CACHE.clear()
        self.addCleanup(series_service._RECENT_ADDED_CACHE.clear)

    def connect(self, _type=None):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        return conn

    def add(self, ident, name='story', path='/story/1.zip', days=1, library=1, deleted=0, fmt='zip'):
        conn = self.connect()
        conn.execute("INSERT INTO books VALUES(?,?,?,'title',?,?,?,datetime('now',?),NULL)",
                     (ident, library, name, path, fmt, deleted, f'-{days} days' if days is not None else None))
        conn.commit()
        conn.close()

    def annotate(self, *ids, db_type='general'):
        return SeriesService.annotate_recent_additions(db_type, [
            {'representative_book_id': i, 'book_count': 1} for i in ids])

    def test_new_added_old_and_original_entry_unchanged(self):
        self.add(100, days=30)
        self.add(101, path='/story/2.zip')
        self.add(102, path='/story/3.zip')
        self.add(103, name='new', path='/new/1.zip')
        original = [{'representative_book_id': 100}]
        added = SeriesService.annotate_recent_additions('general', original)[0]
        self.assertEqual(added['recent_added_count'], 2)
        self.assertFalse(added['is_new_series'])
        self.assertNotIn('recent_added_count', original[0])
        self.assertTrue(self.annotate(103)[0]['is_new_series'])
        self.assertNotIn('recent_added_count', self.annotate(1)[0])

    def test_dashboard_id_and_history_book_id(self):
        self.add(100)
        for entry in ({'id': 100}, {'book_id': 100}, {'id': 1, 'book_id': 100}):
            result = SeriesService.annotate_recent_additions('general', [entry])[0]
            self.assertEqual(result['recent_added_count'], 1)
            self.assertTrue(result['is_new_series'])
            self.assertNotIn('recent_added_count', entry)

    def test_same_name_different_folder_and_library_do_not_mix(self):
        self.add(100, days=30)
        self.add(101, path='/story/2.zip')
        self.add(102, path='/different/1.zip', days=30)
        self.add(103, path='/story/3.zip', library=2)
        first, second = self.annotate(100, 102)
        self.assertEqual(first['recent_added_count'], 1)
        self.assertNotIn('recent_added_count', second)

    def test_blank_names_and_literal_fallback_keep_folder_identity(self):
        self.add(100, name='', path='/blank/old.zip', days=30)
        self.add(101, name=None, path='/blank/new.zip')
        self.add(102, name='기타 단행본', path='/literal/old.zip', days=30)
        first, second = self.annotate(100, 102)
        self.assertEqual(first['recent_added_count'], 1)
        self.assertNotIn('recent_added_count', second)

    def test_imgdir_chapters_group_under_series_parent(self):
        self.add(100, path='/images/01/__folder__.imgdir', days=30, fmt='imgdir')
        self.add(101, path='/images/02/__folder__.imgdir', fmt='imgdir')
        entry = self.annotate(100)[0]
        self.assertEqual(entry['recent_added_count'], 1)
        self.assertFalse(entry['is_new_series'])

    def test_deleted_volumes_excluded_but_new_library_has_badges(self):
        self.add(100, days=30)
        self.add(101, deleted=1)
        self.add(102, name='import', library=2)
        entries = self.annotate(100, 101, 102)
        self.assertTrue(all('recent_added_count' not in e for e in entries[:2]))
        self.assertTrue(entries[2]['is_new_series'])

    def test_recent_favorite_in_existing_series_is_not_new(self):
        self.add(100, days=30)
        self.add(101, path='/story/2.zip')
        self.assertFalse(self.annotate(101)[0]['is_new_series'])

    def test_null_date_is_old_without_rewriting_it(self):
        self.add(100, days=None)
        self.add(101, path='/story/2.zip')
        self.assertFalse(self.annotate(101)[0]['is_new_series'])
        conn = self.connect()
        self.assertIsNone(conn.execute('SELECT created_at FROM books WHERE id=100').fetchone()[0])
        conn.close()

    def test_both_book_types_and_non_book_types(self):
        self.add(100)
        self.assertTrue(self.annotate(100, db_type='adult')[0]['is_new_series'])
        for kind in ('audiobook', 'video'):
            self.assertNotIn('recent_added_count', self.annotate(100, db_type=kind)[0])
        author = [{'is_author_group': True, 'representative_book_id': 100}]
        self.assertEqual(SeriesService.annotate_recent_additions('general', author), author)

    def test_cache_invalidation_recounts_new_volumes(self):
        self.add(100, days=30)
        self.assertNotIn('recent_added_count', self.annotate(100)[0])
        self.add(101, path='/story/2.zip')
        self.assertNotIn('recent_added_count', self.annotate(100)[0])
        with patch.dict('sys.modules', {'utils.redis_helper': types.SimpleNamespace(redis_delete_pattern=lambda *_: None)}):
            SeriesService.invalidate_all_books_cache()
        self.assertEqual(self.annotate(100)[0]['recent_added_count'], 1)

    def test_summary_rebuild_survives_missing_created_at(self):
        self.add(100, days=None)
        self.assertTrue(SeriesRepository.rebuild_summary('general'))
        conn = self.connect()
        self.assertEqual(conn.execute("SELECT latest_added FROM series_summary WHERE series_key='story'").fetchone()[0], '')
        conn.close()


if __name__ == '__main__':
    unittest.main()
