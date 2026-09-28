import unittest

from services.book_detail_service import _series_book_display_title


class SeriesBookDisplayTitleTests(unittest.TestCase):
    def test_metadata_title_takes_precedence(self):
        book = {
            'title': 'file-name',
            'metadata_title': 'Metadata title',
            'file_format': 'cbz',
            'file_path': '/books/file-name.cbz',
        }
        self.assertEqual(_series_book_display_title(book), 'Metadata title')

    def test_missing_metadata_title_falls_back_to_filename(self):
        book = {
            'title': 'stored-file-name',
            'metadata_title': '',
            'file_format': 'epub',
            'file_path': '/books/file-name.epub',
        }
        self.assertEqual(_series_book_display_title(book), 'file-name')

    def test_imgdir_falls_back_to_directory_name(self):
        book = {
            'title': 'stored-file-name',
            'metadata_title': None,
            'file_format': 'imgdir',
            'file_path': '/books/series/volume 1/.imgdir',
        }
        self.assertEqual(_series_book_display_title(book), 'volume 1')


if __name__ == '__main__':
    unittest.main()
