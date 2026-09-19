import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask

from api.routes.library_routes import library_bp
from repositories.mariadb import category_repository as mariadb_category_repository
from repositories.mariadb.category_repository import CategoryRepository as MariaDBCategoryRepository
from repositories.sqlite import category_repository as sqlite_category_repository
from repositories.sqlite.category_repository import CategoryRepository as SQLiteCategoryRepository
from services.category_service import CategoryService
from services.db_migration_service import _SCHEMA_SQL, auto_migrate_schema, parse_schema_columns
from tools.db_schema_updater import MARIADB_CENTRAL_SCHEMA


class _FakeCursor:
    lastrowid = 73

    def __init__(self):
        self.query = None
        self.params = None

    def execute(self, query, params=()):
        self.query = query
        self.params = params


class _FakeConnection:
    lastrowid = 73

    def __init__(self):
        self.cursor_instance = _FakeCursor()

    def cursor(self):
        return self.cursor_instance

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        pass


def _create_app():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-library-content-kind')
    app.register_blueprint(library_bp)
    return app


class LibraryContentKindTests(unittest.TestCase):
    def test_sqlite_migration_keeps_existing_library_unclassified(self):
        connection = sqlite3.connect(':memory:')
        connection.row_factory = sqlite3.Row
        connection.execute(
            'CREATE TABLE libraries (id INTEGER PRIMARY KEY, name TEXT, physical_path TEXT)'
        )
        connection.execute(
            "INSERT INTO libraries (name, physical_path) VALUES ('Legacy', '/legacy')"
        )

        auto_migrate_schema(connection, _SCHEMA_SQL)
        row = connection.execute(
            'SELECT content_kind FROM libraries WHERE name = ?', ('Legacy',)
        ).fetchone()

        self.assertEqual(row['content_kind'], 'unspecified')
        connection.close()

    def test_both_database_schemas_define_content_kind(self):
        sqlite_columns = dict(parse_schema_columns(_SCHEMA_SQL)['libraries'])
        self.assertEqual(sqlite_columns['content_kind'], "TEXT NOT NULL DEFAULT 'unspecified'")
        self.assertIn("content_kind VARCHAR(24) NOT NULL DEFAULT 'unspecified'", MARIADB_CENTRAL_SCHEMA)

    def test_content_kind_is_written_by_both_repository_backends(self):
        for repository, repository_module in (
            (SQLiteCategoryRepository, sqlite_category_repository),
            (MariaDBCategoryRepository, mariadb_category_repository),
        ):
            connection = _FakeConnection()
            with patch.object(repository_module.database, 'get_connection', return_value=connection):
                library_id = repository.add_library(
                    'general', 'Fantasy', '/books', 0, None, 'fa-book', '#94a3b8', 0,
                    content_kind='novel',
                )

            self.assertEqual(library_id, 73)
            self.assertIn('content_kind', connection.cursor_instance.query)
            self.assertEqual(connection.cursor_instance.params[-1], 'novel')
            marker = '?' if repository is SQLiteCategoryRepository else '%s'
            self.assertEqual(
                connection.cursor_instance.query.count(marker),
                len(connection.cursor_instance.params),
            )

            connection = _FakeConnection()
            with patch.object(repository_module.database, 'get_connection', return_value=connection):
                repository.edit_library(
                    'general', 73, 'Fantasy', '/books', 0, None, 'fa-book',
                    '#94a3b8', 0, content_kind='manga',
                )
            self.assertIn('content_kind', connection.cursor_instance.query)
            self.assertEqual(connection.cursor_instance.params[-2], 'manga')
            self.assertEqual(
                connection.cursor_instance.query.count(marker),
                len(connection.cursor_instance.params),
            )

    def test_general_and_adult_libraries_require_a_supported_kind(self):
        with patch('services.category_service.CategoryRepository.add_library', return_value=5) as add_library:
            CategoryService.add_library(
                'general', 'Manga', '/books', content_kind='manga'
            )
        self.assertEqual(add_library.call_args.args[-1], 'manga')

        with self.assertRaisesRegex(ValueError, '콘텐츠 유형'):
            CategoryService.add_library('adult', 'Unclassified', '/books')

        with patch('services.category_service.CategoryRepository.add_library', return_value=8) as add_audio:
            CategoryService.add_library('audiobook', 'Audio', '/audio')
        self.assertEqual(add_audio.call_args.args[-1], 'unspecified')

    def test_edit_updates_only_the_selected_library_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = f'{temp_dir}/libraries.db'
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE libraries (
                    id INTEGER PRIMARY KEY, name TEXT, physical_path TEXT,
                    is_remote INTEGER, rclone_rc_url TEXT, icon TEXT, color TEXT,
                    hide_cover INTEGER, group_id INTEGER, gdrive_copy_remote TEXT,
                    gdrive_view_local_mirror_path TEXT, cover_aspect_ratio TEXT,
                    hide_title INTEGER, use_folder_cover INTEGER, content_kind TEXT
                )
                """
            )
            connection.executemany(
                "INSERT INTO libraries (id, name, physical_path, content_kind) VALUES (?, ?, ?, ?)",
                [(11, 'Manga', '/manga', 'unspecified'), (12, 'Novel', '/novel', 'unspecified')],
            )
            connection.commit()
            connection.close()

            def connect_db(_db_type):
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                return conn

            with patch.object(sqlite_category_repository.database, 'get_connection', side_effect=connect_db):
                SQLiteCategoryRepository.edit_library(
                    'general', 12, 'Novel', '/novel', 0, None, 'fa-book',
                    '#94a3b8', 0, content_kind='novel',
                )

            result = sqlite3.connect(db_path)
            values = result.execute(
                'SELECT id, content_kind FROM libraries ORDER BY id'
            ).fetchall()
            result.close()
            self.assertEqual(values, [(11, 'unspecified'), (12, 'novel')])

    def test_add_library_api_passes_selected_kind_to_storage_service(self):
        client = _create_app().test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'admin'
            session['is_default_password'] = 0

        with (
            patch('api.routes.library_routes.validate_library_paths', return_value=(['/books'], None)),
            patch('api.routes.library_routes.parse_remote_flag', return_value=0),
            patch('api.routes.library_routes.detect_library_media_mismatch', return_value=None),
            patch('api.routes.library_routes.CategoryService.add_library', return_value=73) as add_library,
            patch('api.routes.library_routes.database.get_db_path', return_value='/db/general.db'),
            patch('services.scanner_queue.scanner_queue.enqueue', return_value=True),
            patch('api.routes.library_routes.SchedulerService.reload_all_jobs'),
        ):
            response = client.post('/api/media/libraries/add', data={
                'type': 'general',
                'name': 'Manga library',
                'physical_path': '/books',
                'content_kind': 'manga',
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(add_library.call_args.args[-1], 'manga')

    def test_edit_library_api_preserves_kind_for_older_clients(self):
        client = _create_app().test_client()
        with client.session_transaction() as session:
            session['user_id'] = 1
            session['role'] = 'admin'
            session['is_default_password'] = 0

        with (
            patch('api.routes.library_routes.validate_library_paths', return_value=(['/books'], None)),
            patch('api.routes.library_routes.parse_remote_flag', return_value=0),
            patch('api.routes.library_routes.detect_library_media_mismatch', return_value=None),
            patch('api.routes.library_routes.CategoryRepository.get_library_by_id', return_value={
                'id': 73,
                'name': 'Novel library',
                'physical_path': '/books',
                'content_kind': 'novel',
            }),
            patch('api.routes.library_routes.CategoryService.edit_library') as edit_library,
            patch('api.routes.library_routes.CategoryService._clean_physical_path', side_effect=lambda path: path),
            patch('api.routes.library_routes.SchedulerService.reload_all_jobs'),
        ):
            response = client.post('/api/media/libraries/edit', data={
                'type': 'general',
                'id': '73',
                'name': 'Novel library',
                'physical_path': '/books',
            })

        self.assertEqual(response.status_code, 200)
        self.assertEqual(edit_library.call_args.args[-1], 'novel')


if __name__ == '__main__':
    unittest.main()
