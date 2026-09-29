import unittest
from unittest.mock import patch, Mock
from utils.filename_page_count import filename_page_count, with_filename_page_counts


class FilenamePageCountTests(unittest.TestCase):
    def test_terminal_marker_only(self):
        for path in ('/books/title#163.zip', 'title#163.CBZ',
                     'gdrive://folder/title#163.zip?gid=abc', r'C:\books\title#163.zip'):
            self.assertEqual(filename_page_count(path), 163)
        for path in ('/folder#163/title.zip', 'title#163 extra.zip', 'title#0.zip',
                     'title#-1.zip', 'title#163.epub', 'title#163.pdf', 'title.zip', 'x#999999999.zip'):
            self.assertEqual(filename_page_count(path), 0)

    def test_insert_preserves_known_count_and_input(self):
        row = (1, '', '', '', '', '', 'title#163.zip', 'zip', 0)
        self.assertEqual(with_filename_page_counts([row])[0][8], 163)
        self.assertEqual(row[8], 0)
        self.assertEqual(with_filename_page_counts([row[:8] + (170,)])[0][8], 170)

    def test_both_database_batch_writers_use_hint(self):
        from tools.scanner import db_writer_sqlite, db_writer_mariadb
        row = (1, '', '', '', '', '', 'title#163.zip', 'zip', 0)
        for writer in (db_writer_sqlite, db_writer_mariadb):
            cursor = Mock()
            writer.bulk_insert_books(cursor, [row])
            self.assertEqual(cursor.executemany.call_args.args[1][0][8], 163)

    def test_viewer_uses_hint_without_archive_io(self):
        import api
        from services.book_info_service import BookInfoService
        for old in (0, 1, 170):
            with patch('services.book_info_service.BookRepository') as repo, \
                 patch('services.book_info_service.get_zip_file_hybrid') as archive:
                repo.get_book_pages_and_path.return_value = {
                    'total_pages': old, 'file_format': 'zip', 'file_path': 'gdrive://folder/title#163.zip?gid=abc'}
                self.assertEqual(BookInfoService.get_total_pages('general', 9), 170 if old == 170 else 163)
                archive.assert_not_called()
                if old != 170:
                    repo.update_book_pages.assert_called_once_with('general', 9, 163)
                else:
                    repo.update_book_pages.assert_not_called()
