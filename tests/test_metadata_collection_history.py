import tempfile
import unittest
import os
import time
from unittest.mock import patch
from services.metadata_collection_history import record_event, get_history, connection


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, BOOKOASIS_METADATA_HISTORY_DB=os.path.join(self.tmp.name, 'history.db'))
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def event(self, event, **details):
        record_event('test', 'general', 19, '테스트', event, details)

    def test_pagination_search_and_repeated_results(self):
        for i in range(51):
            self.event('item_started', book_id=i, title=f'작품 {i}')
            self.event('item_result', book_id=i, title=f'작품 {i}', status='applied')
        self.assertEqual(len(get_history('test')['items']), 50)
        self.assertEqual(len(get_history('test', page=2)['items']), 1)
        self.assertEqual(get_history('test', query='작품 50')['total'], 1)
        self.assertEqual(get_history('test', query="%' OR 1=1 --")['total'], 0)
        self.assertEqual(get_history(library_id=20)['total'], 0)
        self.assertEqual(get_history(query='작품 50')['total'], 1)

    def test_failure_keeps_counts_and_finishes_current_item(self):
        self.event('progress', completed=3, total=4, matched=2, updated=2)
        self.event('item_started', book_id=1, title='진행 작품')
        self.assertEqual(get_history('test')['run']['current_title'], '진행 작품')
        self.event('failed')
        result = get_history('test')
        self.assertEqual(result['run']['processed'], 3)
        self.assertEqual(result['run']['current_title'], '')
        self.assertEqual(result['items'][0]['status'], 'failed')

    def test_retention_and_stale_run(self):
        self.event('item_started', book_id=1, title='중단')
        with connection() as db:
            db.execute('UPDATE runs SET updated=?', (time.time()-90000,))
        self.assertEqual(get_history('test')['run']['status'], 'interrupted')
        with connection() as db:
            db.execute('UPDATE runs SET started=?', (time.time()-31*86400,))
        self.assertIsNone(get_history('test'))
        with connection() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM entries').fetchone()[0], 0)

    def test_clear_removes_empty_job(self):
        self.event('started')
        self.event('clear')
        self.assertEqual(get_history()['total'], 0)


if __name__ == '__main__':
    unittest.main()
