import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.lazy_scan_progress import advance_lazy_scan_progress_state
from repositories.sqlite.scanner_queue_repository import ScannerQueueRepository


class LazyScanProgressTests(unittest.TestCase):
    def test_progress_accumulates_across_subprocess_batches(self):
        state, reduction = advance_lazy_scan_progress_state(None, 27097)
        self.assertEqual((state, reduction), ({'total': 27097, 'remaining': 27097}, 0))

        state, reduction = advance_lazy_scan_progress_state(state, 27032)
        self.assertEqual((state, reduction), ({'total': 27097, 'remaining': 27032}, 65))

        state, reduction = advance_lazy_scan_progress_state(state, 27010)
        self.assertEqual((state, reduction), ({'total': 27097, 'remaining': 27010}, 87))

    def test_new_candidates_preserve_prior_completion(self):
        previous = {'total': 27097, 'remaining': 27010}

        state, reduction = advance_lazy_scan_progress_state(previous, 27015)

        self.assertEqual(state, {'total': 27102, 'remaining': 27015})
        self.assertEqual(reduction, 87)

    def test_scanner_task_kwargs_can_persist_lazy_progress(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            database_path = Path(temp_dir) / 'scanner_tasks.sqlite'

            def connect(_db_type):
                connection = sqlite3.connect(database_path)
                connection.row_factory = sqlite3.Row
                return connection

            connection = connect('general')
            connection.execute(
                'CREATE TABLE scanner_tasks (id INTEGER PRIMARY KEY, kwargs TEXT, status TEXT)'
            )
            connection.execute(
                'INSERT INTO scanner_tasks (id, kwargs, status) VALUES (?, ?, ?)',
                (7, json.dumps({'db_type': 'general'}), 'running'),
            )
            connection.commit()
            connection.close()

            with patch(
                'repositories.sqlite.scanner_queue_repository.database.get_connection',
                side_effect=connect,
            ):
                updated = ScannerQueueRepository.update_task_kwargs(7, {
                    'db_type': 'general',
                    '_lazy_scan_progress': {
                        'general': {'total': 100, 'remaining': 75},
                    },
                })
                kwargs = ScannerQueueRepository.get_task_kwargs(7)

        self.assertTrue(updated)
        self.assertEqual(kwargs['db_type'], 'general')
        self.assertEqual(kwargs['_lazy_scan_progress']['general'], {'total': 100, 'remaining': 75})


if __name__ == '__main__':
    unittest.main()
