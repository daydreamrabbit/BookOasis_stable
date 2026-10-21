"""Persist recent authenticated UI use without treating background polling as activity."""
import logging
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

from flask import request, session
from repositories.user_repository import UserRepository

INTERVAL_SECONDS = 60
_recent = OrderedDict()
_lock = threading.Lock()
_logger = logging.getLogger(__name__)
_BACKGROUND_PATHS = {
    '/api/system/library-events', '/api/media/progress-state',
    '/api/system/health', '/api/system/status', '/api/media/scan-status',
    '/api/media/scan-activity', '/api/media/library-schedules',
    '/api/media/tts/status', '/api/media/notifications',
}


def should_record(path, method, status):
    if not 200 <= status < 400 or method in ('HEAD', 'OPTIONS'):
        return False
    if path in _BACKGROUND_PATHS:
        return False
    if method == 'GET' and path.endswith(('/status', '-status')):
        return False
    if path.startswith(('/api/system/', '/api/scanner/', '/api/webhook/', '/api/notifications/')):
        return False
    return path in ('/', '/login', '/tv') or path.startswith(('/api/account/', '/api/admin/', '/api/media/'))


def record_activity(user_id):
    now = time.monotonic()
    with _lock:
        if user_id in _recent and now - _recent[user_id] < INTERVAL_SECONDS:
            return
        # Reserve before I/O so concurrent requests don't all write.
        _recent[user_id] = now
        _recent.move_to_end(user_id)
        while len(_recent) > 2048:
            _recent.popitem(last=False)
    stamp = datetime.now(timezone.utc)
    try:
        UserRepository.touch_last_seen(
            user_id, stamp.strftime('%Y-%m-%d %H:%M:%S'),
            (stamp - timedelta(seconds=INTERVAL_SECONDS)).strftime('%Y-%m-%d %H:%M:%S'))
    except Exception:
        # Activity must never prevent normal use. Keep the reservation to avoid
        # hammering a database that is temporarily unavailable.
        _logger.warning('Could not persist user last access time', exc_info=True)


def init_app(app):
    @app.after_request
    def track_user_activity(response):
        user_id = session.get('user_id')
        if user_id and should_record(request.path, request.method, response.status_code):
            record_activity(int(user_id))
        return response
