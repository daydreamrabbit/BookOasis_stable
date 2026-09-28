"""Metadata-only, fail-closed listings. Never read/download book contents."""
import json
import os
import re
import subprocess
from pathlib import PurePosixPath

EXTENSIONS = {'.txt', '.epub', '.pdf', '.zip', '.cbz', '.rar', '.cbr', '.7z',
              '.jpg', '.jpeg', '.png', '.webp', '.gif', '.mp3', '.m4b', '.m4a',
              '.flac', '.ogg', '.wav', '.mp4', '.mkv', '.avi', '.webm', '.xml', '.json', '.yaml'}
LIMIT = 200000


def relative_path(value):
    path = PurePosixPath(value)
    if path.is_absolute() or '..' in path.parts or '\\' in value or '\x00' in value:
        raise ValueError('잘못된 원격 상대 경로')
    return str(path)


def supported(path):
    return not any(p.startswith('.') for p in PurePosixPath(path).parts) and PurePosixPath(path).suffix.lower() in EXTENSIONS


def local_listing(root):
    if not os.path.isabs(root) or not os.path.isdir(root):
        raise ValueError('라이브러리 경로에 접근할 수 없습니다.')
    from utils.drive_helper import _find_best_remote_mount_point
    stable_inodes = not _find_best_remote_mount_point(root)
    result = {}
    def onerror(error):
        raise error
    for directory, dirs, files in os.walk(root, onerror=onerror, followlinks=False):
        dirs[:] = [d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(directory, d))]
        for name in files:
            path = os.path.join(directory, name)
            rel = os.path.relpath(path, root).replace(os.sep, '/')
            if not supported(rel) or os.path.islink(path):
                continue
            info = os.stat(path)
            result[rel] = [info.st_size, str(info.st_mtime_ns),
                           f'local:{info.st_dev}:{info.st_ino}' if stable_inodes else '']
            if len(result) > LIMIT:
                raise ValueError('감시 파일 한도 초과 (200000개). 라이브러리를 나눠 주세요.')
    return result


def rclone_listing(remote):
    if not re.match(r'^[\w .-]+:', remote) or remote.startswith('-'):
        raise ValueError('rclone 경로는 remote:folder 형식이어야 합니다.')
    from utils.rclone_gdrive_copy import _rclone_config_args
    result = subprocess.run(['rclone', *_rclone_config_args(), 'lsjson', remote,
                             '--recursive', '--files-only', '--no-mimetype', '--retries', '1',
                             '--low-level-retries', '1', '--contimeout', '15s', '--timeout', '60s'],
                            capture_output=True, text=True, timeout=100)
    if result.returncode:
        if result.returncode == 3:
            raise ValueError(f'rclone 목록 조회 실패: 원격 폴더가 없습니다 ({remote}). 라이브러리 경로를 확인하세요.')
        raise ValueError('rclone 목록 조회 실패. 리모트 설정과 연결을 확인하세요.')
    files = {}
    for entry in json.loads(result.stdout):
        path = relative_path(entry['Path'])
        if supported(path):
            files[path] = [entry['Size'], entry.get('ModTime', ''), entry.get('ID', '')]
        if len(files) > LIMIT:
            raise ValueError('감시 파일 한도 초과')
    return files


