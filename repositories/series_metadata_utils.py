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
    return f"""EXISTS (
        SELECT 1
        FROM books {metadata_book}
        WHERE {metadata_book}.library_id = {book_alias}.library_id
          AND COALESCE(NULLIF({metadata_book}.series_name, ''), {metadata_book}.title)
              = COALESCE(NULLIF({book_alias}.series_name, ''), {book_alias}.title)
          AND ({metadata_book}.is_deleted = 0 OR {metadata_book}.is_deleted IS NULL)
          AND ({' OR '.join(conditions)})
    )"""
