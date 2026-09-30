"""Opt-in integration checks; all rows live in a connection-local temporary table."""
import os
import time
import unittest
from unittest.mock import patch

import database
from repositories.recent_additions import fetch


@unittest.skipUnless(os.getenv('BOOKOASIS_TEST_MARIADB') == '1', 'requires MariaDB temporary-table test connection')
class MariaRecentAdditionsTests(unittest.TestCase):
    def setUp(self):
        self.conn = database.get_connection('general')
        self.addCleanup(self.conn.close)
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TEMPORARY TABLE books (
            id INTEGER PRIMARY KEY, library_id INTEGER, series_name VARCHAR(255),
            title VARCHAR(255), file_path VARCHAR(1000), file_format VARCHAR(20),
            created_at DATETIME, is_deleted INTEGER DEFAULT 0,
            INDEX idx_books_series_lib_title(series_name, library_id, title),
            INDEX idx_books_library_id(library_id))''')
        self.addCleanup(lambda: self.conn.cursor().execute('DROP TEMPORARY TABLE books'))
        connection = self.conn
        class Connection:
            def cursor(self): return connection.cursor()
            def close(self): pass
        p = patch.object(database, 'get_connection', return_value=Connection())
        p.start()
        self.addCleanup(p.stop)

    def test_folders_null_dates_and_image_directory_volumes(self):
        cursor = self.conn.cursor()
        cursor.execute('''INSERT INTO books VALUES
            (1,1,'same','old','/a/1.zip','zip',NULL,0),
            (2,1,'same','new','/a/2.zip','zip',NOW(),0),
            (3,1,'same','other','/b/1.zip','zip',NOW() - INTERVAL 30 DAY,0),
            (4,2,'same','other library','/a/1.zip','zip',NOW(),0),
            (5,1,'images','01','/img/01/__folder__.imgdir','imgdir',NOW() - INTERVAL 30 DAY,0),
            (6,1,'images','02','/img/02/__folder__.imgdir','imgdir',NOW(),0),
            (7,1,'same','deleted','/a/3.zip','zip',NOW(),1)''')
        result = fetch('general', 7, [1, 3, 5])
        self.assertEqual((result['series'][1]['total_count'], result['series'][1]['recent_count']), (2, 1))
        self.assertEqual(result['series'][3]['recent_count'], 0)
        self.assertEqual((result['series'][5]['total_count'], result['series'][5]['recent_count']), (2, 1))
        self.assertEqual(result['libraries'][1]['total_count'], 5)

    def test_large_category_returns_only_visible_series(self):
        cursor = self.conn.cursor()
        cursor.executemany("INSERT INTO books VALUES(%s,1,%s,'title',%s,'zip',NOW() - INTERVAL 30 DAY,0)",
                           [(i, f's{i // 10}', f'/books/{i // 10}/{i}.zip') for i in range(1, 40001)])
        started = time.perf_counter()
        result = fetch('general', 7, list(range(10, 310, 10)))
        elapsed = time.perf_counter() - started
        self.assertEqual(len(result['series']), 30)
        self.assertTrue(all(row['total_count'] == 10 for row in result['series'].values()))
        print(f'[RecentBadge MariaDB] 40,000 books / 30 cards: {elapsed:.3f}s')


if __name__ == '__main__':
    unittest.main()
