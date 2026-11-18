"""Permission-scoped series search. Filter after computing the maximum series rating."""
import json
import re
import threading
import time
import database
from services.series_coverage import coverage_sql, missing_sql
from repositories import rated_series_page as rated

FIELDS = ('publisher', 'publication_status', 'genre', 'tags', 'rating')
_OPTIONS_CACHE = {}
_OPTIONS_CACHE_LOCK = threading.Lock()
_OPTIONS_CACHE_TTL = 60.0
_OPTIONS_CACHE_LIMIT = 128


def normalize(raw):
    if not isinstance(raw, dict):
        raise ValueError('검색 조건은 객체여야 합니다.')
    result = {}
    result['read_filter'] = raw.get('read_filter') if raw.get('read_filter') in ('only_read', 'exclude_read') else ''
    for key in ('series', 'author', 'cover_artist'):
        result[key] = str(raw.get(key) or '').strip()[:200]
    for key in ('categories',) + FIELDS:
        values = raw.get(key) or []
        if not isinstance(values, list) or len(values) > 200:
            raise ValueError('선택 조건이 너무 많거나 형식이 잘못되었습니다.')
        result[key] = list(dict.fromkeys(str(v).strip()[:200] for v in values if str(v).strip()))
    if any(not v.isdigit() or int(v) < 1 for v in result['categories']):
        raise ValueError('카테고리 ID가 올바르지 않습니다.')
    if any(v not in ('0', '15', '18', '19', '20', '19-manga', '19-light-novel') for v in result['rating']):
        raise ValueError('연령등급이 올바르지 않습니다.')
    if any(v not in ('0', '1', '2', 'missing', 'unknown', 'short') for v in result['publication_status']):
        raise ValueError('연재상태가 올바르지 않습니다.')
    for key in ('genre_mode', 'tags_mode'):
        result[key] = 'or' if raw.get(key) == 'or' else 'and'
    return result


def tokens(value):
    return [v.strip(' \t\r\n\"\'[]') for v in re.split(r'[,;|\n]+', str(value or '')) if v.strip(' \t\r\n\"\'[]')]


def _rabbit_config(conn):
    cur = conn.cursor()
    cur.execute('SELECT value FROM settings WHERE `key`=?', ('PLUGIN_CONFIG_rabbit_plugins',))
    row = cur.fetchone()
    try:
        config = json.loads(row['value']) if row else {}
    except (ValueError, TypeError):
        config = {}
    if not isinstance(config, dict):
        config = {}
    return config


def excluded_terms(conn, db_type='general'):
    """Shared general settings, with explicit adult overrides like Rabbit."""
    config = _rabbit_config(conn)
    if db_type != 'general':
        shared_conn = database.get_connection('general')
        try:
            config = {**_rabbit_config(shared_conn), **config}
        finally:
            shared_conn.close()
    return {key: {v.casefold() for v in tokens(config.get(setting))}
            for key, setting in [('genre', 'exclude_genres'), ('tags', 'exclude_tags')]}


