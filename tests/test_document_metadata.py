import io
import sys
import tempfile
import types
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from tools.scanner import cover as cover_tools
from tools.scanner.metadata import merge_embedded_metadata, parse_embedded_metadata
from tools.scanner.metadata.document_metadata import parse_pdf_xmp_metadata
from tools.lazy_scanner import _update_scanned_document_metadata


class EmbeddedDocumentMetadataTests(unittest.TestCase):
    def _make_epub(self, folder):
        path = Path(folder) / 'sample.epub'
        container = '''<?xml version="1.0"?>
        <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles><rootfile full-path="OEBPS/content.opf"/></rootfiles>
        </container>'''
        opf = '''<?xml version="1.0"?>
        <package xmlns="http://www.idpf.org/2007/opf"
                 xmlns:dc="http://purl.org/dc/elements/1.1/">
          <metadata>
            <meta name="cover" content="cover-image"/>
            <dc:title>EPUB volume title</dc:title>
            <dc:creator id="writer">작가 이름</dc:creator>
            <meta refines="#writer" property="role">aut</meta>
            <dc:creator id="translator">번역자 이름</dc:creator>
            <meta refines="#translator" property="role">trl</meta>
            <dc:creator id="artist">그림 작가</dc:creator>
            <meta refines="#artist" property="role">art</meta>
            <dc:identifier id="uuid">urn:uuid:abcd-1234</dc:identifier>
            <dc:identifier id="isbn" xmlns:opf="http://www.idpf.org/2007/opf" opf:scheme="ISBN">9780306406157</dc:identifier>
            <dc:publisher>출판사</dc:publisher>
            <dc:description>&lt;p&gt;책 설명&lt;/p&gt;</dc:description>
            <dc:subject>라이트노벨, 판타지</dc:subject>
            <dc:date>2011-07-02</dc:date>
            <meta name="calibre:series">테스트 시리즈</meta>
            <meta name="calibre:series_index">1.5</meta>
            <meta name="calibre:series_count" content="8"/>
          </metadata>
          <manifest><item id="cover-image" href="cover.png" media-type="image/png"/></manifest>
        </package>'''
        from PIL import Image
        with zipfile.ZipFile(path, 'w') as epub:
            epub.writestr('META-INF/container.xml', container)
            epub.writestr('OEBPS/content.opf', opf)
            cover_bytes = io.BytesIO()
            Image.new('RGB', (8, 12), (40, 90, 140)).save(cover_bytes, format='PNG')
            epub.writestr('OEBPS/cover.png', cover_bytes.getvalue())
        return path

    def test_epub_opf_extracts_roles_and_book_fields(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._make_epub(folder)
            metadata = parse_embedded_metadata(str(path), 'epub')

        self.assertEqual(metadata['author'], '작가 이름')
        self.assertEqual(metadata['title'], 'EPUB volume title')
        self.assertEqual(metadata['cover_artist'], '그림 작가')
        self.assertEqual(metadata['isbn'], '9780306406157')
        self.assertEqual(metadata['publisher'], '출판사')
        self.assertEqual(metadata['summary'], '책 설명')
        self.assertEqual(metadata['genre'], '라이트노벨, 판타지')
        self.assertEqual(metadata['release_date'], '2011-07-02')
        self.assertEqual(metadata['document_series_name'], '테스트 시리즈')
        self.assertEqual(metadata['document_volume_index'], 1.5)
        self.assertEqual(metadata['document_volume_count'], 8)
        self.assertNotIn('번역자 이름', metadata['author'])

    def test_epub3_collection_metadata_extracts_series_index_and_optional_count(self):
        from xml.etree import ElementTree as ET
        from tools.scanner.metadata.document_metadata import parse_epub_opf_metadata

        opf = ET.fromstring('''<package xmlns="http://www.idpf.org/2007/opf">
          <metadata>
            <meta id="series" property="belongs-to-collection">EPUB 3 시리즈</meta>
            <meta refines="#series" property="collection-type">series</meta>
            <meta refines="#series" property="group-position">2</meta>
            <meta refines="#series" property="collection-count">5</meta>
          </metadata>
        </package>''')

        metadata = parse_epub_opf_metadata(opf)

        self.assertEqual(metadata['document_series_name'], 'EPUB 3 시리즈')
        self.assertEqual(metadata['document_volume_index'], 2.0)
        self.assertEqual(metadata['document_volume_count'], 5)

    def test_epub3_dcterms_issued_extracts_publication_date(self):
        from xml.etree import ElementTree as ET
        from tools.scanner.metadata.document_metadata import parse_epub_opf_metadata

        opf = ET.fromstring('''<package xmlns="http://www.idpf.org/2007/opf">
          <metadata>
            <meta property="dcterms:issued">2014-05-06</meta>
            <meta property="dcterms:modified">2024-09-18T12:00:00Z</meta>
          </metadata>
        </package>''')

        metadata = parse_epub_opf_metadata(opf)

        self.assertEqual(metadata['release_date'], '2014-05-06')

    def test_epub_series_index_does_not_invent_missing_count(self):
        from xml.etree import ElementTree as ET
        from tools.scanner.metadata.document_metadata import parse_epub_opf_metadata

        opf = ET.fromstring('''<package xmlns="http://www.idpf.org/2007/opf">
          <metadata>
            <meta name="calibre:series">단권 시리즈</meta>
            <meta name="calibre:series_index" content="1"/>
          </metadata>
        </package>''')

        metadata = parse_epub_opf_metadata(opf)

        self.assertEqual(metadata['document_series_name'], '단권 시리즈')
        self.assertEqual(metadata['document_volume_index'], 1.0)
        self.assertNotIn('document_volume_count', metadata)

    def test_epub_cover_and_metadata_share_one_archive_open(self):
        with tempfile.TemporaryDirectory() as folder:
            path = self._make_epub(folder)
            cover_path = Path(folder) / 'cover.webp'
            metadata = {}
            opf_read = {}
            original_zipfile = zipfile.ZipFile
            with patch.object(cover_tools.zipfile, 'ZipFile', wraps=original_zipfile) as open_zip:
                extracted = cover_tools.extract_epub_cover_direct(
                    str(path),
                    str(cover_path),
                    metadata_out=metadata,
                    opf_read_out=opf_read,
                )
            self.assertTrue(extracted)
            self.assertTrue(cover_path.is_file())
            self.assertEqual(open_zip.call_count, 1)
            self.assertTrue(opf_read['parsed'])
            self.assertEqual(metadata['author'], '작가 이름')
            self.assertEqual(metadata['cover_artist'], '그림 작가')

    def test_folder_metadata_keeps_priority_over_embedded_values(self):
        target = {'author': 'sidecar author', 'publisher': ''}
        merge_embedded_metadata(target, {'author': 'EPUB author', 'publisher': 'EPUB publisher'})
        self.assertEqual(target, {'author': 'sidecar author', 'publisher': 'EPUB publisher'})

    def test_immediate_document_scan_persists_embedded_series_fields(self):
        import sqlite3

        connection = sqlite3.connect(':memory:')
        cursor = connection.cursor()
        cursor.execute('''CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            metadata_locked INTEGER DEFAULT 0,
            metadata_title TEXT,
            document_series_name TEXT,
            document_volume_index REAL,
            document_volume_count INTEGER
        )''')
        cursor.execute('INSERT INTO books (id) VALUES (1)')

        changed = _update_scanned_document_metadata(cursor, 1, {
            'title': 'EPUB document title',
            'document_series_name': '스파이 패밀리 -가족의 초상-',
            'document_volume_index': 1.0,
            'document_volume_count': 4,
        })
        row = cursor.execute(
            'SELECT metadata_title, document_series_name, document_volume_index, document_volume_count FROM books WHERE id = 1'
        ).fetchone()
        connection.close()

        self.assertTrue(changed)
        self.assertEqual(row, ('EPUB document title', '스파이 패밀리 -가족의 초상-', 1.0, 4))

    def test_pdf_info_dictionary_is_mapped_and_closed(self):
        class FakePdf:
            closed = False

            def get_metadata_dict(self):
                return {
                    'Title': 'PDF volume title',
                    'Author': 'PDF author',
                    'Subject': 'PDF summary',
                    'Keywords': 'history, reference',
                    'Creator': 'Not a book author',
                    'Producer': 'Not a publisher',
                }

            def close(self):
                self.closed = True

        fake_pdf = FakePdf()
        pdfium = types.SimpleNamespace(PdfDocument=lambda _path: fake_pdf)
        with (
            patch.dict(sys.modules, {'pypdfium2': pdfium}),
            patch('tools.scanner.metadata.document_metadata._parse_pdf_xmp_file', return_value={}),
        ):
            metadata = parse_embedded_metadata('/tmp/sample.pdf', 'pdf')

        self.assertEqual(metadata, {
            'title': 'PDF volume title',
            'author': 'PDF author',
            'summary': 'PDF summary',
            'tags': 'history, reference',
        })
        self.assertTrue(fake_pdf.closed)

    def test_pdf_xmp_extracts_current_cbb_and_calibre_metadata(self):
        xmp = '''<?xpacket begin=""?>
        <x:xmpmeta xmlns:x="adobe:ns:meta/">
          <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
            <rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" rdf:about="">
              <dc:title><rdf:Alt><rdf:li xml:lang="x-default">1권</rdf:li></rdf:Alt></dc:title>
              <dc:description><rdf:Alt><rdf:li xml:lang="x-default">책 설명</rdf:li></rdf:Alt></dc:description>
              <dc:creator><rdf:Seq><rdf:li>야마다 마루</rdf:li></rdf:Seq></dc:creator>
              <dc:subject><rdf:Bag><rdf:li>라이트노벨</rdf:li><rdf:li>해외라이트노벨</rdf:li></rdf:Bag></dc:subject>
              <dc:publisher><rdf:Bag><rdf:li>출판사</rdf:li></rdf:Bag></dc:publisher>
              <dc:date><rdf:Seq><rdf:li>2017-02-28T00:00:00</rdf:li></rdf:Seq></dc:date>
            </rdf:Description>
            <rdf:Description xmlns:calibre="http://calibre-ebook.com/xmp-namespace"
              xmlns:calibreSI="http://calibre-ebook.com/xmp-namespace-series-index"
              calibre:series="아저씨가 미녀" calibreSI:series_index="1.00" rdf:about=""/>
            <rdf:Description xmlns:cbb="https://daydreamrabbit.github.io/comic-book-butler/xmp/1.0/" rdf:about="">
              <cbb:localizedSeries>おっさんがびじょ。</cbb:localizedSeries>
              <cbb:count>2</cbb:count>
              <cbb:webUrls><rdf:Bag><rdf:li>https://example.com/book</rdf:li></rdf:Bag></cbb:webUrls>
            </rdf:Description>
          </rdf:RDF>
        </x:xmpmeta>'''.encode('utf-8')

        metadata = parse_pdf_xmp_metadata(xmp)

        self.assertEqual(metadata['title'], '1권')
        self.assertEqual(metadata['author'], '야마다 마루')
        self.assertEqual(metadata['summary'], '책 설명')
        self.assertEqual(metadata['publisher'], '출판사')
        self.assertEqual(metadata['genre'], '라이트노벨, 해외라이트노벨')
        self.assertNotIn('tags', metadata)
        self.assertEqual(metadata['release_date'], '2017-02-28')
        self.assertEqual(metadata['document_series_name'], '아저씨가 미녀')
        self.assertEqual(metadata['document_volume_index'], 1.0)
        self.assertEqual(metadata['document_volume_count'], 2)
        self.assertEqual(metadata['localized_series'], 'おっさんがびじょ。')
        self.assertEqual(metadata['link'], 'https://example.com/book')

    def test_pdf_xmp_explicit_genre_and_tags_override_subject_fallback(self):
        xmp = '''<x:xmpmeta xmlns:x="adobe:ns:meta/">
          <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
            <rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/"
              xmlns:cbb="https://example.com/book-metadata" rdf:about="">
              <dc:subject><rdf:Bag><rdf:li>fallback subject</rdf:li></rdf:Bag></dc:subject>
              <cbb:genre><rdf:Bag><rdf:li>Fantasy</rdf:li><rdf:li>Romance</rdf:li></rdf:Bag></cbb:genre>
              <cbb:tags><rdf:Bag><rdf:li>Magic</rdf:li><rdf:li>School</rdf:li></rdf:Bag></cbb:tags>
            </rdf:Description>
          </rdf:RDF>
        </x:xmpmeta>'''

        metadata = parse_pdf_xmp_metadata(xmp)

        self.assertEqual(metadata['genre'], 'Fantasy, Romance')
        self.assertEqual(metadata['tags'], 'Magic, School')

    def test_pdf_info_keywords_remain_tags_when_xmp_only_has_subject(self):
        class FakePdf:
            def get_metadata_dict(self):
                return {'Keywords': 'Owned, Digital'}

        from tools.scanner.metadata.document_metadata import parse_pdf_document_metadata

        metadata = parse_pdf_document_metadata(FakePdf(), {
            'genre': 'Light Novel, Fantasy',
        })

        self.assertEqual(metadata['genre'], 'Light Novel, Fantasy')
        self.assertEqual(metadata['tags'], 'Owned, Digital')

    def test_pdf_xmp_rejects_malformed_and_oversized_packets(self):
        self.assertEqual(parse_pdf_xmp_metadata(b'<rdf:RDF>'), {})
        self.assertEqual(parse_pdf_xmp_metadata(b'x' * (8 * 1024 * 1024 + 1)), {})

    def test_pdf_xmp_stream_is_decoded_from_real_pdf(self):
        from pypdf import PdfWriter
        from pypdf.generic import DecodedStreamObject, NameObject

        xmp = b'''<x:xmpmeta xmlns:x="adobe:ns:meta/">
          <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">
            <rdf:Description xmlns:dc="http://purl.org/dc/elements/1.1/" rdf:about="">
              <dc:title><rdf:Alt><rdf:li xml:lang="x-default">PDF XMP title</rdf:li></rdf:Alt></dc:title>
              <dc:subject><rdf:Bag><rdf:li>Novel</rdf:li></rdf:Bag></dc:subject>
            </rdf:Description>
          </rdf:RDF>
        </x:xmpmeta>'''
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'xmp.pdf'
            writer = PdfWriter()
            writer.add_blank_page(width=100, height=100)
            stream = DecodedStreamObject()
            stream.set_data(xmp)
            stream.update({NameObject('/Type'): NameObject('/Metadata'), NameObject('/Subtype'): NameObject('/XML')})
            writer._root_object[NameObject('/Metadata')] = writer._add_object(stream)
            with path.open('wb') as output:
                writer.write(output)

            metadata = parse_embedded_metadata(str(path), 'pdf')

        self.assertEqual(metadata['title'], 'PDF XMP title')
        self.assertEqual(metadata['genre'], 'Novel')


if __name__ == '__main__':
    unittest.main()
