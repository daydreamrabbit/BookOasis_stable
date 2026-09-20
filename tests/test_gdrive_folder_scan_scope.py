import json
import os
import re
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlparse

from utils.drive_helper import fetch_gdrive_folder_files


class _JsonResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode('utf-8')

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return self.payload


class GDriveFolderScanScopeTests(unittest.TestCase):
    def test_target_subpath_walks_only_the_requested_series_folder(self):
        folder_items = {
            'share-folder-12345678901234567890': [
                {
                    'id': 'series-folder-12345678901234567890',
                    'name': 'Series',
                    'mimeType': 'application/vnd.google-apps.folder',
                },
                {
                    'id': 'other-folder-45678901234567890123',
                    'name': 'Other',
                    'mimeType': 'application/vnd.google-apps.folder',
                },
                {'id': 'root-book', 'name': 'Root Book.cbz', 'mimeType': 'application/octet-stream'},
            ],
            'series-folder-12345678901234567890': [
                {'id': 'series-book', 'name': 'Series 01.cbz', 'mimeType': 'application/octet-stream'},
            ],
            'other-folder-45678901234567890123': [
                {'id': 'other-book', 'name': 'Other 01.cbz', 'mimeType': 'application/octet-stream'},
            ],
        }
        requested_folders = []

        def fake_urlopen(request, timeout=None):
            query = parse_qs(urlparse(request.full_url).query).get('q', [''])[0]
            match = re.search(r"'([^']+)' in parents", query)
            folder_id = match.group(1)
            requested_folders.append(folder_id)
            return _JsonResponse({'files': folder_items.get(folder_id, [])})

        with patch.dict(os.environ, {'GDRIVE_API_KEY': 'test-key'}), \
             patch('dotenv.load_dotenv'), \
             patch('urllib.request.urlopen', side_effect=fake_urlopen):
            files = fetch_gdrive_folder_files(
                'https://drive.google.com/drive/folders/share-folder-12345678901234567890',
                target_subpath='Series',
            )

        self.assertEqual([file['name'] for file in files], ['Series 01.cbz'])
        self.assertEqual(requested_folders, [
            'share-folder-12345678901234567890',
            'series-folder-12345678901234567890',
        ])
        self.assertEqual(files[0]['rel_folder'], 'Series')


if __name__ == '__main__':
    unittest.main()