def status_query(sql):
    # Computed holdings precede display classification; stored publication status is untouched.
    fields = coverage_sql('m', database.is_mariadb_mode())
    gap = missing_sql('c')
    standalone_files = "SUM(CASE WHEN INSTR(LOWER(COALESCE(m.file_path,'')), '(단편)')>0 OR INSTR(LOWER(COALESCE(m.file_path,'')), '（단편）')>0 THEN 1 ELSE 0 END) AS standalone_files"
    completed_filename = "MAX(CASE WHEN INSTR(LOWER(COALESCE(m.file_path,'')), '(완결)')>0 OR INSTR(LOWER(COALESCE(m.file_path,'')), '（완결）')>0 THEN 1 ELSE 0 END) AS completed_filename"
    return sql + f''' , search_coverage AS (
        SELECT g.representative_id, {fields}, {standalone_files}, {completed_filename}
        FROM grouped g JOIN scoped s ON s.library_id=g.library_id
            AND s.group_name=g.group_name AND s.group_dir=g.group_dir
        JOIN books m ON m.id=s.id GROUP BY g.representative_id
    ), search_status AS (
        SELECT g.representative_id,
            CASE WHEN c.files=1 AND c.standalone_files=1 THEN 'short'
                 WHEN {gap} THEN 'missing'
                 WHEN c.ambiguous=0 AND c.expected>0 AND c.volumes>0 AND c.volumes<c.expected THEN 'missing'
                 WHEN c.ambiguous=0 AND c.expected>0 AND c.volumes=0 AND c.files<c.expected THEN 'missing'
                 WHEN c.ambiguous=0 AND c.expected>0 AND c.volumes>=c.expected THEN '2'
                 WHEN c.completed_filename=1 THEN '2'
                 WHEN COALESCE(b.publication_status,'') IN ('0','1') THEN b.publication_status
                 WHEN COALESCE(b.publication_status,'')='2' THEN '2'
                 WHEN c.last_volume>0 OR c.chapters>0 THEN '0'
                 ELSE 'unknown' END AS status
        FROM grouped g JOIN search_coverage c ON c.representative_id=g.representative_id
        LEFT JOIN books b ON b.id=g.publication_status_id
    ) '''


def filtered_query(conn, library_id, user_id, rating, filters):
    sql, params = rated._query(conn, library_id, user_id, rating, library_ids=filters['categories'], read_filter=filters.get('read_filter', ''))
    terms = []
    if filters['categories']:
        terms.append('g.library_id IN (' + ','.join('?' for _ in filters['categories']) + ')')
        params.extend(map(int, filters['categories']))
    if filters['rating']:
        rating_terms = []
        numeric = [value for value in filters['rating'] if value not in ('19-manga', '19-light-novel')]
        if numeric:
            rating_terms.append('g.series_level IN (' + ','.join('?' for _ in numeric) + ')')
            params.extend(map(int, numeric))
        if '19-light-novel' in filters['rating']:
            rating_terms.append('(g.series_level=19 AND g.series_is_adult_light_novel=1)')
        if '19-manga' in filters['rating']:
            rating_terms.append('(g.series_level=19 AND COALESCE(g.series_is_adult_light_novel,0)=0)')
        terms.append('(' + ' OR '.join(rating_terms) + ')')
    scope = 's.library_id=g.library_id AND s.group_name=g.group_name AND s.group_dir=g.group_dir'
    def exists(condition):
        return f'EXISTS (SELECT 1 FROM scoped s JOIN books m ON m.id=s.id WHERE {scope} AND ({condition}))'
    for key, column in [('series', "COALESCE(NULLIF(m.series_name,''),m.title,'' )"), ('author', 'm.author'), ('cover_artist', 'm.cover_artist')]:
        if filters[key]:
            terms.append(exists(f"INSTR(LOWER(COALESCE({column},'')),LOWER(?))>0"))
            params.append(filters[key])
    if filters['publication_status']:
        sql = status_query(sql)
        terms.append('g.representative_id IN (SELECT representative_id FROM search_status WHERE status IN ('
                     + ','.join('?' for _ in filters['publication_status']) + '))')
        params.extend(filters['publication_status'])
    for key in ('publisher',):
        if filters[key]:
            terms.append(exists(f"COALESCE(m.{key},'') IN ({','.join('?' for _ in filters[key])})"))
            params.extend(filters[key])
    for key in ('genre', 'tags'):
        matches = []
        for value in filters[key]:
            # Match complete metadata tokens, not a substring such as 'SF' in 'SFX'.
            if database.is_mariadb_mode():
                condition = f"COALESCE(m.{key},'') REGEXP ?"
                params.append(r"""(^|[,;|\n\["'])[[:space:]]*""" + re.escape(value) + r"""[[:space:]]*([,;|\n\]"']|$)""")
            else:
                conn.create_function('bo_has_token', 2, lambda text, token: int(str(token).casefold() in [v.casefold() for v in tokens(text)]))
                condition = f'bo_has_token(m.{key},?)=1'
                params.append(value)
            matches.append(exists(condition))
        if matches:
            joiner = ' OR ' if filters[key + '_mode'] == 'or' else ' AND '
            terms.append('(' + joiner.join(matches) + ')')
    return sql + ', filtered AS (SELECT g.* FROM grouped g WHERE ' + (' AND '.join(terms) or '1=1') + ') ', params


