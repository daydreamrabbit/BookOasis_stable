import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from api.routes.scan_routes import scan_bp


class ForceBookScanRouteTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            'CREATE TABLE books ('
            'id INTEGER PRIMARY KEY, library_id INTEGER, title TEXT, series_name TEXT, '
            'cover_image TEXT, file_path TEXT, is_deleted INTEGER DEFAULT 0)'
        )
        self.connection.executemany(
            'INSERT INTO books '
            '(id, library_id, title, series_name, cover_image, file_path, is_deleted) '
            'VALUES (?, ?, ?, ?, ?, ?, ?)',
            [
                (11, 4, 'Series 01', 'Series', 'cover-01.webp', '', 0),
                (12, 4, 'Series 02', 'Series', None, '', 0),
            ],
        )
        self.connection.commit()
        self.temp_dir = tempfile.TemporaryDirectory()
        self.series_dir = os.path.join(self.temp_dir.name, 'Series')
        os.makedirs(self.series_dir)
        self.connection.execute(
            'UPDATE books SET file_path = ? WHERE id = 11',
            (os.path.join(self.series_dir, 'Series 01.cbz'),),
        )
        self.connection.execute(
            'UPDATE books SET file_path = ? WHERE id = 12',
            (os.path.join(self.series_dir, 'Series 02.cbz'),),
        )
        self.connection.commit()

        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-force-book-scan')
        app.register_blueprint(scan_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'admin'
            session['is_default_password'] = 0

    def tearDown(self):
        try:
            self.connection.close()
        except sqlite3.ProgrammingError:
            pass
        self.temp_dir.cleanup()

    def test_forced_series_scope_queues_folder_scan_and_includes_registered_volumes(self):
        with patch('api.routes.scan_routes.database.get_connection', return_value=self.connection), \
             patch('api.routes.scan_routes.get_db_path_for_scan', return_value='/db/media_general.db'), \
             patch(
                 'repositories.category_repository.CategoryRepository.get_library_by_id',
                 return_value={'id': 4, 'physical_path': self.temp_dir.name},
             ), \
             patch('services.scanner_queue.scanner_queue.enqueue', return_value=True) as enqueue:
            response = self.client.post(
                '/api/media/books/scan-batch',
                json={'type': 'general', 'scope': 'series', 'book_ids': [11], 'force': True},
            )

        self.assertEqual(response.status_code, 202)
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(enqueue.call_args.args, ('batch_book_scan',))
        self.assertEqual(kwargs['book_ids'], [11, 12])
        self.assertEqual(kwargs['scan_mode'], 'force_series_path')
        self.assertEqual(kwargs['target_path'], self.series_dir)
        self.assertTrue(kwargs['force'])
        self.assertEqual(kwargs['library_id'], 4)

    def test_forced_book_scope_stays_on_the_requested_book(self):
        with patch('api.routes.scan_routes.database.get_connection', return_value=self.connection), \
             patch('services.scanner_queue.scanner_queue.enqueue', return_value=True) as enqueue:
            response = self.client.post(
                '/api/media/books/scan-batch',
                json={'type': 'general', 'scope': 'book', 'book_ids': [11], 'force': True},
            )

        self.assertEqual(response.status_code, 202)
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs['book_ids'], [11])
        self.assertEqual(kwargs['scope'], 'book')
        self.assertTrue(kwargs['force'])
        self.assertNotIn('target_path', kwargs)

    def test_series_folder_outside_library_is_rejected(self):
        with patch('api.routes.scan_routes.database.get_connection', return_value=self.connection), \
             patch(
                 'repositories.category_repository.CategoryRepository.get_library_by_id',
                 return_value={'id': 4, 'physical_path': os.path.join(self.temp_dir.name, 'other-root')},
             ), \
             patch('services.scanner_queue.scanner_queue.enqueue', return_value=True) as enqueue:
            response = self.client.post(
                '/api/media/books/scan-batch',
                json={'type': 'general', 'scope': 'series', 'book_ids': [11], 'force': True},
            )

        self.assertEqual(response.status_code, 400)
        enqueue.assert_not_called()

    def test_gdrive_share_series_queues_the_virtual_subfolder_without_local_mount(self):
        self.connection.execute(
            'UPDATE books SET file_path = ? WHERE id = 11',
            ('gdrive:/share-folder-12345678901234567890/Series/Series 01.cbz?gid=drive-file-11',),
        )
        self.connection.commit()
        share_url = 'https://drive.google.com/drive/folders/share-folder-12345678901234567890'

        with patch('api.routes.scan_routes.database.get_connection', return_value=self.connection), \
             patch('api.routes.scan_routes.get_db_path_for_scan', return_value='/db/media_general.db'), \
             patch(
                 'repositories.category_repository.CategoryRepository.get_library_by_id',
                 return_value={'id': 4, 'physical_path': share_url},
             ), \
             patch('services.scanner_queue.scanner_queue.enqueue', return_value=True) as enqueue:
            response = self.client.post(
                '/api/media/books/scan-batch',
                json={'type': 'general', 'scope': 'series', 'book_ids': [11], 'force': True},
            )

        self.assertEqual(response.status_code, 202)
        kwargs = enqueue.call_args.kwargs
        self.assertEqual(kwargs['target_path'], share_url)
        self.assertEqual(kwargs['gdrive_subpath'], 'Series')
        self.assertEqual(kwargs['path_scope'], 'gdrive:/share-folder-12345678901234567890/Series')
        self.assertEqual(kwargs['scan_mode'], 'force_series_path')


if __name__ == '__main__':
    unittest.main()
