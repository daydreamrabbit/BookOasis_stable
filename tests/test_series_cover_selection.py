import unittest
import os
import sqlite3
import tempfile
from unittest.mock import patch

from repositories.series_metadata_utils import select_series_cover_row


class SeriesCoverSelectionTests(unittest.TestCase):
    def test_prefers_volume_one_over_an_earlier_inserted_later_volume(self):
        rows = [
            {'id': 10, 'title': '소드 아트 온라인 29권', 'cover_image': '29.webp'},
            {'id': 11, 'title': '소드 아트 온라인 01권', 'cover_image': '01.webp'},
        ]

        self.assertEqual(select_series_cover_row(rows)['cover_image'], '01.webp')

    def test_uses_earliest_available_volume_when_volume_one_has_no_cover(self):
        rows = [
            {'id': 10, 'title': 'Series 29권', 'cover_image': '29.webp'},
            {'id': 11, 'title': 'Series 01권', 'cover_image': ''},
            {'id': 12, 'title': 'Series 03권', 'cover_image': '03.webp'},
        ]

        self.assertEqual(select_series_cover_row(rows)['cover_image'], '03.webp')

    def test_ignores_no_cover_marker(self):
        self.assertIsNone(select_series_cover_row([
            {'id': 1, 'title': 'Series 01권', 'cover_image': 'NO_COVER'},
        ]))

    def test_persisted_volume_takes_priority_over_insert_id_and_filename(self):
        rows=[
            {'id':1,'title':'Unnumbered','document_volume_index':6,'cover_image':'six.webp'},
            {'id':2,'title':'Misleading 99권','document_volume_index':1,'cover_image':'one.webp'},
        ]
        self.assertEqual(select_series_cover_row(rows)['cover_image'],'one.webp')

    def test_sqlite_summary_and_search_choose_the_later_added_first_volume(self):
        from services.db_migration_service import _SCHEMA_SQL
        from repositories.sqlite.series_repository import SeriesRepository
        with tempfile.TemporaryDirectory() as directory:
            path=os.path.join(directory,'test.db')
            def connect(*args,**kwargs):
                conn=sqlite3.connect(path);conn.row_factory=sqlite3.Row;return conn
            conn=connect();conn.executescript(_SCHEMA_SQL)
            conn.execute("INSERT INTO libraries(id,name,physical_path) VALUES(1,'Library','/books')")
            for id,volume,cover in [(1,6,'six.webp'),(2,1,'one.webp')]:
                conn.execute("INSERT INTO books(id,library_id,series_name,title,file_path,file_format,total_pages,document_volume_index,cover_image,created_at) VALUES(?,1,'Mafia',? ,?,'cbz',10,?,?, '2026-01-01')",
                             (id,f'Mafia {volume}권',f'/books/{id}.cbz',volume,cover))
            conn.commit();conn.close()
            with patch('database.get_connection',side_effect=connect):
                self.assertTrue(SeriesRepository.rebuild_summary('general'))
                rows=SeriesRepository.fetch_books_for_grouping('general',1,search_query='Mafia')
            self.assertEqual(rows[0]['cover_image'],'one.webp')
            conn=connect()
            self.assertEqual(conn.execute('SELECT representative_book_id FROM series_summary').fetchone()[0],2)
            conn.close()


if __name__ == '__main__':
    unittest.main()
