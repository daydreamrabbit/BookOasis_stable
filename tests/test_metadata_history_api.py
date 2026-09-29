import os
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from api.routes.system_routes import system_bp
from services.metadata_collection_history import record_event


class HistoryApiTests(unittest.TestCase):
    def test_authorization_and_validation(self):
        app = Flask(__name__)
        app.secret_key = 'test-only'
        app.register_blueprint(system_bp)
        client = app.test_client()
        path = '/api/system/metadata-history'
        with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, BOOKOASIS_METADATA_HISTORY_DB=os.path.join(folder,'history.db')):
            self.assertEqual(client.get(path).status_code, 401)
            with client.session_transaction() as session:
                session['user_id'] = 1
                session['role'] = 'user'
            self.assertEqual(client.get(path).status_code, 403)
            with client.session_transaction() as session:
                session['role'] = 'admin'
            record_event('test', 'general', 19, '테스트', 'started', {})
            result = client.get(path)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json['total'], 1)
            self.assertEqual(result.headers['Cache-Control'], 'no-store')
            self.assertEqual(client.get(path+'?page=invalid').status_code, 400)
            self.assertEqual(client.get(path+'?run_id=missing').status_code, 404)
