"""Names and conservative garbage collection for generated library images.

Never scans original media. Unknown files, symlinks, plugin_logo and recent
uncommitted outputs are excluded from background collection.
"""
import hashlib
import json
import os
import re
import time
import unicodedata
from urllib.parse import unquote, urlsplit

import database
from services.cover_storage_service import get_covers_dir


def generated_image_name(file_path, kind='cover', series_name=None, content=None, book_title=None):
    path = str(file_path or '').replace('\\', '/')
    is_cache_key = '://' in path or path.startswith('rabbit_plugins:')
    stem = str(book_title) if book_title else ('' if is_cache_key else os.path.splitext(os.path.basename(path))[0])
    series = str(series_name or ('' if is_cache_key else os.path.basename(os.path.dirname(path))) or stem or '도서')
    volume = re.search(r'(\d+(?:\.\d+)?)\s*(권|화|회|부)', stem)
    if not volume:
        volume = re.search(r'(\d+)(?:\s*\([^)]*\))?$', stem)
    unit = volume.group(2) if volume and volume.lastindex == 2 else '권'
    label = '배너' if kind == 'banner' else ((volume.group(1) + unit) if volume else '표지')
    series = unicodedata.normalize('NFC', series)
    series = re.sub(r'[<>:"/\\|?#*\x00-\x1f\x7f]', '_', series).strip(' ._') or '도서'
    series = series[:10].rstrip(' ._') or '도서'
    # Keep UTF-8 component length below common filesystem limits (255 bytes).
    while len(f'{series}_{label}'.encode('utf-8')) > 170:
        series = series[:-1]
    text = f'{series}_{label}'
    digest = hashlib.sha256((kind + ':' + path).encode('utf-8')).hexdigest()[:16]
    version = '_' + hashlib.sha256(content).hexdigest()[:16] if content is not None else ''
    return f'{text}__bo_{kind}_{digest}{version}.webp'


def normalized_reference(value):
    text = str(value or '').replace('\\', '/')
    if text.startswith(('https://', 'http://')):
        return None
    text = unquote(urlsplit(text).path).lstrip('/')
    if text.startswith('covers/'):
        text = text[7:]
    if '/covers/' in text:
        text = text.split('/covers/', 1)[1]
    if '..' in text.split('/') or not text.lower().endswith(('.webp', '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.avif')):
        return None
    return text


def reference_snapshot():
    """Fail closed if ANY database cannot be inspected; include plugin preferences."""
    refs, libraries = set(), set()
    def collect(value):
        if isinstance(value, dict):
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, str):
            ref = normalized_reference(value)
            if ref:
                refs.add(ref)
            elif value.startswith(('{', '[')):
                try:
                    collect(json.loads(value))
                except (ValueError, TypeError):
                    pass
    for db_type in ('general', 'adult', 'audiobook', 'video'):
        conn = database.get_connection(db_type)
        try:
            cur = conn.cursor()
            if database.is_mariadb_mode():
                cur.execute('SELECT TABLE_NAME AS table_name, COLUMN_NAME AS column_name '
                            'FROM information_schema.COLUMNS WHERE TABLE_SCHEMA=DATABASE()')
                columns = [(r['table_name'], r['column_name']) for r in cur.fetchall()]
            else:
                cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                tables = [r['name'] for r in cur.fetchall()]
                columns = []
                for table in tables:
                    if re.fullmatch(r'\w+', table):
                        cur.execute(f'PRAGMA table_info(`{table}`)')
                        columns.extend((table, r['name']) for r in cur.fetchall())
            for table, column in columns:
                if not re.fullmatch(r'\w+', table) or not re.fullmatch(r'\w+', column):
                    continue
                is_image = column in ('cover_image', 'banner_image', 'cover_path', 'cover_url', 'thumbnail',
                                      'thumbnail_path', 'thumbnail_url', 'poster', 'poster_path', 'poster_url', 'image_path')
                if is_image or (column == 'value' and 'setting' in table):
                    has_key = column == 'value' and (table, 'key') in columns
                    key_field = ', `key` AS setting_key' if has_key else ''
                    cur.execute(f'SELECT DISTINCT `{column}` AS value{key_field} FROM `{table}` WHERE `{column}` IS NOT NULL')
                    values = cur.fetchall()
                    for row in values:
                        if has_key and row['setting_key'] == 'rabbit_plugins:external-cover-preferences:v1':
                            preferences = json.loads(row['value'])
                            cur.execute('SELECT id FROM books')
                            live_ids = {str(book['id']) for book in cur.fetchall()}
                            collect({key: value for key, value in preferences.items() if key in live_ids})
                        else:
                            collect(row['value'])
            cur.execute('SELECT id FROM libraries')
            libraries.update(str(r['id']) for r in cur.fetchall())
        finally:
            conn.close()
    return refs, libraries


def generated_file(name):
    return bool(re.fullmatch(r'(?:book|series|banner)_[0-9a-f]{32}(?:_[0-9a-f]{16})?\.webp', name)
                or re.fullmatch(r'.+__bo_(?:cover|external|embedded|banner)_[0-9a-f]{16}(?:_[0-9a-f]{16})?\.webp', name))


def cleanup_library_images(library_id, deleted_category=False, min_age=86400, snapshot=None):
    identifier = str(library_id)
    if not identifier.isdecimal():
        raise ValueError('Numeric library ID required')
    root = os.path.realpath(get_covers_dir())
    folder = os.path.join(root, identifier)
    if os.path.islink(folder) or not os.path.isdir(folder):
        return []
    refs, libraries = snapshot if snapshot is not None else reference_snapshot()
    # IDs are shared across DB types. Another category may own the same directory.
    all_files = deleted_category and identifier not in libraries
    removed = []
    for entry in os.scandir(folder):
        if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
            continue
        relative = f'{identifier}/{entry.name}'
        if relative in refs or (not all_files and not generated_file(entry.name)):
            continue
        if time.time() - entry.stat(follow_symlinks=False).st_mtime < min_age:
            continue
        os.remove(entry.path)
        removed.append(relative)
    try:
        os.rmdir(folder)  # Only empty directories, never recursive deletion.
    except OSError:
        pass
    return removed


def cleanup_generated_images():
    removed = []
    print('[GeneratedMedia] Cleanup started (unreferenced generated images older than 24h)', flush=True)
    try:
        snapshot = reference_snapshot()
        for entry in os.scandir(get_covers_dir()):
            if entry.name.isdecimal() and entry.is_dir(follow_symlinks=False):
                removed.extend(cleanup_library_images(entry.name, snapshot=snapshot))
        print(f'[GeneratedMedia] Cleanup completed: removed {len(removed)} files', flush=True)
        return removed
    except Exception as exc:
        print(f'[GeneratedMedia] Cleanup stopped after {len(removed)} removals: {exc}', flush=True)
