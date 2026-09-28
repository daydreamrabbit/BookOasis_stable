import sqlite3
import unittest

from tools.scanner.db_writer_sqlite import bulk_insert_books, bulk_update_books


class BookWriterMetadataTitleTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(':memory:')
        self.cursor = self.connection.cursor()
        self.cursor.execute('''CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            library_id INTEGER,
            title TEXT,
            metadata_title TEXT,
            series_name TEXT,
            author TEXT,
            isbn TEXT,
            file_path TEXT UNIQUE,
            file_format TEXT,
            total_pages INTEGER,
            cover_image TEXT,
            banner_updated_at TEXT,
            banner_image TEXT,
            publisher TEXT,
            link TEXT,
            score REAL,
            summary TEXT,
            release_date TEXT,
            genre TEXT,
            tags TEXT,
            books_lv TEXT,
            publication_status TEXT,
            cover_artist TEXT,
            teams TEXT,
            locations TEXT,
            characters TEXT,
            localized_series TEXT,
            document_series_name TEXT,
            document_volume_index REAL,
            document_volume_count INTEGER,
            file_mtime REAL,
            file_size INTEGER,
            is_deleted INTEGER DEFAULT 0,
            metadata_locked INTEGER DEFAULT 0,
            cover_updated_at TEXT
        )''')

    def tearDown(self):
        self.connection.close()

    def test_bulk_insert_and_update_store_metadata_title(self):
        row = (
            1, 'file-name', 'Embedded title', 'Series', 'Author', '',
            '/books/file-name.cbz', 'cbz', 0, 'cover.webp', None, 'Publisher',
            '', 0, '', '', '', '', '', '', '', '', '', '', '', '', None,
            None, 1.0, 123,
        )
        bulk_insert_books(self.cursor, [row])
        self.connection.commit()

        self.assertEqual(
            self.cursor.execute('SELECT metadata_title FROM books').fetchone()[0],
            'Embedded title',
        )

        update = (
            (1, 'Series', 'Updated embedded title')
            + ('',) * 6  # cover and banner values
            + ('',) * 4  # author, ISBN, publisher, and link
            + (0, 0)  # duplicated score parameters
            + ('',) * 12  # remaining text metadata fields
            + (None, None, 2.0, 456, '/books/file-name.cbz')
        )
        bulk_update_books(self.cursor, [update])
        self.connection.commit()

        self.assertEqual(
            self.cursor.execute('SELECT metadata_title FROM books').fetchone()[0],
            'Updated embedded title',
        )


if __name__ == '__main__':
    unittest.main()
