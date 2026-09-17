import importlib.util
import io
import unittest
import zipfile
from pathlib import Path


_OFFSET_MODULE_PATH = Path(__file__).resolve().parents[1] / 'tools' / 'scanner' / 'offset.py'
_OFFSET_SPEC = importlib.util.spec_from_file_location('_bookoasis_offset_test_module', _OFFSET_MODULE_PATH)
_OFFSET_MODULE = importlib.util.module_from_spec(_OFFSET_SPEC)
_OFFSET_SPEC.loader.exec_module(_OFFSET_MODULE)


class LazyScannerRemoteOffsetTests(unittest.TestCase):
    def test_open_zip_rows_match_database_shape_and_allow_header_probe_fallback(self):
        archive_bytes = io.BytesIO()
        with zipfile.ZipFile(archive_bytes, 'w') as archive:
            archive.writestr('page-1.jpg', b'page one')
            archive.writestr('page-2.png', b'page two')
            archive.writestr('readme.txt', b'not an image')

        with zipfile.ZipFile(io.BytesIO(archive_bytes.getvalue()), 'r') as archive:
            offsets = _OFFSET_MODULE.collect_zip_offsets_from_open_zip(archive)

        self.assertEqual(len(offsets), 2)
        self.assertTrue(all(len(row) == 7 for row in offsets))
        self.assertEqual([row[1] for row in offsets], ['page-1.jpg', 'page-2.png'])
        self.assertTrue(all(row[6] is None for row in offsets))


if __name__ == '__main__':
    unittest.main()
