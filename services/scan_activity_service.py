"""Read-only details for the activity panel; never enqueue or clear a task."""
import datetime as dt
import json
import os

import database

from apscheduler.triggers.cron import CronTrigger
from repositories.scanner_queue_repository import ScannerQueueRepository
from repositories.scheduler_repository import SchedulerRepository
from services.settings_service import SettingsService


def scan_activity_details(now=None):
    from services.scheduler_service import normalize_cron_expression
    now = now or dt.datetime.now(dt.timezone.utc)
    history = []
    names = {}
    upcoming = []
    unavailable = []
    for db_type in ('general', 'adult', 'audiobook'):
        db_path = database.get_db_path(db_type)
        if not db_path.startswith('mariadb:') and not os.path.exists(db_path):
            continue
        try:
            libraries = SchedulerRepository.get_scheduled_libraries(db_type)
        except Exception:
            unavailable.append(db_type)
            continue
        for library in libraries:
            names[(db_type, library['id'])] = library['name']
            cron = library['cron_schedule']
            try:
                # Match register_job(): same weekday normalization and trigger TZ.
                trigger = CronTrigger.from_crontab(normalize_cron_expression(cron))
                next_run = trigger.get_next_fire_time(None, now)
            except (TypeError, ValueError):
                unavailable.append(f'{db_type}:{library["id"]}')
                continue
            if next_run:
                upcoming.append(dict(library_id=library['id'], db_type=db_type,
                    name=library['name'], cron=cron, next_run_at=next_run.isoformat()))
    lazy_cron = SettingsService.get('LAZY_SCAN_CRON', '')
    if lazy_cron:
        try:
            next_run = CronTrigger.from_crontab(lazy_cron).get_next_fire_time(None, now)
            if next_run:
                upcoming.append(dict(name='미디어 검색', cron=lazy_cron,
                    db_type='general', library_id=None, next_run_at=next_run.isoformat()))
        except (TypeError, ValueError):
            unavailable.append('lazy_scan')
    rows = (ScannerQueueRepository.fetch_recent_library_scans(limit=10)
            + ScannerQueueRepository.fetch_recent_batch_book_scans(limit=10))
    for row in rows:
        try:
            kwargs = json.loads(row.get('kwargs') or '{}')
        except (TypeError, ValueError):
            kwargs = {}
        if not isinstance(kwargs, dict):
            kwargs = {}
        # Do not send physical paths, remote credentials or arbitrary task kwargs.
        kwargs = {key: kwargs[key] for key in ('library_id', 'db_type', 'series_name', 'book_ids', 'book_title') if key in kwargs}
        db_type, library_id = kwargs.get('db_type', 'general'), kwargs.get('library_id')
        if db_type not in ('general', 'adult', 'audiobook', 'video'):
            db_type = 'general'
        try:
            library_id = int(library_id) if library_id is not None else None
        except (ValueError, TypeError):
            library_id = None
        kwargs.update(db_type=db_type, library_id=library_id)
        name = names.get((db_type, library_id))
        if not name and library_id is not None:
            from repositories.category_repository import CategoryRepository
            try:
                library = CategoryRepository.get_library_by_id(db_type, library_id)
                name = library['name'] if library else None
            except Exception:
                pass
        history.append(dict(id=row['id'], type=row['task_type'], key=row['task_key'],
            kwargs=kwargs, library_name=name or '도서 스캔', status=row['status'],
            started_at=row.get('started_at'), finished_at=row.get('finished_at')))
    upcoming.sort(key=lambda item: dt.datetime.fromisoformat(item['next_run_at']))
    history.sort(key=lambda item: str(item['finished_at'] or ''), reverse=True)
    return dict(history=history, upcoming=upcoming, unavailable=unavailable)
