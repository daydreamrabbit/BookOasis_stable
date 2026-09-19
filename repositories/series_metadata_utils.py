# -*- coding: utf-8 -*-
"""Helpers for presenting per-book metadata as series-level detail metadata."""


def book_metadata_exists_sql(book_alias='b'):
    """Return a correlated SQL predicate for real metadata on any volume in a series.

    Titles, paths, covers, and the manual-lock flag are intentionally excluded: those
    exist even when no metadata source has supplied information. The helper is shared
    by the MariaDB and SQLite series-list queries.
    """
    metadata_book = 'metadata_book'
    populated_fields = (
        'author', 'isbn', 'publisher', 'link', 'release_date', 'summary',
        'genre', 'tags', 'books_lv', 'publication_status', 'cover_artist',
        'teams', 'locations', 'characters', 'series_alias', 'title_alias',
    )
    conditions = []
    for field in populated_fields:
        value_present = f"NULLIF(TRIM(COALESCE({metadata_book}.{field}, '')), '') IS NOT NULL"
        if field == 'summary':
            # This sentinel is used by older metadata imports to mean that no description exists.
            value_present = (
                f"({value_present} AND "
                f"TRIM(COALESCE({metadata_book}.summary, '')) != '등록된 설명이 없습니다.')"
            )
        conditions.append(value_present)
    conditions.append(f'COALESCE({metadata_book}.score, 0) <> 0')
    # 시리즈 키 = COALESCE(NULLIF(series_name,''), title) (series_summary 그룹 키와 동일).
    # 비교식의 안쪽(metadata_book) 컬럼을 COALESCE로 감싸면 idx_books_series_name을 못 타고
    # library_id 인덱스로 라이브러리 전체를 훑는다(대형 카테고리에서 수 초). 그래서 같은 의미를
    # 안쪽 컬럼은 맨몸으로 두는 두 갈래로 나눈다 - (a) series_name이 있는 권은 series_name 인덱스,
    # (b) series_name이 비어 있는 권은 title 인덱스. 바깥(b) 쪽 COALESCE는 행마다 상수라 무방하다.
    series_key = f"COALESCE(NULLIF({book_alias}.series_name, ''), {book_alias}.title)"
    base = f"""SELECT 1
        FROM books {metadata_book}
        WHERE {metadata_book}.library_id = {book_alias}.library_id
          AND ({metadata_book}.is_deleted = 0 OR {metadata_book}.is_deleted IS NULL)
          AND ({' OR '.join(conditions)})"""
    return f"""(
        EXISTS ({base}
          AND {metadata_book}.series_name <> ''
          AND {metadata_book}.series_name = {series_key})
        OR EXISTS ({base}
          AND ({metadata_book}.series_name IS NULL OR {metadata_book}.series_name = '')
          AND {metadata_book}.title = {series_key})
    )"""


def book_metadata_select_expr(book_alias='b', include=False):
    """Return the SELECT expression for a list row's has_metadata column.

    The correlated EXISTS scans the whole category per result row (seconds on a ~40K-book
    library), so list queries emit NULL unless the caller opted in (include_has_metadata).
    """
    return book_metadata_exists_sql(book_alias) if include else 'NULL'
