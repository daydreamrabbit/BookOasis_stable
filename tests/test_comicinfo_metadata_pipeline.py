import sqlite3
import tempfile
import re
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

from repositories.series_metadata_utils import merge_series_metadata_rows
from repositories.sqlite.book_repository import BookRepository as SQLiteBookRepository
from repositories.sqlite.book_scan_repository import BookScanRepository
from repositories.mariadb.book_scan_repository import BookScanRepository as MariaDBBookScanRepository
from services.book_scan_service import _merge_comicinfo_metadata
from services.content_rating_service import (
    ContentRatingService,
    LEVEL_15,
    LEVEL_18,
    LEVEL_ADULT_MANGA,
    LEVEL_PORN,
    SUPPORTED_CONTENT_RATING_LEVELS,
    get_user_content_rating_max,
)
from tools.scanner.metadata.comicinfo_xml import parse_comicinfo_from_cbz
from tools.scanner.tasks import _merge_comicinfo_fallback


class ComicInfoMetadataPipelineTests(unittest.TestCase):
    def test_comicinfo_age_rating_mapping_preserves_all_five_access_levels(self):
        self.assertEqual(ContentRatingService.normalize_books_lv('M'), LEVEL_18)
        self.assertEqual(ContentRatingService.normalize_books_lv('MA15+'), LEVEL_15)
        self.assertEqual(ContentRatingService.normalize_books_lv('R18'), LEVEL_ADULT_MANGA)
        self.assertEqual(ContentRatingService.normalize_books_lv('R18+'), LEVEL_ADULT_MANGA)
        self.assertEqual(ContentRatingService.normalize_books_lv('Adult Only 18+'), LEVEL_PORN)
        self.assertEqual(ContentRatingService.normalize_books_lv('X18+'), LEVEL_PORN)
        self.assertEqual(ContentRatingService.get_level_label(LEVEL_ADULT_MANGA), '성인망가')
        self.assertEqual(ContentRatingService.get_level_label(LEVEL_PORN), '포르노')
        self.assertEqual(ContentRatingService.normalize_books_lv('unrecognized rating'), LEVEL_PORN)
        self.assertEqual(SUPPORTED_CONTENT_RATING_LEVELS, (0, 15, 18, 19, 20))

    def test_admin_content_rating_max_is_always_porn_level(self):
        self.assertEqual(
            get_user_content_rating_max({'role': 'admin', 'content_rating_max': 18}),
            LEVEL_PORN,
        )
        self.assertEqual(
            get_user_content_rating_max({'role': 'user', 'content_rating_max': 18}),
            LEVEL_18,
        )

    def test_comicinfo_parser_reads_artist_age_rating_and_related_link(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / 'volume.cbz'
            xml = '''<?xml version="1.0" encoding="UTF-8"?>
            <ComicInfo>
              <Penciller>Comic Artist</Penciller>
              <AgeRating>M</AgeRating>
              <Web>https://example.com/work</Web>
            </ComicInfo>'''
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('ComicInfo.xml', xml)

            meta = parse_comicinfo_from_cbz(archive_path)

        self.assertEqual(meta['cover_artist'], 'Comic Artist')
        self.assertEqual(meta['books_lv'], 'M')
        self.assertEqual(meta['link'], 'https://example.com/work')

    def test_single_scan_comicinfo_merge_includes_link_and_creator_fields(self):
        target = {'author': '', 'link': 'https://sidecar.example/work'}
        comicinfo = {
            'author': 'Writer',
            'cover_artist': 'Artist',
            'teams': 'Team A',
            'locations': 'Location A',
            'characters': 'Character A',
            'link': 'https://comicinfo.example/work',
        }

        _merge_comicinfo_metadata(target, comicinfo)

        self.assertEqual(target['author'], 'Writer')
        self.assertEqual(target['cover_artist'], 'Artist')
        self.assertEqual(target['teams'], 'Team A')
        self.assertEqual(target['locations'], 'Location A')
        self.assertEqual(target['characters'], 'Character A')
        self.assertEqual(target['link'].splitlines(), [
            'https://sidecar.example/work', 'https://comicinfo.example/work'
        ])

    def test_full_scan_comicinfo_merge_adds_link_without_dropping_sidecar_link(self):
        target = {'link': 'https://sidecar.example/work'}

        _merge_comicinfo_fallback(target, {'link': 'https://comicinfo.example/work'})

        self.assertEqual(target['link'].splitlines(), [
            'https://sidecar.example/work', 'https://comicinfo.example/work'
        ])

    def test_single_scan_repository_persists_comicinfo_fields(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / 'books.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY, library_id INTEGER, series_name TEXT,
                    cover_image TEXT, cover_updated_at TEXT, author TEXT, isbn TEXT,
                    publisher TEXT, link TEXT, score REAL, summary TEXT,
                    release_date TEXT, genre TEXT, tags TEXT, books_lv TEXT,
                    cover_artist TEXT, teams TEXT, locations TEXT, characters TEXT,
                    localized_series TEXT,
                    metadata_locked INTEGER DEFAULT 0
                )
            ''')
            conn.execute(
                "INSERT INTO books (id, library_id, series_name) VALUES (1, 1, 'Series')"
            )
            conn.commit()
            conn.close()

            def connect(_db_type):
                connection = sqlite3.connect(db_path)
                connection.row_factory = sqlite3.Row
                return connection

            with patch('repositories.sqlite.book_scan_repository.database.get_connection', side_effect=connect):
                BookScanRepository.update_book_scanned_metadata(
                    'general',
                    1,
                    'Series',
                    None,
                    {
                        'author': '', 'isbn': '', 'publisher': '', 'link': 'https://example.com',
                        'score': 0, 'summary': '', 'release_date': '', 'genre': '', 'tags': '',
                        'books_lv': 'M', 'cover_artist': 'Comic Artist', 'teams': 'Team A',
                        'locations': 'Location A', 'characters': 'Character A',
                        'localized_series': 'Original Series',
                    },
                )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT link, books_lv, cover_artist, teams, locations, characters, localized_series FROM books WHERE id = 1'
            ).fetchone()
            conn.close()

        self.assertEqual(row, (
            'https://example.com', 'M', 'Comic Artist', 'Team A', 'Location A', 'Character A', 'Original Series'
        ))

    def test_series_metadata_aggregates_links_and_highest_rating(self):
        result = merge_series_metadata_rows([
            {
                'summary': 'Series summary', 'link': 'https://first.example/work',
                'books_lv': 'MA15+', 'cover_artist': '',
            },
            {
                'summary': '', 'link': 'https://second.example/work; https://first.example/work',
                'books_lv': 'M', 'cover_artist': 'Volume Artist',
            },
        ])

        self.assertEqual(result['books_lv'], 'M')
        self.assertEqual(result['cover_artist'], 'Volume Artist')
        self.assertEqual(result['link'].splitlines(), [
            'https://first.example/work', 'https://second.example/work'
        ])

    def test_sqlite_series_detail_reads_metadata_from_all_volumes(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / 'series.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY, series_name TEXT, library_id INTEGER,
                    is_deleted INTEGER DEFAULT 0, author TEXT, isbn TEXT,
                    publisher TEXT, link TEXT, score REAL, summary TEXT,
                    genre TEXT, tags TEXT, books_lv TEXT, publication_status TEXT,
                    cover_artist TEXT, teams TEXT, locations TEXT, characters TEXT,
                    series_alias TEXT, metadata_locked INTEGER DEFAULT 0
                )
            ''')
            conn.execute('''
                INSERT INTO books (id, series_name, library_id, summary, books_lv)
                VALUES (1, 'Series', 1, 'Series summary', 'MA15+')
            ''')
            conn.execute('''
                INSERT INTO books (id, series_name, library_id, link, books_lv, cover_artist)
                VALUES (2, 'Series', 1, 'https://volume.example/work', 'M', 'Volume Artist')
            ''')
            conn.commit()
            conn.close()

            def connect(_db_type):
                connection = sqlite3.connect(db_path)
                connection.row_factory = sqlite3.Row
                return connection

            with patch('repositories.sqlite.book_repository.database.get_connection', side_effect=connect):
                meta = SQLiteBookRepository.get_series_meta('general', 'Series', 1, '', [])

        self.assertEqual(meta['books_lv'], 'M')
        self.assertEqual(meta['cover_artist'], 'Volume Artist')
        self.assertEqual(meta['link'], 'https://volume.example/work')

    def test_mariadb_single_scan_query_has_a_value_for_each_placeholder(self):
        class RecordingCursor:
            def __init__(self):
                self.calls = []

            def execute(self, query, params=()):
                self.calls.append((query, params))

            def fetchone(self):
                return None

        class RecordingConnection:
            def __init__(self):
                self.recording_cursor = RecordingCursor()

            def cursor(self):
                return self.recording_cursor

            def commit(self):
                pass

            def rollback(self):
                pass

            def close(self):
                pass

        connection = RecordingConnection()
        with patch(
            'repositories.mariadb.book_scan_repository.database.get_connection',
            return_value=connection,
        ):
            MariaDBBookScanRepository.update_book_scanned_metadata(
                'general', 1, 'Series', None,
                {
                    'author': '', 'isbn': '', 'publisher': '', 'link': '', 'score': 0,
                    'summary': '', 'release_date': '', 'genre': '', 'tags': '',
                    'books_lv': 'M', 'cover_artist': 'Artist', 'teams': 'Team',
                    'locations': 'Location', 'characters': 'Character',
                },
            )

        query, parameters = connection.recording_cursor.calls[0]
        self.assertEqual(query.count('%s'), len(parameters))
        for field in ('cover_artist', 'teams', 'locations', 'characters'):
            self.assertRegex(query, rf'{field}\s*=\s*CASE')