def search(db_type, user_id, rating, filters, *, library_id='all', page=1, limit=30, sort='asc', totals=False, index=False):
    if db_type not in ('general', 'adult') or not user_id:
        raise ValueError('로그인한 일반/성인도서 검색만 지원합니다.')
    filters = normalize(filters)
    if filters['genre'] or filters['tags']:
        conn = database.get_connection(db_type)
        try:
            excluded = excluded_terms(conn, db_type)
        finally:
            conn.close()
        if any(v.casefold() in excluded[key] for key in ('genre', 'tags') for v in filters[key]):
            raise ValueError('표시 제외된 장르·태그입니다. 검색 조건을 초기화해 주세요.')
    return rated.fetch(db_type, library_id, user_id, min(20, int(rating)), limit=limit+1,
                       offset=(page-1)*limit, sort=sort, totals=totals, index=index, filters=filters)


def entries(db_type, rows, include_metadata=False):
    from services.series_service import _build_series_entries, _strip_series_entry_internal_fields
    if include_metadata and rows:
        from repositories.series_metadata_utils import book_metadata_select_expr
        conn = database.get_connection(db_type)
        try:
            cur = conn.cursor()
            cur.execute('SELECT b.id,' + book_metadata_select_expr('b', True) + ' AS has_metadata FROM books b WHERE b.id IN (' + ','.join('?' for _ in rows) + ')', tuple(r['id'] for r in rows))
            flags = {r['id']:r['has_metadata'] for r in cur.fetchall()}
            for row in rows:
                row['has_metadata'] = flags.get(row['id'])
        finally:
            conn.close()
    result = _build_series_entries(db_type, rows)
    progress = {r['id']: r for r in rows}
    for item in result:
        row = progress[item['representative_book_id']]
        item['is_completed'] = int(row['all_completed'] or 0)
        item['has_progress'] = int(row['has_progress'] or 0)
        item['has_unfinished_siblings'] = int(not item['is_completed'])
    _strip_series_entry_internal_fields(result)
    return result


def options(db_type, user_id, rating, categories):
    """Return short-lived, permission-scoped facets to avoid rescanning all books on every open."""
    filters = normalize({'categories': categories})
    try:
        conn = database.get_connection(db_type)
        try:
            cur = conn.cursor()
            cur.execute(
                'SELECT library_id FROM user_category_permissions WHERE user_id=? AND has_access=1 ORDER BY library_id',
                (user_id,)
            )
            permitted = tuple(str(row['library_id']) for row in cur.fetchall())
        finally:
            conn.close()
    except Exception:
        # Do not use cached facets when the permission scope cannot be verified.
        return _compute_options(db_type, user_id, rating, filters['categories'])

    key = (str(db_type), str(user_id), min(20, int(rating)), tuple(filters['categories']), permitted)
    now = time.monotonic()
    with _OPTIONS_CACHE_LOCK:
        cached = _OPTIONS_CACHE.get(key)
        if cached and cached[0] > now:
            return {field: list(values) for field, values in cached[1].items()}
        _OPTIONS_CACHE.pop(key, None)

    result = _compute_options(db_type, user_id, rating, filters['categories'])
    with _OPTIONS_CACHE_LOCK:
        _OPTIONS_CACHE[key] = (time.monotonic() + _OPTIONS_CACHE_TTL,
                               {field: tuple(values) for field, values in result.items()})
        if len(_OPTIONS_CACHE) > _OPTIONS_CACHE_LIMIT:
            expired = [cache_key for cache_key, (expiry, _) in _OPTIONS_CACHE.items()
                       if expiry <= time.monotonic()]
            for cache_key in expired:
                _OPTIONS_CACHE.pop(cache_key, None)
            while len(_OPTIONS_CACHE) > _OPTIONS_CACHE_LIMIT:
                _OPTIONS_CACHE.pop(next(iter(_OPTIONS_CACHE)))
    return {field: list(values) for field, values in result.items()}


