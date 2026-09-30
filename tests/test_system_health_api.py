import ast
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

from flask import Flask, jsonify, request, session, current_app, send_from_directory
from services.library_events import library_event_stream
from services.system_health_service import SystemHealthService


class SystemHealthApiTests(unittest.TestCase):
    def test_favicon_is_public_png_and_supports_cache_validation(self):
        import os
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'api/routes/system_routes.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'favicon')
        function.decorator_list = []
        scope = dict(current_app=current_app, send_from_directory=send_from_directory, os=os)
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<favicon-test>', 'exec'), scope)
        app = Flask(__name__, static_folder=str(root / 'static'))
        auth_tree = ast.parse((root / 'api/auth.py').read_text())
        auth_function = next(n for n in auth_tree.body if isinstance(n, ast.FunctionDef) and n.name == 'check_authentication')
        auth_function.decorator_list = []
        auth_scope = dict(request=request, url_for=lambda *_: '/login')
        exec(compile(ast.Module(body=[auth_function], type_ignores=[]), '<auth-test>', 'exec'), auth_scope)
        app.before_request(auth_scope['check_authentication'])
        app.add_url_rule('/favicon.ico', view_func=scope['favicon'])
        with app.test_client() as client:
            response = client.get('/favicon.ico')
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.mimetype, 'image/png')
            self.assertEqual(response.data[:8], b'\x89PNG\r\n\x1a\n')
            with client.get('/favicon.ico', headers={'If-None-Match':response.headers['ETag']}) as cached:
                self.assertEqual(cached.status_code, 304)
            response.close()

    def test_status_keeps_scan_fields_and_only_admin_gets_warnings(self):
        # Use the real endpoint body without importing app startup/worker services.
        path = Path(__file__).resolve().parents[1] / 'api/routes/system_routes.py'
        tree = ast.parse(path.read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'get_system_status')
        function.decorator_list = []
        scope = dict(jsonify=jsonify, request=request, session=session,
                     database=types.SimpleNamespace(is_db_tuning=lambda _: False),
                     get_library_name=lambda *_: 'Library')
        exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), 'exec'), scope)
        queue = Mock()
        queue.get_queue_status.side_effect = lambda: {'running': None, 'pending': []}
        metadata = [{'status': 'running', 'library_name': 'Metadata', 'stage': '2/3', 'kwargs': {}}]
        stubs = {
            'services.scanner_queue': types.SimpleNamespace(scanner_queue=queue),
            'services.metadata_scan_activity': types.SimpleNamespace(list_metadata_scan_activities=lambda: metadata),
        }
        app = Flask(__name__)
        app.secret_key = 'isolated-test'
        for role in ('admin', 'member'):
            with self.subTest(role=role), app.test_request_context('/api/system/status'), \
                    patch.dict('sys.modules', stubs), \
                    patch.object(SystemHealthService, 'get_active_warnings', return_value=[{'key': 'warning'}]) as warnings:
                session['role'] = role
                response = scope['get_system_status']()
                self.assertEqual(response.status_code, 200)
                data = response.get_json()
                self.assertTrue(data['is_active'])
                self.assertEqual(data['raw_status']['metadata_activities'], metadata)
                self.assertEqual(data['system_warnings'], [{'key': 'warning'}] if role == 'admin' else [])
                self.assertEqual(warnings.call_count, int(role == 'admin'))

    def test_health_events_are_admin_only_and_keep_library_events(self):
        for admin in (True, False):
            subscription = Mock()
            subscription.get_message.side_effect = [
                None,
                {'type': 'message', 'data': json.dumps({'type': 'system_health'})},
                {'type': 'message', 'data': json.dumps({'type': 'general', 'revision': '2'})},
            ]
            client = Mock()
            client.pubsub.return_value = subscription
            with self.subTest(admin=admin), patch('services.series_service._read_shared_books_cache_epoch', return_value='1'):
                stream = library_event_stream(client, include_health=admin)
                self.assertIn('event: snapshot', next(stream))
                if admin:
                    self.assertIn('event: system-health', next(stream))
                self.assertIn('event: changed', next(stream))
                stream.close()
                subscription.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
