import sqlite3
import unittest

from services.batch_book_scan_targets import resolve_batch_book_scan_targets


class BatchBookScanTargetsTests(unittest.TestCase):
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
                (1, 2, 'Series 01', 'Series', '/covers/series-01.webp', 0),
                (2, 2, 'Series 02', 'Series', None, 0),
                (3, 3, 'Series 03 other library', 'Series', None, 0),
                (4, 2, 'Other series 01', 'Other series', '', 0),
                (5, 2, 'Standalone', '', None, 0),
                (6, 2, 'Deleted volume', 'Series', None, 1),
                (7, 2, 'Series 04 no-cover marker', 'Series', 'NO_COVER', 0),
                (8, 2, 'Series 05 existing cover', 'Series', '/covers/series-05.webp', 0),
            ],
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def scan_ids(self, book_ids, scope):
        rows = resolve_batch_book_scan_targets(self.connection.cursor(), book_ids, scope)
        return [int(row['id']) for row in rows]

    def test_series_scope_includes_all_active_volumes_in_the_same_library(self):
        self.assertEqual(self.scan_ids([1], 'series'), [1, 2, 7, 8])

    def test_series_scope_expands_each_selected_card_and_keeps_standalone_books(self):
        self.assertEqual(self.scan_ids([1, 4, 5], 'series'), [1, 2, 4, 5, 7, 8])

    def test_book_scope_preserves_single_book_behavior(self):
        self.assertEqual(self.scan_ids([1], 'book'), [1])

    def test_missing_covers_scope_includes_anchor_and_only_missing_same_series_covers(self):
        self.assertEqual(self.scan_ids([1], 'missing_covers'), [1, 2, 7])

    def test_missing_covers_scope_keeps_standalone_anchor(self):
        self.assertEqual(self.scan_ids([5], 'missing_covers'), [5])

    def test_series_expansion_does_not_cross_library_or_include_deleted_volumes(self):
        self.assertEqual(self.scan_ids([1], 'series'), [1, 2, 7, 8])

    def test_missing_or_invalid_scope_is_rejected(self):
        with self.assertRaises(LookupError):
            self.scan_ids([999], 'series')
        with self.assertRaises(ValueError):
            self.scan_ids([1], 'all')


if __name__ == '__main__':
    unittest.main()
