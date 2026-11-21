#!/usr/bin/env python3
"""Apply an administrator-requested update from the fixed BookOasis GitHub repository."""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid


REPOSITORY = 'daydreamrabbit/BookOasis_stable'
ACTIVE_STATES = {'queued', 'checking', 'waiting', 'downloading', 'building', 'restarting', 'verifying'}
TERMINAL_STATES = {'complete', 'failed'}
MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
MAX_EXPANDED_BYTES = 2 * 1024 * 1024 * 1024
MAX_ARCHIVE_FILES = 100_000
MAX_CHANGED_FILES = 300
MAX_CHANGED_BYTES = 512 * 1024 * 1024
HOST_DATA_PATHS = {'db', 'covers', 'cache', 'plugins', 'rclone', 'logs', 'custom_fonts'}


class UpdateError(RuntimeError):
    pass


def is_within(path, parent):
    try:
        pathlib.Path(path).relative_to(pathlib.Path(parent))
        return True
    except ValueError:
        return False


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def atomic_json(path, value):
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix='.bookoasis-update-', suffix='.tmp', dir=str(path.parent))
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o640)
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def read_json(path):
    with open(path, 'r', encoding='utf-8') as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise UpdateError('업데이트 요청 형식이 올바르지 않습니다.')
    return value


def command(args, cwd=None, timeout=120, check=True):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        detail = (result.stderr or result.stdout or '').strip()[-1200:]
        raise UpdateError(f'서버 업데이트 명령이 실패했습니다: {pathlib.Path(args[0]).name} (exit {result.returncode}) {detail}')
    return result


