import fnmatch
import sys
import types
from unittest.mock import patch

from services import metadata_scan_activity as activity


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}

    def set(self, key, value, ex=None):
        self.values[key] = value
        self.ttls[key] = ex
        return True

    def get(self, key):
        return self.values.get(key)

    def delete(self, key):
        self.ttls.pop(key, None)
        return int(self.values.pop(key, None) is not None)

    def scan_iter(self, match, count=50):
        return [key for key in self.values if fnmatch.fnmatch(key, match)]


def redis_helper_stub(client):
    module = types.ModuleType('utils.redis_helper')

    def save(key, value, ex=None):
        return client.set(f'bookoasis:{key}', value, ex=ex)

    module.redis_set = save
    module.redis_del = lambda key: client.delete(f'bookoasis:{key}')
    module.get_redis_client = lambda: client
    module.make_key = lambda key: f'bookoasis:{key}'
    return module


def test_metadata_activity_is_shared_via_redis_and_keeps_only_counts():
    client = FakeRedis()

    with patch.dict(sys.modules, {'utils.redis_helper': redis_helper_stub(client)}):
        assert activity.save_metadata_scan_activity({
            'type': 'metadata_auto_collect',
            'db_type': 'general',
            'library_id': 19,
            'library_name': 'GDS테스트용',
            'status': 'running',
            'stage': '자동 메타데이터 검색 2/4개 · 매칭 1개 · 적용 1개',
            'started_at': '2026-09-28 22:00:00',
        })
        listed = activity.list_metadata_scan_activities()

    assert len(listed) == 1
    assert listed[0]['status'] == 'running'
    assert listed[0]['stage'].startswith('자동 메타데이터 검색')
    assert 'series_name' not in listed[0]
    assert next(iter(client.ttls.values())) == activity._RUNNING_TTL_SECONDS


def test_completed_metadata_activity_is_retained_briefly():
    client = FakeRedis()

    with patch.dict(sys.modules, {'utils.redis_helper': redis_helper_stub(client)}):
        activity.save_metadata_scan_activity({
            'type': 'metadata_auto_collect',
            'db_type': 'general',
            'library_id': 19,
            'status': 'completed',
            'stage': '자동 메타데이터 수집 완료 · 검색 4개 · 매칭 2개 · 적용 2개',
            'started_at': '2026-09-28 22:00:00',
        })

    assert next(iter(client.ttls.values())) == activity._FINISHED_TTL_SECONDS


def test_empty_metadata_run_can_remove_its_temporary_activity():
    client = FakeRedis()

    with patch.dict(sys.modules, {'utils.redis_helper': redis_helper_stub(client)}):
        activity.save_metadata_scan_activity({
            'type': 'metadata_auto_collect',
            'db_type': 'general',
            'library_id': 19,
            'status': 'running',
        })
        assert activity.clear_metadata_scan_activity('general', 19)
        assert activity.list_metadata_scan_activities() == []
