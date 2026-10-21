"""Explicit, previewed EPUB metadata synchronization; never part of auto scans."""
import os
from concurrent.futures import ThreadPoolExecutor

import database
from services.batch_book_scan_targets import resolve_batch_book_scan_targets

FIELDS = ('genre', 'tags', 'author', 'translator', 'publisher', 'summary', 'isbn')


def validate_request(payload):
    if not isinstance(payload, dict):
        raise ValueError('요청 형식이 올바르지 않습니다.')
    kind = payload.get('type', 'general')
    ids, fields = payload.get('book_ids'), payload.get('fields', ['genre'])
    if kind not in ('general', 'adult'):
        raise ValueError('일반·성인 도서만 지원합니다.')
    if not isinstance(ids, list) or not 1 <= len(ids) <= 50 or any(type(i) is not int or i <= 0 for i in ids):
        raise ValueError('도서 ID는 1~50개여야 합니다.')
    if not isinstance(fields, list) or not fields or any(f not in FIELDS for f in fields):
        raise ValueError('갱신할 항목을 선택해 주세요.')
    if payload.get('mode', 'replace') not in ('replace', 'merge'):
        raise ValueError('지원하지 않는 갱신 방식입니다.')
    if payload.get('mode') == 'merge' and any(f not in ('genre', 'tags') for f in fields):
        raise ValueError('누락 추가는 장르·태그만 지원합니다.')
    return kind, list(dict.fromkeys(ids)), list(dict.fromkeys(fields))


def read_source(book):
    from tools.scanner.metadata import parse_embedded_metadata
    from utils.drive_helper import is_remote_path, is_gdrive_url, resolve_gdrive_local_path
    path = book['file_path']
    if is_gdrive_url(path):
        path = resolve_gdrive_local_path(path)
    if not os.path.isfile(path):
        raise ValueError('등록된 원본 EPUB 파일을 읽을 수 없습니다. 원격 마운트와 경로를 확인해 주세요.')
    status = {}
    source = parse_embedded_metadata(path, 'epub', is_remote=is_remote_path(path), status_out=status)
    if not status.get('parsed'):
        raise ValueError('EPUB 메타데이터 읽기 실패 또는 시간 초과')
    return source


def proposed_value(before, source, mode):
    if mode != 'merge':
        return source
    from tools.scanner.metadata import normalize_metadata_list_field
    return normalize_metadata_list_field(', '.join(filter(None, (before, source))))


def preview(payload):
    kind, ids, fields = validate_request(payload)
    with database.connection(kind) as conn:
        cursor = conn.cursor()
        targets = resolve_batch_book_scan_targets(cursor, ids, payload.get('scope', 'book'))
        if len(targets) > 50:
            raise ValueError('한 번에 50권까지 갱신할 수 있습니다. 권 단위로 나눠 선택해 주세요.')
        selected = ','.join('?' for _ in targets)
        cursor.execute(f"SELECT id,title,file_path,file_format,metadata_locked,{','.join(FIELDS)} FROM books WHERE id IN ({selected}) AND COALESCE(is_deleted,0)=0", tuple(row['id'] for row in targets))
        books = [dict(row) for row in cursor.fetchall()]

    def inspect(book):
        result = {'id': book['id'], 'title': book['title'], 'changes': {}}
        if book['metadata_locked']:
            return {**result, 'error': '메타데이터 잠금: 변경하지 않습니다.'}
        if str(book['file_format']).lower() != 'epub':
            return {**result, 'error': 'EPUB만 지원합니다.'}
        try:
            source = read_source(book)
            for field in fields:
                value = str(source.get(field) or '').strip()
                if not value:  # Missing source fields must never erase stored data.
                    continue
                before = str(book[field] or '')
                after = proposed_value(before, value, payload.get('mode', 'replace'))
                if before != after:
                    result['changes'][field] = {'before': before, 'after': after, 'source': value}
        except Exception as error:
            result['error'] = str(error)
        return result

    with ThreadPoolExecutor(max_workers=4) as pool:
        entries = list(pool.map(inspect, books))
    return {'success': True, 'entries': entries}


def apply(payload):
    kind, ids, fields = validate_request(payload)
    approved = payload.get('approved')
    if not isinstance(approved, list) or not approved or len(approved) > 50:
        raise ValueError('미리보기 결과를 먼저 확인해 주세요.')
    approval = {}
    for entry in approved:
        if not isinstance(entry, dict) or type(entry.get('id')) is not int or not isinstance(entry.get('changes'), dict):
            raise ValueError('미리보기 확인 값이 올바르지 않습니다.')
        if entry['id'] in approval:
            raise ValueError('중복 도서입니다.')
        approval[entry['id']] = entry['changes']
    # Re-read the actual EPUB; never trust client-supplied replacement values.
    fresh = preview(payload)['entries']
    allowed = {entry['id'] for entry in fresh}
    if not set(approval).issubset(allowed):
        raise ValueError('선택 범위를 벗어난 도서입니다.')
    results = []
    for entry in fresh:
        book_id = entry['id']
        if book_id not in approval:
            continue
        changes = entry['changes']
        if entry.get('error') or changes != approval[book_id]:
            results.append({'id': book_id, 'status': 'skipped', 'error': entry.get('error') or 'DB 또는 원본이 변경됐습니다. 다시 미리보기 해 주세요.'})
            continue
        if not changes:
            results.append({'id': book_id, 'status': 'unchanged'})
            continue
        columns = [field for field in fields if field in changes]
        assignments = ','.join(f'{field}=?' for field in columns)
        guards = ' AND '.join(f"COALESCE({field},'')=?" for field in columns)
        with database.connection(kind) as conn:
            cursor = conn.cursor()
            cursor.execute(f"UPDATE books SET {assignments} WHERE id=? AND COALESCE(metadata_locked,0)=0 AND COALESCE(is_deleted,0)=0 AND {guards}", tuple(changes[f]['after'] for f in columns)+(book_id,)+tuple(changes[f]['before'] for f in columns))
            updated = cursor.rowcount > 0
            conn.commit()
        results.append({'id': book_id, 'status': 'updated' if updated else 'skipped', 'fields': columns})
    if any(entry['status'] == 'updated' for entry in results):
        from services.series_service import SeriesService
        SeriesService.invalidate_all_books_cache(kind)
        try:
            from utils.redis_helper import redis_delete_pattern
            for prefix in ('cache:recent_added', 'cache:history', 'cache:series_summary'):
                redis_delete_pattern(f'{prefix}*:{kind}:*')
        except Exception:
            import logging
            logging.getLogger(__name__).warning('Metadata updated; Redis invalidation unavailable', exc_info=True)
    return {'success': True, 'results': results, 'updated': sum(row['status'] == 'updated' for row in results)}
