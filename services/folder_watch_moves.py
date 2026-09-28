"""Conservative, same-database moves; never merge independent book records."""
import os
from collections import Counter, defaultdict

from services import folder_watch_store as store


def namespace(root, config):
    from services.folder_watch_sources import mounted_remote
    if root.startswith(('http://', 'https://', 'gdrive:')):
        return 'drive'
    if config['mode'] == 'rclone':
        roots = [p.strip().rstrip('/') for p in config['paths'].splitlines() if p.strip()]
        return 'rclone:' + config['rclone_remote'].splitlines()[roots.index(root)].split(':', 1)[0].strip()
    remote = mounted_remote(root) if config['mode'] == 'auto' else None
    return 'rclone:' + remote.split(':', 1)[0] if remote else 'local'


def identity(signature, scope):
    if len(signature) < 3 or not signature[2]:
        return None
    if scope == 'local' and not str(signature[2]).startswith('local:'):
        return None
    return (scope, str(signature[2]), signature[0], signature[1])


def book_path(root, relative, signature):
    from tools.scanner.path_utils import canonical_path
    if root.startswith(('http://', 'https://', 'gdrive:')):
        from utils.drive_helper import extract_gdrive_folder_id, encode_gdrive_file_id
        return encode_gdrive_file_id(canonical_path(f'gdrive://{extract_gdrive_folder_id(root)}/{relative}'), signature[2])
    return canonical_path(os.path.join(root, relative))


def reconcile_before_scan(db_type, library_id, target_paths):
    """Use the same identity check for path/manual scans, before DB caches load.

    Never fall back to new inserts when the watched source cannot be verified.
    Unwatched libraries retain their existing scan behavior.
    """
    from services.folder_watch_service import library, probe, verify_mount
    key = f'{db_type}:{library_id}'
    config, _ = store.get(key)
    if not config.get('enabled'):
        return 0
    lib = library(key)
    if not lib or lib['physical_path'] != config.get('paths'):
        raise RuntimeError('감시 경로와 카테고리 경로가 다릅니다. 이동 확인을 중단합니다.')
    moved = 0
    for root in config['paths'].splitlines():
        root = root.strip().rstrip('/')
        if not root or not any(
            str(path).rstrip('/') == root or str(path).startswith(root + '/')
            for path in target_paths
        ):
            continue
        files = probe(root, config)
        verify_mount(root, config, files, db_type, int(library_id))
        moved += reconcile_moves(key, root, config, files)
    return moved


def _retire_unread_duplicate(cursor, duplicate_id):
    """Explicit recovery only: do not discard ANY destination user activity.

    Derived offsets may be recreated. Other book references require a human
    conflict decision; never blindly merge progress or annotation anchors.
    """
    import database
    if database.is_mariadb_mode():
        cursor.execute("SELECT TABLE_NAME AS name FROM information_schema.COLUMNS "
                       "WHERE TABLE_SCHEMA=DATABASE() AND COLUMN_NAME='book_id'")
        tables = [row['name'] for row in cursor.fetchall()]
    else:
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = []
        for row in cursor.fetchall():
            table = row['name']
            cursor.execute(f'PRAGMA table_info(`{table}`)')
            if any(col['name'] == 'book_id' for col in cursor.fetchall()):
                tables.append(table)
    for table in tables:
        if table == 'book_offsets':
            continue
        cursor.execute(f'SELECT 1 FROM `{table}` WHERE book_id=? LIMIT 1', (duplicate_id,))
        if cursor.fetchone():
            raise RuntimeError(f'중복 도서 {duplicate_id}에 {table} 참조가 있어 자동 복구를 중단합니다.')
    cursor.execute('DELETE FROM book_offsets WHERE book_id=?', (duplicate_id,))
    cursor.execute('DELETE FROM books WHERE id=?', (duplicate_id,))


