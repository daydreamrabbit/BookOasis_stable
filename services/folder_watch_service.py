"""Durable change coalescing and outbox -> existing scanner queue.

Watchers never delete source files. Missing books are only soft-deleted, when
explicitly enabled, after complete repeated listings and a final recheck.
"""
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import PurePosixPath
from services import folder_watch_store as store


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def library(key):
    from repositories.category_repository import CategoryRepository
    db_type, identifier = key.split(':')
    return CategoryRepository.get_library_by_id(db_type, int(identifier))


def roots_for(lib):
    return [p.strip().rstrip('/') for p in lib['physical_path'].splitlines() if p.strip()]


def validate_config(data, lib):
    config = dict(store.DEFAULTS)
    for key in ('enabled', 'reflect_deletions'):
        if key in data and not isinstance(data[key], bool):
            raise ValueError('감시/삭제 옵션은 true 또는 false여야 합니다.')
        config[key] = data.get(key, config[key])
    config['mode'] = data.get('mode', 'auto')
    if config['mode'] not in ('auto', 'local', 'poll', 'rclone'):
        raise ValueError('지원하지 않는 감시 방식입니다.')
    for key, low, high in [('interval', 10, 86400), ('settle', 10, 3600)]:
        value = data.get(key, config[key])
        if isinstance(value, bool) or not str(value).isdigit() or not low <= int(value) <= high:
            raise ValueError(f'{key}: {low}~{high}초로 입력하세요.')
        config[key] = int(value)
    config['rclone_remote'] = str(data.get('rclone_remote', '')).strip()
    roots = roots_for(lib)
    if config['mode'] == 'rclone':
        import re
        remotes = config['rclone_remote'].splitlines()
        if len(roots) != len(remotes) or not roots or any(not os.path.isabs(p) for p in roots) or any(not re.match(r'^[\w .-]+:', p.strip()) or p.strip().startswith('-') for p in remotes):
            raise ValueError('라이브러리 경로 순서대로 각 remote:folder를 한 줄씩 입력하세요.')
    # Bind settings to the current library, preventing ID reuse/path edits from
    # automatically enabling monitoring on an unrelated replacement library.
    config['paths'] = lib['physical_path']
    return config


def status(key):
    config, summary = store.public_status(key)
    return {'config': config, 'status': (summary.get('status') or '첫 확인 대기') if config['enabled'] else '꺼짐',
            'last_check': summary.get('last_check'), 'error': summary.get('error') or summary.get('event_warning') or '',
            'pending': summary.get('pending', 0)}


