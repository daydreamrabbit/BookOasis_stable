# -*- coding: utf-8 -*-
"""Refresh only changed series after direct scans; retain custom summary/health policy."""
import os
import threading
import time
from contextlib import contextmanager

DEBOUNCE_SEC = 1.0
MAX_INCREMENTAL_KEYS = 500
SUMMARY_DB_TYPES = ('general', 'adult')
_lock = threading.Lock()
_timers = {}
_pending = {}
_running = set()


def _clear_recent_caches(db_type):
    try:
        from utils.redis_helper import redis_delete_pattern
        redis_delete_pattern(f"cache:recent_added*:{db_type}:*")
        redis_delete_pattern(f"cache:history*:{db_type}:*")
    except Exception as error:
        print(f"[ScanRefresh] recent cache clear failed ({db_type}): {error}")


def rebuild_series_views(db_type, keys=None):
    from repositories.series_repository import SeriesRepository
    from services.series_service import SeriesService
    from services.system_health_service import SystemHealthService, series_summary_health_key
    try:
        if db_type not in SUMMARY_DB_TYPES:
            return
        started = time.perf_counter()
        refreshed = None
        if keys is not None and len(keys) <= MAX_INCREMENTAL_KEYS:
            try:
                refreshed = SeriesRepository.refresh_summary_keys(db_type, sorted(keys)) if keys else 0
            except Exception as error:
                # The repository rolled back; preserve visibility by falling back to a full rebuild.
                print(f"[ScanRefresh] incremental refresh failed ({db_type}), rebuilding: {error}")
            if refreshed:
                SystemHealthService.record_success(series_summary_health_key(db_type)[0])
        if refreshed is None:
            rebuilt = SystemHealthService.rebuild_series_summary(db_type)
            mode = 'full' if rebuilt else 'already fresh'
        else:
            mode = f'keys={refreshed}'
        print(f"[ScanRefresh] summary refreshed: db={db_type}, {mode}, "
              f"elapsed_ms={(time.perf_counter() - started) * 1000:.1f}")
    except Exception as error:
        print(f"[ScanRefresh] series summary refresh failed ({db_type}): {error}")
    finally:
        SeriesService.invalidate_all_books_cache(db_type=db_type)


def _schedule_locked(db_type):
    timer = threading.Timer(DEBOUNCE_SEC, _run, args=(db_type,))
    timer.daemon = True
    _timers[db_type] = timer
    timer.start()


def _run(db_type):
    with _lock:
        _timers.pop(db_type, None)
        if db_type in _running:
            return
        _running.add(db_type)
    try:
        while True:
            with _lock:
                job = _pending.pop(db_type, None)
                if job is None:
                    return
            rebuild_series_views(db_type, None if job['full'] else job['keys'])
    finally:
        with _lock:
            _running.discard(db_type)
            if db_type in _pending and db_type not in _timers:
                _schedule_locked(db_type)


def refresh_after_direct_scan(db_type, keys=None):
    db_type = str(db_type or 'general')
    _clear_recent_caches(db_type)
    with _lock:
        job = _pending.setdefault(db_type, {'keys': set(), 'full': False})
        if keys is None:
            job['full'] = True
            job['keys'].clear()
        elif not job['full']:
            job['keys'].update(keys)
            if len(job['keys']) > MAX_INCREMENTAL_KEYS:
                job['full'] = True
                job['keys'].clear()
        timer = _timers.pop(db_type, None)
        if timer is not None:
            timer.cancel()
        _schedule_locked(db_type)


def _scope_prefix(target_path):
    from tools.scanner.path_utils import canonical_path
    path = str(target_path or '').strip()
    return canonical_path(os.path.dirname(path) if os.path.isfile(path) else path)


def _snapshot(db_type, library_id, prefix):
    try:
        from repositories.series_repository import SeriesRepository
        return SeriesRepository.fetch_series_snapshot(db_type, library_id, prefix)
    except Exception as error:
        print(f"[ScanRefresh] series snapshot failed ({db_type}, library={library_id}): {error}")
        return None


def changed_series_keys(library_id, before, after):
    keys = set()
    for book_id in set(before) | set(after):
        old, new = before.get(book_id), after.get(book_id)
        if old != new:
            if old:
                keys.add((library_id, old[0]))
            if new:
                keys.add((library_id, new[0]))
    return keys


@contextmanager
def track_direct_scan(db_type, library_id, target_path):
    from utils.drive_helper import is_gdrive_url
    db_type = str(db_type or 'general')
    before = prefix = None
    if db_type in SUMMARY_DB_TYPES and not is_gdrive_url(str(target_path or '')):
        prefix = _scope_prefix(target_path)
        before = _snapshot(db_type, library_id, prefix)
    yield
    keys = None
    if before is not None:
        after = _snapshot(db_type, library_id, prefix)
        if after is not None:
            keys = changed_series_keys(library_id, before, after)
    refresh_after_direct_scan(db_type, keys=keys)
