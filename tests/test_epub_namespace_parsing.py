import os
import tempfile
import unittest
import zipfile

from services.text_epub_content_service import (
    EPUB_CHAPTER_CACHE_VERSION,
    EPUB_META_CACHE_VERSION,
    EPUB_SPINE_CACHE_VERSION,
    TextEpubContentService,
)


class EpubNamespaceParsingTests(unittest.TestCase):
    def _create_prefixed_epub(self, target_path):
        container_xml = '''<?xml version="1.0"?>
        <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
          <rootfiles>
            <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
          </rootfiles>
        </container>'''
        opf_xml = '''<?xml version="1.0" encoding="utf-8"?>
        <ns0:package xmlns:dc="http://purl.org/dc/elements/1.1/"
                     xmlns:ns0="http://www.idpf.org/2007/opf" version="2.0">
          <ns0:metadata><dc:title>Prefixed EPUB</dc:title></ns0:metadata>
          <ns0:manifest>
            <ns0:item id="chapter" href="Text/chapter.xhtml" media-type="application/xhtml+xml"/>
          </ns0:manifest>
          <ns0:spine><ns0:itemref idref="chapter"/></ns0:spine>
        </ns0:package>'''
        chapter_xhtml = '''<?xml version="1.0" encoding="utf-8"?>
        <html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter</h1><p>본문</p></body></html>'''
        with zipfile.ZipFile(target_path, 'w') as archive:
            archive.writestr('mimetype', 'application/epub+zip')
            archive.writestr('META-INF/container.xml', container_xml)
            archive.writestr('OEBPS/content.opf', opf_xml)
            archive.writestr('OEBPS/Text/chapter.xhtml', chapter_xhtml)

    def test_prefixed_opf_namespace_exposes_spine_and_chapter_content(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            epub_path = os.path.join(temp_dir, 'prefixed.epub')
            self._create_prefixed_epub(epub_path)

            meta, meta_error = TextEpubContentService.get_epub_meta(
                epub_path, None, 'general'
            )
            chapter, chapter_error = TextEpubContentService.get_epub_chapter(
                epub_path, None, 'general', 0
            )

        self.assertIsNone(meta_error)
        self.assertEqual(meta['title'], 'Prefixed EPUB')
        self.assertEqual(meta['total_chapters'], 1)
        self.assertEqual(meta['spine_itemrefs'], ['Text/chapter.xhtml'])
        self.assertIsNone(chapter_error)
        self.assertEqual(chapter['total_chapters'], 1)
        self.assertIn('<p>본문</p>', chapter['content'])

    def test_namespace_fix_uses_new_cache_generations(self):
        self.assertEqual(EPUB_META_CACHE_VERSION, 'v3')
        self.assertEqual(EPUB_SPINE_CACHE_VERSION, 'v2')
        self.assertEqual(EPUB_CHAPTER_CACHE_VERSION, 'v3')
        self.assertIn(':v2:', TextEpubContentService._spine_cache_key('general', 1))
        self.assertIn(':v3:', TextEpubContentService._chapter_cache_key('general', 1, 0))


if __name__ == '__main__':
    unittest.main()
