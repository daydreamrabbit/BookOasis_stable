import os
import shutil
import pytest

pytestmark = pytest.mark.skipif(os.getenv('BOOKOASIS_TEST_WATCH_DB') != '1', reason='disposable DB required')


def test_remote_identity_is_scoped_and_missing_ids_never_match():
    from services.folder_watch_moves import identity
    sig=[100,'2026-01-01','remote-file-id']
    assert identity(sig,'rclone:a') != identity(sig,'rclone:b')
    assert identity([100,'date',''],'rclone:a') is None
    assert identity(sig,'local') is None


def test_direct_scan_preflight_preserves_old_id(environment):
    import database
    from services.folder_watch_moves import reconcile_before_scan
    source,dest,old,ids,configs,book_id=environment
    target=dest/'one.txt';old.rename(target)
    assert reconcile_before_scan('general',ids[1],[str(dest)]) == 1
    with database.connection('general') as conn:
        assert conn.execute('SELECT file_path FROM books WHERE id=?',(book_id,)).fetchone()[0] == str(target)


def test_real_direct_path_scan_inserts_only_new_volume(environment):
    import database
    from tools.scanner.core import scan_library_path
    source,dest,old,ids,configs,book_id=environment
    target=dest/'series'/'one.txt';target.parent.mkdir();old.rename(target)
    (target.parent/'two.txt').write_text('new volume\n'*30)
    scan_library_path(database.get_db_path('general'), ids[1], str(target.parent), skip_vfs_refresh=True)
    with database.connection('general') as conn:
        rows=conn.execute('SELECT id,file_path FROM books WHERE library_id=?',(ids[1],)).fetchall()
        assert len(rows) == 2
        assert next(r['id'] for r in rows if r['file_path']==str(target)) == book_id
        assert conn.execute('SELECT pages_read FROM user_progress WHERE book_id=?',(book_id,)).fetchone()[0] == 32


@pytest.mark.parametrize('has_progress', [False, True])
def test_explicit_duplicate_recovery_preserves_source_or_rejects_conflict(environment, has_progress):
    import database
    from services.folder_watch_moves import reconcile_moves
    from services.folder_watch_sources import local_listing
    source,dest,old,ids,configs,book_id=environment
    target=dest/'one.txt';old.rename(target)
    with database.connection('general') as conn:
        duplicate=conn.execute('INSERT INTO books(library_id,title,file_path,file_format,total_pages) VALUES (?,?,?,?,100)',
            (ids[1],'duplicate',str(target),'txt')).lastrowid
        if has_progress:
            conn.execute('INSERT INTO user_progress(book_id,user_id,pages_read) VALUES (?,?,?)',(duplicate,1,7))
        conn.commit()
    run=lambda: reconcile_moves(f'general:{ids[1]}',str(dest),configs[1],local_listing(str(dest)),recover_duplicates=True)
    if has_progress:
        with pytest.raises(RuntimeError,match='참조'): run()
    else:
        assert run() == 1
    with database.connection('general') as conn:
        assert conn.execute('SELECT pages_read FROM user_progress WHERE book_id=?',(book_id,)).fetchone()[0] == 32
        row=conn.execute('SELECT library_id FROM books WHERE id=?',(book_id,)).fetchone()
        assert row[0] == ids[0 if has_progress else 1]
        assert bool(conn.execute('SELECT id FROM books WHERE id=?',(duplicate,)).fetchone()) == has_progress


def test_stale_source_scan_does_not_trash_moved_book(environment):
    import database
    from services.folder_watch_moves import reconcile_before_scan
    from tools.scanner.sync_detector import handle_deleted_books
    source,dest,old,ids,configs,book_id=environment
    target=dest/'one.txt';old.rename(target)
    reconcile_before_scan('general',ids[1],[str(dest)])
    with database.connection('general') as conn:
        handle_deleted_books(conn.cursor(),{str(old):book_id},{str(old)},[str(source)],{str(source/'other.txt')})
        assert conn.execute('SELECT is_deleted FROM books WHERE id=?',(book_id,)).fetchone()[0] == 0