def request_json(url):
    req = urllib.request.Request(url, headers={
        'User-Agent': 'BookOasis-Custom-Updater/1.0',
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            length = response.headers.get('Content-Length')
            if length and int(length) > 16 * 1024 * 1024:
                raise UpdateError('GitHub 변경 목록이 허용 크기를 초과했습니다.')
            body = response.read(16 * 1024 * 1024 + 1)
        if len(body) > 16 * 1024 * 1024:
            raise UpdateError('GitHub 변경 목록이 허용 크기를 초과했습니다.')
        return json.loads(body.decode('utf-8'))
    except Exception as error:
        raise UpdateError(f'GitHub에서 최신 커밋을 확인하지 못했습니다. ({type(error).__name__})') from error


def latest_main_commit():
    info = request_json(f'https://api.github.com/repos/{REPOSITORY}/commits/main')
    sha = str(info.get('sha') or '').strip().lower()
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise UpdateError('GitHub main 커밋 번호가 올바르지 않습니다.')
    return sha


def compare_release_commits(base, target):
    if not re.fullmatch(r'[0-9a-f]{40}', base) or not re.fullmatch(r'[0-9a-f]{40}', target):
        raise UpdateError('설치된 GitHub 커밋 기록이 없거나 올바르지 않습니다. 호스트 업데이트 설정을 확인해 주세요.')
    comparison = request_json(f'https://api.github.com/repos/{REPOSITORY}/compare/{base}...{target}')
    files = comparison.get('files')
    if not isinstance(files, list) or len(files) >= MAX_CHANGED_FILES:
        raise UpdateError('변경 파일이 너무 많아 자동 업데이트를 보류했습니다. 변경 내용을 검토한 뒤 수동 배포해 주세요.')
    if comparison.get('status') not in ('ahead', 'identical'):
        raise UpdateError('GitHub main이 설치된 버전의 다음 커밋이 아닙니다. 변경 내용을 검토해야 합니다.')
    changes = []
    for item in files:
        path = str(item.get('filename') or '').replace('\\', '/')
        parts = pathlib.PurePosixPath(path).parts
        if not path or path.startswith('/') or any(part in ('', '.', '..') for part in parts):
            raise UpdateError('GitHub 변경 목록에 안전하지 않은 파일 경로가 있습니다.')
        if parts[0] in HOST_DATA_PATHS:
            raise UpdateError(f'호스트 데이터 폴더의 변경은 자동 반영하지 않습니다: {parts[0]}/')
        if path == 'Dockerfile' or path.startswith('docker-compose'):
            raise UpdateError('Dockerfile 또는 Compose 변경이 포함되어 있어 자동 업데이트를 보류했습니다. 서버 설정과 함께 검토해야 합니다.')
        status = item.get('status')
        if status not in ('added', 'modified', 'removed', 'renamed'):
            raise UpdateError('GitHub 변경 목록에 처리할 수 없는 파일 상태가 있습니다.')
        previous = str(item.get('previous_filename') or '').replace('\\', '/')
        if status == 'renamed':
            old_parts = pathlib.PurePosixPath(previous).parts
            if not previous or previous.startswith('/') or any(part in ('', '.', '..') for part in old_parts):
                raise UpdateError('GitHub 변경 목록에 안전하지 않은 이전 파일 경로가 있습니다.')
            if old_parts[0] in HOST_DATA_PATHS:
                raise UpdateError('호스트 데이터 폴더에서 이동된 파일은 자동 업데이트하지 않습니다.')
            changes.append({'path': previous, 'status': 'removed'})
            changes.append({'path': path, 'status': 'added'})
        else:
            changes.append({'path': path, 'status': status})
    if not changes:
        raise UpdateError('버전은 올라갔지만 GitHub 변경 파일이 없어 자동 업데이트를 중단했습니다.')
    return changes


def validate_version_file(path, expected_version):
    text = pathlib.Path(path).read_text(encoding='utf-8-sig')
    match = re.search(r'"dashboard"\s*:\s*"([^"]+)"', text)
    version = match.group(1).strip() if match else ''
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.[a-z])?', version, re.I):
        raise UpdateError('GitHub VERSION의 대시보드 버전 형식이 올바르지 않습니다.')
    if version != expected_version:
        raise UpdateError('요청한 버전과 GitHub 소스의 버전이 다릅니다. 업데이트를 다시 확인해 주세요.')
    return version


def safe_extract_github_tarball(archive_path, destination):
    destination = pathlib.Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode='r:gz') as archive:
        members = archive.getmembers()
        if not members or len(members) > MAX_ARCHIVE_FILES:
            raise UpdateError('GitHub 소스 아카이브의 파일 수가 허용 범위를 벗어났습니다.')
        total_size = sum(max(0, member.size) for member in members if member.isfile())
        if total_size > MAX_EXPANDED_BYTES:
            raise UpdateError('GitHub 소스 아카이브의 압축 해제 크기가 허용 범위를 벗어났습니다.')

        top_level = None
        for member in members:
            raw = member.name.replace('\\', '/')
            parts = pathlib.PurePosixPath(raw).parts
            if not parts or raw.startswith('/') or any(part in ('', '.', '..') for part in parts):
                raise UpdateError('GitHub 소스 아카이브에 안전하지 않은 파일 경로가 있습니다.')
            if top_level is None:
                top_level = parts[0]
            if parts[0] != top_level:
                raise UpdateError('GitHub 소스 아카이브의 루트 구조가 올바르지 않습니다.')
            if member.issym() or member.islnk() or not (member.isdir() or member.isfile()):
                raise UpdateError('GitHub 소스 아카이브에 지원하지 않는 파일 형식이 있습니다.')

        for member in members:
            parts = pathlib.PurePosixPath(member.name.replace('\\', '/')).parts[1:]
            if not parts:
                continue
            target = (destination.joinpath(*parts)).resolve()
            if not is_within(target, destination):
                raise UpdateError('GitHub 소스 아카이브가 작업 폴더를 벗어납니다.')
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise UpdateError('GitHub 소스 파일을 읽지 못했습니다.')
                with source, open(target, 'wb') as output:
                    shutil.copyfileobj(source, output, length=1024 * 1024)
                os.chmod(target, member.mode & 0o755 or 0o644)


