import sqlite3
import unittest
from unittest.mock import patch

from flask import Flask

from api.routes.scan_routes import scan_bp


class BatchBookScanRouteTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.connection.row_factory = sqlite3.Row
        self.connection.execute(
            'CREATE TABLE books ('
            'id INTEGER PRIMARY KEY, library_id INTEGER, title TEXT, '
            'series_name TEXT, cover_image TEXT, is_deleted INTEGER DEFAULT 0)'
        )
        self.connection.executemany(
            'INSERT INTO books (id, library_id, title, series_name, cover_image, is_deleted) '
            'VALUES (?, ?, ?, ?, ?, ?)',
            [
                (11, 4, 'Series 01', 'Series', 'cover-01.webp', 0),
                (12, 4, 'Series 02', 'Series', None, 0),
                (13, 5, 'Series other library', 'Series', None, 0),
                (14, 4, 'Deleted volume', 'Series', None, 1),
            ],
        )
        self.connection.commit()

        app = Flask(__name__)
        app.config.update(TESTING=True, SECRET_KEY='test-batch-book-scan')
        app.register_blueprint(scan_bp)
        self.client = app.test_client()
        with self.client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'admin'
            session['is_default_password'] = 0

    def tearDown(self):
        self.connection.close()

    def _post(self, scope):
        with patch(
            'api.routes.scan_routes.database.get_connection',
            return_value=self.connection,
        ), patch(
            'services.scanner_queue.scanner_queue.enqueue',
            return_value=True,
        ) as enqueue:
            response = self.client.post(
                '/api/media/books/scan-batch',
                json={'type': 'general', 'scope': scope, 'book_ids': [11]},
            )
        return response, enqueue

    def test_explicit_series_scope_expands_single_anchor_before_enqueue(self):
        response, enqueue = self._post('series')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.args, ('batch_book_scan',))
        self.assertEqual(enqueue.call_args.kwargs['book_ids'], [11, 12])
        self.assertEqual(enqueue.call_args.kwargs['scope'], 'series')
        self.assertIn('시리즈 전체 2권', response.get_json()['message'])

    def test_explicit_book_scope_does_not_expand_anchor(self):
        response, enqueue = self._post('book')

        self.assertEqual(response.status_code, 202)
        self.assertEqual(enqueue.call_args.kwargs['book_ids'], [11])
        self.assertEqual(enqueue.call_args.kwargs['scope'], 'book')


if __name__ == '__main__':
    unittest.main()
