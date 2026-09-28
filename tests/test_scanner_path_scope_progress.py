import unittest

from tools.scanner.engine import (
    _should_skip_checkpointed_folder,
    _uses_library_scan_checkpoints,
)


class ScannerPathScopeProgressTests(unittest.TestCase):
    def test_full_library_scan_uses_resume_checkpoints(self):
        self.assertTrue(_uses_library_scan_checkpoints(None))

    def test_explicit_path_scan_does_not_use_library_resume_checkpoints(self):
        self.assertFalse(_uses_library_scan_checkpoints('/library/series'))

    def test_explicit_path_scan_reprocesses_folder_marked_complete_by_full_scan(self):
        root = '/library/series'
        completed_folders = {root}

        self.assertFalse(
            _should_skip_checkpointed_folder(
                root, completed_folders, path_scope=root
            )
        )

    def test_full_library_scan_still_skips_completed_folder(self):
        root = '/library/series'

        self.assertTrue(
            _should_skip_checkpointed_folder(root, {root}, path_scope=None)
        )


if __name__ == '__main__':
    unittest.main()