def reconcile_moves(destination_key, root, config, files, recover_duplicates=False, only_book_ids=None):
    import database
    from services.folder_watch_service import library, probe, verify_mount
    db_type, destination_id = destination_key.split(':')
    scope = namespace(root, config)
    counts = Counter(identity(sig, scope) for sig in files.values())
    candidates = defaultdict(list)
    for key, candidate_config, _ in store.all_watches():
        if not key.startswith(db_type + ':') or not candidate_config.get('enabled'):
            continue
        lib = library(key)
        if not lib or lib['physical_path'] != candidate_config.get('paths'):
            continue
        _, state = store.get(key)
        for source_root, source_state in state.get('roots', {}).items():
            if key == destination_key and source_root == root:
                continue
            source_scope = namespace(source_root, candidate_config)
            if source_scope != scope:
                continue
            known = {p: item['signature'] for p, item in source_state.get('move_candidates', {}).items()}
            known.update(source_state.get('baseline', {}))
            known.update(source_state.get('observed', {}))
            for path, sig in known.items():
                ident = identity(sig, scope)
                if ident is not None and counts.get(ident) == 1:
                    candidates[ident].append((key, source_root, path, sig, candidate_config))
    source_listings = {}
    moved = 0
    if candidates and probe(root, config) != files:
        raise RuntimeError('이동 확인 중 대상 목록 변경: 다음 감시에서 다시 확인합니다.')
    for relative, signature in files.items():
        ident = identity(signature, scope)
        matches = candidates.get(ident, [])
        if not matches:
            continue
        # Ignore historical paths from earlier A->B->C moves. Only a record
        # still owning that old path can supply its ID/history.
        eligible = []
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            ph = '%s' if database.is_mariadb_mode() else '?'
            for candidate in matches:
                key, source, path, sig, _ = candidate
                cursor.execute(f'SELECT id FROM books WHERE library_id={ph} AND file_path={ph}',
                               (int(key.split(':')[1]), book_path(source, path, sig)))
                if cursor.fetchone():
                    eligible.append(candidate)
        matches = eligible
        if len(matches) != 1:
            continue  # ambiguous identity: do not steal another book's history
        source_key, source_root, old_relative, old_sig, source_config = matches[0]
        source_id = int(source_key.split(':')[1])
        source_cache_key = (source_key, source_root)
        if source_cache_key not in source_listings:
            source_files = probe(source_root, source_config)  # fail closed on an inaccessible root
            verify_mount(source_root, source_config, source_files, db_type, source_id)
            source_listings[source_cache_key] = source_files
        if old_relative in source_listings[source_cache_key]:
            continue  # copy/hard-link, not a move
        old_path = book_path(source_root, old_relative, old_sig)
        new_path = book_path(root, relative, signature)
        if old_path == new_path:
            continue
        if store.get(destination_key)[0] != config or store.get(source_key)[0] != source_config:
            raise RuntimeError('이동 확인 중 감시 설정이 변경되었습니다.')
        ph = '%s' if database.is_mariadb_mode() else '?'
        lock = ' FOR UPDATE' if database.is_mariadb_mode() else ''
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            cursor.execute(f'SELECT id, metadata_locked FROM books WHERE file_path={ph}' + lock, (new_path,))
            duplicate = cursor.fetchone()
            if duplicate and not recover_duplicates:
                print(f'[FolderWatch-Move] Existing destination requires explicit recovery: book_id={duplicate["id"]}')
                continue
            cursor.execute(f'SELECT id FROM books WHERE library_id={ph} AND file_path={ph}' + lock, (source_id, old_path))
            rows = cursor.fetchall()
            if len(rows) != 1:
                continue
            book_id = rows[0]['id']
            if only_book_ids is not None and book_id not in only_book_ids:
                continue
            if duplicate:
                if int(duplicate['metadata_locked'] or 0) or duplicate['id'] <= book_id:
                    raise RuntimeError('기존 또는 잠긴 대상 도서는 자동 복구하지 않습니다.')
                _retire_unread_duplicate(cursor, duplicate['id'])
            cursor.execute(f'UPDATE books SET library_id={ph}, file_path={ph}, is_deleted=0, deleted_at=NULL WHERE id={ph}',
                           (int(destination_id), new_path, book_id))
            cursor.execute(f'UPDATE gdrive_book_copies SET library_id={ph} WHERE book_id={ph}', (int(destination_id), book_id))
            conn.commit()
        moved += 1
        print(f'[FolderWatch-Move] book_id={book_id} library={source_id}->{destination_id}: {old_path} -> {new_path}')
    return moved
