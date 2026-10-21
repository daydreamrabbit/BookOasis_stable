"""Sort by the active plugin's own stars, never overwrite metadata scores.

Only a small rating map is cached by the provider. SQL grouping/paging and
permission checks remain in the existing list repository.
"""
import hashlib
import json
import database
from utils.isbn import normalize_isbn, mariadb_valid_isbn_expression

SORTS = ('rating_desc', 'rating_asc')


def ratings(db_type):
    from api.routes.plugin_routes import _find_active_rating_provider
    provider = _find_active_rating_provider(db_type)
    if provider is None:
        return {'identity': 'book_key', 'ratings': {}}
    export = getattr(provider, 'get_sort_ratings', None)
    if not callable(export):
        raise ValueError('현재 별점 플러그인은 목록 정렬을 지원하지 않습니다.')
    result = export(db_type)
    if not result.get('success'):
        raise ValueError(result.get('error') or '플러그인 별점을 불러오지 못했습니다.')
    if result.get('identity') not in ('book_key', 'adult_series'):
        raise ValueError('별점 식별 형식이 올바르지 않습니다.')
    return result


def identity_expression(conn, kind, alias='rb'):
    if database.is_mariadb_mode():
        if kind == 'adult_series':
            raw = f"CONCAT('[',{alias}.library_id,', ',JSON_QUOTE(COALESCE({alias}.series_name,'')),']')"
        else:
            isbn = mariadb_valid_isbn_expression(f'{alias}.isbn')
            raw = f"CASE WHEN ({isbn})<>'' THEN CONCAT('isbn:',({isbn})) WHEN TRIM(COALESCE({alias}.author,''))<>'' THEN CONCAT('ta:',TRIM(COALESCE({alias}.series_name,'')),'|',TRIM({alias}.author)) ELSE CONCAT('t:',TRIM(COALESCE({alias}.series_name,''))) END"
        return f'SHA2({raw},256)'
    def key(library, title, author, isbn):
        if kind == 'adult_series':
            raw = json.dumps([int(library), str(title or '')], ensure_ascii=False)
        else:
            title, author, isbn = [str(v or '').strip() for v in (title, author, isbn)]
            isbn = normalize_isbn(isbn)
            raw = 'isbn:' + isbn if isbn else ('ta:' + title + '|' + author if author else 't:' + title)
        return hashlib.sha256(raw.encode()).hexdigest()
    conn.create_function('bo_plugin_rating_key', 4, key)
    return f'bo_plugin_rating_key({alias}.library_id,{alias}.series_name,{alias}.author,{alias}.isbn)'


def prepare(conn, db_type):
    result = ratings(db_type)
    cursor = conn.cursor()
    # Temporary tables are connection-local and explicitly dropped for pools.
    cursor.execute('DROP TABLE IF EXISTS temp.bo_plugin_sort' if not database.is_mariadb_mode()
                   else 'DROP TEMPORARY TABLE IF EXISTS bo_plugin_sort')
    cursor.execute('CREATE TEMPORARY TABLE bo_plugin_sort (key_hash CHAR(64) PRIMARY KEY, rating REAL NOT NULL)')
    for key, value in result['ratings'].items():
        value = float(value)
        if len(key) != 64 or not 0.5 <= value <= 5 or value * 2 != int(value * 2):
            raise ValueError('별점 데이터가 올바르지 않습니다.')
        cursor.execute('INSERT INTO bo_plugin_sort VALUES(?,?)', (key, value))
    return identity_expression(conn, result['identity'])


def cleanup(conn):
    conn.cursor().execute('DROP TEMPORARY TABLE IF EXISTS bo_plugin_sort' if database.is_mariadb_mode()
                          else 'DROP TABLE IF EXISTS temp.bo_plugin_sort')


def sort_entries(entries, sort, db_type):
    if db_type not in ('general', 'adult'):
        entries.sort(key=lambda e: int(e['representative_book_id']))
        return
    conn = database.get_connection(db_type)
    try:
        expression = prepare(conn, db_type)
        from repositories.rated_series_page import _rating_expressions
        _, directory, _ = _rating_expressions(conn)
        sibling_directory = directory.replace('b.', 'rb.')
        values = {}
        ids = [int(e['representative_book_id']) for e in entries]
        cursor = conn.cursor()
        for offset in range(0, len(ids), 500):
            batch = ids[offset:offset+500]
            cursor.execute(f'''SELECT b.id,MAX(r.rating) AS rating FROM books b
                JOIN books rb ON rb.library_id=b.library_id AND COALESCE(rb.series_name,'')=COALESCE(b.series_name,'')
                    AND ({sibling_directory})=({directory}) AND COALESCE(rb.is_deleted,0)=0
                LEFT JOIN bo_plugin_sort r ON r.key_hash={expression}
                WHERE b.id IN ({",".join("?" for _ in batch)}) GROUP BY b.id''', tuple(batch))
            values.update((r['id'], r['rating']) for r in cursor.fetchall())
        for entry in entries:
            entry['plugin_rating'] = values.get(entry['representative_book_id'])
        direction = -1 if sort == 'rating_desc' else 1
        entries.sort(key=lambda e: (direction * (e['plugin_rating'] or 0), int(e['representative_book_id'])))
    finally:
        try:
            cleanup(conn)
        finally:
            conn.close()