def drive_listing(root):
    # Existing BookOasis shared-folder integration uses API keys, not OAuth.
    # Do not silently fall back to incomplete HTML scraping on API failure.
    import requests
    from utils.drive_helper import extract_gdrive_folder_id
    key = os.getenv('GDRIVE_API_KEY') or os.getenv('GOOGLE_API_KEY')
    folder_id = extract_gdrive_folder_id(root)
    if not key or not folder_id:
        raise ValueError('공개 Drive 폴더 감시에는 유효한 폴더 주소와 GDRIVE_API_KEY가 필요합니다.')
    try:
        access = requests.get(f'https://www.googleapis.com/drive/v3/files/{folder_id}',
                              params={'key': key, 'fields': 'id,mimeType', 'supportsAllDrives': 'true'}, timeout=20)
    except requests.RequestException:
        raise ValueError('Drive 폴더 접근 확인 실패') from None
    if access.status_code != 200:
        raise ValueError(f'Drive 폴더 접근 실패 (HTTP {access.status_code})')
    if access.json().get('mimeType') != 'application/vnd.google-apps.folder':
        raise ValueError('Drive 감시 대상이 폴더가 아닙니다.')
    pending = [(folder_id, '', 0)]
    files, seen = {}, set()
    while pending:
        folder, parent, depth = pending.pop()
        if folder in seen:
            continue
        seen.add(folder)
        if depth > 32:
            raise ValueError('Drive 폴더 깊이 한도 초과')
        token = None
        while True:
            try:
                response = requests.get('https://www.googleapis.com/drive/v3/files', params={
                    'key': key, 'q': f"'{folder}' in parents and trashed = false", 'pageSize': 1000,
                    'fields': 'nextPageToken,incompleteSearch,files(id,name,mimeType,size,modifiedTime)',
                    'supportsAllDrives': 'true', 'includeItemsFromAllDrives': 'true', 'pageToken': token,
                }, timeout=20)
            except requests.RequestException:
                raise ValueError('Drive 연결 오류. 인증 설정과 네트워크를 확인하세요.') from None
            if response.status_code != 200:
                raise ValueError(f'Drive 목록 조회 실패 (HTTP {response.status_code})')
            data = response.json()
            if data.get('incompleteSearch') or 'files' not in data:
                raise ValueError('Drive 목록이 불완전하여 변경 반영을 중단했습니다.')
            for item in data['files']:
                path = relative_path('/'.join(filter(None, [parent, item['name']])))
                if item['mimeType'] == 'application/vnd.google-apps.folder':
                    pending.append((item['id'], path, depth + 1))
                elif supported(path):
                    if path in files:
                        raise ValueError('Drive에 같은 경로/이름의 파일이 중복되어 있습니다.')
                    files[path] = [int(item.get('size', 0)), item.get('modifiedTime', ''), item['id']]
                if len(files) > LIMIT or len(seen) + len(pending) > LIMIT:
                    raise ValueError('Drive 감시 항목 한도 초과')
            token = data.get('nextPageToken')
            if not token:
                break
    return files


def mounted_remote(root, mountinfo_path='/proc/self/mountinfo'):
    """Resolve each container path, including bind-mount subroots, independently."""
    from utils.drive_helper import _decode_mount_token
    target = os.path.realpath(root)
    candidates = []
    with open(mountinfo_path, encoding='utf-8') as stream:
        for line in stream:
            before, separator, after = line.partition(' - ')
            fields, filesystem = before.split(), after.split()
            if not separator or len(fields) < 5 or len(filesystem) < 2:
                continue
            mount = _decode_mount_token(fields[4])
            if os.path.commonpath([target, mount]) != mount:
                continue
            candidates.append((len(mount), mount, fields[3], filesystem))
    if not candidates:
        return None
    _, mount, subroot, filesystem = max(candidates, key=lambda item: item[0])
    if filesystem[0] not in ('fuse.rclone', 'rclone'):
        return None
    source = _decode_mount_token(filesystem[1])
    if not re.match(r'^[\w .-]+:', source) or source.startswith('-'):
        raise ValueError('rclone 원격 경로 자동 연결 실패. 수동 rclone 경로를 설정하세요.')
    suffix = os.path.relpath(target, mount)
    parts = [source.split(':', 1)[1].strip('/'), _decode_mount_token(subroot).strip('/')]
    if suffix != '.':
        parts.append(suffix)
    return source.split(':', 1)[0] + ':' + '/'.join(p for p in parts if p)


def list_source(root, mode='auto', remote=''):
    if root.startswith(('http://', 'https://', 'gdrive:')):
        return drive_listing(root)
    if mode == 'rclone':
        return rclone_listing(remote)
    if mode == 'auto':
        remote = mounted_remote(root)
        if remote:
            return rclone_listing(remote)
    return local_listing(root)
