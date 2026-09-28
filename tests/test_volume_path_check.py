from pathlib import Path
import tempfile
import unittest

from tools.check_volume_paths import check_path


class CheckVolumePathTests(unittest.TestCase):
    def test_check_path_accepts_readable_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            Path(temp_dir, "entry").touch()
            check_path(temp_dir)

    def test_check_path_accepts_readable_file(self):
        with tempfile.NamedTemporaryFile() as mounted_file:
            mounted_file.write(b"mounted")
            mounted_file.flush()
            check_path(mounted_file.name)

    def test_check_path_rejects_missing_mount_source(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir, "not-mounted")
            with self.assertRaises(FileNotFoundError):
                check_path(str(missing))


if __name__ == "__main__":
    unittest.main()
