import io
import pathlib
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

from flask import Flask
from services import series_service
from tools import mcp_server
from sample_plugins.metadata.naver_webtoon.naver_webtoon import NaverWebtoonMetadataProvider


class SelectedUpdateRegressions(unittest.TestCase):
    def test_jump_cache_returns_list_and_has_more_and_preserves_old_contract(self):
        key = ('general', 7, '', 'asc', (), (), 42, 'member', '', '', False)
        entries = [{'id': n} for n in range(3)]
        with patch.dict(series_service._LIST_QUERY_CACHE, {}, clear=True), \
             patch.dict(series_service._JUMP_INDEX_CACHE, {key: (time.time(), entries)}, clear=True), \
             patch.object(series_service, '_sync_local_books_cache_with_shared_epoch'), \
             patch.object(series_service, '_build_jump_page_entries', return_value=entries):
            args = ('general', 7, 1, 2, '')
            options = dict(user_id=42, role='member')
            self.assertEqual(series_service.SeriesService.get_books_list(*args, **options), entries)
            self.assertEqual(series_service.SeriesService.get_books_list(*args, **options, return_has_more=True), (entries, True))

    def test_query_cache_contract(self):
        for group_by in ('', 'author'):
            key = ('general', 7, '', 'asc', (), (), 42, 'member', group_by, '', False)
            entries = [{'id': n} for n in range(3)]
            with patch.dict(series_service._LIST_QUERY_CACHE, {key: (time.time(), entries)}, clear=True), \
                 patch.object(series_service, '_sync_local_books_cache_with_shared_epoch'):
                self.assertEqual(series_service.SeriesService.get_books_list('general', 7, 2, 2, '', user_id=42, role='member', group_by=group_by, return_has_more=True), (entries[2:], False))

    def test_invalid_mcp_limits_fail_before_querying(self):
        with patch.object(series_service.SeriesService, 'get_books_list') as query:
            for limit in (-1, 0, True, 1.5, '5', 1001):
                with self.subTest(limit=limit), self.assertRaises(ValueError):
                    mcp_server._search_books_impl('', 'general', 'all', '', '', limit, 'asc')
            query.assert_not_called()

    def test_invalid_webtoon_image_does_not_overwrite_cover_or_update_database(self):
        provider = NaverWebtoonMetadataProvider()
        gateway = MagicMock()
        gateway.fetch_one.return_value = {'series_name': 'Example', 'library_id': 7}
        import hashlib
        filename = 'naverwebtoon_' + hashlib.md5(b'7:Example').hexdigest() + '.webp'
        with tempfile.TemporaryDirectory() as root:
            dest = pathlib.Path(root) / '7' / filename
            dest.parent.mkdir()
            dest.write_bytes(b'existing cover')
            with patch.object(provider, 'get_db_gateway', return_value=gateway), \
                 patch('services.cover_storage_service.get_covers_dir', return_value=root), \
                 patch('urllib.request.urlopen', return_value=io.BytesIO(b'<html>upstream error</html>')):
                success, _ = provider.apply('general', 1, {'cover': 'https://example.test/image'})
            self.assertFalse(success)
            self.assertEqual(dest.read_bytes(), b'existing cover')
            gateway.execute.assert_not_called()

    def test_cover_cache_revalidates_permissions_and_queries_once(self):
        from api.routes.audiobook_routes import audiobook_bp
        from api.routes.video_routes import video_bp
        app = Flask(__name__)
        app.secret_key = 'test-only'
        app.register_blueprint(audiobook_bp)
        app.register_blueprint(video_bp)
        for kind, repo, method in (
            ('audiobooks', 'audiobook_repository.AudiobookRepository', 'get_audiobook_by_id'),
            ('videos', 'video_repository.VideoRepository', 'get_video_by_id'),
        ):
            with self.subTest(kind=kind), app.test_client() as client:
                with client.session_transaction() as session:
                    session['user_id'] = 42
                with patch(f'repositories.{repo}.{method}', return_value={'title': 'Example', 'library_id': 7}) as query, \
                     patch('repositories.category_repository.CategoryRepository.check_user_category_access', return_value=True) as access:
                    response = client.get(f'/api/media/{kind}/1/cover')
                    self.assertEqual(response.status_code, 200)
                    query.assert_called_once()
                    etag = response.headers['ETag']
                    self.assertIn('private', response.headers['Cache-Control'])
                    query.reset_mock()
                    response = client.get(f'/api/media/{kind}/1/cover', headers={'If-None-Match': etag})
                    self.assertEqual(response.status_code, 304)
                    query.assert_called_once()
                    access.return_value = False
                    self.assertEqual(client.get(f'/api/media/{kind}/1/cover', headers={'If-None-Match': etag}).status_code, 403)
                    query.return_value = None
                    query.reset_mock()
                    self.assertEqual(client.get(f'/api/media/{kind}/999/cover').status_code, 403)
                    query.assert_called_once()


if __name__ == '__main__':
    unittest.main()
