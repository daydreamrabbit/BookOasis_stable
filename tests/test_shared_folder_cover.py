import io
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from tools.scanner.cover import get_folder_batch_cover, save_as_thumbnail_webp
from tools.scanner.cover import get_series_cover_fallback
from tools.scanner.db_writer_sqlite import bulk_update_book_covers
from tools.scanner.path_utils import canonical_path
from tools.scanner.tasks import process_folder_task


class SharedFolderCoverTests(unittest.TestCase):
    def test_immediate_remote_scan_can_extract_only_the_first_archive_image(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            archive_path = folder / 'volume.cbz'
            cache_dir = Path(temp_dir) / 'covers'

            def jpeg_bytes(color):
                output = io.BytesIO()
                Image.new('RGB', (80, 120), color=color).save(output, format='JPEG')
                return output.getvalue()

            with zipfile.ZipFile(archive_path, 'w') as archive:
                archive.writestr('10.jpg', jpeg_bytes('blue'))
                archive.writestr('2.jpg', jpeg_bytes('red'))

            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                # Ordinary remote library scans still defer archive covers.
                self.assertIsNone(get_series_cover_fallback(
                    'Series', str(folder), force=True, is_remote=True,
                    filename=archive_path.name, file_path=str(archive_path), library_id=7,
                ))
                cover_path = get_series_cover_fallback(
                    'Series', str(folder), force=True, is_remote=True,
                    filename=archive_path.name, file_path=str(archive_path), library_id=7,
                    allow_remote_archive_read=True,
                )

            self.assertTrue(cover_path.startswith('7/book_'))
            with Image.open(cache_dir / cover_path) as cover:
                red, green, blue = cover.convert('RGB').getpixel((0, 0))
            self.assertGreater(red, 180)
            self.assertLess(blue, 80)

    def test_exact_cover_jpg_is_cached_once_per_folder(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            Image.new('RGB', (80, 120), color='navy').save(folder / 'Cover.JPG', format='JPEG')
            cache_dir = Path(temp_dir) / 'covers'

            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                with patch(
                    'tools.scanner.cover.save_as_thumbnail_webp',
                    wraps=save_as_thumbnail_webp,
                ) as save_cover:
                    first = get_folder_batch_cover(str(folder), 7)
                    second = get_folder_batch_cover(str(folder), 7)

            self.assertEqual(first, second)
            self.assertTrue(first.startswith('7/folder_'))
            self.assertTrue((cache_dir / first).is_file())
            self.assertEqual(save_cover.call_count, 1)

    def test_normal_scan_updates_cached_volumes_without_reopening_archives(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir) / 'Series'
            folder.mkdir()
            Image.new('RGB', (80, 120), color='navy').save(folder / 'cover.jpg', format='JPEG')
            archives = [folder / 'volume 1.cbz', folder / 'volume 2.cbz']
            for archive in archives:
                archive.write_bytes(b'cached archive placeholder')

            paths = [canonical_path(str(archive)) for archive in archives]
            cache_dir = Path(temp_dir) / 'covers'
            files = [archive.name for archive in archives] + ['cover.jpg']
            file_cache = {
                path: (archive.stat().st_mtime, archive.stat().st_size)
                for path, archive in zip(paths, archives)
            }

            with patch('tools.scanner.cover.get_covers_dir', return_value=str(cache_dir)):
                with patch('tools.scanner.tasks.get_folder_banner', return_value=None):
                    result = process_folder_task(
                        root=str(folder),
                        files=files,
                        force=False,
                        db_meta_full=set(paths),
                        db_offsets_cached=set(paths),
                        db_folder_mtimes={},
                        library_id=7,
                        db_files_cache=file_cache,
                        db_book_ids={path: index + 1 for index, path in enumerate(paths)},
                        db_banner_images={},
                        use_folder_cover=True,
                        db_cover_images={path: f'7/book_old_{index}.webp' for index, path in enumerate(paths)},
                    )

            results = result['results']
            self.assertEqual(len(results), 2)
            self.assertTrue(all(item['skip'] for item in results))
            self.assertTrue(all(item['folder_cover_only'] for item in results))
            self.assertEqual(results[0]['cover_image'], results[1]['cover_image'])
            self.assertTrue((cache_dir / results[0]['cover_image']).is_file())

    def test_cover_only_database_update_preserves_metadata_and_locked_covers(self):
        connection = sqlite3.connect(':memory:')
        connection.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                file_path TEXT NOT NULL,
                library_id INTEGER NOT NULL,
                cover_image TEXT,
                cover_updated_at TEXT,
                metadata_locked INTEGER DEFAULT 0,
                author TEXT
            )
        """)
        connection.executemany(
            "INSERT INTO books (id, file_path, library_id, cover_image, metadata_locked, author) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (1, '/series/one.cbz', 7, 'old-one.webp', 0, 'Writer One'),
                (2, '/series/two.cbz', 7, 'manual.webp', 1, 'Writer Two'),
            ],
        )

        bulk_update_book_covers(
            connection.cursor(),
            [
                ('7/shared.webp', '/series/one.cbz', 7),
                ('7/shared.webp', '/series/two.cbz', 7),
            ],
        )
        rows = connection.execute(
            "SELECT cover_image, author FROM books ORDER BY id"
        ).fetchall()
        connection.close()

        self.assertEqual(rows, [('7/shared.webp', 'Writer One'), ('manual.webp', 'Writer Two')])


if __name__ == '__main__':
    unittest.main()
