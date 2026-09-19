import unittest

from utils.library_scan_progress import format_library_scan_progress


class LibraryScanProgressTests(unittest.TestCase):
    def test_directory_discovery_stage_shows_how_many_folders_were_seen(self):
        self.assertEqual(
            format_library_scan_progress('discover', count=1250),
            '폴더 탐색 중 · 1,250개 방문',
        )

    def test_file_processing_stage_shows_fraction_percent_and_remaining(self):
        self.assertEqual(
            format_library_scan_progress(
                'process', completed=32, total=128, current='/series/volume 4.epub'
            ),
            '도서 파일 32/128 (25%) · 남음 96권 · volume 4.epub',
        )

    def test_empty_library_has_a_human_readable_stage(self):
        self.assertEqual(
            format_library_scan_progress('process', completed=0, total=0),
            '처리 대상 도서 파일 없음 · 마무리 중',
        )

    def test_all_files_processed_stage_makes_clear_database_commit_is_pending(self):
        self.assertEqual(
            format_library_scan_progress('process', completed=4, total=4, current='/series/book.cbz'),
            '도서 파일 4/4 (100%) · 남음 0권 · DB 반영 중',
        )


if __name__ == '__main__':
    unittest.main()
