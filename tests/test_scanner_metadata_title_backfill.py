import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.scanner.tasks import process_folder_task


class ScannerMetadataTitleBackfillTests(unittest.TestCase):
    def test_normal_scan_rechecks_unchanged_book_for_current_embedded_metadata(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(
                    'ComicInfo.xml',
                    '<ComicInfo><Publisher>Embedded Publisher</Publisher><Genre>Drama</Genre></ComicInfo>',
                )

            with (
                patch('tools.scanner.tasks.get_folder_banner', return_value=None),
                patch('tools.scanner.tasks.get_series_cover_fallback', return_value=None),
            ):
                result = process_folder_task(
                    root,
                    ['01.cbz'],
                    False,
                    {path},
                    {path},
                    {},
                    library_id=1,
                    db_files_cache={path: (os.path.getmtime(path), os.path.getsize(path))},
                    db_book_ids={path: 1},
                    db_embedded_metadata_outdated={path},
                )

            item = result['results'][0]
            self.assertEqual(item['merged_meta']['publisher'], 'Embedded Publisher')
            self.assertEqual(item['merged_meta']['genre'], 'Drama')
            self.assertTrue(item['embedded_metadata_checked'])

    def test_failed_embedded_metadata_parse_is_not_marked_checked(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('page.jpg', b'not-an-image')

            with (
                patch('tools.scanner.tasks.parse_comicinfo_from_cbz', side_effect=TimeoutError('timed out')),
                patch('tools.scanner.tasks.get_folder_banner', return_value=None),
                patch('tools.scanner.tasks.get_series_cover_fallback', return_value=None),
            ):
                result = process_folder_task(
                    root,
                    ['01.cbz'],
                    False,
                    {path},
                    {path},
                    {},
                    library_id=1,
                    db_files_cache={path: (os.path.getmtime(path), os.path.getsize(path))},
                    db_book_ids={path: 1},
                    db_embedded_metadata_outdated={path},
                )

            self.assertFalse(result['results'][0]['embedded_metadata_checked'])

    def test_normal_scan_rechecks_unchanged_book_with_unchecked_title(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(
                    'ComicInfo.xml',
                    '<ComicInfo><Title>ComicInfo title</Title></ComicInfo>',
                )

            file_cache = {path: (os.path.getmtime(path), os.path.getsize(path))}
            with (
                patch('tools.scanner.tasks.get_folder_banner', return_value=None),
                patch('tools.scanner.tasks.get_series_cover_fallback', return_value=None),
                patch('tools.scanner.tasks.collect_zip_offsets_data', return_value=[]),
            ):
                result = process_folder_task(
                    root,
                    ['01.cbz'],
                    False,
                    {path},
                    {path},
                    {},
                    library_id=1,
                    db_files_cache=file_cache,
                    db_book_ids={path: 1},
                    db_metadata_title_unchecked={path},
                )

            self.assertEqual(result['results'][0]['merged_meta']['title'], 'ComicInfo title')

    def test_normal_scan_keeps_fast_skip_for_already_checked_book(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr('ComicInfo.xml', '<ComicInfo><Title>Already checked</Title></ComicInfo>')

            result = process_folder_task(
                root,
                ['01.cbz'],
                False,
                {path},
                {path},
                {},
                library_id=1,
                db_files_cache={path: (os.path.getmtime(path), os.path.getsize(path))},
                db_book_ids={path: 1},
            )

            self.assertIsNone(result)


if __name__ == '__main__':
    unittest.main()
