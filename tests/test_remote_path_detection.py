import unittest
from unittest.mock import patch

from utils.drive_helper import is_remote_path


class RemotePathDetectionTests(unittest.TestCase):
    def test_explicit_remote_library_flag_marks_target_remote(self):
        self.assertTrue(is_remote_path('/books/volume.cbz', library_is_remote=1))

    def test_rclone_mount_path_is_detected(self):
        with patch('utils.drive_helper._find_best_remote_mount_point', return_value='/mnt/rclone'):
            self.assertTrue(is_remote_path('/mnt/rclone/manga/volume.cbz'))

    def test_local_path_remains_local(self):
        with patch('utils.drive_helper._find_best_remote_mount_point', return_value=''):
            self.assertFalse(is_remote_path('/srv/books/volume.cbz'))


if __name__ == '__main__':
    unittest.main()
