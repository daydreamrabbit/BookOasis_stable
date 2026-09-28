import json
from unittest.mock import Mock
import pytest
from services.folder_watch_service import advance_root, changed_folders, validate_config
from services.folder_watch_sources import local_listing, relative_path, rclone_listing, drive_listing
from services import folder_watch_store as store


def config(**kwargs):
    return dict(store.DEFAULTS, **kwargs)


@pytest.mark.parametrize('engine', ['sqlite', 'mariadb'])
@pytest.mark.parametrize('result', ['completed', 'failed'])
def test_terminal_watch_result_survives_queue_cleanup(monkeypatch, engine, result):
    import importlib
    module = importlib.import_module(f'repositories.{engine}.scanner_queue_repository')
    cursor = Mock()
    cursor.fetchone.side_effect = [None, {'status': result}]
    connection = Mock()
    connection.cursor.return_value = cursor
    monkeypatch.setattr(module.database, 'get_connection', lambda *a: connection)
    assert module.ScannerQueueRepository.get_watch_task_result('folder_watch_token') == {'status': result}
    assert 'scan_history' in cursor.execute.call_args.args[0]
    assert cursor.execute.call_args.args[1] == ('folder_watch_token',)
    connection.close.assert_called_once()


def test_two_roots_preserve_retry_state_and_new_files(tmp_path, monkeypatch):
    from services import folder_watch_service as service
    from repositories.scanner_queue_repository import ScannerQueueRepository
    from services.scanner_queue import scanner_queue
    monkeypatch.setenv('BOOKOASIS_WATCH_DB', str(tmp_path/'watch.db'))
    cfg = config(enabled=True, paths='/one\n/two')
    store.configure('general:1', cfg)
    old = {'old.txt': [1,'1']}; new = dict(old, **{'nana.txt':[2,'2']})
    store.save_state('general:1', {'roots': {'/one': {'baseline':old, 'observed':old,
        'active':{'token':'old-token','files':old}}, '/two':{'baseline':{},'observed':{}}}})
    monkeypatch.setattr(service, 'library', lambda _: {'physical_path':cfg['paths']})
    monkeypatch.setattr(service, 'probe', lambda root,c: new if root == '/one' else {})
    monkeypatch.setattr(ScannerQueueRepository, 'get_watch_task_result', lambda _: {'status':'failed'})
    enqueue=Mock(); monkeypatch.setattr(scanner_queue,'enqueue',enqueue)
    service.tick('general:1', cfg, {})
    state=store.get('general:1')[1]
    assert state['status']=='작업 재시도 대기'
    assert state['roots']['/one']['observed']==new
    assert 'active' not in state['roots']['/one']
    enqueue.assert_not_called()
    monkeypatch.setattr(service,'probe',lambda root,c: (_ for _ in ()).throw(ValueError('offline')) if root=='/one' else {})
    service.tick('general:1',cfg,{})
    state=store.get('general:1')[1]
    assert state['status']=='감시 오류/보호 중'
    assert '/one' in state['error']
    assert state['roots']['/two']['status']=='감시 중'


def step(state, files, now, cfg=None, phase=None):
    return advance_root(state, files, now, cfg or config(), lambda job: None, lambda token: phase)


def test_initial_baseline_then_two_stable_samples():
    state = {}
    a = {'series/a.txt': [10, '1']}
    b = dict(a, **{'series/b.txt': [20, '2']})
    step(state, a, 0)
    assert 'active' not in state
    step(state, b, 10)
    step(state, b, 30)
    assert 'active' not in state
    step(state, b, 71)
    assert state['active']['folders'] == ['series']
    assert state['baseline'] == a  # enqueue is NOT completion


