"""Scanner regressions using disposable SQLite and connection-local MariaDB tables."""
import contextlib
import datetime
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from tools.scanner import engine, sync_detector
from tools.scanner import db_writer_sqlite, db_writer_mariadb


class ScannerReliabilityTests(unittest.TestCase):
    maria = False

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.book = str(self.root / 'book.epub')
        Path(self.book).touch()
        if self.maria:
            import database
            self.conn = database.get_connection('general')
        else:
            self.conn = sqlite3.connect(':memory:', check_same_thread=False)
            self.conn.row_factory = sqlite3.Row
        self.addCleanup(self.conn.close)
        self.cur = self.conn.cursor()
        prefix = 'CREATE TEMPORARY TABLE' if self.maria else 'CREATE TABLE'
        text_columns = '''title metadata_title series_name author isbn file_format cover_image
            banner_image publisher link summary release_date genre tags books_lv publication_status
            cover_artist translator teams locations characters localized_series document_series_name
            cover_updated_at banner_updated_at deleted_at'''.split()
        numeric_columns = '''library_id total_pages score document_volume_index document_number
            document_volume_count file_mtime file_size is_deleted metadata_locked metadata_title_checked
            embedded_metadata_version has_offsets'''.split()
        columns = ['id INTEGER PRIMARY KEY ' + ('AUTO_INCREMENT' if self.maria else 'AUTOINCREMENT'),
                   'file_path VARCHAR(700) UNIQUE']
        columns += [f'{c} TEXT' for c in text_columns]
        columns += [f'{c} REAL DEFAULT 0' for c in numeric_columns]
        schemas = {
            'books': ','.join(columns),
            'libraries': 'id INTEGER PRIMARY KEY, name TEXT, use_folder_cover INTEGER, scan_status TEXT, last_scanned_at TEXT',
            'settings': '`key` VARCHAR(255), `value` TEXT',
            'folder_mtimes': 'folder_path VARCHAR(700) PRIMARY KEY, dir_mtime REAL, meta_mtime REAL',
            'scanner_progress': 'library_id VARCHAR(20), folder_path VARCHAR(700)',
        }
        for table in ('user_progress', 'user_reading_log', 'book_offsets', 'user_favorites',
                      'book_annotations', 'epub_bookmarks', 'collection_items', 'tts_progress'):
            schemas[table] = 'book_id INTEGER'
        for name, schema in schemas.items():
            self.cur.execute(f'{prefix} {name} ({schema})')
            if self.maria:
                self.addCleanup(self.cur.execute, f'DROP TEMPORARY TABLE IF EXISTS {name}')
        self.cur.execute("INSERT INTO libraries(id,name,use_folder_cover) VALUES(1,'test',0)")
        self.add_book(1, self.book)
        self.conn.commit()
        self.stack.enter_context(patch.object(sync_detector, '_is_mariadb_mode', return_value=self.maria))
        writer = db_writer_mariadb if self.maria else db_writer_sqlite
        for name in ('bulk_insert_books', 'bulk_update_books', 'bulk_update_book_covers',
                     'clear_book_banners', 'bulk_save_book_offsets'):
            self.stack.enter_context(patch.object(engine, name, getattr(writer, name)))
        self.stack.enter_context(patch.object(engine, 'DB_DIR', str(self.root)))
        self.stack.enter_context(patch.object(engine, '_dispatch_scan_completed_to_plugin_hooks'))
        self.stack.enter_context(patch.object(engine, '_dispatch_new_books_to_plugin_hooks'))
        self.stack.enter_context(patch.object(engine.database, 'get_pool_stats', return_value={}))
        self.problems = self.stack.enter_context(patch.object(engine, '_record_scan_problems'))
        self.gate = self.stack.enter_context(patch('services.scan_problem_service.gate_deletions', return_value=(True, None, set())))
        self.stack.enter_context(patch('utils.redis_helper.redis_acquire_lock', return_value='test'))
        self.stack.enter_context(patch('utils.redis_helper.redis_release_lock'))
        self.stack.enter_context(patch('utils.report_helper.save_scan_report', return_value='test-report'))
        self.stack.enter_context(patch('services.cover_storage_service.get_covers_dir', return_value=str(self.root)))
        self.stack.enter_context(patch.dict(os.environ, {'SCAN_JSONL_REMOVE': 'true'}))

    def add_book(self, book_id, path, library_id=1, deleted=0, timestamp=None):
        self.cur.execute('INSERT INTO books(id,file_path,library_id,is_deleted,deleted_at) VALUES(?,?,?,?,?)',
                         (book_id, path, library_id, deleted, timestamp))

    def row(self, book_id=1):
        self.cur.execute('SELECT * FROM books WHERE id=?', (book_id,))
        row = self.cur.fetchone()
        return dict(row) if row else None

    def scan(self, mutate=None, partial=False, cover_only=False, allow_missing=True, result_count=1):
        meta = dict(title='Embedded title', translator='Translator', author='Author',
                    localized_series='Localized', document_series_name='Document series',
                    document_volume_index=2, document_number=3, document_volume_count=4,
                    cover_artist='Artist', teams='Team', locations='Place', characters='Character')
        def folder(*args, **kwargs):
            if mutate:
                mutate()
            return dict(merged_meta=meta, results=[dict(
                full_path=self.book, filename='book.epub', file_format='epub', series_name='Series',
                title='Display title', cover_image='cover.jpg', offsets_data=[], skip=False,
                folder_cover_only=cover_only, merged_meta=meta)] * result_count)
        connection = self.conn
        class Borrowed:
            def cursor(self): return connection.cursor()
            def commit(self): return connection.commit()
            def rollback(self): return connection.rollback()
            def close(self): pass
        self.errors = []
        self.summary = {}
        with patch.object(engine, 'process_folder_task', side_effect=folder):
            engine._scan_library_internal(
                Borrowed(), 'test.db', 1, str(self.root), False, 'general', [str(self.root)],
                False, 1, self.errors, path_scope=str(self.root) if partial else None,
                allow_missing=allow_missing, moves_reconciled=True, result_summary=self.summary)

    def remove_book(self):
        self.cur.execute('DELETE FROM books WHERE id=1')
        self.conn.commit()

    def test_stale_update_recovers_all_custom_metadata(self):
        self.scan(mutate=self.remove_book, partial=True)
        self.cur.execute('SELECT * FROM books WHERE file_path=?', (self.book,))
        row = dict(self.cur.fetchone())
        for key, expected in dict(translator='Translator', metadata_title='Embedded title',
                                  localized_series='Localized', document_series_name='Document series',
                                  document_volume_index=2, document_number=3, document_volume_count=4,
                                  cover_artist='Artist', teams='Team', locations='Place', characters='Character').items():
            self.assertEqual(row[key], expected, key)
        self.assertEqual(self.summary['errors'], 0)

    def test_silent_update_loss_is_retried_after_commit(self):
        with patch.object(engine, 'bulk_update_books', side_effect=lambda *a, **kw: self.remove_book()):
            self.scan(partial=True)
        self.cur.execute('SELECT translator FROM books WHERE file_path=?', (self.book,))
        self.assertEqual(self.cur.fetchone()['translator'], 'Translator')

    def test_unpersisted_partial_scan_raises_and_records(self):
        with patch.object(engine, 'bulk_insert_books'):
            with self.assertRaisesRegex(RuntimeError, 'registration failed'):
                self.scan(mutate=self.remove_book, partial=True)
        self.assertEqual(self.errors[0]['error_type'], 'DBWriteInvariantError')
        self.problems.assert_called_once()

    def test_unpersisted_full_scan_reports_error(self):
        with patch.object(engine, 'bulk_insert_books'):
            self.scan(mutate=self.remove_book)
        self.assertEqual(self.summary['errors'], 1)

    def test_missing_cover_only_target_is_not_sparse_insert(self):
        with self.assertRaisesRegex(RuntimeError, 'registration failed'):
            self.scan(mutate=self.remove_book, partial=True, cover_only=True)
        self.assertIsNone(self.row())

    def test_existing_cover_only_keeps_metadata(self):
        self.cur.execute("UPDATE books SET translator='Keep', metadata_title='Keep title'")
        self.scan(cover_only=True, partial=True)
        self.assertEqual(self.row()['translator'], 'Keep')
        self.assertEqual(self.row()['metadata_title'], 'Keep title')
        self.assertEqual(self.row()['metadata_title_checked'], 0)

    def test_category_move_is_not_reclaimed(self):
        def move():
            self.cur.execute('UPDATE books SET library_id=2 WHERE id=1')
            self.conn.commit()
        error = None
        try:
            self.scan(mutate=move, partial=True)
        except RuntimeError as exc:
            error = exc
        self.assertEqual(self.row()['library_id'], 2)
        self.assertIsNotNone(error)
        self.assertIn('registration failed', str(error))

    def test_allow_missing_false_bypasses_gate(self):
        self.scan(partial=True, allow_missing=False)
        self.gate.assert_not_called()
        self.assertEqual(self.problems.call_args.kwargs['scope_paths'], [str(self.root)])

    def test_gate_holds_missing_books_but_restores_found_books(self):
        missing = str(self.root / 'missing.txt')
        self.add_book(2, missing)
        self.cur.execute("UPDATE books SET is_deleted=1,deleted_at='2000-01-01' WHERE id=1")
        self.gate.return_value = (False, 'mass', {missing})
        self.scan(partial=True)
        self.assertEqual(self.row(2)['is_deleted'], 0)
        self.assertEqual(self.row()['is_deleted'], 0)
        self.assertIsNone(self.row()['deleted_at'])
        self.assertEqual(self.problems.call_args.kwargs['trashed_paths'], set())
        self.assertEqual(self.problems.call_args.kwargs['held'], 'root')

    def test_flush_refreshes_snapshot_before_existence_query(self):
        commits = []
        inspected = []
        original_lookup = engine._existing_book_ids
        original_commit = engine._commit_with_retry
        def committed(conn, label, **kwargs):
            commits.append(label)
            return original_commit(conn, label, **kwargs)
        def lookup(cursor, library_id, paths, **kwargs):
            if self.maria and kwargs.get('lock') and not inspected:
                inspected.append(True)
                cursor.execute('SELECT @@in_transaction AS active')
                # The first lookup in a flush follows an explicit commit.
                if 'flush-pending' not in commits:
                    self.assertEqual(cursor.fetchone()['active'], 0)
            return original_lookup(cursor, library_id, paths, **kwargs)
        with patch.object(engine, '_existing_book_ids', side_effect=lookup), \
             patch.object(engine, '_commit_with_retry', side_effect=committed):
            self.scan(partial=True)
        self.assertIn('flush-pending', commits)

    def test_commit_failure_cannot_report_success(self):
        original = engine._commit_with_retry
        def commit(conn, label, **kwargs):
            if label == 'flush-pending':
                return False
            return original(conn, label, **kwargs)
        with patch.object(engine, '_commit_with_retry', side_effect=commit):
            with self.assertRaisesRegex(RuntimeError, 'final flush failed'):
                self.scan(partial=True)

    def test_nonfinal_failed_batch_is_reported(self):
        with patch.object(engine, 'bulk_update_books', side_effect=ValueError('invalid metadata')):
            self.scan(result_count=100)
        self.assertEqual({e['error_type'] for e in self.errors}, {'DBWriteError'})
        self.assertEqual(self.summary['errors'], 100)
        self.assertEqual(self.problems.call_args.kwargs['processed_paths'], {str(self.root)})

    def test_metadata_update_clears_restored_trash_timestamp(self):
        self.cur.execute("UPDATE books SET is_deleted=1,deleted_at='2000-01-01' WHERE id=1")
        self.scan(partial=True)
        self.assertEqual(self.row()['is_deleted'], 0)
        self.assertIsNone(self.row()['deleted_at'])

    def test_partial_scope_does_not_purge_unrelated_trash(self):
        self.add_book(2, '/outside-scope', deleted=1, timestamp='2000-01-01')
        sync_detector.handle_deleted_books(self.cur, {self.book: 1}, {self.book}, [], {'/other'})
        self.assertIsNotNone(self.row(2))

    def test_trash_age_preserved_and_stale_path_guarded(self):
        recent = (datetime.datetime.now() - datetime.timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S')
        self.cur.execute('UPDATE books SET is_deleted=1, deleted_at=? WHERE id=1', (recent,))
        sync_detector.handle_deleted_books(self.cur, {self.book: 1}, {self.book}, [], {'/other'})
        self.assertEqual(str(self.row()['deleted_at']), recent)
        self.cur.execute("UPDATE books SET file_path='/moved',is_deleted=0,deleted_at=NULL WHERE id=1")
        sync_detector.handle_deleted_books(self.cur, {self.book: 1}, {self.book}, [], {'/other'})
        self.assertEqual(self.row()['is_deleted'], 0)

    def test_reappeared_old_trash_restores_and_outside_scope_survives(self):
        old = '2000-01-01 00:00:00'
        self.cur.execute('UPDATE books SET is_deleted=1, deleted_at=? WHERE id=1', (old,))
        self.add_book(2, '/outside-scope', deleted=1, timestamp=old)
        sync_detector.handle_deleted_books(self.cur, {self.book: 1}, {self.book}, [], {'/other'})
        self.assertEqual(self.row()['is_deleted'], 0)
        self.assertIsNone(self.row()['deleted_at'])
        self.assertIsNotNone(self.row(2))

    def test_reappeared_found_path_restores_even_when_missing_disallowed(self):
        self.cur.execute("UPDATE books SET is_deleted=1, deleted_at='2000-01-01' WHERE id=1")
        sync_detector.handle_deleted_books(self.cur, {self.book: 1}, set(), [], {self.book}, allow_missing=False)
        self.assertEqual(self.row()['is_deleted'], 0)
        self.assertIsNone(self.row()['deleted_at'])


class ScannerProblemContractTests(unittest.TestCase):
    def test_record_and_scoped_reconcile_contract(self):
        from unittest.mock import Mock
        from services import scan_problem_service as service
        cursor = Mock()
        conn = Mock()
        conn.cursor.return_value = cursor
        for held in (None, 'root', 'incomplete'):
            with self.subTest(held=held), \
                 patch.object(engine.database, 'connection', return_value=contextlib.nullcontext(conn)), \
                 patch.object(service, 'record_trashed') as trashed, \
                 patch.object(service, 'record_scan_errors', return_value={'/scope/bad'}) as errors, \
                 patch.object(service, 'reconcile') as reconcile:
                engine._record_scan_problems(
                    'general', 1, library_errors=[{'file_path': '/scope/bad'}],
                    trashed_paths={'/scope/gone'}, db_books={'/scope/gone': 2},
                    found_file_paths={'/scope/good'}, processed_paths={'/scope/good'},
                    scope_paths=['/scope'], held=held)
                trashed.assert_called_once_with(cursor, 'general', 1, {'/scope/gone'}, {'/scope/gone': 2})
                errors.assert_called_once()
                if held == 'incomplete':
                    reconcile.assert_not_called()
                else:
                    reconcile.assert_called_once_with(
                        cursor, 'general', 1, found_file_paths={'/scope/good'}, processed_paths={'/scope/good'},
                        error_paths={'/scope/bad'}, scope_paths=['/scope'], held=held)

    def test_report_is_not_saved_twice(self):
        from tools.scanner.core import _save_report_unless_saved
        with patch('utils.report_helper.save_scan_report', return_value='report') as save:
            summary = {}
            errors = [{'file_path': '/bad'}]
            _save_report_unless_saved(1, errors, summary)
            _save_report_unless_saved(1, errors, summary)
            save.assert_called_once()
            self.assertEqual(summary, {'errors': 1, 'report_file': 'report'})


@unittest.skipUnless(os.getenv('BOOKOASIS_TEST_MARIADB') == '1', 'requires MariaDB temporary-table connection')
class MariaDBScannerReliabilityTests(ScannerReliabilityTests):
    maria = True


if __name__ == '__main__':
    unittest.main()
