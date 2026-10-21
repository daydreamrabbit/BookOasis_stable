"""Permission-scoped series search. Filter after computing the maximum series rating."""
import json
import re
import database
from repositories import rated_series_page as rated

FIELDS = ('publisher', 'publication_status', 'genre', 'tags', 'rating')


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
    if any(v not in ('0', '15', '18', '19', '20') for v in result['rating']):
        raise ValueError('연령등급이 올바르지 않습니다.')
    if any(v not in ('0', '1', '2', 'missing', 'unknown') for v in result['publication_status']):
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
    # Aggregate in SQL, before pagination. No archive opens or per-series API calls.
    # Match the first non-empty stored status used by the series renderer, not
    # any historical status on an arbitrary volume.
    return sql + ''' , search_coverage AS (
        SELECT g.representative_id,
               MAX(COALESCE(m.document_volume_count,0)) AS expected,
               MAX(COALESCE(m.document_volume_index,0)) AS last_volume,
               COUNT(*) AS files,
               COUNT(DISTINCT CASE WHEN m.document_volume_index>0 AND
                    (m.document_volume_count IS NULL OR m.document_volume_index<=m.document_volume_count)
                    THEN m.document_volume_index END) AS volumes,
               COUNT(DISTINCT CASE WHEN m.document_number>0 THEN m.document_number END) AS chapters,
               MAX(COALESCE(m.document_number,0)) AS last_chapter
        FROM grouped g JOIN scoped s ON s.library_id=g.library_id
            AND s.group_name=g.group_name AND s.group_dir=g.group_dir
        JOIN books m ON m.id=s.id GROUP BY g.representative_id
    ), search_status AS (
        SELECT g.representative_id,
            CASE WHEN COALESCE(b.publication_status,'') IN ('0','1') THEN b.publication_status
                 WHEN c.expected>0 AND
                     (CASE WHEN c.volumes>0 THEN c.volumes WHEN c.chapters>0 THEN c.chapters ELSE c.files END)<c.expected
                     THEN 'missing'
                 WHEN COALESCE(b.publication_status,'')='2' THEN '2'
                 WHEN c.chapters>0 AND c.chapters<c.last_chapter THEN 'missing'
                 WHEN c.expected>0 THEN '2'
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
        terms.append('g.series_level IN (' + ','.join('?' for _ in filters['rating']) + ')')
        params.extend(map(int, filters['rating']))
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
    filters = normalize({'categories': categories})
    conn = database.get_connection(db_type)
    try:
        sql, params = filtered_query(conn, 'all', user_id, min(20, int(rating)), filters)
        sql = status_query(sql)
        excluded = excluded_terms(conn, db_type)
        join = ' FROM filtered g JOIN scoped s ON s.library_id=g.library_id AND s.group_name=g.group_name AND s.group_dir=g.group_dir JOIN books m ON m.id=s.id'
        result = {field:set() for field in FIELDS}
        cur = conn.cursor()
        cur.execute(sql + 'SELECT DISTINCT m.publisher,ss.status AS publication_status,m.genre,m.tags,g.series_level AS rating' + join + ' JOIN search_status ss ON ss.representative_id=g.representative_id', tuple(params))
        while True:
            rows = cur.fetchmany(500)
            if not rows:
                break
            for row in rows:
                for field in FIELDS:
                    value = row[field]
                    if value is not None and str(value).strip():
                        result[field].update([v for v in tokens(value) if v.casefold() not in excluded[field]] if field in ('genre','tags') else [str(value)])
        return {field:sorted(values,key=str.casefold) for field,values in result.items()}
    finally:
        conn.close()
