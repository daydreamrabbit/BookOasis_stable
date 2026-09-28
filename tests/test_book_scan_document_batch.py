import os
import tempfile
import types
import unittest
from unittest.mock import patch

from services.book_scan_service import BookScanService
from repositories.book_scan_repository import BookScanRepository


class BookScanDocumentBatchTests(unittest.TestCase):
    def test_runs_one_forced_isolated_scan_and_returns_persisted_covers(self):
        books = {
            41: {'id': 41, 'series_name': 'Example', 'cover_image': '3/41.webp'},
            42: {'id': 42, 'series_name': 'Example', 'cover_image': '3/42.webp'},
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            library_covers = os.path.join(temp_dir, 'covers')
            os.makedirs(os.path.join(library_covers, '3'))
            for book_id in books:
                with open(os.path.join(library_covers, '3', f'{book_id}.webp'), 'wb') as cover_file:
                    cover_file.write(b'cover')

            completed = types.SimpleNamespace(returncode=0)
            with (
                patch.object(BookScanRepository, 'get_book_basic_info_raw', side_effect=lambda _db, book_id: books[book_id]),
                patch.object(BookScanRepository, 'update_book_scanned_metadata') as update_series_cover,
                patch('services.book_scan_service.subprocess.run', return_value=completed) as run_process,
                patch('services.cover_storage_service.get_covers_dir', return_value=library_covers),
                patch('services.book_scan_service.redis_delete_pattern'),
            ):
                success, message, covers = BookScanService.scan_document_books(
                    'general', [41, 42, 41], task_id=88
                )

        self.assertTrue(success)
        self.assertIn('표지 확인 2/2권', message)
        self.assertEqual(covers, {41: '3/41.webp', 42: '3/42.webp'})
        self.assertEqual(run_process.call_count, 1)
        command = run_process.call_args.args[0]
        self.assertEqual(command[command.index('--book-ids') + 1:command.index('--db-type')], ['41', '42'])
        self.assertIn('--force-document-covers', command)
        self.assertEqual(command[command.index('--task-id') + 1], '88')
        self.assertEqual(update_series_cover.call_count, 2)


if __name__ == '__main__':
    unittest.main()
