"""Recent additions for the visible series page, using current folder grouping."""
import database
from repositories.rated_series_page import _dir


def _directory(alias, maria):
    if not maria:
        return f"bo_recent_dir({alias}.file_path, {alias}.file_format)"
    path = f"COALESCE({alias}.file_path, '')"
    parent = f"CASE WHEN INSTR({path}, '/')=0 THEN '' ELSE COALESCE(NULLIF(REGEXP_REPLACE({path}, '/[^/]*$', ''), ''), '/') END"
    grand = f"CASE WHEN INSTR(({parent}), '/')=0 THEN '' ELSE COALESCE(NULLIF(REGEXP_REPLACE(({parent}), '/[^/]*$', ''), ''), '/') END"
    return f"CASE WHEN LOWER({alias}.file_format)='imgdir' AND RIGHT({path},18)='/__folder__.imgdir' THEN {grand} ELSE {parent} END"


def fetch(db_type, days, book_ids):
    """Aggregate only series authorized and selected by the list endpoint.

    Include old volumes even on favorites/search pages, so adding a favorite
    volume cannot turn an existing series into NEW. Library totals implement
    the upstream initial-import suppression rule.
    """
    if not book_ids:
        return {'series': {}, 'libraries': {}}
    conn = database.get_connection(db_type)
    try:
        maria = database.is_mariadb_mode()
        marker = '%s' if maria else '?'
        if not maria:
            conn.create_function('bo_recent_dir', 2, _dir, deterministic=True)
        cursor = conn.cursor()
        cursor.execute(
            "SELECT NOW() - INTERVAL %s DAY AS cutoff" if maria
            else "SELECT datetime('now', '-' || ? || ' days') AS cutoff",
            (int(days),),
        )
        cutoff = cursor.fetchone()['cutoff']
        series = {}
        for start in range(0, len(book_ids), 100):
            ids = book_ids[start:start + 100]
            slots = ','.join([marker] * len(ids))
            cursor.execute(f"""
                SELECT id, library_id, series_name, file_path, file_format
                FROM books WHERE id IN ({slots}) AND (is_deleted = 0 OR is_deleted IS NULL)
            """, tuple(ids))
            representatives = cursor.fetchall()
            queries, params = [], []
            for row in representatives:
                # Binding the name directly lets the existing series-name index
                # narrow the query before computing folder paths. A COALESCE
                # self-join would examine the whole library for every card.
                ident, library = int(row['id']), int(row['library_id'])
                name = row['series_name'] or '기타 단행본'
                params.extend([cutoff, library])
                if name == '기타 단행본':
                    name_filter = "(b.series_name IS NULL OR b.series_name IN ('', '기타 단행본'))"
                else:
                    name_filter = f'b.series_name = {marker}'
                    params.append(name)
                params.append(_dir(row['file_path'], row['file_format']))
                queries.append(f"""
                    SELECT {ident} AS id, {library} AS library_id, COUNT(*) AS total_count,
                           SUM(CASE WHEN b.created_at >= {marker} THEN 1 ELSE 0 END) AS recent_count
                    FROM books b WHERE b.library_id = {marker} AND {name_filter}
                      AND {_directory('b', maria)} = {marker}
                      AND (b.is_deleted = 0 OR b.is_deleted IS NULL)
                """)
            if queries:
                cursor.execute(' UNION ALL '.join(queries), tuple(params))
                series.update((int(row['id']), dict(row)) for row in cursor.fetchall())
        library_ids = sorted({int(row['library_id']) for row in series.values()})
        libraries = {}
        if library_ids:
            slots = ','.join([marker] * len(library_ids))
            cursor.execute(f"""
                SELECT library_id, COUNT(*) AS total_count,
                       SUM(CASE WHEN created_at >= {marker} THEN 1 ELSE 0 END) AS recent_count
                FROM books WHERE library_id IN ({slots})
                  AND (is_deleted = 0 OR is_deleted IS NULL)
                GROUP BY library_id
            """, (cutoff, *library_ids))
            libraries = {int(row['library_id']): dict(row) for row in cursor.fetchall()}
        return {'series': series, 'libraries': libraries}
    finally:
        conn.close()
