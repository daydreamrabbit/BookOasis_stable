"""Local durable control/outbox state, shared by SQLite and MariaDB installations.

Kept in the existing persistent /app/db volume; no changes to library schemas.
"""
import json
import os
import sqlite3
from contextlib import contextmanager

DEFAULTS = dict(enabled=False, mode='auto', interval=300, settle=60, reflect_deletions=False, rclone_remote='')


@contextmanager
def connection():
    import database
    path = os.getenv('BOOKOASIS_WATCH_DB', os.path.join(database.DB_DIR, 'folder_watch.db'))
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS watches (key TEXT PRIMARY KEY, config TEXT NOT NULL, state TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '{}')")
        if 'summary' not in {r[1] for r in conn.execute('PRAGMA table_info(watches)')}:
            conn.execute("ALTER TABLE watches ADD COLUMN summary TEXT NOT NULL DEFAULT '{}'")
        yield conn
        conn.commit()
    finally:
        conn.close()


def get(key):
    with connection() as conn:
        row = conn.execute('SELECT * FROM watches WHERE key=?', (key,)).fetchone()
    return (json.loads(row['config']), json.loads(row['state'])) if row else (dict(DEFAULTS), {})


def configure(key, config):
    with connection() as conn:
        conn.execute('INSERT INTO watches (key, config, state) VALUES (?, ?, ?) ON CONFLICT(key) DO UPDATE SET config=excluded.config',
                     (key, json.dumps(config), '{}'))


def save_state(key, state):
    summary = {k: state.get(k) for k in ('status', 'last_check', 'error', 'event_warning')}
    summary['pending'] = sum(bool(r.get('active')) for r in state.get('roots', {}).values())
    with connection() as conn:
        conn.execute('UPDATE watches SET state=?, summary=? WHERE key=?', (json.dumps(state), json.dumps(summary), key))


def public_status(key):
    with connection() as conn:
        row = conn.execute('SELECT config, summary FROM watches WHERE key=?', (key,)).fetchone()
    return (json.loads(row['config']), json.loads(row['summary'])) if row else (dict(DEFAULTS), {})


def all_watches():
    with connection() as conn:
        result = []
        for row in conn.execute('SELECT key, config, summary FROM watches').fetchall():
            config = json.loads(row['config'])
            result.append((row['key'], config, json.loads(row['summary'])))
        return result
