"""Run only with disposable BOOKOASIS_TEST_WATCH_DB=1 databases (Docker tmpfs)."""
import os
import pytest


@pytest.mark.skipif(os.getenv('BOOKOASIS_TEST_WATCH_DB') != '1', reason='requires disposable databases')
@pytest.mark.parametrize('error', [None, 'file changed during wait'])
def test_real_queue_cleanup_retains_watch_outcome(error):
    import database
    from repositories.scanner_queue_repository import ScannerQueueRepository as Queue
    database.init_databases()
    key = 'folder_watch_cleanup_' + ('failed' if error else 'completed')
    with database.connection('general') as conn:
        cursor = conn.execute("INSERT INTO scanner_tasks(task_type,task_key,status,kwargs) VALUES (?,?,?,?)",
                              ('folder_watch', key, 'running', '{}'))
        identifier = cursor.lastrowid
        conn.commit()
    Queue.update_task_result(identifier, '2026-09-24 05:00:00', error)
    assert Queue.get_task_by_key(key) is None
    assert Queue.get_watch_task_result(key)['status'] == ('failed' if error else 'completed')


@pytest.mark.skipif(os.getenv('BOOKOASIS_TEST_WATCH_DB') != '1', reason='requires disposable databases')
def test_real_partial_scan_and_reversible_missing_book(tmp_path, monkeypatch):
    import database
    from services import folder_watch_store as store
    from services.folder_watch_service import advance_root, execute_task, digest
    from services.folder_watch_sources import local_listing
    from repositories.scanner_queue_repository import ScannerQueueRepository
    from tools.scanner.core import scan_library_path
    database.init_databases()
    root=tmp_path/'books';folder=root/'Series';folder.mkdir(parents=True)
    (folder/'01.txt').write_text('첫 번째 도서의 본문입니다.\n'*30)
    conn=database.get_connection('general')
    cur=conn.cursor()
    cur.execute("INSERT INTO libraries (name, physical_path) VALUES (?, ?)",('watch test',str(root)))
    library_id=cur.lastrowid;conn.commit();conn.close()
    key=f'general:{library_id}'
    cfg=dict(store.DEFAULTS,enabled=True,paths=str(root),mode='poll',reflect_deletions=True)
    monkeypatch.setenv('BOOKOASIS_WATCH_DB',str(tmp_path/'watch.db'))
    store.configure(key,cfg)
    monkeypatch.setattr(ScannerQueueRepository,'is_cancel_requested',lambda _:False)
    monkeypatch.setattr(ScannerQueueRepository,'update_task_stage',lambda *a:None)
    scan_library_path(database.get_db_path('general'),library_id,str(folder),allow_missing=False)
    original=local_listing(str(root));state={}
    advance_root(state,original,0,cfg,lambda _:None,lambda _:None)
    (folder/'02.txt').write_text('두 번째 도서의 본문입니다.\n'*30)
    current=local_listing(str(root))
    advance_root(state,current,10,cfg,lambda _:None,lambda _:None)
    advance_root(state,current,71,cfg,lambda _:None,lambda _:None)
    store.save_state(key,{'roots':{str(root):state}})
    execute_task(1,key,state['active']['token'],str(root),digest(cfg))
    with database.connection('general') as conn:
        rows=conn.execute('SELECT file_path,is_deleted FROM books WHERE library_id=?',(library_id,)).fetchall()
    assert len(rows)==2 and not any(r['is_deleted'] for r in rows)
    advance_root(state,current,80,cfg,lambda _:None,lambda _:'completed')
    (folder/'01.txt').unlink()  # synthetic fixture file only
    current=local_listing(str(root))
    advance_root(state,current,90,cfg,lambda _:None,lambda _:None)
    advance_root(state,current,151,cfg,lambda _:None,lambda _:None)
    store.save_state(key,{'roots':{str(root):state}})
    execute_task(2,key,state['active']['token'],str(root),digest(cfg))
    with database.connection('general') as conn:
        rows=conn.execute('SELECT file_path,is_deleted FROM books WHERE library_id=?',(library_id,)).fetchall()
    assert len(rows)==2 and sum(bool(r['is_deleted']) for r in rows)==1
    assert (folder/'02.txt').exists()