def test_copy_stability_reset_and_changes_while_running():
    a, b, c = ({'s/a.txt': [n, str(n)]} for n in [10, 20, 30])
    state = {}
    step(state, a, 0); step(state, b, 10); step(state, c, 50)
    step(state, c, 80); assert 'active' not in state
    step(state, c, 111); token = state['active']['token']
    step(state, b, 130, phase='running')
    assert state['active']['token'] == token
    step(state, b, 160, phase='completed')
    assert state['baseline'] == c and 'active' not in state
    step(state, b, 221)
    assert state['active']['files'] == b


def test_outbox_recovers_after_restart_and_failed_task_retries():
    state = {};a={'s/a.txt':[1,'a']};b={'s/a.txt':[2,'b']}
    step(state,a,0);step(state,b,10);step(state,b,71)
    restored=json.loads(json.dumps(state));enqueue=Mock()
    advance_root(restored,b,72,config(),enqueue,lambda _:None)
    enqueue.assert_called_once_with(restored['active'])
    step(restored,b,80,phase='failed')
    assert 'active' not in restored and restored['baseline']==a
    step(restored,b,141);assert 'active' in restored


def test_delete_disabled_and_disconnect_protection():
    a={'s/a.txt':[1,'a'],'s/b.txt':[2,'b']};b={'s/a.txt':[1,'a']}
    state={};step(state,a,0);step(state,b,10);step(state,b,71)
    assert 'active' not in state and state['baseline']==b
    with pytest.raises(ValueError,match='모두 사라'):
        step(state,{},100)
    assert state['baseline']==b


def test_enabled_deletion_is_explicit_and_delayed():
    cfg=config(reflect_deletions=True,settle=10)
    a={'s/a.txt':[1,'a'],'s/b.txt':[2,'b']};b={'s/a.txt':[1,'a']}
    state={};step(state,a,0,cfg);step(state,b,10,cfg);step(state,b,21,cfg)
    assert 'active' not in state
    step(state,b,71,cfg)
    assert state['active']['removed']=={'s/b.txt':[2,'b']} and not state['active']['folders']


def test_mass_missing_does_not_advance_baseline():
    a={f'{i}.txt':[1,'a'] for i in range(30)};state={}
    step(state,a,0)
    with pytest.raises(ValueError,match='대량'):
        step(state,{'0.txt':[1,'a']},10)
    assert state['baseline']==a


def test_local_listing_ignores_temporary_files_and_links(tmp_path):
    (tmp_path/'a.txt').write_text('hi')
    (tmp_path/'a.txt.part').write_text('incomplete')
    (tmp_path/'.secret.txt').write_text('hidden')
    (tmp_path/'link.txt').symlink_to(tmp_path/'a.txt')
    listing=local_listing(str(tmp_path))
    assert list(listing)==['a.txt'] and listing['a.txt'][0]==2
    with pytest.raises(ValueError):local_listing(str(tmp_path/'missing'))


@pytest.mark.parametrize('path',['../outside.txt','/outside.txt','a/../../b','a\\b'])
def test_bad_remote_paths_are_rejected(path):
    with pytest.raises(ValueError):relative_path(path)


def test_durable_config_does_not_overwrite_worker_state(tmp_path,monkeypatch):
    monkeypatch.setenv('BOOKOASIS_WATCH_DB',str(tmp_path/'watch.db'))
    store.configure('general:1',config(enabled=True))
    store.save_state('general:1',{'roots':{'/books':{'baseline':{'a.txt':[1,'2']}}}})
    store.configure('general:1',config(enabled=False))
    cfg,state=store.get('general:1')
    assert cfg['enabled'] is False and state['roots']['/books']['baseline']


def test_configuration_and_folder_coalescing():
    lib={'physical_path':'/books'}
    assert validate_config({'enabled':True},lib)['paths']=='/books'
    for values in [{'interval':0},{'enabled':'false'},{'mode':'bad'},{'mode':'rclone'}]:
        with pytest.raises(ValueError):validate_config(values,lib)
    assert changed_folders({}, {'a/b/c.txt':[1],'a/b.txt':[2]})==['a']


