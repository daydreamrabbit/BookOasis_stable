"""Read existing terminal scan history; never write reports or alter queue/protection state."""
import json
import re

import database

DB_TYPES = ('general', 'adult', 'audiobook', 'video')
TASK_TYPES = ('library_scan', 'folder_watch', 'batch_book_scan', 'cover_scan')
REPORT_NAME = re.compile(r'^task-(general|adult|audiobook|video)-([1-9][0-9]*)-([1-9][0-9]*)\.json$')


def failure_reason(value, hide_paths=False):
    text = str(value or '').split('Traceback (most recent call last):', 1)[0].strip()
    if not text:
        return '저장된 상세 원인이 없습니다.'
    text = re.sub(r'(https?://)[^\s/@]+:[^\s/@]+@', r'\1[인증정보 숨김]@', text)
    text = re.sub(r'(?i)((?:password|passwd|token|secret|api[_-]?key|authorization)\s*[=:]\s*)[^\s,;\]\}]+', r'\1[숨김]', text)
    if hide_paths:
        text = re.sub(r"(['\"])(?:/|[A-Za-z]:[\\/]).*?\1", '[경로]', text)
        text = re.sub(r'(?<![\w:])(?:/[\w.\-가-힣]+){2,}', '[경로]', text)
    return text[:2000]


def _scope(db_type, library_id):
    if db_type not in DB_TYPES or int(library_id) <= 0:
        raise ValueError('유효하지 않은 리포트 카테고리입니다.')
    return db_type, int(library_id)


def _read(db_type, library_id, history_id=None):
    db_type, library_id = _scope(db_type, library_id)
    maria = database.is_mariadb_mode()
    ph = '%s' if maria else '?'
    extract = lambda key: (f"JSON_UNQUOTE(JSON_EXTRACT(kwargs, '$.{key}'))" if maria else f"json_extract(kwargs, '$.{key}')")
    # CASE keeps malformed legacy kwargs from aborting the complete report list.
    db_expr = f"CASE WHEN JSON_VALID(kwargs) THEN {extract('db_type')} END"
    lib_expr = f"CASE WHEN JSON_VALID(kwargs) THEN {extract('library_id')} END"
    query = ("SELECT id, task_type, status, kwargs, started_at, finished_at, error_message FROM scan_history "
             f"WHERE status IN ('failed','cancelled') AND task_type IN ({','.join([ph]*len(TASK_TYPES))}) "
             f"AND COALESCE({db_expr},'general')={ph} AND CAST({lib_expr} AS {'SIGNED' if maria else 'INTEGER'})={ph}")
    args = [*TASK_TYPES, db_type, library_id]
    if history_id is not None:
        query += f' AND id={ph}'
        args.append(int(history_id))
    query += ' ORDER BY finished_at DESC,id DESC LIMIT 50'
    with database.connection('general') as conn:
        cursor = conn.cursor()
        try:
            cursor.execute('START TRANSACTION READ ONLY' if maria else 'BEGIN')
            cursor.execute(query, args)
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.rollback()


def list_task_reports(db_type, library_id):
    return [dict(filename=f'task-{db_type}-{int(library_id)}-{row["id"]}.json',
                 timestamp=str(row.get('finished_at') or row.get('started_at') or ''),
                 errors_count=1, kind='task_interruption') for row in _read(db_type, library_id)]


def task_report(filename):
    match = REPORT_NAME.fullmatch(str(filename))
    if not match:
        raise ValueError('유효하지 않은 작업 리포트입니다.')
    db_type, library_id, history_id = match.groups()
    rows = _read(db_type, library_id, history_id)
    if not rows:
        return None
    row = rows[0]
    label = {'folder_watch':'폴더 감시','library_scan':'카테고리 스캔','batch_book_scan':'선택 도서 스캔','cover_scan':'표지 스캔'}[row['task_type']]
    return dict(library_id=int(library_id), db_type=db_type, kind='task_interruption',
                timestamp=str(row.get('finished_at') or ''), errors_count=1,
                errors=[dict(filename=f'{label} 작업 #{row["id"]}', error_type='작업 중단',
                             message=failure_reason(row.get('error_message')), file_path='',
                             status=row['status'])])
