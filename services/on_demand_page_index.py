"""Persist a ZIP page map when, and only when, that book is opened."""
import hashlib
import os
import threading
import zipfile
import database
from utils.lru_cache import LRUCache

_ready = LRUCache(capacity=512)
_locks = [threading.Lock() for _ in range(64)]


def _signature(path):
    info = os.stat(path)
    return hashlib.sha256(f'{path}|{info.st_size}|{info.st_mtime_ns}'.encode()).hexdigest()


def _virtual_signature(path, book):
    return hashlib.sha256(f"{path}|{book.get('file_size',0)}|{book.get('file_mtime',0)}".encode()).hexdigest()


def ensure_page_index(db_type, book_id, file_path):
    virtual = str(file_path).startswith(('gdrive:', 'gdrive://'))
    if db_type not in ('general', 'adult') or not book_id or not str(file_path).split('?',1)[0].lower().endswith(('.zip', '.cbz')):
        return None
    try:
        book_id = int(book_id)
        key = f'VIEWER_ZIP_INDEX_V1:{db_type}:{book_id}'
        fingerprint = None if virtual else _signature(file_path)
        with _locks[hash(key) % len(_locks)]:
            cached = _ready.get(key)
            if not virtual and cached and cached[0] == fingerprint:
                return cached[1]
            from repositories.settings_repository import SettingsRepository
            with database.connection(db_type) as conn:
                cursor = conn.cursor()
                cursor.execute('SELECT file_path,total_pages,has_offsets,file_size,file_mtime FROM books WHERE id=? AND COALESCE(is_deleted,0)=0', (book_id,))
                book = cursor.fetchone()
            if not book:
                return None
            book = dict(book)
            if virtual:
                fingerprint = _virtual_signature(file_path, book)
                if cached and cached[0] == fingerprint:
                    return cached[1]
            original_path = book['file_path']
            if original_path != file_path and not original_path.startswith(('gdrive:', 'gdrive://')):
                return None
            if (book['has_offsets'] == 1 and book['total_pages'] > 0
                    and SettingsRepository.get_value(key) == fingerprint):
                _ready.put(key, (fingerprint, int(book['total_pages'])))
                return int(book['total_pages'])
            from tools.scanner.offset import collect_zip_offsets_from_open_zip
            # Private handle, central directory only. No image decompression or
            # full-archive background copy is needed to construct the map.
            if virtual:
                from utils.drive_helper import split_gdrive_file_id, fetch_gdrive_zip_offsets
                _, file_id = split_gdrive_file_id(file_path)
                if not file_id:
                    return None
                rows, _ = fetch_gdrive_zip_offsets(file_id)
            else:
                with zipfile.ZipFile(file_path, 'r') as archive:
                    rows = collect_zip_offsets_from_open_zip(archive)
            if not rows or (not virtual and _signature(file_path) != fingerprint):
                return None
            with database.connection(db_type) as conn:
                cursor = conn.cursor()
                lock = ' FOR UPDATE' if database.is_mariadb_mode() else ''
                cursor.execute('SELECT id,file_size,file_mtime FROM books WHERE id=? AND file_path=? AND COALESCE(is_deleted,0)=0' + lock, (book_id, original_path))
                current = cursor.fetchone()
                if not current or (virtual and _virtual_signature(file_path, dict(current)) != fingerprint):
                    return None
                cursor.execute('DELETE FROM book_offsets WHERE book_id=?', (book_id,))
                cursor.executemany('''INSERT INTO book_offsets
                    (book_id,page_idx,filename,local_header_offset,compress_size,file_size,compress_type,data_offset)
                    VALUES(?,?,?,?,?,?,?,?)''', [(book_id, *row) for row in rows])
                cursor.execute('UPDATE books SET total_pages=?,has_offsets=1 WHERE id=? AND file_path=?', (len(rows), book_id, original_path))
                conn.commit()
            from repositories.book_offset_repository import BookOffsetRepository
            BookOffsetRepository.invalidate_book_offsets(db_type, book_id)
            from api.cache import image_cache, zip_cache, namelist_cache
            with image_cache.lock:
                for entry in list(image_cache.cache):
                    if isinstance(entry, tuple) and entry[0] == file_path:
                        _, size = image_cache.cache.pop(entry)
                        image_cache.current_bytes -= size
            for cache in (zip_cache, namelist_cache):
                with cache.lock:
                    cache.cache.pop(file_path, None)
            from utils.redis_helper import redis_delete_pattern
            redis_delete_pattern(f'cache:stream:book:{db_type}:{book_id}:page:*')
            SettingsRepository.set_value(key, fingerprint)
            _ready.put(key, (fingerprint, len(rows)))
            print(f'[Viewer-Index] Indexed on open: book={book_id}, pages={len(rows)}')
            return len(rows)
    except Exception as error:
        # Index failure must not prevent the normal ZIP reader from working.
        print(f'[Viewer-Index] Falling back to ZIP reader for book={book_id}: {error}')
        return None
