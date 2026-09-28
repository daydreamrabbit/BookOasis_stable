import unittest
from unittest.mock import patch
import api  # Initialize the existing route/cache import graph before services.
from services.book_info_service import BookInfoService


class ComicPageCountTests(unittest.TestCase):
    def test_failed_count_does_not_report_placeholder_as_one_real_page(self):
        with patch('services.book_info_service.BookRepository') as repo, \
             patch('services.book_info_service.get_zip_file_hybrid', return_value=None):
            repo.get_book_pages_and_path.return_value = {'total_pages':1,'file_format':'cbz','file_path':'gdrive://folder/book.cbz'}
            self.assertEqual(BookInfoService.get_total_pages('general', 9), 0)
            repo.update_book_pages.assert_not_called()

    def test_virtual_drive_and_one_page_placeholder_are_counted(self):
        for path, old_count, exists in [('gdrive://folder/book.cbz', 0, False), ('/books/book.zip', 1, True)]:
            with self.subTest(path=path), patch('services.book_info_service.BookRepository') as repo, \
                 patch('services.book_info_service.os.path.exists', return_value=exists), \
                 patch('services.book_info_service.get_zip_file_hybrid') as archive:
                repo.get_book_pages_and_path.return_value = {'total_pages':old_count, 'file_format':'cbz', 'file_path':path}
                archive.return_value.namelist.return_value = ['01.jpg','02.PNG','03.webp','ComicInfo.xml']
                self.assertEqual(BookInfoService.get_total_pages('general', 7), 3)
                repo.update_book_pages.assert_called_once_with('general', 7, 3)

    def test_known_multi_page_archive_does_not_download_again(self):
        with patch('services.book_info_service.BookRepository') as repo, \
             patch('services.book_info_service.get_zip_file_hybrid') as archive:
            repo.get_book_pages_and_path.return_value = {'total_pages':50,'file_format':'cbz','file_path':'gdrive://folder/book.cbz'}
            self.assertEqual(BookInfoService.get_total_pages('adult', 8), 50)
            archive.assert_not_called()


if __name__ == '__main__':
    unittest.main()
