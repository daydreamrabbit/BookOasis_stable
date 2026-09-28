# -*- coding: utf-8 -*-
"""DB 엔진 공용 시리즈 데이터 영구 삭제 SQL.

원본 도서 파일은 다루지 않는다. UI가 넘긴 시리즈명 대신 대표 도서 ID를 기준으로
라이브러리와 시리즈 키를 서버에서 다시 확정해 다른 라이브러리의 동명 시리즈를 보호한다.
"""
import os

import database


_BOOK_DEPENDENT_TABLES = (
    'user_progress',
    'user_reading_log',
    'user_favorites',
    'book_offsets',
    'book_annotations',
    'epub_bookmarks',
    'collection_items',
    'gdrive_book_copies',
    'tts_progress',
)


def _series_filter(placeholder):
    return (
        f"library_id = {placeholder} "
        f"AND COALESCE(NULLIF(series_name, ''), title) = {placeholder}"
    )


def delete_series_batch(db_type, targets, placeholder):
    """Resolve all anchors before writing, then delete a bounded batch in one transaction."""
    conn = database.get_connection(db_type)
    cursor = conn.cursor()
    try:
        marks = ','.join([placeholder] * len(targets))
        cursor.execute(
            f'SELECT id, library_id, title, series_name FROM books '
            f'WHERE id IN ({marks}) AND COALESCE(is_deleted, 0) = 0',
            [target['book_id'] for target in targets],
        )
        anchors = {int(row['id']): dict(row) for row in cursor.fetchall()}
        groups, results = {}, []
        for target in targets:
            anchor = anchors.get(target['book_id'])
            if not anchor:
                results.append({'book_id': target['book_id'], 'success': False,
                                'error': '삭제할 시리즈를 찾을 수 없습니다.'})
                continue
            if int(anchor['library_id']) != target['library_id']:
                raise ValueError('선택한 도서와 라이브러리 정보가 일치하지 않습니다.')
            # Match the SQL expression exactly, including significant whitespace.
            key = (int(anchor['library_id']), anchor['series_name'] or anchor['title'])
            if not key[1]:
                raise ValueError('삭제할 시리즈를 식별할 수 없습니다.')
            result = {'library_id': key[0], 'series_name': key[1], 'deleted_count': 0}
            results.append({'book_id': target['book_id'], 'success': True, 'result': result})
            groups.setdefault(key, result)
        if not groups:
            conn.rollback()
            return {'results': results, 'unreferenced_media': []}
        where = ' OR '.join(f'({_series_filter(placeholder)})' for _ in groups)
        params = [value for key in groups for value in key]
        cursor.execute(f'SELECT library_id, COALESCE(NULLIF(series_name, \'\'), title) AS series_key, '
                       f'file_path, cover_image, banner_image FROM books WHERE {where}', params)
        media, folders = set(), set()
        for row in cursor.fetchall():
            groups[(int(row['library_id']), row['series_key'])]['deleted_count'] += 1
            media.update(str(row[field]) for field in ('cover_image', 'banner_image') if row[field])
            if row['file_path']:
                folders.add(os.path.dirname(row['file_path']))
        for table in _BOOK_DEPENDENT_TABLES:
            cursor.execute(f'DELETE FROM {table} WHERE book_id IN '
                           f'(SELECT id FROM books WHERE {where})', params)
        folders = sorted(folders)
        for start in range(0, len(folders), 300):
            chunk = folders[start:start + 300]
            marks = ','.join([placeholder] * len(chunk))
            cursor.execute(f'DELETE FROM folder_mtimes WHERE folder_path IN ({marks})', chunk)
        summary_where = ' OR '.join(
            f'(library_id = {placeholder} AND series_key = {placeholder})' for _ in groups)
        cursor.execute(f'DELETE FROM series_summary WHERE {summary_where}', params)
        # Optional legacy table: only tolerate absence, never hide other SQL failures.
        try:
            cursor.execute(f'DELETE FROM series WHERE {summary_where.replace("series_key", "name")}', params)
        except Exception as exc:
            if 'no such table' not in str(exc).lower() and "doesn't exist" not in str(exc).lower():
                raise
        cursor.execute(f'DELETE FROM books WHERE {where}', params)
        referenced = set()
        candidates = sorted(media)
        for start in range(0, len(candidates), 300):
            chunk = candidates[start:start + 300]
            marks = ','.join([placeholder] * len(chunk))
            cursor.execute(f'SELECT cover_image, banner_image FROM books WHERE '
                           f'cover_image IN ({marks}) OR banner_image IN ({marks})', chunk + chunk)
            for row in cursor.fetchall():
                referenced.update(value for value in (row['cover_image'], row['banner_image']) if value)
            cursor.execute(f'SELECT cover_image FROM collections WHERE cover_image IN ({marks})', chunk)
            referenced.update(row['cover_image'] for row in cursor.fetchall())
        conn.commit()
        return {'results': results, 'unreferenced_media': sorted(media - referenced)}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def delete_series_by_anchor(db_type, book_id, expected_library_id, placeholder):
    """대표 도서가 속한 한 라이브러리의 시리즈 DB 행을 완전히 삭제한다."""
    conn = database.get_connection(db_type)
    cursor = conn.cursor()
    try:
        cursor.execute(
            f"""
            SELECT id, library_id, title, series_name
            FROM books
            WHERE id = {placeholder} AND COALESCE(is_deleted, 0) = 0
            """,
            (book_id,),
        )
        anchor = cursor.fetchone()
        if not anchor:
            return None

        library_id = int(anchor['library_id'])
        if expected_library_id is not None and int(expected_library_id) != library_id:
            raise ValueError('선택한 도서와 라이브러리 정보가 일치하지 않습니다.')

        raw_series_name = str(anchor['series_name'] or '').strip()
        series_key = raw_series_name or str(anchor['title'] or '').strip()
        if not series_key:
            raise ValueError('삭제할 시리즈를 식별할 수 없습니다.')

        where = _series_filter(placeholder)
        params = (library_id, series_key)
        cursor.execute(
            f"SELECT id, file_path, cover_image, banner_image FROM books WHERE {where}",
            params,
        )
        books = [dict(row) for row in cursor.fetchall()]
        if not books:
            return None

        media_candidates = sorted({
            str(value).strip()
            for row in books
            for value in (row.get('cover_image'), row.get('banner_image'))
            if value and str(value).strip()
        })
        affected_folders = sorted({
            os.path.dirname(str(row.get('file_path') or '').strip())
            for row in books
            if str(row.get('file_path') or '').strip()
        })

        # 모든 종속 데이터는 동일한 서버 확정 조건을 서브쿼리로 사용한다.
        for table in _BOOK_DEPENDENT_TABLES:
            cursor.execute(
                f"""
                DELETE FROM {table}
                WHERE book_id IN (SELECT id FROM books WHERE {where})
                """,
                params,
            )

        # 다음 일반 스캔에서 원본 파일을 다시 발견할 수 있게 해당 폴더 캐시만 제거한다.
        for folder in affected_folders:
            cursor.execute(
                f"DELETE FROM folder_mtimes WHERE folder_path = {placeholder}",
                (folder,),
            )

        cursor.execute(
            f"DELETE FROM series_summary WHERE library_id = {placeholder} AND series_key = {placeholder}",
            params,
        )

        # 구형 설치에만 남아 있을 수 있는 legacy series 테이블도 같은 범위로 정리한다.
        if raw_series_name:
            try:
                cursor.execute(
                    f"DELETE FROM series WHERE library_id = {placeholder} AND name = {placeholder}",
                    (library_id, raw_series_name),
                )
            except Exception:
                pass

        cursor.execute(f"DELETE FROM books WHERE {where}", params)

        # 다른 도서의 cover/banner 또는 컬렉션 대표 이미지로 남아 있는 파일은 보존한다.
        referenced_media = set()
        for start in range(0, len(media_candidates), 300):
            chunk = media_candidates[start:start + 300]
            marks = ','.join([placeholder] * len(chunk))
            cursor.execute(
                f"""
                SELECT cover_image, banner_image FROM books
                WHERE cover_image IN ({marks}) OR banner_image IN ({marks})
                """,
                (*chunk, *chunk),
            )
            for row in cursor.fetchall():
                row_data = dict(row)
                if row_data.get('cover_image'):
                    referenced_media.add(str(row_data['cover_image']))
                if row_data.get('banner_image'):
                    referenced_media.add(str(row_data['banner_image']))
            cursor.execute(
                f"SELECT cover_image FROM collections WHERE cover_image IN ({marks})",
                chunk,
            )
            for row in cursor.fetchall():
                row_data = dict(row)
                if row_data.get('cover_image'):
                    referenced_media.add(str(row_data['cover_image']))

        conn.commit()
        return {
            'library_id': library_id,
            'series_name': series_key,
            'deleted_count': len(books),
            'unreferenced_media': [item for item in media_candidates if item not in referenced_media],
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
