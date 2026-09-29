"""Bounded, durable admin-only metadata collection history (not book metadata)."""
import os
import sqlite3
import time
from contextlib import contextmanager


@contextmanager
def connection():
    import database
    path = os.environ.get('BOOKOASIS_METADATA_HISTORY_DB') or os.path.join(database.DB_DIR, 'metadata_collection_history.db')
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.executescript('''
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, db_type TEXT, library_id INTEGER, library_name TEXT,
                started REAL, updated REAL, status TEXT, total INTEGER DEFAULT 0,
                processed INTEGER DEFAULT 0, matched INTEGER DEFAULT 0, applied INTEGER DEFAULT 0,
                current_title TEXT DEFAULT '');
            CREATE INDEX IF NOT EXISTS runs_started ON runs(started);
            CREATE TABLE IF NOT EXISTS entries (
                run_id TEXT, book_id INTEGER, title TEXT, status TEXT, sources TEXT,
                reason TEXT, updated REAL, PRIMARY KEY(run_id,book_id));
        ''')
        # 30 days and at most 1,000 finished runs. Never prune a live run.
        now = time.time()
        db.execute("UPDATE runs SET status='interrupted',current_title='' WHERE status='running' AND updated<?", (now-86400,))
        db.execute("UPDATE entries SET status='interrupted',reason='수집이 중단되어 결과를 확인할 수 없습니다.' WHERE status='searching' AND run_id IN (SELECT id FROM runs WHERE status='interrupted')")
        db.execute("DELETE FROM runs WHERE status!='running' AND (started<? OR id IN (SELECT id FROM runs WHERE status!='running' ORDER BY started DESC LIMIT -1 OFFSET 1000))", (now-30*86400,))
        db.execute('DELETE FROM entries WHERE run_id NOT IN (SELECT id FROM runs)')
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def record_event(run_id, db_type, library_id, library_name, event, details):
    with connection() as db:
        now = time.time()
        if event == 'clear':
            db.execute('DELETE FROM entries WHERE run_id=?', (run_id,))
            db.execute('DELETE FROM runs WHERE id=?', (run_id,))
            return
        db.execute("INSERT OR IGNORE INTO runs(id,db_type,library_id,library_name,started,updated,status) VALUES(?,?,?,?,?,?,'running')",
                   (run_id, db_type, library_id, str(library_name or '')[:200], now, now))
        if event in ('item_started', 'item_result'):
            status = 'searching' if event == 'item_started' else details.get('status', 'failed')
            if status not in ('searching', 'applied', 'not_matched', 'skipped', 'failed'):
                status = 'failed'
            title = str(details.get('title') or '')[:500]
            db.execute('INSERT OR REPLACE INTO entries VALUES(?,?,?,?,?,?,?)',
                       (run_id, int(details['book_id']), title, status,
                        str(details.get('sources') or '')[:300], str(details.get('reason') or '')[:1000], now))
            db.execute('UPDATE runs SET updated=?,current_title=? WHERE id=?',
                       (now, title if event == 'item_started' else '', run_id))
        elif event in ('completed', 'failed'):
            db.execute("UPDATE runs SET status=?,updated=?,current_title='',processed=COALESCE(?,processed),matched=COALESCE(?,matched),applied=COALESCE(?,applied) WHERE id=?",
                       (event, now, details.get('processed', details.get('completed')),
                        details.get('matched'), details.get('updated'), run_id))
            db.execute("UPDATE entries SET status=?,reason=? WHERE run_id=? AND status='searching'",
                       ('failed' if event == 'failed' else 'interrupted', '수집이 종료되어 결과를 확인할 수 없습니다.', run_id))
        elif event == 'progress':
            db.execute('UPDATE runs SET updated=?,total=?,processed=?,matched=?,applied=? WHERE id=?',
                       (now, int(details.get('total',0)), int(details.get('completed',0)),
                        int(details.get('matched',0)), int(details.get('updated',0)), run_id))


def get_history(run_id='', page=1, query='', status='', library_id=None, db_type=''):
    page = max(1, int(page)); query = str(query)[:200]; status = str(status)[:32]
    with connection() as db:
        if run_id:
            run = db.execute('SELECT * FROM runs WHERE id=?', (run_id,)).fetchone()
            if not run:
                return None
            clauses, args = ['run_id=?'], [run_id]
            if query:
                clauses.append('instr(lower(title),lower(?))>0'); args.append(query)
            if status:
                clauses.append('status=?'); args.append(status)
            where = ' AND '.join(clauses)
            count = db.execute('SELECT count(*) FROM entries WHERE '+where, args).fetchone()[0]
            rows = db.execute('SELECT * FROM entries WHERE '+where+' ORDER BY updated DESC,book_id LIMIT 50 OFFSET ?', args+[(page-1)*50]).fetchall()
            return dict(run=dict(run), items=[dict(r) for r in rows], total=count, page=page, page_size=50)
        clauses, args = ['1=1'], []
        if query:
            clauses.append('EXISTS(SELECT 1 FROM entries e WHERE e.run_id=r.id AND instr(lower(e.title),lower(?))>0)'); args.append(query)
        if status:
            clauses.append('r.status=?'); args.append(status)
        if library_id is not None:
            clauses.append('r.library_id=?'); args.append(int(library_id))
        if db_type:
            clauses.append('r.db_type=?'); args.append(db_type)
        where = ' AND '.join(clauses)
        count = db.execute('SELECT count(*) FROM runs r WHERE '+where, args).fetchone()[0]
        rows = db.execute('SELECT r.* FROM runs r WHERE '+where+' ORDER BY started DESC,id LIMIT 50 OFFSET ?', args+[(page-1)*50]).fetchall()
        libraries = db.execute('SELECT DISTINCT db_type,library_id,library_name FROM runs WHERE library_id IS NOT NULL ORDER BY db_type,library_id').fetchall()
        return dict(items=[dict(r) for r in rows], total=count, page=page, page_size=50,
                    libraries=[dict(r) for r in libraries])