class HostUpdater:
    def __init__(self, root, worker_path=None):
        self.root = pathlib.Path(root).resolve()
        if not (self.root / 'docker-compose.yml').is_file() or not (self.root / 'logs').is_dir():
            raise UpdateError('BookOasis 서버 경로 또는 로그 마운트를 찾을 수 없습니다.')
        self.logs = self.root / 'logs'
        self.update_root = self.root / '.codex-updates' / 'github-self-update'
        self.update_root.mkdir(parents=True, exist_ok=True)
        self.request_path = self.logs / 'bookoasis-update-request.json'
        self.status_path = self.logs / 'bookoasis-update-status.json'
        self.processing_path = self.update_root / 'processing-request.json'
        configured_worker = worker_path or os.environ.get('BOOKOASIS_UPDATE_WORKER_PATH')
        self.worker_path = pathlib.Path(configured_worker).expanduser().resolve() if configured_worker else None

    def status(self, request_id, state, message, **extra):
        value = {'request_id': request_id, 'state': state, 'message': message, 'updated_at': utc_now()}
        value.update(extra)
        atomic_json(self.status_path, value)

    def recover_interrupted_request(self):
        if self.processing_path.exists() and not self.request_path.exists():
            os.replace(self.processing_path, self.request_path)

    def active_scans(self):
        code = (
            "import json,database; "
            "conn=database.get_connection('general'); cur=conn.cursor(); "
            "cur.execute(\"SELECT id,task_type,status FROM scanner_tasks WHERE status IN ('running','exit_pending') ORDER BY id LIMIT 50\"); "
            "rows=cur.fetchall(); conn.close(); print(json.dumps(rows,default=str))"
        )
        result = command(['docker', 'exec', 'bookoasis', 'python3', '-c', code], timeout=30)
        try:
            rows = json.loads(result.stdout.splitlines()[-1])
        except Exception as error:
            raise UpdateError('서버 스캔 상태를 확인하지 못해 업데이트를 보류했습니다.') from error
        return rows

    def image_id(self):
        result = command(['docker', 'inspect', '--format', '{{.Image}}', 'bookoasis'], timeout=30)
        return result.stdout.strip()

    def health_status(self):
        result = command(['docker', 'inspect', '--format', '{{.State.Status}} {{.State.Health.Status}}', 'bookoasis'], timeout=30)
        return result.stdout.strip()

    def wait_for_idle(self, request_id, timeout_seconds=1800):
        deadline = time.monotonic() + timeout_seconds
        while True:
            active = self.active_scans()
            if not active:
                return
            self.status(request_id, 'waiting', f'진행 중인 스캔 {len(active)}건이 끝나기를 기다리고 있습니다.', active_scans=len(active))
            if time.monotonic() >= deadline:
                raise UpdateError('진행 중인 스캔이 끝나지 않아 업데이트를 취소했습니다.')
            time.sleep(5)

    def download_source(self, commit, stage):
        url = f'https://api.github.com/repos/{REPOSITORY}/tarball/{commit}'
        req = urllib.request.Request(url, headers={'User-Agent': 'BookOasis-Custom-Updater/1.0'})
        archive_path = stage / f'{commit[:12]}.tar.gz'
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                host = urllib.parse.urlsplit(response.geturl()).hostname or ''
                if host not in {'api.github.com', 'codeload.github.com'}:
                    raise UpdateError('GitHub 아카이브 주소가 허용된 도메인이 아닙니다.')
                length = response.headers.get('Content-Length')
                if length and int(length) > MAX_ARCHIVE_BYTES:
                    raise UpdateError('GitHub 소스 아카이브 크기가 허용 범위를 벗어났습니다.')
                total = 0
                with open(archive_path, 'wb') as output:
                    while True:
                        chunk = response.read(1024 * 1024)
                        if not chunk:
                            break
                        total += len(chunk)
                        if total > MAX_ARCHIVE_BYTES:
                            raise UpdateError('GitHub 소스 아카이브 크기가 허용 범위를 벗어났습니다.')
                        output.write(chunk)
        except UpdateError:
            raise
        except Exception as error:
            raise UpdateError(f'GitHub 소스 다운로드에 실패했습니다. ({type(error).__name__})') from error
        if not archive_path.is_file() or archive_path.stat().st_size == 0:
            raise UpdateError('GitHub 소스 아카이브가 비어 있습니다.')
        return archive_path

    def ensure_server_files_match_base(self, base_source, changes):
        paths = sorted({item['path'] for item in changes})
        code = '''import hashlib,json,pathlib,sys
root=pathlib.Path('/app').resolve()
paths=json.loads(sys.argv[1])
result={}
unsafe=[]
for value in paths:
 parts=pathlib.PurePosixPath(value).parts
 lexical=root.joinpath(*parts)
 cursor=root
 for part in parts:
  cursor=cursor/part
  if cursor.is_symlink():
   unsafe.append(value)
   break
 else:
  target=lexical.resolve()
  try:
   target.relative_to(root)
  except ValueError:
   unsafe.append(value)
   continue
  if target.is_file():
   result[value]=hashlib.sha256(target.read_bytes()).hexdigest()
  elif not target.exists():
   result[value]=None
  else:
   result[value]='unsupported'
print(json.dumps({'files':result,'unsafe':unsafe}))
'''
        result = command(['docker', 'exec', 'bookoasis', 'python3', '-c', code, json.dumps(paths)], timeout=60)
        try:
            running_files = json.loads(result.stdout.splitlines()[-1])
            actual = running_files['files']
        except Exception as error:
            raise UpdateError('실행 중인 서버 파일을 비교하지 못해 업데이트를 보류했습니다.') from error
        if running_files.get('unsafe'):
            raise UpdateError('서버 변경 파일 경로가 안전하지 않아 자동 업데이트를 중단했습니다.')

        conflicts = []
        for item in changes:
            path = item['path']
            base_file = pathlib.Path(base_source).joinpath(*pathlib.PurePosixPath(path).parts)
            if base_file.is_file() and not base_file.is_symlink():
                expected = hashlib.sha256(base_file.read_bytes()).hexdigest()
            else:
                expected = None
            if actual.get(path) != expected:
                conflicts.append(path)
        if conflicts:
            shown = ', '.join(conflicts[:8])
            suffix = f' 외 {len(conflicts) - 8}개' if len(conflicts) > 8 else ''
            raise UpdateError(f'서버에서 별도로 수정된 파일이 있어 덮어쓰기를 중단했습니다: {shown}{suffix}')

    def installed_commit(self):
        marker = self.logs / 'bookoasis-update-installed.json'
        try:
            data = read_json(marker)
        except Exception as error:
            raise UpdateError('현재 설치 커밋 기록을 찾지 못했습니다. 호스트 업데이트 설정을 확인해 주세요.') from error
        commit = str(data.get('commit') or '').strip().lower()
        if not re.fullmatch(r'[0-9a-f]{40}', commit):
            raise UpdateError('현재 설치 커밋 기록이 올바르지 않습니다. 호스트 업데이트 설정을 확인해 주세요.')
        return commit

    def build_candidate(self, source, commit, changes, base_image, stage):
        tag = f'bookoasis:github-update-{commit[:12]}'
        context = stage / 'image-patch'
        payload_root = context / 'payload'
        payload_root.mkdir(parents=True, exist_ok=True)
        (payload_root / '.patch-placeholder').write_text('', encoding='utf-8')
        changed_bytes = 0
        requirements_changed = False
        for change in changes:
            rel = pathlib.PurePosixPath(change['path'])
            if rel.as_posix() == 'requirements.txt' and change['status'] != 'removed':
                requirements_changed = True
            if change['status'] == 'removed':
                continue
            source_file = (source.joinpath(*rel.parts)).resolve()
            if not is_within(source_file, source.resolve()) or not source_file.is_file() or source_file.is_symlink():
                raise UpdateError(f'GitHub에서 변경된 파일을 안전하게 찾지 못했습니다: {rel.as_posix()}')
            changed_bytes += source_file.stat().st_size
            if changed_bytes > MAX_CHANGED_BYTES:
                raise UpdateError('변경 파일 크기가 허용 범위를 넘어 자동 업데이트를 중단했습니다.')
            target = payload_root.joinpath(*rel.parts)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_file, target)

        (context / 'changes.json').write_text(json.dumps(changes), encoding='utf-8')
        apply_patch_script = '''import json,pathlib,shutil,sys
root=pathlib.Path('/app').resolve()
payload=pathlib.Path('/tmp/bookoasis-update/payload').resolve()
changes=json.loads(pathlib.Path('/tmp/bookoasis-update/changes.json').read_text(encoding='utf-8'))
for item in changes:
 parts=pathlib.PurePosixPath(item['path']).parts
 if not parts or any(part in ('','.', '..') for part in parts): raise SystemExit('unsafe release path')
 lexical=root.joinpath(*parts)
 cursor=root
 for part in parts:
  cursor=cursor/part
  if cursor.is_symlink(): raise SystemExit('release path traverses symlink')
 target=lexical.resolve()
 try: target.relative_to(root)
 except ValueError: raise SystemExit('release path escapes app root')
 if item['status']=='removed':
  if target.is_file() or target.is_symlink(): target.unlink()
  parent=target.parent
  while parent!=root:
   try: parent.rmdir()
   except OSError: break
   parent=parent.parent
 else:
  source=(payload.joinpath(*parts)).resolve()
  try: source.relative_to(payload)
  except ValueError: raise SystemExit('missing release payload')
  if not source.is_file() or source.is_symlink(): raise SystemExit('missing release payload')
  target.parent.mkdir(parents=True,exist_ok=True)
  shutil.copy2(source,target)
'''
        (context / 'apply_patch.py').write_text(apply_patch_script, encoding='utf-8')
        dockerfile = [
            f'FROM {base_image}',
            'COPY payload/ /tmp/bookoasis-update/payload/',
            'COPY changes.json /tmp/bookoasis-update/changes.json',
            'COPY apply_patch.py /tmp/bookoasis-update/apply_patch.py',
            'RUN python3 /tmp/bookoasis-update/apply_patch.py',
        ]
        if requirements_changed:
            dockerfile.append('RUN pip install --no-cache-dir -r /app/requirements.txt')
        (context / 'Dockerfile').write_text('\n'.join(dockerfile) + '\n', encoding='utf-8')
        network = 'default' if requirements_changed else 'none'
        command(['docker', 'build', '--network', network, '--pull=false', '-t', tag,
                 '-f', str(context / 'Dockerfile'), str(context)], cwd=self.root, timeout=2400)
        return tag

    def validate_candidate(self, image, expected_version):
        code = (
            "import pathlib,re,sys; "
            "text=pathlib.Path('/app/VERSION').read_text(encoding='utf-8-sig'); "
            "match=re.search(r'\\\"dashboard\\\"\\s*:\\s*\\\"([^\\\"]+)\\\"',text); "
            "assert match and match.group(1)==sys.argv[1], 'candidate version mismatch'; "
            "assert pathlib.Path('/app/tools/bookoasis_host_updater.py').is_file(), 'host updater source missing'; "
            "print(match.group(1))"
        )
        result = command(['docker', 'run', '--rm', '--network', 'none', '--entrypoint', 'python3', image, '-c', code, expected_version], timeout=120)
        if result.stdout.strip().splitlines()[-1] != expected_version:
            raise UpdateError('새 서버 이미지의 버전을 확인하지 못했습니다.')

    def wait_ready(self, timeout_seconds=180):
        deadline = time.monotonic() + timeout_seconds
        last = ''
        while time.monotonic() < deadline:
            last = self.health_status()
            if last == 'running healthy':
                try:
                    with urllib.request.urlopen('http://127.0.0.1:5930/login', timeout=5) as response:
                        if response.status == 200:
                            return
                except (urllib.error.URLError, TimeoutError):
                    pass
            if last.startswith(('exited', 'dead')):
                raise UpdateError(f'BookOasis 컨테이너가 시작되지 않았습니다. ({last})')
            time.sleep(2)
        raise UpdateError(f'BookOasis 정상 상태 확인 시간이 초과됐습니다. ({last})')

    def install_worker_from_source(self, source):
        source_worker = source / 'tools' / 'bookoasis_host_updater.py'
        if not source_worker.is_file() or not self.worker_path:
            return None
        old_bytes = self.worker_path.read_bytes() if self.worker_path.is_file() else None
        self.worker_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='.updater-', suffix='.tmp', dir=str(self.worker_path.parent))
        try:
            with os.fdopen(fd, 'wb') as output, open(source_worker, 'rb') as input_file:
                shutil.copyfileobj(input_file, output)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o750)
            os.replace(temp_name, self.worker_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return old_bytes

    def restore_worker(self, old_bytes):
        if old_bytes is None or not self.worker_path:
            return
        self.worker_path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(prefix='.updater-rollback-', suffix='.tmp', dir=str(self.worker_path.parent))
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(old_bytes)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temp_name, 0o750)
            os.replace(temp_name, self.worker_path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

    def process(self):
        if not self.request_path.exists():
            return False

        lock_path = self.update_root / 'worker.lock'
        with open(lock_path, 'w', encoding='utf-8') as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            if not self.request_path.exists():
                return False
            request = read_json(self.request_path)
            request_id = str(request.get('request_id') or '')
            commit = str(request.get('commit') or '').lower()
            version = str(request.get('version') or '')
            if not re.fullmatch(r'[0-9a-f]{32}', request_id) or not re.fullmatch(r'[0-9a-f]{40}', commit):
                self.request_path.unlink(missing_ok=True)
                raise UpdateError('업데이트 요청의 식별자 형식이 올바르지 않습니다.')
            if not re.fullmatch(r'\d+\.\d+\.\d+(?:\.[a-z])?', version, re.I):
                self.request_path.unlink(missing_ok=True)
                raise UpdateError('업데이트 요청의 버전 형식이 올바르지 않습니다.')

            os.replace(self.request_path, self.processing_path)
            stage = self.update_root / f'job-{request_id}'
            candidate_image = None
            old_image = None
            container_switched = False
            worker_backup = None
            rollback_error = None
            try:
                self.status(request_id, 'checking', '서버와 GitHub 커밋을 확인하고 있습니다.', version=version)
                if self.health_status() != 'running healthy':
                    raise UpdateError('현재 BookOasis 서버가 정상 상태가 아니어서 업데이트를 중단했습니다.')
                current_main = latest_main_commit()
                if current_main != commit:
                    raise UpdateError('GitHub main이 확인 후 변경됐습니다. 업데이트를 다시 확인해 주세요.')
                base_commit = self.installed_commit()
                if base_commit == commit:
                    raise UpdateError('이 GitHub 커밋은 이미 설치되어 있습니다.')
                changes = compare_release_commits(base_commit, commit)

                active = self.active_scans()
                if active:
                    self.status(request_id, 'waiting', f'진행 중인 스캔 {len(active)}건이 끝나기를 기다리고 있습니다.', version=version)
                    self.wait_for_idle(request_id)

                stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
                stage.mkdir(parents=True, exist_ok=False)
                source = stage / 'source'
                source.mkdir()
                base_source = stage / 'base-source'
                base_source.mkdir()
                self.status(request_id, 'downloading', 'GitHub에서 승인된 소스 커밋을 내려받고 있습니다.', version=version)
                base_archive = self.download_source(base_commit, stage)
                safe_extract_github_tarball(base_archive, base_source)
                archive = self.download_source(commit, stage)
                safe_extract_github_tarball(archive, source)
                validate_version_file(source / 'VERSION', version)
                self.status(request_id, 'checking', '서버의 별도 수정 파일을 확인하고 있습니다.', version=version)
                self.ensure_server_files_match_base(base_source, changes)

                compose_hash = command(['docker', 'compose', 'config', '--hash', 'bookoasis'], cwd=self.root).stdout.strip()
                old_image = self.image_id()
                rollback_tag = f'bookoasis:rollback-{datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ").lower()}'
                command(['docker', 'tag', old_image, rollback_tag], timeout=30)
                self.status(request_id, 'building', '새 서버 이미지를 만들고 검사하고 있습니다.', version=version)
                candidate_image = self.build_candidate(source, commit, changes, rollback_tag, stage)
                self.validate_candidate(candidate_image, version)

                self.wait_for_idle(request_id)
                if command(['docker', 'compose', 'config', '--hash', 'bookoasis'], cwd=self.root).stdout.strip() != compose_hash:
                    raise UpdateError('업데이트 준비 중 Docker Compose 설정이 바뀌어 적용을 중단했습니다.')
                if self.image_id() != old_image:
                    raise UpdateError('업데이트 준비 중 실행 중인 이미지가 바뀌어 적용을 중단했습니다.')

                worker_backup = self.install_worker_from_source(source)
                command(['docker', 'tag', candidate_image, 'bookoasis:local'], timeout=30)
                container_switched = True
                self.status(request_id, 'restarting', '새 이미지로 BookOasis를 재시작하고 있습니다.', version=version)
                command(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', 'bookoasis'], cwd=self.root, timeout=180)
                self.status(request_id, 'verifying', '로그인 화면과 컨테이너 상태를 확인하고 있습니다.', version=version)
                self.wait_ready()
                running_image = self.image_id()
                if running_image != command(['docker', 'image', 'inspect', '--format', '{{.Id}}', candidate_image]).stdout.strip():
                    raise UpdateError('새 버전 이미지가 실행 중인지 확인하지 못했습니다.')

                atomic_json(self.logs / 'bookoasis-update-installed.json', {
                    'version': version, 'commit': commit, 'installed_at': utc_now(),
                })
                self.status(request_id, 'complete', f'BookOasis v{version} 업데이트를 완료했습니다. 화면을 새로고침해 주세요.',
                            version=version, commit=commit, image=running_image)
                self.processing_path.unlink(missing_ok=True)
                shutil.rmtree(stage, ignore_errors=True)
                return True
            except Exception as error:
                if container_switched and old_image:
                    try:
                        command(['docker', 'tag', old_image, 'bookoasis:local'], timeout=30)
                        command(['docker', 'compose', 'up', '-d', '--no-deps', '--no-build', 'bookoasis'], cwd=self.root, timeout=180)
                        self.wait_ready()
                    except Exception as rollback:
                        rollback_error = f' 이전 버전 복구도 실패했습니다: {type(rollback).__name__}'
                if worker_backup is not None:
                    try:
                        self.restore_worker(worker_backup)
                    except Exception as rollback:
                        rollback_error = (rollback_error or '') + f' 업데이트 작업 복구도 실패했습니다: {type(rollback).__name__}'
                message = str(error)[:700]
                if rollback_error:
                    message += rollback_error
                self.status(request_id, 'failed', message, version=version, rolled_back=container_switched and not rollback_error)
                self.processing_path.unlink(missing_ok=True)
                shutil.rmtree(stage, ignore_errors=True)
                return False


def main():
    parser = argparse.ArgumentParser(description='BookOasis GitHub host updater')
    parser.add_argument('--watch', action='store_true', help='Poll the host request file and apply queued updates.')
    parser.add_argument('--root', default=os.environ.get('BOOKOASIS_UPDATE_ROOT', ''), help='BookOasis Compose project directory.')
    parser.add_argument('--worker-path', default=os.environ.get('BOOKOASIS_UPDATE_WORKER_PATH', ''), help='Installed worker file to refresh after updates.')
    parser.add_argument('--poll-seconds', type=float, default=2.0)
    args = parser.parse_args()
    if not args.root:
        parser.error('Set BOOKOASIS_UPDATE_ROOT or pass --root.')
    updater = HostUpdater(args.root, args.worker_path or None)
    updater.recover_interrupted_request()
    if not args.watch:
        return 0

    while True:
        try:
            changed = updater.process()
            if changed and updater.worker_path and updater.worker_path.is_file():
                os.execv(sys.executable, [sys.executable, str(updater.worker_path), '--watch'])
        except BlockingIOError:
            pass
        except Exception as error:
            print(f'[BookOasis Updater] {type(error).__name__}: {error}', flush=True)
            try:
                if updater.request_path.exists():
                    request = read_json(updater.request_path)
                    request_id = str(request.get('request_id') or '')
                    if re.fullmatch(r'[0-9a-f]{32}', request_id):
                        updater.status(request_id, 'failed', str(error)[:700])
                        updater.request_path.unlink(missing_ok=True)
            except Exception:
                pass
        time.sleep(max(0.5, min(args.poll_seconds, 30.0)))


if __name__ == '__main__':
    raise SystemExit(main())
