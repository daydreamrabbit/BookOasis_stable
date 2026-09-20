import os
import tempfile
import unittest
from unittest.mock import patch

from tools.lazy_scanner import _build_scan_targets


class LazyScanForcedDocumentTargetsTests(unittest.TestCase):
    def _book(self, book_id, file_format='epub', metadata_locked=0):
        return {
            'id': book_id,
            'file_path': f'/remote/book-{book_id}.{file_format}',
            'file_format': file_format,
            'cover_image': f'7/book-{book_id}.webp',
            'library_id': 7,
            'total_pages': 10,
            'has_offsets': 1,
            'metadata_locked': metadata_locked,
        }

    def test_force_includes_existing_epub_cover_for_targeted_rescan(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cover_dir = os.path.join(temp_dir, 'covers')
            os.makedirs(os.path.join(cover_dir, '7'))
            cover_path = os.path.join(cover_dir, '7', 'book-11.webp')
            with open(cover_path, 'wb') as cover_file:
                cover_file.write(b'cover')

            book = self._book(11)
            with patch('services.cover_storage_service.get_covers_dir', return_value=cover_dir):
                targets = _build_scan_targets(
                    'general', [book], {7: True}, force_cover_book_ids={11}
                )

        self.assertEqual(targets, [(book, False)])

    def test_locked_document_and_non_document_are_not_force_reextracted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            cover_dir = os.path.join(temp_dir, 'covers')
            os.makedirs(os.path.join(cover_dir, '7'))
            for name in ('book-12.webp', 'book-13.webp'):
                with open(os.path.join(cover_dir, '7', name), 'wb') as cover_file:
                    cover_file.write(b'cover')

            locked_epub = self._book(12, metadata_locked=1)
            cbz = self._book(13, file_format='cbz')
            with patch('services.cover_storage_service.get_covers_dir', return_value=cover_dir):
                targets = _build_scan_targets(
                    'general', [locked_epub, cbz], {7: True},
                    force_cover_book_ids={12, 13},
                )

        self.assertEqual(targets, [])


if __name__ == '__main__':
    unittest.main()
