import unittest
import time
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
from services import series_service as module
from services.series_service import SeriesService


class SeriesListIndexTests(unittest.TestCase):
    def setUp(self):
        module._LIST_QUERY_CACHE.clear()
        module._TOTALS_CACHE.clear()
        self.scope = patch.object(module, '_list_security_scope', return_value=((7,), ()))
        self.sync = patch.object(module, '_sync_local_books_cache_with_shared_epoch')
        self.scope.start()
        self.sync.start()
        # These tests exercise the retained search/complex-list index path.
        rating_page = patch.object(module.rated_series_page, 'supported', return_value=False)
        rating_page.start()
        self.addCleanup(rating_page.stop)
        self.refresh = patch.object(module, '_refresh_list_index_later')
        self.refresh.start()
        self.addCleanup(self.refresh.stop)
        self.addCleanup(self.scope.stop)
        self.addCleanup(self.sync.stop)
        self.addCleanup(module._LIST_QUERY_CACHE.clear)
        self.addCleanup(module._TOTALS_CACHE.clear)

    def entries(self, count=200):
        return [dict(series_name=f'Book {i:06}', library_id=7, anchor_dir='/books',
                     _source_series_name=f'Book {i:06}', book_count=1) for i in range(count)]

    def call(self, page=1):
        return SeriesService.get_books_list('general', 7, page, 30, '',
            user_id=1, role='member', content_rating_max=18)

    def test_totals_still_work_when_index_exceeds_cache_budget(self):
        entries = self.entries()
        with patch.object(module, '_LIST_QUERY_CACHE', module.BoundedCache(120, max_bytes=1)), \
             patch.object(module.SeriesRepository, 'fetch_books_for_grouping', return_value=[]), \
             patch.object(module, '_build_series_entries', return_value=entries), \
             patch('utils.redis_helper.get_redis_client', return_value=None):
            totals = SeriesService.get_books_totals('general',7,user_id=1,content_rating_max=18)
            self.assertEqual(totals, dict(total_series_count=200,total_book_count=200))

    def test_progress_is_fresh_and_only_visible_page_is_hydrated(self):
        entries = self.entries()
        with patch.object(module.SeriesRepository, 'fetch_books_for_grouping', return_value=[]) as fetch, \
             patch.object(module, '_build_series_entries', return_value=entries), \
             patch.object(module, '_apply_series_reading_progress', side_effect=lambda db, rows, user: rows) as progress:
            first = self.call()
            key = next(iter(module._LIST_QUERY_CACHE))
            module._LIST_QUERY_CACHE[key] = (time.time() - 60, entries)
            second = self.call()
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual([len(call.args[1]) for call in progress.call_args_list], [31, 31])
            self.assertNotIn('_source_series_name', first[0])
            self.assertIn('_source_series_name', entries[0])
            self.assertIsNot(first[0], second[0])

    def test_parallel_cold_requests_build_once(self):
        def slow_fetch(*args, **kwargs):
            time.sleep(.03)
            return []
        with patch.object(module.SeriesRepository, 'fetch_books_for_grouping', side_effect=slow_fetch) as fetch, \
             patch.object(module, '_build_series_entries', return_value=self.entries()), \
             patch.object(module, '_apply_series_reading_progress', side_effect=lambda db, rows, user: rows):
            with ThreadPoolExecutor(max_workers=4) as pool:
                pages = list(pool.map(lambda _: self.call(), range(4)))
            self.assertEqual(fetch.call_count, 1)
            self.assertTrue(all(len(page) == 31 for page in pages))

    def test_permission_or_rating_scope_change_cannot_reuse_old_index(self):
        with patch.object(module.SeriesRepository, 'fetch_books_for_grouping', return_value=[]) as fetch, \
             patch.object(module, '_build_series_entries', return_value=self.entries()), \
             patch.object(module, '_apply_series_reading_progress', side_effect=lambda db, rows, user: rows):
            self.call()
            with patch.object(module, '_list_security_scope', return_value=((), ('restricted',))):
                self.call()
            self.assertEqual(fetch.call_count, 2)

    def test_totals_share_the_metadata_index_without_requerying_all_books(self):
        with patch.object(module.SeriesRepository, 'fetch_books_for_grouping', return_value=[]) as fetch, \
             patch.object(module, '_build_series_entries', return_value=self.entries()), \
             patch.object(module, '_apply_series_reading_progress', side_effect=lambda db, rows, user: rows), \
             patch('utils.redis_helper.get_redis_client', return_value=None):
            self.call()
            totals = SeriesService.get_books_totals('general', 7, user_id=1, role='member', content_rating_max=18)
            self.assertEqual(fetch.call_count, 1)
            self.assertEqual(totals, dict(total_series_count=200, total_book_count=200))

    def test_index_cache_is_bounded(self):
        for i in range(20):
            module._store_list_index((i,), [])
        self.assertLessEqual(len(module._LIST_QUERY_CACHE), 8)

    def test_invalidation_during_rebuild_does_not_publish_stale_index(self):
        generation = module._INDEX_GENERATION
        module._INDEX_GENERATION += 1
        module._store_list_index(('stale',), self.entries(), generation)
        self.assertNotIn(('stale',), module._LIST_QUERY_CACHE)

    def test_background_refresh_is_deduplicated_and_bounded(self):
        self.refresh.stop()
        module._INDEX_REFRESH_PENDING.clear()
        jobs = []
        with patch.object(module._INDEX_REFRESH_POOL, 'submit', side_effect=lambda job: jobs.append(job)), \
             patch.object(SeriesService, 'get_books_list') as rebuild:
            for key in [('a',), ('a',), ('b',), ('c',)]:
                module._refresh_list_index_later(key, time.time() - 180, {'db_type': 'general', 'library_id': 7})
            self.assertEqual(len(jobs), 2)
            for job in jobs:
                job()
            self.assertEqual(len(module._INDEX_REFRESH_PENDING), 0)
            self.assertTrue(all(call.kwargs['_refresh_index'] for call in rebuild.call_args_list))


if __name__ == '__main__':
    unittest.main()
