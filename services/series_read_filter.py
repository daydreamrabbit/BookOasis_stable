"""Apply live completion state without changing the custom search/group rules."""
import database
from repositories import rated_series_page as rated


def normalize(value):
    return value if value in ('only_read', 'exclude_read') else ''


def filter_rows(db_type, rows, library_id, user_id, rating, read_filter):
    if not read_filter or db_type == 'video':
        return rows
    if db_type == 'audiobook':
        conn = database.get_connection(db_type)
        try:
            cur = conn.cursor()
            comparison = '=1' if read_filter == 'only_read' else '=0'
            cur.execute(f'''SELECT a.id FROM audiobooks a
                LEFT JOIN audiobook_progress p ON p.audiobook_id=a.id AND p.user_id=?
                WHERE COALESCE(a.is_deleted,0)=0 AND COALESCE(p.is_completed,0){comparison}''',
                (int(user_id or 0),))
            allowed = {r['id'] for r in cur.fetchall()}
        finally:
            conn.close()
        return [r for r in rows if r['id'] in allowed]
    groups = {(r['library_id'], r['series_name'], r['group_dir'])
              for r in rated.fetch(db_type, library_id, user_id, rating if rating is not None else 20,
                                   index=True, read_filter=read_filter)}
    return [r for r in rows if (r['library_id'], r['series_name'] or '기타 단행본',
                               rated._dir(r['file_path'], r['file_format'])) in groups]