@pytest.fixture
def environment(tmp_path, monkeypatch):
    import database
    from services import folder_watch_store as store
    from services.folder_watch_sources import local_listing
    database.init_databases()
    monkeypatch.setenv('BOOKOASIS_WATCH_DB', str(tmp_path/'watch.db'))
    source=tmp_path/'ongoing'; dest=tmp_path/'finished'; source.mkdir(); dest.mkdir()
    old=source/'series'/'one.txt'; old.parent.mkdir(); old.write_text('same book\n'*30)
    ids=[]
    with database.connection('general') as conn:
        for path in (source,dest):
            cursor=conn.execute('INSERT INTO libraries(name,physical_path) VALUES (?,?)',(str(path),str(path)))
            ids.append(cursor.lastrowid)
        cursor=conn.execute('INSERT INTO books(library_id,title,series_name,file_path,file_format,total_pages) VALUES (?,?,?,?,?,100)',
                            (ids[0],'one','series',str(old),'txt'))
        book_id=cursor.lastrowid
        conn.execute('INSERT INTO user_progress(book_id,user_id,pages_read) VALUES (?,?,?)',(book_id,1,32))
        conn.execute('INSERT INTO epub_bookmarks(book_id,user_id,format,chapter_idx,label) VALUES (?,?,?,?,?)',(book_id,1,'txt',2,'bookmark'))
        conn.execute('INSERT INTO book_annotations(book_id,user_id,format,start_offset,end_offset,quote,note) VALUES (?,?,?,?,?,?,?)',
                     (book_id,1,'txt',0,4,'same','my note'))
        conn.commit()
    configs=[]
    for identifier,path in zip(ids,(source,dest)):
        config=dict(store.DEFAULTS,enabled=True,mode='poll',paths=str(path))
        configs.append(config)
        store.configure(f'general:{identifier}',config)
        listing=local_listing(str(path))
        store.save_state(f'general:{identifier}',{'roots':{str(path):{'baseline':listing,'observed':listing}}})
    return source,dest,old,ids,configs,book_id


@pytest.mark.parametrize('source_first',[False,True])
def test_real_move_preserves_id_progress_bookmarks_annotations(environment,source_first):
    import database
    from services import folder_watch_store as store
    from services.folder_watch_service import advance_root, execute_task, digest
    from services.folder_watch_moves import reconcile_moves
    from services.folder_watch_sources import local_listing
    source,dest,old,ids,configs,book_id=environment
    target=dest/'series'/'one.txt';target.parent.mkdir();old.rename(target)
    if source_first:
        # Source already reflected the missing file: retained identity still permits recovery.
        key=f'general:{ids[0]}';c,s=store.get(key);r=s['roots'][str(source)]
        try: advance_root(r,{},100,configs[0],lambda _:None,lambda _:None)
        except ValueError: pass  # entire source missing is protected, but identity retained
        r['baseline']={};r['observed']={};store.save_state(key,s)
        with database.connection('general') as conn:
            conn.execute('UPDATE books SET is_deleted=1 WHERE id=?',(book_id,));conn.commit()
    files=local_listing(str(dest))
    destination_key=f'general:{ids[1]}'
    _, destination_state=store.get(destination_key)
    destination_state['roots'][str(dest)]['active']={'token':'move-test','files':files,'folders':['series'],'removed':{}}
    store.save_state(destination_key,destination_state)
    execute_task(999999,destination_key,'move-test',str(dest),digest(configs[1]))
    assert reconcile_moves(f'general:{ids[1]}',str(dest),configs[1],files)==0
    with database.connection('general') as conn:
        row=conn.execute('SELECT * FROM books WHERE id=?',(book_id,)).fetchone()
        assert row['library_id']==ids[1] and row['file_path']==str(target) and not row['is_deleted']
        assert conn.execute('SELECT pages_read FROM user_progress WHERE book_id=?',(book_id,)).fetchone()[0]==32
        assert conn.execute('SELECT label FROM epub_bookmarks WHERE book_id=?',(book_id,)).fetchone()[0]=='bookmark'
        assert conn.execute('SELECT note FROM book_annotations WHERE book_id=?',(book_id,)).fetchone()[0]=='my note'


@pytest.mark.parametrize('case',['copy','hardlink','ambiguous','existing_destination','disconnected'])
def test_unsafe_cases_do_not_transfer_history(environment,case):
    import database
    from services.folder_watch_moves import reconcile_moves
    from services.folder_watch_sources import local_listing
    source,dest,old,ids,configs,book_id=environment
    target=dest/'one.txt'
    if case=='copy':shutil.copy2(old,target)
    elif case=='hardlink':os.link(old,target)
    else:old.rename(target)
    if case=='ambiguous':os.link(target,dest/'another.txt')
    if case=='existing_destination':
        with database.connection('general') as conn:
            conn.execute('INSERT INTO books(library_id,title,file_path,file_format,total_pages) VALUES (?,?,?,?,100)',(ids[1],'duplicate',str(target),'txt'));conn.commit()
    if case=='disconnected':source.rename(source.with_name('offline'))
    if case=='disconnected':
        with pytest.raises(ValueError,match='접근'):
            reconcile_moves(f'general:{ids[1]}',str(dest),configs[1],local_listing(str(dest)))
    else:
        assert reconcile_moves(f'general:{ids[1]}',str(dest),configs[1],local_listing(str(dest)))==0
    with database.connection('general') as conn:
        assert conn.execute('SELECT library_id FROM books WHERE id=?',(book_id,)).fetchone()[0]==ids[0]


def test_different_database_never_transfers(environment):
    from services.folder_watch_moves import reconcile_moves
    from services.folder_watch_sources import local_listing
    source,dest,old,ids,configs,book_id=environment
    old.rename(dest/'one.txt')
    assert reconcile_moves(f'adult:{ids[1]}',str(dest),configs[1],local_listing(str(dest)))==0
