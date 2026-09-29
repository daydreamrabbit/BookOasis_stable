import ast
import pathlib
import sqlite3
import types
import unittest
from unittest.mock import Mock, patch
from services import scanner_queue as queue


class LazyYieldTests(unittest.TestCase):
    def test_batch_yield_is_distinct_from_completion(self):
        from repositories.scanner_queue_repository import ScannerQueueRepository as repo
        for code, priority, expected in [(10, True, True), (0, False, False)]:
            process = Mock(returncode=code)
            process.communicate.return_value = ('', '')
            with patch.object(queue, 'stop_requested', False), \
                 patch.object(queue.subprocess, 'Popen', return_value=process), \
                 patch.object(repo, 'update_task_status'), \
                 patch.object(repo, 'has_pending_priority_task', return_value=priority):
                self.assertEqual(queue._process_lazy_scan(Mock(), 7), expected)

    def test_unexpected_kill_is_not_success(self):
        process = Mock(returncode=-9)
        process.communicate.return_value = ('', '')
        with patch.object(queue, 'stop_requested', False), \
             patch.object(queue.subprocess, 'Popen', return_value=process):
            with self.assertRaises(RuntimeError):
                queue._process_lazy_scan(Mock(), 7)

    def test_requeue_retains_checkpoint_and_obeys_cancellation_both_backends(self):
        for backend in ('sqlite', 'mariadb'):
            source = ast.parse(pathlib.Path(f'repositories/{backend}/scanner_queue_repository.py').read_text())
            cls = next(n for n in source.body if isinstance(n, ast.ClassDef))
            cls.body = [n for n in cls.body if getattr(n, 'name', '') in ('requeue_yielded_task','get_next_pending_task')]
            for cancel in (0, 1):
                with self.subTest(backend=backend, cancel=cancel):
                    db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
                    db.execute('CREATE TABLE scanner_tasks(id,task_type,task_key,kwargs,status,worker_pid,stage,cancel_requested)')
                    db.execute("INSERT INTO scanner_tasks VALUES(1,'lazy_scan','lazy','checkpoint','exit_pending',99,'working',?)",(cancel,))
                    db.execute("INSERT INTO scanner_tasks VALUES(2,'library_scan','lib','{}','pending',NULL,NULL,0)")
                    class Cursor:
                        def execute(self, sql, params=()): self.result=db.execute(sql.replace('%s','?'),params)
                        def fetchone(self): return self.result.fetchone()
                        @property
                        def rowcount(self): return self.result.rowcount
                    conn=types.SimpleNamespace(cursor=Cursor,commit=db.commit,rollback=db.rollback,close=lambda:None)
                    ns={'database':types.SimpleNamespace(get_connection=lambda _:conn)}
                    exec(compile(ast.Module(body=[cls],type_ignores=[]),'<repo>','exec'),ns)
                    repo=ns['ScannerQueueRepository']
                    self.assertEqual(repo.requeue_yielded_task(1),not cancel)
                    row=db.execute('SELECT * FROM scanner_tasks WHERE id=1').fetchone()
                    self.assertEqual(row['kwargs'],'checkpoint')
                    if not cancel:
                        self.assertEqual(row['status'],'pending');self.assertIsNone(row['worker_pid'])
                        self.assertEqual(repo.get_next_pending_task()['id'],2)
                        db.execute('DELETE FROM scanner_tasks WHERE id=2')
                        self.assertEqual(repo.get_next_pending_task()['id'],1)
                    db.close()

    def test_worker_does_not_record_yield_as_completed(self):
        from repositories.scanner_queue_repository import ScannerQueueRepository as repo
        task={'id':7,'task_type':'lazy_scan','task_key':'lazy_scan','kwargs':'{}'}
        def yielded(*a,**kw):
            queue.stop_requested=True
            return True
        with patch.object(queue,'stop_requested',False), \
             patch.object(queue,'ScannerQueue',return_value=Mock()), \
             patch.object(queue,'_process_lazy_scan',side_effect=yielded), \
             patch.object(repo,'cleanup_stale_tasks',return_value=0), \
             patch.object(repo,'get_next_pending_task',return_value=task), \
             patch.object(repo,'try_acquire_task',return_value=True), \
             patch.object(repo,'requeue_yielded_task',return_value=True) as requeue, \
             patch.object(repo,'update_task_result') as completed, \
             patch('utils.logger.setup_rotating_logger'), \
             patch('utils.redis_helper.redis_brpop',return_value=None), \
             patch('utils.redis_helper.redis_acquire_lock',return_value=None), \
             patch('utils.redis_helper.redis_delete_pattern'), \
             patch('repositories.series_repository.SeriesRepository.rebuild_summary'), \
             patch('services.series_service.SeriesService.invalidate_all_books_cache'):
            queue.run_scanner_worker_loop()
            requeue.assert_called_once_with(7)
            completed.assert_not_called()
