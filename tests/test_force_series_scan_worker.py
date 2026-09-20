import types
import unittest
from unittest.mock import Mock, patch

from services.scanner_queue import _process_batch_book_scan


class ForceSeriesScanWorkerTests(unittest.TestCase):
    def test_gdrive_series_force_scan_preserves_virtual_scope_and_reports_activity(self):
        queue = Mock()
        scan_library_path = Mock()
        scanner_core_module = types.ModuleType('tools.scanner.core')
        scanner_core_module.scan_library_path = scan_library_path

        book_repository_module = types.ModuleType('repositories.book_scan_repository')
        book_repository_module.BookScanRepository = object
        book_scan_module = types.ModuleType('services.book_scan_service')
        book_scan_module.BookScanService = object
        drive_helper_module = types.ModuleType('utils.drive_helper')
        drive_helper_module.is_remote_path = lambda *_args, **_kwargs: True
        stage_update = Mock()
        queue_repository_module = types.ModuleType('repositories.scanner_queue_repository')
        queue_repository_module.ScannerQueueRepository = types.SimpleNamespace(
            update_task_stage=stage_update
        )

        with patch.dict('sys.modules', {
            'tools.scanner.core': scanner_core_module,
            'repositories.book_scan_repository': book_repository_module,
            'services.book_scan_service': book_scan_module,
            'repositories.scanner_queue_repository': queue_repository_module,
            'utils.drive_helper': drive_helper_module,
        }):
            _process_batch_book_scan(
                queue,
                task_id=31,
                db_type='general',
                book_ids=[11, 12],
                scan_mode='force_series_path',
                target_path='https://drive.google.com/drive/folders/share-folder-12345678901234567890',
                path_scope='gdrive:/share-folder-12345678901234567890/Series',
                gdrive_subpath='Series',
                db_path='/db/media_general.db',
                library_id=4,
                series_name='Series',
                force=True,
            )

        scan_library_path.assert_called_once_with(
            '/db/media_general.db',
            4,
            'https://drive.google.com/drive/folders/share-folder-12345678901234567890',
            force=True,
            path_scope='gdrive:/share-folder-12345678901234567890/Series',
            gdrive_subpath='Series',
        )
        stages = [call.args[1] for call in stage_update.call_args_list]
        self.assertTrue(any('시리즈 폴더 강제 스캔 중' in stage for stage in stages))
        self.assertTrue(any('신규 권 검색 및 기존 권 갱신 완료' in stage for stage in stages))


if __name__ == '__main__':
    unittest.main()
