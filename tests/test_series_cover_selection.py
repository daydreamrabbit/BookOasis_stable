import unittest

from repositories.series_metadata_utils import select_series_cover_row


class SeriesCoverSelectionTests(unittest.TestCase):
    def test_prefers_volume_one_over_an_earlier_inserted_later_volume(self):
        rows = [
            {'id': 10, 'title': '소드 아트 온라인 29권', 'cover_image': '29.webp'},
            {'id': 11, 'title': '소드 아트 온라인 01권', 'cover_image': '01.webp'},
        ]

        self.assertEqual(select_series_cover_row(rows)['cover_image'], '01.webp')

    def test_uses_earliest_available_volume_when_volume_one_has_no_cover(self):
        rows = [
            {'id': 10, 'title': 'Series 29권', 'cover_image': '29.webp'},
            {'id': 11, 'title': 'Series 01권', 'cover_image': ''},
            {'id': 12, 'title': 'Series 03권', 'cover_image': '03.webp'},
        ]

        self.assertEqual(select_series_cover_row(rows)['cover_image'], '03.webp')

    def test_ignores_no_cover_marker(self):
        self.assertIsNone(select_series_cover_row([
            {'id': 1, 'title': 'Series 01권', 'cover_image': 'NO_COVER'},
        ]))


if __name__ == '__main__':
    unittest.main()
