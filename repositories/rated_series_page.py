"""SQL pagination with the highest active volume rating applied to its series."""
import os
import re

import database
from services.content_rating_service import ContentRatingService, _BOOKS_LV_LEVEL_MAP


def supported(db_type, rating, search='', genres=None, tags=None, group='', author=''):
    return (db_type in ('general', 'adult') and rating is not None and rating <= 20
            and not any((search, genres, tags, group, author)))


def _dir(path, fmt):
    path = str(path or '')
    if str(fmt or '').lower() == 'imgdir' and path.replace('\\', '/').endswith('/__folder__.imgdir'):
        return os.path.dirname(os.path.dirname(path))
    return os.path.dirname(path)


def _sort(value):
    raw = str(value or '').strip()
    return re.sub(r'^\s*(?:(?:\[[^\]]+\]|\{[^}]+\})\s*)+', '', raw).strip() or raw


def _query(conn, library_id, user_id, rating, series_scope=None):
    maria = database.is_mariadb_mode()
    keywords = ContentRatingService.get_adult_keywords()
    params = []
    if maria:
        cases = []
        for key, level in _BOOKS_LV_LEVEL_MAP.items():
            cases.append('WHEN ? THEN ' + str(level))
            params.append(key)
        normalized = "LOWER(REGEXP_REPLACE(COALESCE(b.books_lv,''), '^[[:space:]]+|[[:space:]]+$', ''))"
        level = "CASE WHEN b.books_lv IS NULL OR b.books_lv='' THEN 0 ELSE CASE " + normalized + ' ' + ' '.join(cases) + ' ELSE 20 END END'
        keyword_conditions = []
        for keyword in keywords:
            keyword_conditions.append("INSTR(CAST(LOWER(CONCAT(COALESCE(b.genre,''),' ',COALESCE(b.tags,''))) AS BINARY), CAST(? AS BINARY)) > 0")
            params.append(keyword)
        if keyword_conditions:
            level = f"GREATEST(({level}), CASE WHEN {' OR '.join(keyword_conditions)} THEN 18 ELSE 0 END)"
        path = "COALESCE(b.file_path,'')"
        # Same POSIX dirname convention as series_service, including image folders.
        parent = f"CASE WHEN INSTR({path}, '/')=0 THEN '' ELSE COALESCE(NULLIF(REGEXP_REPLACE({path}, '/[^/]*$', ''),''),'/') END"
        grand = f"CASE WHEN INSTR(({parent}), '/')=0 THEN '' ELSE COALESCE(NULLIF(REGEXP_REPLACE(({parent}), '/[^/]*$', ''),''),'/') END"
        directory = f"CASE WHEN LOWER(b.file_format)='imgdir' AND RIGHT({path},18)='/__folder__.imgdir' THEN {grand} ELSE {parent} END"
    else:
        conn.create_function('bo_rating', 3, lambda lv, genre, tags: ContentRatingService.compute_effective_level(lv, genre, tags, keywords))
        conn.create_function('bo_dir', 2, _dir)
        conn.create_function('bo_sort', 1, _sort)
        level = 'bo_rating(b.books_lv,b.genre,b.tags)'
        directory = 'bo_dir(b.file_path,b.file_format)'
    where = ['(b.is_deleted=0 OR b.is_deleted IS NULL)']
    if str(library_id) not in ('all', 'home', 'history', 'favorite', 'None'):
        where.append('b.library_id=?')
        params.append(int(library_id))
    if user_id:
        where.append('EXISTS (SELECT 1 FROM user_category_permissions p WHERE p.library_id=b.library_id AND p.user_id=? AND p.has_access=1)')
        params.append(user_id)
    if series_scope is not None:
        where.extend(["COALESCE(NULLIF(b.series_name,''),'기타 단행본')=?", f'({directory})=?'])
        params.extend(series_scope)
    params.append(rating)
    safe_user = int(user_id or 0)
    sql = f"""WITH raw_books AS (
        SELECT b.id,b.library_id,COALESCE(NULLIF(b.series_name,''),'기타 단행본') AS group_name,
               {directory} AS group_dir,b.created_at,b.cover_image,b.author,b.genre,b.tags,
               b.books_lv,b.publication_status,b.series_alias,b.metadata_locked,({level}) AS effective_level,
               CASE WHEN COALESCE(p.is_completed,0)=1 OR (COALESCE(b.total_pages,0)>0 AND COALESCE(p.pages_read,0)>=b.total_pages) THEN 1 ELSE 0 END AS completed,
               COALESCE(p.pages_read,0) AS pages_read,
               CASE WHEN EXISTS(SELECT 1 FROM user_favorites f WHERE f.book_id=b.id AND f.user_id={safe_user}) THEN 1 ELSE 0 END AS favorite
        FROM books b LEFT JOIN user_progress p ON p.book_id=b.id AND p.user_id={safe_user}
        WHERE {' AND '.join(where)}
    ), scoped AS (
        SELECT raw_books.*,MAX(effective_level) OVER(PARTITION BY library_id,group_name,group_dir) AS series_level FROM raw_books
    ), eligible AS (
        SELECT * FROM scoped {'WHERE favorite=1' if library_id == 'favorite' else ''}
    ), grouped AS (
        SELECT library_id,group_name,group_dir,MIN(id) AS representative_id,
               COUNT(*) AS series_book_count,MAX(created_at) AS series_latest_added,
               MAX(COALESCE(metadata_locked,0)) AS any_locked,
               MIN(completed) AS all_completed, MAX(CASE WHEN completed=1 OR pages_read>0 THEN 1 ELSE 0 END) AS has_progress,
               MAX(favorite) AS is_favorite,MAX(series_level) AS series_level,
               MIN(CASE WHEN cover_image IS NOT NULL AND cover_image<>'' THEN id END) AS cover_id,
               {','.join(f"MIN(CASE WHEN {field} IS NOT NULL AND {field}<>'' THEN id END) AS {field}_id" for field in ('author','genre','tags','books_lv','publication_status','series_alias'))}
        FROM eligible GROUP BY library_id,group_name,group_dir HAVING MAX(series_level)<=?
    ) """
    return sql, params


