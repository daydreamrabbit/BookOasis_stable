# -*- coding: utf-8 -*-
"""Redis-backed progress for metadata collection started by scan hooks."""
import json


_ACTIVITY_KEY_PREFIX = 'scan:metadata:auto_collect:'
_RUNNING_TTL_SECONDS = 1800
_FINISHED_TTL_SECONDS = 180


def save_metadata_scan_activity(activity):
    """Save one metadata activity without exposing book or series titles."""
    if not isinstance(activity, dict):
        return False
    db_type = str(activity.get('db_type') or '').strip()
    library_id = activity.get('library_id')
    if not db_type or library_id is None:
        return False
    try:
        from utils.redis_helper import redis_set

        key = f'{_ACTIVITY_KEY_PREFIX}{db_type}:{int(library_id)}'
        ttl = _RUNNING_TTL_SECONDS if activity.get('status') == 'running' else _FINISHED_TTL_SECONDS
        return redis_set(key, json.dumps(activity, ensure_ascii=False), ex=ttl)
    except (TypeError, ValueError, OverflowError):
        return False


def clear_metadata_scan_activity(db_type, library_id):
    if library_id is None:
        return False
    try:
        from utils.redis_helper import redis_del

        key = f'{_ACTIVITY_KEY_PREFIX}{str(db_type or "").strip()}:{int(library_id)}'
        return redis_del(key)
    except (TypeError, ValueError, OverflowError):
        return False


def list_metadata_scan_activities():
    """Return current and briefly retained completed metadata activities."""
    try:
        from utils.redis_helper import get_redis_client, make_key

        client = get_redis_client()
        if client is None:
            return []
        pattern = make_key(f'{_ACTIVITY_KEY_PREFIX}*')
        activities = []
        for key in client.scan_iter(match=pattern, count=50):
            raw = client.get(key)
            if not raw:
                continue
            try:
                activity = json.loads(raw)
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(activity, dict):
                activities.append(activity)
        activities.sort(key=lambda item: str(item.get('started_at') or ''), reverse=True)
        return activities[:10]
    except Exception:
        return []
