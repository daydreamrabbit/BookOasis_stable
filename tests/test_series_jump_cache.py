import unittest
from unittest.mock import patch

from services import series_service
from services.series_service import SeriesService


class SeriesJumpCacheTests(unittest.TestCase):
    def setUp(self):
        self.original_cache = dict(series_service._LIST_QUERY_CACHE)
        series_service._LIST_QUERY_CACHE.clear()

    def tearDown(self):
        series_service._LIST_QUERY_CACHE.clear()
        series_service._LIST_QUERY_CACHE.update(self.original_cache)

    def test_jump_returns_target_page_and_reuses_list_cache(self):
        entries = [
            {'series_name': '[Manga] Alpha', 'representative_title': 'Alpha', 'id': 1},
            {'series_name': 'Beta', 'representative_title': 'Beta', 'id': 2},
            {'series_name': 'Bravo', 'representative_title': 'Bravo', 'id': 3},
        ]
        jump_entries = [
            {**entry, '_representative_id': entry['id'], '_source_rows': [{}]} for entry in entries
        ]

        with (
            patch.object(series_service, '_sync_local_books_cache_with_shared_epoch'),
            patch.object(series_service.SeriesRepository, 'fetch_books_for_grouping', return_value=[])
            as fetch_rows,
            patch.object(
                series_service.SeriesRepository,
                'fetch_books_by_ids',
                side_effect=lambda _db_type, ids, **_kwargs: [entries[index - 1] for index in ids],
            ) as fetch_page_rows,
            patch.object(series_service, '_build_series_jump_entries', return_value=jump_entries),
            patch.object(
                series_service,
                '_build_series_entries',
                side_effect=lambda _db_type, rows: entries[:len(rows)],
            ),
        ):
            result = SeriesService.find_jump_position(
                'general', 7, '', 'asc', 'B', 2, user_id=42, role='member'
            )
            page = SeriesService.get_books_list(
                'general', 7, 1, 2, '', 'asc', user_id=42, role='member'
            )

        self.assertTrue(result['found'])
        self.assertEqual(result['page'], 1)
        self.assertEqual(result['offset_in_page'], 1)
        self.assertEqual(result['series'], entries[:2])
        self.assertTrue(result['has_more'])
        self.assertEqual(page, entries[:3])
        fetch_rows.assert_called_once()
        self.assertEqual(fetch_page_rows.call_count, 2)


if __name__ == '__main__':
    unittest.main()