def test_rclone_error_does_not_become_empty_listing(monkeypatch):
    monkeypatch.setattr('utils.rclone_gdrive_copy._rclone_config_args',lambda:[])
    monkeypatch.setattr('services.folder_watch_sources.subprocess.run',lambda *a,**k:Mock(returncode=1))
    with pytest.raises(ValueError,match='목록 조회 실패'):rclone_listing('remote:books')


def test_mount_remote_handles_bind_subroot_and_multiple_roots(tmp_path):
    from services.folder_watch_sources import mounted_remote
    mounts = tmp_path / 'mountinfo'
    mounts.write_text('1 0 0:1 / / rw - overlay overlay rw\n'
                      '2 1 0:2 / /book ro - fuse.rclone book: ro\n'
                      '3 1 0:2 /Kavita /data/comics ro - fuse.rclone book: ro\n'
                      '4 2 0:3 / /book/local rw - ext4 /dev/test rw\n')
    assert mounted_remote('/book/Kavita/정발/연재', mounts) == 'book:Kavita/정발/연재'
    assert mounted_remote('/book/Kavita/비정발/연재', mounts) == 'book:Kavita/비정발/연재'
    assert mounted_remote('/data/comics/정발/연재', mounts) == 'book:Kavita/정발/연재'
    assert mounted_remote('/book/local/file', mounts) is None
    assert mounted_remote('/books/file', mounts) is None


def test_auto_rclone_uses_remote_listing(monkeypatch):
    from services import folder_watch_sources as sources
    monkeypatch.setattr(sources, 'mounted_remote', lambda root: 'book:' + root.lstrip('/'))
    listing = Mock(return_value={'a.txt': [1, 'date', 'id']})
    monkeypatch.setattr(sources, 'rclone_listing', listing)
    assert sources.list_source('/one') == {'a.txt': [1, 'date', 'id']}
    listing.assert_called_once_with('book:one')


def test_missing_remote_reports_path_without_empty_baseline(monkeypatch):
    monkeypatch.setattr('utils.rclone_gdrive_copy._rclone_config_args', lambda: [])
    monkeypatch.setattr('services.folder_watch_sources.subprocess.run', lambda *a, **k: Mock(returncode=3))
    with pytest.raises(ValueError, match='원격 폴더가 없습니다.*book:missing'):
        rclone_listing('book:missing')


def test_manual_multiple_remote_paths(monkeypatch):
    from services import folder_watch_service as service
    cfg = validate_config({'mode': 'rclone', 'rclone_remote': 'book:one\nbook:two'},
                          {'physical_path': '/one\n/two'})
    runner = Mock(return_value=Mock(returncode=0, stdout='{"files": {}}'))
    monkeypatch.setattr(service.subprocess, 'run', runner)
    service.probe('/two', cfg)
    assert json.loads(runner.call_args.kwargs['input'])['remote'] == 'book:two'
    with pytest.raises(ValueError):
        validate_config({'mode': 'rclone', 'rclone_remote': 'book:one'}, {'physical_path': '/one\n/two'})


def test_drive_pagination_and_fail_closed(monkeypatch):
    monkeypatch.setenv('GDRIVE_API_KEY','test-key')
    responses=iter([
        {'files':[{'id':'a','name':'a.txt','mimeType':'text/plain','size':'2','modifiedTime':'now'}],'nextPageToken':'next'},
        {'files':[{'id':'b','name':'b.txt','mimeType':'text/plain','size':'3','modifiedTime':'now'}]},
    ])
    calls=[]
    def get(*args,**kwargs):
        if '/files/' in args[0]:
            return Mock(status_code=200,json=lambda:{'mimeType':'application/vnd.google-apps.folder'})
        calls.append(kwargs['params']);return Mock(status_code=200,json=lambda:next(responses))
    monkeypatch.setattr('requests.get',get)
    assert len(drive_listing('https://drive.google.com/drive/folders/testid'))==2
    assert calls[1]['pageToken']=='next'
    monkeypatch.setattr('requests.get',lambda *a,**k:Mock(status_code=403))
    with pytest.raises(ValueError,match='403'):drive_listing('gdrive://testid')