def _compute_options(db_type, user_id, rating, categories):
    filters = normalize({'categories': categories})
    conn = database.get_connection(db_type)
    try:
        # Facet lookup does not need progress, favorites, sorting, covers or
        # pagination from rated._query. Keep its permission, deletion, series,
        # directory and maximum-rating rules while scanning only needed fields.
        level, directory, params = rated._rating_expressions(conn)
        adult_light_novel = rated._adult_light_novel_expression(conn)
        where = ['(b.is_deleted=0 OR b.is_deleted IS NULL)']
        if rated._has_pending_delete_column(conn, db_type):
            where.append('NOT EXISTS(SELECT 1 FROM libraries lifecycle WHERE lifecycle.id=b.library_id AND COALESCE(lifecycle.pending_delete,0)<>0)')
        if filters['categories']:
            where.append('b.library_id IN (' + ','.join('?' for _ in filters['categories']) + ')')
            params.extend(map(int, filters['categories']))
        where.append('EXISTS (SELECT 1 FROM user_category_permissions p WHERE p.library_id=b.library_id AND p.user_id=? AND p.has_access=1)')
        params.extend((user_id, min(20, int(rating))))
        sql = f'''WITH raw_books AS (
            SELECT b.id,b.library_id,COALESCE(NULLIF(b.series_name,''),'기타 단행본') AS group_name,
                   {directory} AS group_dir,b.publisher,b.genre,b.tags,b.publication_status,
                   b.document_volume_index,b.document_number,b.document_volume_count,
                   b.file_path,b.metadata_title,b.title,b.series_name,{level} AS effective_level,
                   {adult_light_novel} AS adult_light_novel
            FROM books b WHERE {' AND '.join(where)}
        ), scoped AS (
            SELECT raw_books.*,MAX(effective_level) OVER(PARTITION BY library_id,group_name,group_dir) AS series_level,
                   MAX(adult_light_novel) OVER(PARTITION BY library_id,group_name,group_dir) AS series_is_adult_light_novel
            FROM raw_books
        ), grouped AS (
            SELECT library_id,group_name,group_dir,MIN(id) AS representative_id,COUNT(*) AS series_book_count,
                   MAX(series_level) AS series_level,MAX(series_is_adult_light_novel) AS series_is_adult_light_novel,
                   MIN(CASE WHEN publication_status IS NOT NULL AND publication_status<>'' THEN id END) AS publication_status_id
            FROM scoped GROUP BY library_id,group_name,group_dir HAVING MAX(series_level)<=?
        ), filtered AS (SELECT g.* FROM grouped g) '''
        sql = status_query(sql)
        excluded = excluded_terms(conn, db_type)
        join = ' FROM filtered g JOIN scoped s ON s.library_id=g.library_id AND s.group_name=g.group_name AND s.group_dir=g.group_dir JOIN books m ON m.id=s.id'
        result = {field:set() for field in FIELDS}
        cur = conn.cursor()
        cur.execute(sql + 'SELECT DISTINCT m.publisher,ss.status AS publication_status,m.genre,m.tags,g.series_level AS rating,g.series_is_adult_light_novel AS series_is_adult_light_novel' + join + ' JOIN search_status ss ON ss.representative_id=g.representative_id', tuple(params))
        while True:
            rows = cur.fetchmany(500)
            if not rows:
                break
            for row in rows:
                for field in FIELDS:
                    value = row[field]
                    if value is not None and str(value).strip():
                        if field == 'rating' and int(value) == 19:
                            value = '19-light-novel' if row['series_is_adult_light_novel'] else '19-manga'
                        result[field].update([v for v in tokens(value) if v.casefold() not in excluded[field]] if field in ('genre','tags') else [str(value)])
        return {field:sorted(values,key=str.casefold) for field,values in result.items()}
    finally:
        conn.close()