def probe(root, config):
    remote = config.get('rclone_remote', '')
    if config['mode'] == 'rclone' and config.get('paths'):
        roots = roots_for({'physical_path': config['paths']})
        remote = remote.splitlines()[roots.index(root)].strip()
    script = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'tools', 'folder_watch_probe.py')
    result = subprocess.run([sys.executable, script], input=json.dumps({
        'root': root, 'mode': config['mode'], 'remote': remote,
    }), capture_output=True, text=True, timeout=120)
    try:
        data = json.loads(result.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        raise ValueError('감시 목록 조회 프로세스 오류') from None
    if result.returncode or 'error' in data:
        raise ValueError(data.get('error', '감시 목록 조회 실패'))
    return data['files']


def verify_mount(root, config, files, db_type, library_id, scope_folders=None):
    from services.folder_watch_sources import mounted_remote
    if config['mode'] != 'rclone' and not (config['mode'] == 'auto' and not root.startswith(('http://', 'https://', 'gdrive:')) and mounted_remote(root)):
        return
    import database
    from tools.scanner.vfs import trigger_vfs_refresh
    trigger_vfs_refresh(database.get_db_path(db_type), library_id, root)
    try:
        mounted = probe(root, dict(config, mode='poll'))
    except (OSError, ValueError) as error:
        raise RuntimeError(
            'rclone 원격 목록은 확인했지만 컨테이너의 로컬 마운트 경로를 읽을 수 없습니다. '
            '호스트 rclone 마운트와 Docker bind propagation(rslave)을 확인하세요.'
        ) from error
    folders = tuple(folder for folder in (scope_folders or ()) if folder)
    def in_scope(path):
        return not folders or any(folder == '.' or path == folder or path.startswith(folder + '/') for folder in folders)

    remote_scoped = {path for path in files if in_scope(path)}
    mounted_scoped = {path for path in mounted if in_scope(path)}
    if remote_scoped != mounted_scoped:
        raise RuntimeError('변경 대상 폴더의 rclone 원격 목록과 컨테이너 마운트 목록이 다릅니다. 캐시 갱신 후 재시도합니다.')
    if any(mounted[path][0] != files[path][0] for path in remote_scoped):
        raise RuntimeError('변경 대상 폴더의 원격 파일 크기와 마운트 파일 크기가 다릅니다. 캐시 갱신 후 재시도합니다.')

    from datetime import datetime
    for path, signature in files.items():
        if not in_scope(path):
            continue
        if not signature[1]:
            continue
        remote_time = datetime.fromisoformat(signature[1].replace('Z', '+00:00')).timestamp()
        mounted_time = int(mounted[path][1]) / 1_000_000_000
        if abs(remote_time - mounted_time) > 2:
            raise RuntimeError('변경 대상 폴더의 rclone 마운트 수정 시간이 원격과 다릅니다. 캐시 갱신 후 재시도합니다.')

    full_match = set(mounted) == set(files) and all(mounted[path][0] == files[path][0] for path in files)
    if not full_match and folders:
        print('[Folder-Watch] 변경 대상 폴더는 원격/마운트가 일치합니다. 다른 폴더의 목록 차이는 이번 스캔에서 제외합니다.', flush=True)
    return full_match


def changed_folders(before, after):
    paths = [p for p in after if after[p] != before.get(p)]
    folders = sorted({str(PurePosixPath(p).parent) for p in paths}, key=lambda p: (len(PurePosixPath(p).parts), p))
    result = []
    for folder in folders:
        if not any(parent == '.' or folder == parent or folder.startswith(parent + '/') for parent in result):
            result.append(folder)
    return result


def advance_root(state, files, now, config, enqueue, task_status):
    """Pure reconciliation seam: checkpoint only completed tasks, not queued ones."""
    if 'baseline' not in state:
        state.update(baseline=files, observed=files, since=now)
        return '기준 목록 저장 완료'
    # Retain identities even when deletion reflection is OFF or the source scan
    # runs first. The destination may only be checked several minutes later.
    missing = state.setdefault('move_candidates', {})
    for path, signature in {**state['baseline'], **state.get('observed', {})}.items():
        if path not in files and len(signature) > 2 and signature[2]:
            missing.setdefault(path, {'signature': signature, 'since': now})
    state['move_candidates'] = {p: item for p, item in missing.items()
                                if p not in files and now - item['since'] < 30 * 86400}
    active = state.get('active')
    if active:
        phase = task_status(active['token'])
        if phase == 'completed':
            state['baseline'] = active['files']
            del state['active']
        elif phase in ('failed', 'cancelled', 'interrupted'):
            del state['active']
            state['observed'] = files
            state['since'] = now
            return '작업 재시도 대기'
        else:
            if phase is None:
                enqueue(active)  # durable outbox recovery after crash before enqueue
            return '변경 스캔 대기/진행 중'
    baseline = state['baseline']
    removed = set(baseline) - set(files)
    if baseline and not files:
        raise ValueError('이전 목록이 모두 사라졌습니다. 연결/마운트를 확인하세요. 자동 반영을 보류합니다.')
    if len(removed) >= 10 and len(removed) >= len(baseline) / 2:
        raise ValueError('대량 누락 감지: 연결 장애 보호를 위해 자동 반영을 보류합니다.')
    if files != state.get('observed'):
        state.update(observed=files, since=now)
        return '파일 변경 안정화 대기'
    if files == baseline:
        return '감시 중'
    # At least two complete listings; deletion requires an additional grace period.
    delay = max(config['settle'], 60 if removed else 0)
    if now - state.get('since', now) < delay:
        return '파일 변경 안정화 대기'
    folders = changed_folders(baseline, files)
    deletions = sorted(removed) if config['reflect_deletions'] else []
    if not folders and not deletions:
        state['baseline'] = files
        return '삭제 감지 (자동 반영 OFF)'
    state['active'] = {'token': uuid.uuid4().hex, 'files': files, 'folders': folders,
                       'removed': {p: baseline[p] for p in deletions}}
    # Caller commits outbox before it invokes enqueue.
    return '변경 스캔 예약'


def tick(key, config, state, dirty=False):
    now = time.time()
    if not config.get('enabled'):
        return
    waiting = state.get('status') in ('파일 변경 안정화 대기', '작업 재시도 대기', '변경 스캔 예약', '변경 스캔 대기/진행 중')
    delay = min(config['interval'], config['settle']) if dirty or waiting or state.get('pending') else config['interval']
    if now - (state.get('last_check') or 0) < delay:
        return
    warning = state.get('event_warning')
    full_state = store.get(key)[1]
    state.clear()
    state.update(full_state)
    if warning:
        state['event_warning'] = warning
    lib = library(key)
    if not lib or lib['physical_path'] != config.get('paths'):
        state.update(status='설정 확인 필요', error='라이브러리 경로가 변경/삭제되었습니다. 감시 설정을 다시 저장하세요.')
        store.save_state(key, state)
        return
    from services.scanner_queue import scanner_queue
    from repositories.scanner_queue_repository import ScannerQueueRepository
    db_type, identifier = key.split(':')
    state['last_check'] = now
    state['error'] = ''
    statuses, errors = [], []
    for root in roots_for(lib):
        root_state = state.setdefault('roots', {}).setdefault(root, {})
        try:
            files = probe(root, config)
            def enqueue(active):
                scanner_queue.enqueue('folder_watch', watch_key=key, token=active['token'], root=root,
                                      db_type=db_type, library_id=int(identifier), config_hash=digest(config))
            def phase(token):
                row = ScannerQueueRepository.get_watch_task_result('folder_watch_' + token)
                return row['status'] if row else None
            root_state['status'] = advance_root(root_state, files, now, config, enqueue, phase)
            root_state['error'] = ''
            store.save_state(key, state)
            if root_state.get('active') and phase(root_state['active']['token']) is None:
                enqueue(root_state['active'])
        except Exception as error:
            root_state.update(status='감시 오류/보호 중', error=str(error)[:400])
            errors.append(f'{root}: {error}')
        statuses.append(root_state['status'])
    priorities = ['감시 오류/보호 중', '작업 재시도 대기', '파일 변경 안정화 대기',
                  '변경 스캔 예약', '변경 스캔 대기/진행 중', '기준 목록 저장 완료', '삭제 감지 (자동 반영 OFF)', '감시 중']
    state['status'] = next((s for s in priorities if s in statuses), '감시 중')
    state['error'] = '\n'.join(errors)[:800]
    state['checked_roots'] = len(statuses)
    store.save_state(key, state)


def execute_task(task_id, watch_key, token, root, config_hash, **kwargs):
    import database
    from repositories.scanner_queue_repository import ScannerQueueRepository
    from services.scan_cancellation import ScanCancelledError
    from tools.scanner.core import scan_library_path
    from tools.scanner.path_utils import canonical_path
    from utils.drive_helper import extract_gdrive_folder_id, encode_gdrive_file_id
    config, state = store.get(watch_key)
    lib = library(watch_key)
    if not config.get('enabled') or digest(config) != config_hash or not lib or config.get('paths') != lib['physical_path']:
        raise ScanCancelledError('감시가 꺼졌거나 라이브러리/감시 설정이 변경되었습니다.')
    active = state.get('roots', {}).get(root, {}).get('active')
    if not active or active['token'] != token:
        raise ScanCancelledError('오래된 감시 작업입니다.')
    if probe(root, config) != active['files']:
        raise RuntimeError('대기 중 파일이 다시 변경되었습니다. 안정화 후 재시도합니다.')
    db_type, identifier = watch_key.split(':')
    verify_mount(root, config, active['files'], db_type, int(identifier), active.get('folders'))
    if ScannerQueueRepository.is_cancel_requested(task_id):
        raise ScanCancelledError('사용자가 이동 확인 작업을 중단했습니다.')
    from services.folder_watch_moves import reconcile_moves
    reconcile_moves(watch_key, root, config, active['files'])
    is_drive = root.startswith(('http://', 'https://', 'gdrive:'))
    drive_id = extract_gdrive_folder_id(root) if is_drive else None
    def ensure_active():
        current_config = store.public_status(watch_key)[0]
        if digest(current_config) != config_hash or ScannerQueueRepository.is_cancel_requested(task_id):
            raise ScanCancelledError('감시 설정이 변경되었거나 사용자가 작업을 중단했습니다.')
    for folder in active['folders']:
        ensure_active()
        ScannerQueueRepository.update_task_stage(task_id, f'폴더 감시 · 변경 폴더 스캔 · {folder}')
        target = root if is_drive else os.path.join(root, folder)
        scope = f'gdrive://{drive_id}/' + ('' if folder == '.' else folder + '/') if is_drive else canonical_path(target).rstrip('/') + '/'
        listed_files = None
        if is_drive:
            listed_files = [{'name': PurePosixPath(p).name, 'rel_folder': '' if str(PurePosixPath(p).parent) == '.' else str(PurePosixPath(p).parent),
                             'id': sig[2], 'size': sig[0], 'modifiedTime': sig[1]}
                            for p, sig in active['files'].items() if folder == '.' or p.startswith(folder + '/')]
        scan_library_path(database.get_db_path(db_type), int(identifier), target, force=False,
                          path_scope=scope, gdrive_subpath='' if folder == '.' else folder if is_drive else None,
                          allow_missing=False, gdrive_listing=listed_files, moves_reconciled=True)
    if active['removed'] and config['reflect_deletions']:
        # Deletion reflection needs a complete local/remote snapshot even when
        # a changed-folder scan above was safe to scope narrowly.
        verify_mount(root, config, active['files'], db_type, int(identifier))
        if probe(root, config) != active['files']:
            raise RuntimeError('삭제 반영 직전 목록 변경 감지. 삭제하지 않고 재확인합니다.')
        ensure_active()
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            for path, signature in active['removed'].items():
                full_path = encode_gdrive_file_id(canonical_path(f'gdrive://{drive_id}/{path}'), signature[2]) if is_drive else canonical_path(os.path.join(root, path))
                ph = '%s' if database.is_mariadb_mode() else '?'
                cursor.execute(f'UPDATE books SET is_deleted=1, deleted_at=CURRENT_TIMESTAMP WHERE library_id={ph} AND file_path={ph} AND COALESCE(is_deleted,0)=0',
                               (int(identifier), full_path))
            conn.commit()


def start_watch_thread():
    def run():
        # OS releases this lock even after kill/crash. Web workers never own it.
        import fcntl
        import database
        lock = open(os.path.join(database.DB_DIR, 'folder_watch.lock'), 'a')
        # A duplicate worker waits here and can take over if the owner exits.
        fcntl.flock(lock, fcntl.LOCK_EX)
        observers, events = {}, {}
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
        class Handler(FileSystemEventHandler):
            def __init__(self, event):
                self.event = event
            def on_any_event(self, event):
                if event.event_type in ('created', 'modified', 'deleted', 'moved', 'closed'):
                    self.event.set()
        while True:
            try:
                watches = store.all_watches()
                desired = {k: digest(c) for k, c, _ in watches if c.get('enabled')}
                for key in list(observers):
                    if observers[key][0] != desired.get(key):
                        observers.pop(key)[1].stop()
                for key, config, state in watches:
                    if not config.get('enabled'):
                        continue
                    event = events.setdefault(key, threading.Event())
                    if key not in observers and config['mode'] in ('auto', 'local'):
                        from utils.drive_helper import is_remote_path
                        observer = Observer()
                        try:
                            for root in config['paths'].splitlines():
                                if os.path.isdir(root) and not is_remote_path(root):
                                    observer.schedule(Handler(event), root, recursive=True)
                            observer.start()
                            observers[key] = (digest(config), observer)
                        except Exception:
                            # Periodic reconciliation remains available when inotify
                            # limits are reached or a mount doesn't deliver events.
                            state['event_warning'] = '이벤트 감시 불가: 주기 비교로 동작합니다.'
                    dirty = event.is_set()
                    tick(key, config, state, dirty)
                    if dirty and time.time() - (state.get('last_check') or 0) < 5:
                        event.clear()
            except Exception as error:
                print(f'[Folder-Watch] {type(error).__name__}: {error}', flush=True)
            time.sleep(5)
    threading.Thread(target=run, daemon=True, name='folder-watch').start()
