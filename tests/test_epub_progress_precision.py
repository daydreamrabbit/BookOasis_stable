import unittest
from unittest.mock import patch

from services.reading_progress_service import ReadingProgressService, InMemoryProgressBuffer


class EpubProgressPrecisionTests(unittest.TestCase):
    def test_visible_percent_is_used_instead_of_completed_spine(self):
        book = dict(file_format='epub', total_pages=100, title='', author='',
                    publisher='', series_name='', created_at=None)
        with patch('services.reading_progress_service.ReadingProgressRepository') as repo, \
             patch('services.reading_progress_service.get_redis_client', return_value=None), \
             patch('utils.redis_helper.redis_delete_pattern'), \
             patch('services.reading_progress_service.dispatch_standard_book_event'), \
             patch.object(InMemoryProgressBuffer, 'get', return_value=None), \
             patch.object(InMemoryProgressBuffer, 'set') as save:
            repo.get_book_for_progress.return_value = book
            repo.get_progress_only.return_value = None
            for db_type in ('general', 'adult'):
                for percent, expected in [(0, 0), (0.2, 0), (2, 2), (50, 50), (100, 100)]:
                    ReadingProgressService.record_progress(db_type, 123, 0, 3,
                        epub_session={'percent': percent, 'index': 0, 'cfi': 'anchor'})
                    payload = save.call_args.args[-1]
                    self.assertEqual(payload['pages_read'], expected)
                    self.assertEqual(payload['last_epub_percent'], expected)
                    self.assertEqual(payload['last_epub_cfi'], 'anchor')
                    self.assertEqual(payload['is_completed'], int(expected >= 95))
            # Older clients without a precise location remain compatible.
            ReadingProgressService.record_progress('general', 123, 0, 3)
            self.assertEqual(save.call_args.args[-1]['pages_read'], 33)
            repo.update_book_total_pages.assert_not_called()


if __name__ == '__main__':
    unittest.main()
