"""Resolve the concrete book rows included in a queued scan request."""


def resolve_batch_book_scan_targets(cursor, requested_book_ids, scope='book'):
    """Return requested books, optionally expanding anchors to related volumes.

    Series membership is resolved from the anchor book in the database and scoped to
    its library, so callers do not need to send a potentially ambiguous series title.
    ``missing_covers`` keeps the selected anchor and adds only same-series books whose
    cover is blank or marked as missing.
    """
    if scope not in ('book', 'series', 'missing_covers'):
        raise ValueError('지원하지 않는 스캔 범위입니다.')

    placeholders = ', '.join('?' for _ in requested_book_ids)
    cursor.execute(
        f"SELECT id, library_id, title, series_name, cover_image FROM books "
        f"WHERE id IN ({placeholders}) AND COALESCE(is_deleted, 0) = 0",
        tuple(requested_book_ids),
    )
    anchor_rows = cursor.fetchall()
    found_ids = {int(row['id']) for row in anchor_rows}
    if found_ids != set(requested_book_ids):
        raise LookupError('요청한 도서 중 현재 데이터베이스에서 찾을 수 없는 항목이 있습니다.')
    if scope == 'book':
        return anchor_rows

    if scope == 'missing_covers':
        if len(anchor_rows) != 1:
            raise ValueError('표지가 비어 있는 시리즈 권 검색은 도서 한 권만 지정할 수 있습니다.')
        anchor = anchor_rows[0]
        series_name = str(anchor['series_name'] or '').strip()
        library_id = anchor['library_id']
        if not series_name or library_id is None:
            return anchor_rows

        cursor.execute(
            "SELECT id, library_id, title FROM books "
            "WHERE COALESCE(is_deleted, 0) = 0 AND library_id = ? AND series_name = ? "
            "AND (id = ? OR cover_image IS NULL OR TRIM(cover_image) = '' "
            "OR UPPER(TRIM(cover_image)) = 'NO_COVER') ORDER BY id",
            (library_id, anchor['series_name'], int(anchor['id'])),
        )
        return cursor.fetchall()

    series_keys = set()
    for row in anchor_rows:
        series_name = str(row['series_name'] or '').strip()
        if series_name and row['library_id'] is not None:
            series_keys.add((row['library_id'], row['series_name']))

    conditions = []
    params = []
    for library_id, series_name in sorted(series_keys, key=lambda key: (str(key[0]), str(key[1]))):
        conditions.append('(library_id = ? AND series_name = ?)')
        params.extend((library_id, series_name))

    # Keep standalone books in the batch and guarantee each selected anchor is included.
    conditions.append(f"id IN ({', '.join('?' for _ in requested_book_ids)})")
    params.extend(requested_book_ids)
    cursor.execute(
        "SELECT id, library_id, title FROM books "
        f"WHERE COALESCE(is_deleted, 0) = 0 AND ({' OR '.join(conditions)}) "
        "ORDER BY id",
        tuple(params),
    )
    return cursor.fetchall()
