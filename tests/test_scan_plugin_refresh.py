import pytest


@pytest.mark.parametrize('hook_name', ['_dispatch_new_books_to_plugin_hooks', '_dispatch_scan_completed_to_plugin_hooks'])
def test_metadata_hook_publishes_after_database_and_summary_updates(monkeypatch, hook_name):
    from tools.scanner import engine
    from services.series_service import SeriesService
    from repositories.series_repository import SeriesRepository
    from unittest.mock import Mock
    events = []
    plugin = Mock()
    def save(*args):
        events.append('metadata saved')
        return {'success': True, 'stats': {'updated': 1}}
    plugin.on_scan_completed.side_effect = save
    plugin.on_scan_new_books_detected.side_effect = save
    monkeypatch.setattr(engine.MetadataFactory, 'get_available_providers', lambda **kw: [{'id':'rabbit_plugins','enabled':True}])
    monkeypatch.setattr(engine.MetadataFactory, 'get_provider_by_id', lambda _: plugin)
    monkeypatch.setattr(SeriesRepository, 'rebuild_summary', lambda _: events.append('summary'))
    monkeypatch.setattr(SeriesService, 'invalidate_all_books_cache', lambda **kw: events.append('revision'))
    monkeypatch.setattr('utils.redis_helper.redis_delete_pattern', lambda _: None)
    getattr(engine, hook_name)('general', {})
    assert events == ['metadata saved', 'summary', 'revision']


def test_unmatched_plugin_does_not_publish_false_changes(monkeypatch):
    from tools.scanner.engine import _publish_plugin_metadata_changes
    from services.series_service import SeriesService
    from unittest.mock import Mock
    invalidate=Mock()
    monkeypatch.setattr(SeriesService,'invalidate_all_books_cache',invalidate)
    for result in [None, {'success': True, 'skipped': True}, {'success':True,'stats':{'updated':0}}]:
        _publish_plugin_metadata_changes('general',result)
    invalidate.assert_not_called()
