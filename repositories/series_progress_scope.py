"""Use the list/detail series boundary for destructive progress resets."""
import os


def _directory(row):
    path = str(row['file_path'] or '')
    if str(row['file_format'] or '').lower() == 'imgdir' and path.endswith('/__folder__.imgdir'):
        return os.path.dirname(os.path.dirname(path))
    return os.path.dirname(path)


def book_ids(cursor, series_name, library_id, representative_book_id, mariadb=False):
    marker = '%s' if mariadb else '?'
    cursor.execute(f'''SELECT id,file_path,file_format FROM books
        WHERE series_name={marker} AND library_id={marker} AND COALESCE(is_deleted,0)=0''',
        (series_name, library_id))
    rows = cursor.fetchall()
    anchor = next((row for row in rows if str(row['id']) == str(representative_book_id)), None)
    if anchor is None:
        raise ValueError('현재 시리즈에 해당 도서가 없습니다.')
    directory = _directory(anchor)
    return [row['id'] for row in rows if _directory(row) == directory]