def test_no_delete_mode_still_restores_found_books():
    from tools.scanner.sync_detector import handle_deleted_books
    cursor=Mock()
    assert handle_deleted_books(cursor, {'/a.txt':1,'/b.txt':2}, ['/b.txt'], ['/'], {'/a.txt'},allow_missing=False)
    queries=[c.args[0] for c in cursor.execute.call_args_list]
    assert any('SET is_deleted = 0' in q for q in queries)
    assert not any('SET is_deleted = 1' in q or 'DELETE FROM' in q for q in queries)


def test_watch_api_admin_only_and_validates_body(tmp_path,monkeypatch):
    from flask import Flask
    from api.routes.library_routes import library_bp, CategoryRepository
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(library_bp)
    client=app.test_client()
    monkeypatch.setenv('BOOKOASIS_WATCH_DB',str(tmp_path/'watch.db'))
    monkeypatch.setattr(CategoryRepository,'get_library_by_id',lambda *a:{'id':1,'physical_path':'/books'})
    with client.session_transaction() as session:
        session.update(user_id=2,role='user',is_default_password=0)
    assert client.get('/api/media/libraries/1/watch').status_code==403
    with client.session_transaction() as session:session['role']='admin'
    assert client.post('/api/media/libraries/1/watch',json={'interval':0}).status_code==400
    assert client.post('/api/media/libraries/1/watch',json={'enabled':True}).status_code==200
    data=client.get('/api/media/libraries/1/watch').get_json()
    assert data['watch']['config']['enabled'] is True
    assert client.get('/api/media/libraries/1/watch?type=invalid').status_code==400


def test_probe_does_not_download_content(tmp_path):
    from services.folder_watch_service import probe
    (tmp_path/'book.txt').write_text('text')
    assert probe(str(tmp_path),config())['book.txt'][0]==4


def test_disabled_queued_job_cannot_run(monkeypatch):
    from services.folder_watch_service import execute_task
    from services.scan_cancellation import ScanCancelledError
    monkeypatch.setattr(store,'get',lambda key:(config(enabled=False),{}))
    monkeypatch.setattr('services.folder_watch_service.library',lambda key:{'physical_path':'/books'})
    with pytest.raises(ScanCancelledError):
        execute_task(1,'general:1','token','/books','hash')


def test_same_size_stale_rclone_mount_is_not_acknowledged(monkeypatch):
    from services.folder_watch_service import verify_mount
    monkeypatch.setattr('tools.scanner.vfs.trigger_vfs_refresh',lambda *a:None)
    monkeypatch.setattr('services.folder_watch_service.probe',lambda *a:{'a.txt':[10,'0']})
    with pytest.raises(RuntimeError,match='수정 시간'):
        verify_mount('/books',config(mode='rclone'),{'a.txt':[10,'2026-01-01T00:00:00Z','id']},'general',1)


def test_partial_scan_cannot_include_sibling_or_wildcard_folders():
    import sqlite3
    from tools.scanner.path_utils import descendant_like_pattern
    conn=sqlite3.connect(':memory:');conn.execute('CREATE TABLE books (path TEXT)')
    paths=['/books/A_%/01.txt','/books/A_% other/01.txt','/books/Axx/01.txt','/books/A_%/sub/02.txt']
    conn.executemany('INSERT INTO books VALUES (?)',[(p,) for p in paths])
    found=[r[0] for r in conn.execute("SELECT path FROM books WHERE path LIKE ? ESCAPE '!'",(descendant_like_pattern('/books/A_%'),))]
    assert found==[paths[0],paths[3]]
    conn.close()
