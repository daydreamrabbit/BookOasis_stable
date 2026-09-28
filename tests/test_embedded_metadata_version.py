import sqlite3
import unittest

from embedded_metadata_version import CURRENT_EMBEDDED_METADATA_VERSION
from services.db_migration_service import _SCHEMA_SQL, auto_migrate_schema, parse_schema_columns
from tools.db_schema_updater import MARIADB_CENTRAL_SCHEMA
from tools.scanner.engine import _is_book_scan_complete


class EmbeddedMetadataVersionTests(unittest.TestCase):
    def test_existing_sqlite_books_table_gets_version_column(self):
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        connection.execute('CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT)')
        connection.execute("INSERT INTO books (title) VALUES ('Legacy')")

        auto_migrate_schema(connection, '''
            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY,
                title TEXT,
                embedded_metadata_version INTEGER NOT NULL DEFAULT 0
            );
        ''')

        row = connection.execute(
            'SELECT embedded_metadata_version FROM books WHERE title = ?',
            ('Legacy',),
        ).fetchone()
        connection.close()
        self.assertEqual(row['embedded_metadata_version'], 0)

    def test_new_database_schemas_define_version_marker(self):
        sqlite_columns = dict(parse_schema_columns(_SCHEMA_SQL)['books'])
        self.assertEqual(
            sqlite_columns['embedded_metadata_version'],
            'INTEGER NOT NULL DEFAULT 0',
        )
        self.assertIn(
            'embedded_metadata_version INT NOT NULL DEFAULT 0',
            MARIADB_CENTRAL_SCHEMA,
        )
        self.assertGreater(CURRENT_EMBEDDED_METADATA_VERSION, 0)

    def test_current_parser_version_avoids_reopening_sparse_unchanged_archive(self):
        self.assertTrue(_is_book_scan_complete({
            'file_path': '/books/Series/01.cbz',
            'cover_image': '1/book.webp',
            'embedded_metadata_version': CURRENT_EMBEDDED_METADATA_VERSION,
            'author': '',
            'publisher': '',
            'summary': '',
        }))
        self.assertFalse(_is_book_scan_complete({
            'file_path': '/books/Series/01.cbz',
            'cover_image': '1/book.webp',
            'embedded_metadata_version': CURRENT_EMBEDDED_METADATA_VERSION - 1,
            'author': '',
            'publisher': '',
            'summary': '',
        }))
        self.assertFalse(_is_book_scan_complete({
            'file_path': '/books/Series/01.cbz',
            'cover_image': '',
            'embedded_metadata_version': CURRENT_EMBEDDED_METADATA_VERSION,
            'author': '',
            'publisher': '',
            'summary': '',
        }))


if __name__ == '__main__':
    unittest.main()
