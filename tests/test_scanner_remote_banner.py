import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools.scanner.cover import cleanup_unreferenced_generated_banners, get_folder_banner
from tools.scanner.db_writer_mariadb import clear_book_banners as clear_book_banners_mariadb
from tools.scanner.db_writer_sqlite import clear_book_banners
from tools.scanner.tasks import process_folder_task


class RemoteFolderBannerTests(unittest.TestCase):
    def _make_cached_remote_book(self, folder, *, include_banner):
        archive = folder / 'volume.cbz'
        archive.write_bytes(b'cached archive placeholder')
        files = [archive.name]
        if include_banner:
            Image.new('RGB', (24, 12), color='navy').save(folder / 'banner.jpg', format='JPEG')
            files.append('banner.jpg')

        full_path = str(archive)
        file_cache = {
            full_path: (archive.stat().st_mtime, archive.stat().st_size)
        }
        return files, full_path, file_cache

    def test_remote_mounted_folder_reads_new_banner_for_cached_book(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            files, full_path, file_cache = self._make_cached_remote_book(
                folder, include_banner=True
            )

            cache_dir = Path(temp_dir) / 'cover-cache'
            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                result = process_folder_task(
                    root=str(folder),
                    files=files,
                    force=False,
                    db_meta_full={full_path},
                    db_offsets_cached={full_path},
                    db_folder_mtimes={},
                    is_remote=True,
                    library_id=9,
                    db_files_cache=file_cache,
                    db_banner_missing={full_path},
                )
            banner_image = result['results'][0]['banner_image']
            cached_banner_exists = (cache_dir / banner_image).is_file()

        self.assertIsNotNone(result)
        self.assertTrue(banner_image.startswith('9/banner_'))
        self.assertTrue(cached_banner_exists)
        self.assertTrue(result['results'][0]['skip'])

    def test_remote_cached_folder_without_banner_keeps_fast_skip(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            files, full_path, file_cache = self._make_cached_remote_book(
                folder, include_banner=False
            )

            with patch('tools.scanner.tasks.get_folder_banner') as get_banner:
                result = process_folder_task(
                    root=str(folder),
                    files=files,
                    force=False,
                    db_meta_full={full_path},
                    db_offsets_cached={full_path},
                    db_folder_mtimes={},
                    is_remote=True,
                    library_id=9,
                    db_files_cache=file_cache,
                    db_banner_missing={full_path},
                )

        self.assertIsNone(result)
        get_banner.assert_not_called()

    def test_normal_remote_scan_detects_changed_banner_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            files, full_path, file_cache = self._make_cached_remote_book(
                folder, include_banner=True
            )
            cache_dir = Path(temp_dir) / 'cover-cache'

            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                old_banner = get_folder_banner(full_path, str(folder), library_id=9)
                Image.new('RGB', (24, 12), color='orange').save(
                    folder / 'banner.jpg', format='JPEG'
                )
                result = process_folder_task(
                    root=str(folder),
                    files=files,
                    force=False,
                    db_meta_full={full_path},
                    db_offsets_cached={full_path},
                    db_folder_mtimes={},
                    is_remote=True,
                    library_id=9,
                    db_files_cache=file_cache,
                    db_banner_images={full_path: old_banner},
                )

            item = result['results'][0]
            cached_banner_exists = (cache_dir / item['banner_image']).is_file()

        self.assertTrue(item['skip'])
        self.assertNotEqual(item['banner_image'], old_banner)
        self.assertFalse(item['clear_banner'])
        self.assertTrue(cached_banner_exists)

    def test_removed_banner_clears_db_reference_and_only_its_generated_cache(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            files, full_path, file_cache = self._make_cached_remote_book(
                folder, include_banner=True
            )
            cache_dir = Path(temp_dir) / 'cover-cache'

            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                old_banner = get_folder_banner(full_path, str(folder), library_id=9)
                (folder / 'banner.jpg').unlink()
                result = process_folder_task(
                    root=str(folder),
                    files=[name for name in files if name != 'banner.jpg'],
                    force=False,
                    db_meta_full={full_path},
                    db_offsets_cached={full_path},
                    db_folder_mtimes={},
                    is_remote=True,
                    library_id=9,
                    db_files_cache=file_cache,
                    db_banner_images={full_path: old_banner},
                )

                item = result['results'][0]
                self.assertTrue(item['skip'])
                self.assertIsNone(item['banner_image'])
                self.assertTrue(item['clear_banner'])

                connection = sqlite3.connect(':memory:')
                connection.row_factory = sqlite3.Row
                connection.execute("""
                    CREATE TABLE books (
                        library_id INTEGER, file_path TEXT, banner_image TEXT,
                        banner_updated_at TEXT, metadata_locked INTEGER
                    )
                """)
                connection.executemany(
                    "INSERT INTO books VALUES (?, ?, ?, ?, ?)",
                    [
                        (9, full_path, old_banner, 'old-time', 0),
                        (9, '/Series/locked.cbz', old_banner, 'locked-time', 1),
                        (10, full_path, '10/other-banner.webp', 'other-library-time', 0),
                    ],
                )
                clear_book_banners(connection.cursor(), 9, [full_path])
                cleared, locked = connection.execute(
                    "SELECT banner_image, banner_updated_at, metadata_locked FROM books WHERE library_id = 9 ORDER BY rowid"
                ).fetchall()
                self.assertIsNone(cleared['banner_image'])
                self.assertNotEqual(cleared['banner_updated_at'], 'old-time')
                self.assertEqual(locked['banner_image'], old_banner)
                other_library = connection.execute(
                    "SELECT banner_image FROM books WHERE library_id = 10"
                ).fetchone()
                self.assertEqual(other_library['banner_image'], '10/other-banner.webp')
                connection.close()

                cover_path = cache_dir / '9' / 'cover.webp'
                cover_path.parent.mkdir(parents=True, exist_ok=True)
                cover_path.write_bytes(b'cover')
                referenced_banner = '9/banner_' + ('a' * 32) + '.webp'
                referenced_path = cache_dir / referenced_banner
                referenced_path.write_bytes(b'in-use')
                removed = cleanup_unreferenced_generated_banners(
                    [old_banner, referenced_banner, '9/cover.webp'],
                    [referenced_banner],
                    9,
                )

            self.assertEqual(removed, [old_banner])
            self.assertFalse((cache_dir / old_banner).exists())
            self.assertTrue(cover_path.exists())
            self.assertTrue(referenced_path.exists())

    def test_mariadb_banner_clear_is_library_scoped(self):
        class RecordingCursor:
            def executemany(self, statement, parameters):
                self.statement = statement
                self.parameters = parameters

        cursor = RecordingCursor()
        clear_book_banners_mariadb(cursor, 12, ['/Books/Series/1.cbz'])

        self.assertIn('library_id = %s AND file_path = %s', cursor.statement)
        self.assertEqual(cursor.parameters, [(12, '/Books/Series/1.cbz')])


if __name__ == '__main__':
    unittest.main()
