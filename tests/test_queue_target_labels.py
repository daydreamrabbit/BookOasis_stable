import ast
import pathlib
import types
import unittest
from unittest.mock import Mock, patch
from flask import Flask, jsonify

ROOT = pathlib.Path(__file__).resolve().parents[1]

def function(path, name, scope):
    tree = ast.parse((ROOT / path).read_text())
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node], type_ignores=[]), path, 'exec'), scope)
    return scope[name]

class QueueTargetTests(unittest.TestCase):
    def test_labels(self):
        route = function('api/routes/system_routes.py', 'get_system_queue_status',
                         {'jsonify': jsonify, 'get_library_name': lambda *_: '[만화] 연재'})
        tasks = [dict(type='lazy_scan', kwargs=k) for k in (
            {}, {'db_type':'general','library_id':2,'series_name':'담배 <고양이>'},
            {'db_type':'adult','library_id':2}, {'db_type':'general','book_ids':[1,2]})]
        queue = Mock()
        queue.get_queue_status.return_value = dict(running=tasks[0], pending=tasks[1:])
        with Flask(__name__).app_context(), patch.dict('sys.modules', {
            'services.scanner_queue': types.SimpleNamespace(scanner_queue=queue)}):
            data = route().get_json()['queue']
        self.assertIn('전체 시스템', data['running']['library_name'])
        self.assertIn('담배 <고양이>', data['pending'][0]['library_name'])
        self.assertIn('adult', data['pending'][1]['library_name'])
        self.assertIn('2권', data['pending'][2]['library_name'])
        self.assertTrue(all('전체 시스템' not in t['library_name'] for t in data['pending']))

    def test_existing_requests_and_safe_overlap(self):
        enqueue = function('api/routes/scan_routes.py', '_enqueue_targeted_lazy_scan', {})
        for existing, full, auto, writes in (
            ({'status':'pending'}, None, False, 0),
            ({'status':'running'}, None, False, 0),
            (None, {'status':'pending','started_at':None}, True, 0),
            (None, {'status':'pending','started_at':'2026-10-01'}, True, 1),
            (None, {'status':'running'}, True, 1),
            (None, {'status':'pending','started_at':None}, False, 1),
        ):
            queue, repo = Mock(), Mock()
            repo.get_task_by_key.side_effect = lambda key: full if key == 'lazy_scan' else existing
            queue._get_task_key.return_value = 'target'
            queue.enqueue.return_value = True
            with self.subTest(existing=existing, full=full, auto=auto), patch.dict('sys.modules', {
                'services.scanner_queue':types.SimpleNamespace(scanner_queue=queue),
                'repositories.scanner_queue_repository':types.SimpleNamespace(ScannerQueueRepository=repo)}):
                self.assertTrue(enqueue('general', auto_followup=auto, library_id=2, series_name='story'))
                self.assertEqual(queue.enqueue.call_count, writes)
