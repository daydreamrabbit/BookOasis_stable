from unittest.mock import patch
import pytest
from services import series_service as module


@pytest.fixture
def rows(monkeypatch):
    module._JUMP_INDEX_CACHE.clear()
    module._LIST_QUERY_CACHE.clear()
    monkeypatch.setattr(module, '_sync_local_books_cache_with_shared_epoch', lambda *a: None)
    books = [dict(id=i, library_id=7, series_name=f'Series {i:03}', title=f'Title {i}',
                  file_path=f'/books/{i}/one.txt', file_format='txt') for i in range(1, 206)]
    monkeypatch.setattr(module.SeriesRepository, 'fetch_books_for_grouping', lambda *a, **kw: books)
    yield books
    module._JUMP_INDEX_CACHE.clear()
    module._LIST_QUERY_CACHE.clear()


def select(start, end, **kwargs):
    return module.SeriesService.find_jump_position('general', 7, '', kwargs.pop('sort', 'asc'), '', 60,
        user_id=42, role='member', selection_anchors=[dict(id=start, libraryId=7), dict(id=end, libraryId=7)], **kwargs)['targets']


def test_inclusive_unloaded_range_and_reverse(rows):
    assert [t['id'] for t in select(2, 205)] == list(range(2, 206))
    assert [t['id'] for t in select(205, 2)] == list(range(2, 206))
    assert all(t['libraryId'] == 7 for t in select(2, 205))


def test_descending_order_and_single_item(rows):
    assert [t['id'] for t in select(205, 200, sort='desc')] == [205, 204, 203, 202, 201, 200]
    assert [t['id'] for t in select(7, 7)] == [7]


def test_missing_anchor_fails_without_partial_range(rows):
    with pytest.raises(ValueError):
        select(1, 999)


def test_permission_inputs_and_filters_forwarded(rows):
    with patch.object(module.SeriesRepository, 'fetch_books_for_grouping', return_value=rows) as fetch:
        select(1, 4, genre_filters=['genre'], tag_filters=['tag'])
        assert fetch.call_args.kwargs['user_id'] == 42
        assert fetch.call_args.kwargs['role'] == 'member'
        assert fetch.call_args.kwargs['genre_filters'] == ['genre']
        assert fetch.call_args.kwargs['tag_filters'] == ['tag']


def test_rating_filtered_full_entries(rows):
    entries = [dict(representative_book_id=i, library_id=7, series_name=f'Series {i:03}') for i in [1, 3, 5]]
    with patch.object(module, '_filter_rows_by_content_rating', return_value=rows[::2]) as filtered, \
         patch.object(module, '_build_series_entries', return_value=entries), \
         patch.object(module, '_apply_series_reading_progress', side_effect=lambda db, data, user: data):
        assert [t['id'] for t in select(1, 5, content_rating_max=12)] == [1, 3, 5]
        filtered.assert_called_once()
