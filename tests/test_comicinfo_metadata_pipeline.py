import sqlite3
import tempfile
import re
import zipfile
import unittest
from pathlib import Path
from unittest.mock import patch

from embedded_metadata_version import (
    COMICINFO_RATING_METADATA_VERSION,
    COMICINFO_TRANSLATOR_METADATA_VERSION,
    CURRENT_EMBEDDED_METADATA_VERSION,
    is_embedded_metadata_outdated,
    needs_comicinfo_rating_refresh,
)
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
from tools.scanner.tasks import (
    _merge_comicinfo_fallback,
    _merge_comicinfo_rating,
    _should_read_comicinfo,
)


class ComicInfoMetadataPipelineTests(unittest.TestCase):
    def test_comicinfo_age_rating_mapping_preserves_all_five_access_levels(self):
        self.assertEqual(ContentRatingService.normalize_books_lv('M'), LEVEL_18)
        self.assertEqual(ContentRatingService.normalize_books_lv('MA15+'), LEVEL_15)
        self.assertEqual(ContentRatingService.normalize_books_lv('R18'), LEVEL_ADULT_MANGA)
        self.assertEqual(ContentRatingService.normalize_books_lv('R18+'), LEVEL_ADULT_MANGA)
        self.assertEqual(ContentRatingService.normalize_books_lv('adult only'), LEVEL_18)
        self.assertEqual(ContentRatingService.normalize_books_lv('Adults Only'), LEVEL_18)
        self.assertEqual(ContentRatingService.normalize_books_lv('Adult Only 18+'), LEVEL_PORN)
        self.assertEqual(ContentRatingService.normalize_books_lv('X18+'), LEVEL_PORN)
        self.assertEqual(ContentRatingService.get_level_label(LEVEL_ADULT_MANGA), '성인망가')
        self.assertEqual(ContentRatingService.get_level_label(LEVEL_PORN), '포르노')
        self.assertEqual(ContentRatingService.normalize_books_lv('unrecognized rating'), LEVEL_PORN)
        self.assertEqual(SUPPORTED_CONTENT_RATING_LEVELS, (0, 15, 18, 19, 20))

    def test_legacy_generic_ratings_are_rechecked_against_comicinfo_once(self):
        self.assertTrue(needs_comicinfo_rating_refresh(''))
        self.assertTrue(needs_comicinfo_rating_refresh('adult only'))
        self.assertFalse(needs_comicinfo_rating_refresh('R18+'))
        self.assertFalse(needs_comicinfo_rating_refresh('M'))
        self.assertLess(COMICINFO_RATING_METADATA_VERSION, CURRENT_EMBEDDED_METADATA_VERSION)
        self.assertEqual(COMICINFO_TRANSLATOR_METADATA_VERSION, CURRENT_EMBEDDED_METADATA_VERSION)
        self.assertTrue(is_embedded_metadata_outdated('/Series/01.cbz', 2, 'adult only'))
        self.assertTrue(is_embedded_metadata_outdated('/Series/01.cbz', 2, 'R18+'))
        self.assertTrue(is_embedded_metadata_outdated('/Series/01.cbz', 3, 'M'))
        self.assertTrue(is_embedded_metadata_outdated('/Series/01.cbz', 3, 'adult only'))
        self.assertTrue(is_embedded_metadata_outdated('/Series/01.cbz', 1, 'R18+'))

    def test_kavita_cbz_comicinfo_read_is_limited_to_new_or_flagged_rows(self):
        args = ('cbz', True, True, '/library/Series/01.cbz', {}, set(),
                {'books_lv': 'm'}, ('books_lv',))
        self.assertTrue(_should_read_comicinfo(*args))

        existing = ('cbz', True, True, '/library/Series/01.cbz',
                    {'/library/Series/01.cbz': 1}, {'/library/Series/01.cbz'},
                    {'books_lv': 'adult only'}, ('books_lv',))
        self.assertTrue(_should_read_comicinfo(*existing))

        already_checked = ('cbz', True, True, '/library/Series/01.cbz',
                           {'/library/Series/01.cbz': 1}, set(),
                           {'books_lv': 'R18+'}, ('books_lv',))
        self.assertFalse(_should_read_comicinfo(*already_checked))

        old_precise = ('cbz', True, True, '/library/Series/01.cbz',
                       {'/library/Series/01.cbz': 1}, {'/library/Series/01.cbz'},
                       {'books_lv': 'R18+'}, ('books_lv',))
        # A valid stored rating must not block the one-time Translator
        # backfill for a legacy sidecar-backed book whose translator is empty.
        self.assertTrue(_should_read_comicinfo(*old_precise))
        sidecar_has_translator = (
            *old_precise[:6],
            {'books_lv': 'R18+', 'translator': 'Kavita translator'},
            old_precise[7],
        )
        self.assertFalse(_should_read_comicinfo(*sidecar_has_translator))
        old_generic_db = (*old_precise, {'/library/Series/01.cbz'})
        self.assertTrue(_should_read_comicinfo(*old_generic_db))

    def test_kavita_comicinfo_merge_changes_only_the_per_volume_rating(self):
        target = {'books_lv': 'adult only', 'publisher': 'Kavita publisher'}
        _merge_comicinfo_rating(target, {
            'books_lv': 'R18+', 'publisher': 'Archive publisher',
        })
        self.assertEqual(target['books_lv'], 'R18+')
        self.assertEqual(target['publisher'], 'Kavita publisher')

    def test_content_rating_max_uses_the_saved_value_for_every_role(self):
        self.assertEqual(
            get_user_content_rating_max({'role': 'admin', 'content_rating_max': 18}),
            LEVEL_18,
        )
        self.assertEqual(
            get_user_content_rating_max({'role': 'user', 'content_rating_max': 18}),
            LEVEL_18,
        )

    def test_comicinfo_parser_reads_artist_age_rating_link_and_volume(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            archive_path = Path(temporary_dir) / 'volume.cbz'
            xml = '''<?xml version="1.0" encoding="UTF-8"?>
            <ComicInfo>
              <Title>ComicInfo volume title</Title>
              <Penciller>Comic Artist</Penciller>
              <Translator>박경용</Translator>
              <AgeRating>M</AgeRating>
              <Web>https://example.com/work</Web>
              <Series>Embedded Series</Series>
              <Volume>1.5</Volume>
              <Count>8</Count>
              <Year>2026</Year><Month>9</Month><Day>3</Day>
            </ComicInfo>'''
            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('ComicInfo.xml', xml)

            meta = parse_comicinfo_from_cbz(archive_path)

        self.assertEqual(meta['title'], 'ComicInfo volume title')
        self.assertEqual(meta['cover_artist'], 'Comic Artist')
        self.assertEqual(meta['translator'], '박경용')
        self.assertEqual(meta['books_lv'], 'M')
        self.assertEqual(meta['link'], 'https://example.com/work')
        self.assertEqual(meta['document_series_name'], 'Embedded Series')
        self.assertEqual(meta['document_volume_index'], 1.5)
        self.assertEqual(meta['document_volume_count'], 8)
        self.assertEqual(meta['release_date'], '2026-09-03')

    def test_single_scan_comicinfo_merge_includes_link_and_creator_fields(self):
        target = {
            'title': '', 'author': '', 'books_lv': 'adult only',
            'link': 'https://sidecar.example/work',
        }
        comicinfo = {
            'title': 'ComicInfo volume title',
            'author': 'Writer',
            'translator': '박경용',
            'cover_artist': 'Artist',
            'document_series_name': 'Embedded Series',
            'document_volume_index': 1,
            'document_volume_count': 12,
            'teams': 'Team A',
            'locations': 'Location A',
            'characters': 'Character A',
            'link': 'https://comicinfo.example/work',
            'books_lv': 'R18+',
        }

        _merge_comicinfo_metadata(target, comicinfo)

        self.assertEqual(target['title'], 'ComicInfo volume title')
        self.assertEqual(target['author'], 'Writer')
        self.assertEqual(target['translator'], '박경용')
        self.assertEqual(target['books_lv'], 'R18+')
        self.assertEqual(target['cover_artist'], 'Artist')
        self.assertEqual(target['teams'], 'Team A')
        self.assertEqual(target['locations'], 'Location A')
        self.assertEqual(target['characters'], 'Character A')
        self.assertEqual(target['document_series_name'], 'Embedded Series')
        self.assertEqual(target['document_volume_index'], 1)
        self.assertEqual(target['document_volume_count'], 12)
        self.assertEqual(target['link'].splitlines(), [
            'https://sidecar.example/work', 'https://comicinfo.example/work'
        ])

    def test_full_scan_comicinfo_merge_adds_link_without_dropping_sidecar_link(self):
        target = {
            'link': 'https://sidecar.example/work',
            'books_lv': 'adult only',
            'translator': '',
            'document_series_name': '',
            'document_volume_index': None,
            'document_volume_count': None,
        }

        _merge_comicinfo_fallback(target, {
            'link': 'https://comicinfo.example/work',
            'books_lv': 'R18+',
            'translator': '박경용',
            'document_series_name': 'Embedded Series',
            'document_volume_index': 1,
            'document_volume_count': 10,
        })

        self.assertEqual(target['link'].splitlines(), [
            'https://sidecar.example/work', 'https://comicinfo.example/work'
        ])
        self.assertEqual(target['books_lv'], 'R18+')
        self.assertEqual(target['translator'], '박경용')
        self.assertEqual(target['document_series_name'], 'Embedded Series')
        self.assertEqual(target['document_volume_index'], 1)
        self.assertEqual(target['document_volume_count'], 10)

    def test_comicinfo_fallback_keeps_folder_sidecar_volume_metadata(self):
        target = {
            'document_series_name': 'Sidecar Series',
            'document_volume_index': 7,
            'document_volume_count': 9,
        }

        _merge_comicinfo_fallback(target, {
            'document_series_name': 'Embedded Series',
            'document_volume_index': 1,
            'document_volume_count': 12,
        })

        self.assertEqual(target['document_series_name'], 'Sidecar Series')
        self.assertEqual(target['document_volume_index'], 7)
        self.assertEqual(target['document_volume_count'], 9)

    def test_single_scan_repository_persists_comicinfo_fields(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / 'books.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY, library_id INTEGER, series_name TEXT,
                    metadata_title TEXT,
                    cover_image TEXT, cover_updated_at TEXT, banner_image TEXT,
                    banner_updated_at TEXT, author TEXT, isbn TEXT,
                    publisher TEXT, link TEXT, score REAL, summary TEXT,
                    release_date TEXT, genre TEXT, tags TEXT, books_lv TEXT, publication_status TEXT,
                    cover_artist TEXT, translator TEXT, teams TEXT, locations TEXT, characters TEXT,
                    localized_series TEXT,
                    document_series_name TEXT, document_volume_index REAL,
                    document_number TEXT, document_volume_count INTEGER,
                    embedded_metadata_version INTEGER NOT NULL DEFAULT 0,
                    metadata_locked INTEGER DEFAULT 0
                )
            ''')
            conn.execute(
                "INSERT INTO books (id, library_id, series_name) VALUES (1, 1, 'Series')"
            )
            conn.commit()
            conn.close()

            def connect(_db_type, **_kwargs):
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
                        'title': 'ComicInfo volume title',
                        'author': '', 'isbn': '', 'publisher': '', 'link': 'https://example.com',
                        'score': 0, 'summary': '', 'release_date': '', 'genre': '', 'tags': '',
                        'books_lv': 'M', 'cover_artist': 'Comic Artist', 'teams': 'Team A',
                        'translator': '박경용',
                        'locations': 'Location A', 'characters': 'Character A',
                        'localized_series': 'Original Series',
                        'document_series_name': 'Embedded Series',
                        'document_volume_index': 1.5,
                        'document_number': '특별편',
                        'document_volume_count': 6,
                        '_embedded_metadata_checked': True,
                    },
                )

            conn = sqlite3.connect(db_path)
            row = conn.execute(
                'SELECT metadata_title, link, books_lv, cover_artist, translator, teams, locations, characters, localized_series, document_series_name, document_volume_index, document_number, document_volume_count, embedded_metadata_version FROM books WHERE id = 1'
            ).fetchone()
            conn.close()

        self.assertEqual(row, (
            'ComicInfo volume title', 'https://example.com', 'M', 'Comic Artist', '박경용', 'Team A', 'Location A', 'Character A',
            'Original Series', 'Embedded Series', 1.5, '특별편', 6,
            CURRENT_EMBEDDED_METADATA_VERSION
        ))

    def test_series_metadata_prefers_volume_one_links_and_highest_rating(self):
        result = merge_series_metadata_rows([
            {
                '_volume_title': 'Series 04권', '_volume_path': '/Series/04.cbz',
                'summary': 'Series summary', 'link': 'https://ridi.example/work/4',
                'books_lv': 'MA15+', 'cover_artist': '',
            },
            {
                '_volume_title': 'Series 01권', '_volume_path': '/Series/01.cbz',
                'summary': '', 'link': 'https://mangabaka.example/work; https://ridi.example/work/1',
                'books_lv': 'M', 'cover_artist': 'Volume Artist',
            },
            {
                '_volume_title': 'Series 02권', '_volume_path': '/Series/02.cbz',
                'summary': '', 'link': 'https://ridi.example/work/2',
                'books_lv': 'M', 'cover_artist': '',
            },
        ])

        self.assertEqual(result['books_lv'], 'M')
        self.assertEqual(result['cover_artist'], 'Volume Artist')
        self.assertEqual(result['link'].splitlines(), [
            'https://mangabaka.example/work', 'https://ridi.example/work/1'
        ])

    def test_series_metadata_falls_back_to_next_volume_when_volume_one_has_no_link(self):
        result = merge_series_metadata_rows([
            {'_volume_title': 'Series 03권', 'link': 'https://example.com/3'},
            {'_volume_title': 'Series 01권', 'link': ''},
            {'_volume_title': 'Series 02권', 'link': 'https://example.com/2'},
        ])

        self.assertEqual(result['link'], 'https://example.com/2')

    def test_sqlite_series_detail_reads_metadata_from_all_volumes(self):
        with tempfile.TemporaryDirectory() as temporary_dir:
            db_path = Path(temporary_dir) / 'series.sqlite'
            conn = sqlite3.connect(db_path)
            conn.execute('''
                CREATE TABLE books (
                    id INTEGER PRIMARY KEY, title TEXT, file_path TEXT,
                    series_name TEXT, library_id INTEGER,
                    is_deleted INTEGER DEFAULT 0, author TEXT, isbn TEXT,
                    publisher TEXT, link TEXT, score REAL, summary TEXT,
                    genre TEXT, tags TEXT, books_lv TEXT, publication_status TEXT,
                    cover_artist TEXT, translator TEXT, teams TEXT, locations TEXT, characters TEXT,
                    series_alias TEXT, localized_series TEXT,
                    metadata_locked INTEGER DEFAULT 0
                )
            ''')
            conn.execute('''
                INSERT INTO books (id, title, file_path, series_name, library_id, summary, books_lv)
                VALUES (1, 'Series 04권', '/Series/04.cbz', 'Series', 1, 'Series summary', 'MA15+')
            ''')
            conn.execute('''
                INSERT INTO books (id, title, file_path, series_name, library_id, link, books_lv, cover_artist)
                VALUES (2, 'Series 01권', '/Series/01.cbz', 'Series', 1, 'https://volume.example/work', 'M', 'Volume Artist')
            ''')
            conn.commit()
            conn.close()

            def connect(_db_type, **_kwargs):
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
                    'books_lv': 'M', 'publication_status': 0, 'cover_artist': 'Artist', 'teams': 'Team',
                    'locations': 'Location', 'characters': 'Character',
                },
            )

        query, parameters = connection.recording_cursor.calls[0]
        self.assertEqual(query.count('%s'), len(parameters))
        self.assertIn('0', parameters)
        for field in ('publication_status', 'cover_artist', 'teams', 'locations', 'characters'):
            self.assertRegex(query, rf'{field}\s*=\s*CASE')
