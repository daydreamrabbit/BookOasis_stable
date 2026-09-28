import unittest
import types
import datetime
import json
import sqlite3
from unittest.mock import Mock, patch

from services.scanner_queue import (
    ScannerQueue,
    _is_recent_scan_finished_at,
    _process_batch_book_scan,
)
from repositories.sqlite.scanner_queue_repository import ScannerQueueRepository as SqliteScannerQueueRepository


class BatchBookScanProgressTests(unittest.TestCase):
    def test_pdf_and_remote_epub_are_processed_in_one_isolated_batch(self):
        queue = Mock()
        books = {
            101: {
                'id': 101, 'title': 'PDF 도서', 'file_path': '/books/a.pdf',
                'file_format': 'pdf', 'library_is_remote': 0,
            },
            202: {
                'id': 202, 'title': '원격 EPUB', 'file_path': '/rclone/b.epub',
                'file_format': 'epub', 'library_is_remote': 1,
            },
            303: {
                'id': 303, 'title': 'CBZ 도서', 'file_path': '/books/c.cbz',
                'file_format': 'cbz', 'library_is_remote': 0,
            },
        }
        lookup = Mock(side_effect=lambda _db_type, book_id: books[book_id])
        scan_single = Mock(return_value=(True, '완료', None))
        scan_documents = Mock(return_value=(True, '완료', {101: '1/a.webp', 202: '1/b.webp'}))
        update_stage = Mock()
        book_repository_module = types.ModuleType('repositories.book_scan_repository')
        book_repository_module.BookScanRepository = types.SimpleNamespace(
            get_book_basic_info_raw=lookup
        )
        book_scan_module = types.ModuleType('services.book_scan_service')
        book_scan_module.BookScanService = types.SimpleNamespace(
            scan_single_book=scan_single,
            scan_document_books=scan_documents,
        )
        queue_repository_module = types.ModuleType('repositories.scanner_queue_repository')
        queue_repository_module.ScannerQueueRepository = types.SimpleNamespace(
            update_task_stage=update_stage
        )

        with patch.dict('sys.modules', {
            'repositories.book_scan_repository': book_repository_module,
            'services.book_scan_service': book_scan_module,
            'repositories.scanner_queue_repository': queue_repository_module,
        }):
            _process_batch_book_scan(
                queue,
                task_id=14,
                db_type='general',
                book_ids=[101, 202, 303],
            )

        scan_documents.assert_called_once_with('general', [101, 202], task_id=14)
        scan_single.assert_called_once_with('general', 303)
        self.assertIn('성공 3/3, 실패 0', update_stage.call_args_list[-1].args[1])

    def test_worker_reports_current_book_and_completion_count(self):
        queue = Mock()
        lookup = Mock(side_effect=[{'title': '첫 번째 책'}, {'title': '두 번째 책'}])
        scan = Mock(return_value=(True, '완료', None))
        update_stage = Mock()
        book_repository_module = types.ModuleType('repositories.book_scan_repository')
        book_repository_module.BookScanRepository = types.SimpleNamespace(
            get_book_basic_info_raw=lookup
        )
        book_scan_module = types.ModuleType('services.book_scan_service')
        book_scan_module.BookScanService = types.SimpleNamespace(scan_single_book=scan)
        queue_repository_module = types.ModuleType('repositories.scanner_queue_repository')
        queue_repository_module.ScannerQueueRepository = types.SimpleNamespace(
            update_task_stage=update_stage
        )

        with patch.dict('sys.modules', {
            'repositories.book_scan_repository': book_repository_module,
            'services.book_scan_service': book_scan_module,
            'repositories.scanner_queue_repository': queue_repository_module,
        }):
            _process_batch_book_scan(
                queue,
                task_id=12,
                db_type='general',
                book_ids=[101, 202],
            )

        stages = [entry.args[1] for entry in update_stage.call_args_list]
        self.assertEqual(stages[0], '선택 도서 스캔 1/2 · 첫 번째 책 (완료 0/2)')
        self.assertEqual(stages[1], '선택 도서 스캔 2/2 · 두 번째 책 (완료 1/2)')
        self.assertEqual(stages[-1], '선택 도서 스캔 완료 · 성공 2/2, 실패 0')
        self.assertEqual(scan.call_count, 2)

    def test_batch_task_key_is_stable_for_same_selected_books(self):
        queue = ScannerQueue()
        first = queue._get_task_key(
            'batch_book_scan', {'db_type': 'general', 'book_ids': [101, 202]}
        )
        reordered = queue._get_task_key(
            'batch_book_scan', {'db_type': 'general', 'book_ids': [202, 101]}
        )

        self.assertEqual(first, reordered)
        self.assertTrue(first.startswith('batch_book_scan_general_'))

    def test_targeted_lazy_scan_keys_do_not_block_global_or_other_series_scans(self):
        queue = ScannerQueue()
        global_scan = queue._get_task_key('lazy_scan', {})
        series_scan = queue._get_task_key('lazy_scan', {
            'db_type': 'general', 'library_id': 2, 'series_name': 'Naruto'
        })
        same_series_scan = queue._get_task_key('lazy_scan', {
            'db_type': 'general', 'library_id': 2, 'series_name': ' Naruto '
        })
        other_series_scan = queue._get_task_key('lazy_scan', {
            'db_type': 'general', 'library_id': 2, 'series_name': 'Boruto'
        })

        self.assertEqual(global_scan, 'lazy_scan')
        self.assertEqual(series_scan, same_series_scan)
        self.assertNotEqual(global_scan, series_scan)
        self.assertNotEqual(series_scan, other_series_scan)

    def test_single_book_scan_completion_stage_keeps_the_book_title(self):
        queue = Mock()
        lookup = Mock(return_value={'title': '테스트 단행본'})
        scan = Mock(return_value=(True, '완료', None))
        update_stage = Mock()
        book_repository_module = types.ModuleType('repositories.book_scan_repository')
        book_repository_module.BookScanRepository = types.SimpleNamespace(
            get_book_basic_info_raw=lookup
        )
        book_scan_module = types.ModuleType('services.book_scan_service')
        book_scan_module.BookScanService = types.SimpleNamespace(scan_single_book=scan)
        queue_repository_module = types.ModuleType('repositories.scanner_queue_repository')
        queue_repository_module.ScannerQueueRepository = types.SimpleNamespace(
            update_task_stage=update_stage
        )

        with patch.dict('sys.modules', {
            'repositories.book_scan_repository': book_repository_module,
            'services.book_scan_service': book_scan_module,
            'repositories.scanner_queue_repository': queue_repository_module,
        }):
            _process_batch_book_scan(
                queue,
                task_id=13,
                db_type='general',
                book_ids=[303],
            )

        final_stage = update_stage.call_args_list[-1].args[1]
        self.assertIn('테스트 단행본', final_stage)
        self.assertIn('성공 1/1, 실패 0', final_stage)

    def test_recent_finished_scan_time_window(self):
        now = datetime.datetime(2026, 9, 17, 12, 0, 20)
        just_finished = (now - datetime.timedelta(seconds=10)).strftime('%Y-%m-%d %H:%M:%S')
        too_old = (now - datetime.timedelta(seconds=25)).strftime('%Y-%m-%d %H:%M:%S')

        self.assertTrue(_is_recent_scan_finished_at(just_finished, now=now))
        self.assertFalse(_is_recent_scan_finished_at(too_old, now=now))

    def test_queue_status_includes_recent_completed_book_scans(self):
        queue = ScannerQueue()
        queue._invalidate_status_cache()
        repository_module = types.ModuleType('repositories.scanner_queue_repository')
        repository_module.ScannerQueueRepository = types.SimpleNamespace(
            fetch_queue_status=Mock(return_value=(None, [])),
            fetch_recent_batch_book_scans=Mock(return_value=[{
                'id': 42,
                'task_type': 'batch_book_scan',
                'task_key': 'batch_book_scan_general_test',
                'kwargs': json.dumps({'db_type': 'general', 'book_ids': [303], 'book_title': '테스트 단행본'}),
                'enqueue_at': '2026-09-17 12:00:00',
                'started_at': '2026-09-17 12:00:01',
                'finished_at': datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'status': 'completed',
            }]),
        )

        with patch.dict('sys.modules', {
            'repositories.scanner_queue_repository': repository_module,
        }):
            status = queue.get_queue_status()

        self.assertEqual(len(status['recent_book_scans']), 1)
        self.assertEqual(status['recent_book_scans'][0]['kwargs']['book_ids'], [303])
        self.assertEqual(status['recent_book_scans'][0]['kwargs']['book_title'], '테스트 단행본')

    def test_recent_scan_query_uses_persistent_scan_history(self):
        conn = sqlite3.connect(':memory:')
        conn.row_factory = sqlite3.Row
        conn.execute(
            """CREATE TABLE scan_history (
                id INTEGER PRIMARY KEY,
                task_type TEXT,
                task_key TEXT,
                kwargs TEXT,
                enqueue_at TEXT,
                started_at TEXT,
                finished_at TEXT,
                status TEXT
            )"""
        )
        conn.execute(
            """INSERT INTO scan_history
               (id, task_type, task_key, kwargs, enqueue_at, started_at, finished_at, status)
               VALUES (1, 'batch_book_scan', 'batch-test', '{}', 'now', 'now', 'now', 'completed')"""
        )
        conn.commit()

        with patch('repositories.sqlite.scanner_queue_repository.database.get_connection', return_value=conn):
            rows = SqliteScannerQueueRepository.fetch_recent_batch_book_scans()

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['task_key'], 'batch-test')


if __name__ == '__main__':
    unittest.main()
