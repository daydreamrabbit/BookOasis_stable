import os
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from tools.scanner.metadata import _base_meta
from tools.scanner.tasks import process_folder_task


class ScannerMetadataTitleBackfillTests(unittest.TestCase):
    def test_scan_persists_comicinfo_series_volume_and_count_fields(self):
        with tempfile.TemporaryDirectory() as root:
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(
                    'ComicInfo.xml',
                    '<ComicInfo><Series>작품</Series><Volume>1.5</Volume><Count>8</Count>'
                    '<Year>2026</Year><Month>9</Month><Day>3</Day></ComicInfo>',
                )
                archive.writestr('page.jpg', b'not-an-image')

            with (
                patch('tools.scanner.tasks.get_folder_banner', return_value=None),
                patch('tools.scanner.tasks.get_series_cover_fallback', return_value=None),
                patch('tools.scanner.tasks._compute_offsets', return_value=[]),
            ):
                result = process_folder_task(
                    root,
                    ['01.cbz'],
                    True,
                    set(),
                    set(),
                    {},
                    library_id=1,
                )

            item = result['results'][0]
            metadata = item['merged_meta']
            self.assertEqual(metadata['document_series_name'], '작품')
            self.assertEqual(metadata['document_volume_index'], 1.5)
            self.assertEqual(metadata['document_volume_count'], 8)
            self.assertEqual(metadata['release_date'], '2026-09-03')
            self.assertTrue(item['embedded_metadata_checked'])

    def test_new_cbz_uses_only_comicinfo_rating_when_kavita_yaml_exists(self):
        with tempfile.TemporaryDirectory() as root:
            with open(os.path.join(root, 'kavita.yaml'), 'w', encoding='utf-8') as sidecar:
                sidecar.write('Title: 작품\n')
            path = os.path.join(root, '01.cbz')
            with zipfile.ZipFile(path, 'w') as archive:
                archive.writestr(
                    'ComicInfo.xml',
                    '<ComicInfo><AgeRating>R18+</AgeRating>'
                    '<Publisher>Must be ignored</Publisher></ComicInfo>',
                )
                archive.writestr('page.jpg', b'not-an-image')

            folder_metadata = _base_meta()
            folder_metadata.update({'author': 'Kavita author', 'has_yaml': True})
            with (
                patch('tools.scanner.tasks.merge_local_metadata', return_value=folder_metadata),
                patch('tools.scanner.tasks.get_folder_banner', return_value=None),
                patch('tools.scanner.tasks.get_series_cover_fallback', return_value=None),
                patch('tools.scanner.tasks._compute_offsets', return_value=[]),
            ):
                result = process_folder_task(
                    root,
                    ['kavita.yaml', '01.cbz'],
                    True,
                    {path},
                    {path},
                    {},
                    library_id=1,
                )

            item = result['results'][0]
            self.assertEqual(item['merged_meta']['author'], 'Kavita author')
            self.assertEqual(item['merged_meta']['books_lv'], 'R18+')
            self.assertNotEqual(item['merged_meta']['publisher'], 'Must be ignored')
            self.assertTrue(item['embedded_metadata_checked'])

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
