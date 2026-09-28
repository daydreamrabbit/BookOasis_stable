import ast
import pathlib
import sqlite3
import types
import unittest
from unittest.mock import patch, Mock

ROOT = pathlib.Path(__file__).resolve().parents[1]


class ScanEnqueueGuardTests(unittest.TestCase):
    def test_repository_preserves_active_jobs_even_when_forced(self):
        for engine in ('sqlite', 'mariadb'):
            source = ast.parse((ROOT / 'repositories' / engine / 'scanner_queue_repository.py').read_text())
            cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
            method = next(n for n in cls.body if getattr(n, 'name', '') == 'update_task_to_pending')
            cls.body = [method]
            for status in ('pending', 'running', 'exit_pending', 'completed'):
                with self.subTest(engine=engine, status=status):
                    db = sqlite3.connect(':memory:')
                    db.execute('CREATE TABLE scanner_tasks (id INTEGER, task_type, status, kwargs, stage, enqueue_at, started_at, finished_at, error_message)')
                    db.execute("INSERT INTO scanner_tasks VALUES (1,'library_scan',?,'original','exploring','old','started',NULL,NULL)", (status,))
                    class Cursor:
                        def execute(self, sql, params):
                            self.result = db.execute(sql.replace('%s', '?'), params)
                        @property
                        def rowcount(self):
                            return self.result.rowcount
                    connection = types.SimpleNamespace(cursor=Cursor, commit=db.commit, rollback=db.rollback, close=lambda: None)
                    ns = {'database': types.SimpleNamespace(get_connection=lambda _: connection)}
                    exec(compile(ast.Module(body=[cls], type_ignores=[]), '<repository>', 'exec'), ns)
                    result = ns['ScannerQueueRepository'].update_task_to_pending(1, 'library_scan', 'new', 'now', force_requeue=True)
                    row = db.execute('SELECT status,kwargs,stage,started_at FROM scanner_tasks').fetchone()
                    if status == 'completed':
                        self.assertTrue(result)
                        self.assertEqual(row[0], 'pending')
                    else:
                        self.assertFalse(result)
                        self.assertEqual(row, (status, 'original', 'exploring', 'started'))
                    db.close()

    def test_enqueue_does_not_insert_after_race_or_force_active_job(self):
        import datetime, json
        source = ast.parse((ROOT / 'services/scanner_queue.py').read_text())
        cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if getattr(n, 'name', '') == 'enqueue')
        method.decorator_list = []
        ns = {'datetime': datetime, 'json': json}
        exec(compile(ast.Module(body=[method], type_ignores=[]), '<enqueue>', 'exec'), ns)
        for status in ('running', 'pending', 'exit_pending', 'completed'):
            repo = Mock()
            repo.get_task_by_key.return_value = {'id': 1, 'status': status}
            repo.update_task_to_pending.return_value = False
            module = types.ModuleType('repositories.scanner_queue_repository')
            module.ScannerQueueRepository = repo
            owner = Mock()
            owner._get_task_key.return_value = 'library_scan_general_19'
            with patch.dict('sys.modules', {'repositories.scanner_queue_repository': module}):
                self.assertFalse(ns['enqueue'](owner, 'library_scan', force_requeue=True))
            repo.insert_task.assert_not_called()
            if status != 'completed':
                repo.update_task_to_pending.assert_not_called()


if __name__ == '__main__':
    unittest.main()
