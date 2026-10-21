import tempfile
import unittest
import zipfile
from pathlib import Path
from tools.scanner.metadata.comicinfo_xml import parse_comicinfo_from_cbz
from services.book_scan_service import _merge_comicinfo_metadata
from tools.scanner.tasks import _merge_comicinfo_fallback

class ComicInfoISBNTests(unittest.TestCase):
    def test_gtin_and_legacy_isbn_flow_to_both_scan_paths(self):
        cases = [('<GTIN>9791142306273</GTIN>', '9791142306273'),
                 ('<ISBN>979-11-423-0627-3</ISBN>', '9791142306273'),
                 ('<GTIN>0000000000000</GTIN><ISBN>9791137391628</ISBN>', '9791137391628'),
                 ('<GTIN>0000000000000</GTIN>', ''), ('', '')]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'01.cbz'
            for xml, expected in cases:
                with self.subTest(xml=xml):
                    with zipfile.ZipFile(p, 'w') as z:
                        z.writestr('ComicInfo.xml', '<ComicInfo>'+xml+'</ComicInfo>')
                    meta = parse_comicinfo_from_cbz(p)
                    self.assertEqual(meta['isbn'], expected)
                    for merge in (_merge_comicinfo_metadata, _merge_comicinfo_fallback):
                        result = {'isbn': ''}
                        merge(result, meta)
                        self.assertEqual(result['isbn'], expected)
                        result = {'isbn': 'existing'}
                        merge(result, meta)
                        self.assertEqual(result['isbn'], 'existing')

    def test_isbn_checksum_and_series_volume_selection(self):
        from utils.isbn import normalize_isbn
        from repositories.series_metadata_utils import merge_series_metadata_rows
        self.assertEqual(normalize_isbn('1000000000'), '')
        self.assertEqual(normalize_isbn('9791141126056'), '9791141126056')
        self.assertEqual(normalize_isbn('9791163339595'), '9791163339595')
        self.assertEqual(normalize_isbn('9791141126057'), '')
        later = {'title':'106권', 'isbn':'9791163339595'}
        first = {'title':'01권', 'isbn':'9791141126056'}
        self.assertEqual(merge_series_metadata_rows([later, first])['isbn'], first['isbn'])
        first['isbn'] = ''
        self.assertEqual(merge_series_metadata_rows([later, first])['isbn'], '')