def _order(maria, sort):
    direction = 'DESC' if sort in ('desc', 'date_desc') else 'ASC'
    if sort in ('date_asc', 'date_desc'):
        return f"g.series_latest_added {direction}, g.representative_id ASC"
    def norm(expr):
        if not maria:
            return f'bo_sort({expr}) COLLATE BINARY'
        stripped = f"TRIM(REGEXP_REPLACE(TRIM({expr}), '^(\\\\[[^]]+\\\\]|\\\\{{[^}}]+\\\\}}|[[:space:]])+', ''))"
        return f"CAST(COALESCE(NULLIF({stripped},''),TRIM({expr})) AS BINARY)"
    title = norm("COALESCE(NULLIF(b.title_alias,''),b.title,'')")
    return f"{norm('g.group_name')} {direction}, {title} {direction}, g.representative_id ASC"


def fetch(db_type, library_id, user_id, rating, *, limit=31, offset=0, sort='asc', totals=False, index=False):
    conn = database.get_connection(db_type)
    try:
        sql, params = _query(conn, library_id, user_id, rating)
        if totals:
            sql += 'SELECT COUNT(*) AS total_series_count, COALESCE(SUM(series_book_count),0) AS total_book_count FROM grouped'
        elif index:
            sql += "SELECT g.representative_id AS id,g.library_id,g.group_name AS series_name,g.group_dir,g.series_level,b.title,b.title_alias,b.file_format FROM grouped g JOIN books b ON b.id=g.representative_id ORDER BY " + _order(database.is_mariadb_mode(), sort)
        else:
            # Rich fields are fetched only for the selected page, not all books.
            sql += """SELECT b.id,b.library_id,b.series_name,b.title,b.title_alias,b.file_path,b.file_format,b.created_at,
                g.series_book_count,g.series_latest_added,g.any_locked AS rated_locked,
                g.all_completed,g.has_progress,g.is_favorite,g.series_level,
                cover.cover_image AS rated_cover,cover.cover_updated_at AS rated_cover_updated,
                cover.cover_align AS rated_cover_align,
            """ + ','.join(f'{field}_book.{field} AS rated_{field}' for field in ('author','genre','tags','books_lv','publication_status','series_alias'))
            sql += " FROM grouped g JOIN books b ON b.id=g.representative_id LEFT JOIN books cover ON cover.id=g.cover_id "
            sql += ' '.join(f'LEFT JOIN books {field}_book ON {field}_book.id=g.{field}_id' for field in ('author','genre','tags','books_lv','publication_status','series_alias'))
            sql += ' ORDER BY ' + _order(database.is_mariadb_mode(), sort) + ' LIMIT ? OFFSET ?'
            params.extend([max(0, int(limit)), max(0, int(offset))])
        cur = conn.cursor()
        cur.execute(sql, tuple(params))
        if totals:
            return dict(cur.fetchone())
        rows = [dict(r) for r in cur.fetchall()]
        if index:
            return rows
        for row in rows:
            row['cover_image'] = row.pop('rated_cover')
            row['cover_updated_at'] = row.pop('rated_cover_updated')
            row['cover_align'] = row.pop('rated_cover_align') or 'center'
            row['metadata_locked'] = row.pop('rated_locked')
            for field in ('author','genre','tags','books_lv','publication_status','series_alias'):
                row[field] = row.pop('rated_' + field) or ''
            row['has_metadata'] = None
        return rows
    finally:
        conn.close()


def level_for_book(db_type, book_id):
    """Resolve the same series boundary used by lists, also for direct links."""
    conn = database.get_connection(db_type)
    try:
        cur = conn.cursor()
        cur.execute('SELECT library_id,series_name,file_path,file_format FROM books WHERE id=?', (book_id,))
        row = cur.fetchone()
        if not row:
            return None
        sql, params = _query(conn, row['library_id'], None, 20,
                            (row['series_name'] or '기타 단행본', _dir(row['file_path'], row['file_format'])))
        cur.execute(sql + 'SELECT MAX(series_level) AS level FROM grouped', tuple(params))
        result = cur.fetchone()
        return result['level'] if result else None
    finally:
        conn.close()


def levels_for_libraries(db_type, library_ids):
    result = {}
    for library_id in set(library_ids):
        for row in fetch(db_type, library_id, None, 20, index=True):
            result[(row['library_id'], row['series_name'], row['group_dir'])] = int(row['series_level'])
    return result
