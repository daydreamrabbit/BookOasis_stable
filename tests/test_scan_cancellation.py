import unittest
from unittest.mock import patch

from flask import Flask

from api.routes.scan_routes import scan_bp
from tools.scanner.tasks import process_folder_task


class LibraryScanCancellationRouteTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-scan-cancellation')
        app.register_blueprint(scan_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'admin'
            session['is_default_password'] = 0

    def test_running_library_scan_sets_both_cancellation_signals(self):
        with patch(
            'repositories.scanner_queue_repository.ScannerQueueRepository.get_task_by_key',
            return_value={'id': 10, 'status': 'running'},
        ), patch(
            'services.scanner_queue.scanner_queue.cancel_running_task',
            return_value=True,
        ) as cancel_running, patch(
            'repositories.category_repository.CategoryRepository.update_library_scan_status',
        ) as update_status:
            response = self.client.post(
                '/api/media/libraries/2/cancel-scan',
                data={'type': 'general'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        cancel_running.assert_called_once_with('library_scan_general_2')
        update_status.assert_called_once_with('general', 2, 'cancelling')

    def test_pending_library_scan_is_cancelled_without_leaving_library_stuck(self):
        with patch(
            'repositories.scanner_queue_repository.ScannerQueueRepository.get_task_by_key',
            return_value={'id': 11, 'status': 'pending'},
        ), patch(
            'services.scanner_queue.scanner_queue.cancel_pending_task',
            return_value=True,
        ) as cancel_pending, patch(
            'repositories.category_repository.CategoryRepository.update_library_scan_status',
        ) as update_status:
            response = self.client.post(
                '/api/media/libraries/2/cancel-scan',
                data={'type': 'general'},
            )

        self.assertEqual(response.status_code, 200)
        cancel_pending.assert_called_once_with('library_scan_general_2')
        update_status.assert_called_once_with('general', 2, 'ready')

    def test_queue_lookup_failure_preserves_legacy_status_fallback(self):
        with patch(
            'repositories.scanner_queue_repository.ScannerQueueRepository.get_task_by_key',
            side_effect=RuntimeError('scanner queue schema is temporarily unavailable'),
        ), patch(
            'repositories.category_repository.CategoryRepository.update_library_scan_status',
        ) as update_status:
            response = self.client.post(
                '/api/media/libraries/2/cancel-scan',
                data={'type': 'general'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        update_status.assert_called_once_with('general', 2, 'cancelling')

    def test_missing_task_preserves_cancellation_for_direct_running_scan(self):
        with patch(
            'repositories.scanner_queue_repository.ScannerQueueRepository.get_task_by_key',
            return_value=None,
        ), patch(
            'repositories.category_repository.CategoryRepository.get_library_by_id',
            return_value={'scan_status': 'scanning'},
        ), patch(
            'repositories.category_repository.CategoryRepository.update_library_scan_status',
        ) as update_status:
            response = self.client.post(
                '/api/media/libraries/2/cancel-scan',
                data={'type': 'general'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.get_json()['success'])
        update_status.assert_called_once_with('general', 2, 'cancelling')


class FolderCancellationFallbackTests(unittest.TestCase):
    def test_folder_does_not_start_io_when_cancelled_before_submission(self):
        result = process_folder_task(
            '/tmp/cancelled-folder',
            ['01.cbz'],
            False,
            {},
            {},
            {},
            cancel_checker=lambda: True,
        )

        self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
