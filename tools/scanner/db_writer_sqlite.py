# -*- coding: utf-8 -*-
"""
db_writer_sqlite.py – SQLite 전용 스캐너 DB 업서트/배치 라이터
"""
import os

def clear_book_banners(cursor, library_id, full_paths):
    """Clear scanner-owned banner references after their source disappears."""
    paths = list(dict.fromkeys(path for path in full_paths if path))
    if not paths:
        return
    cursor.executemany("""
        UPDATE books
        SET banner_image = NULL, banner_updated_at = CURRENT_TIMESTAMP
        WHERE library_id = ? AND file_path = ? AND COALESCE(metadata_locked, 0) = 0
    """, [(library_id, path) for path in paths])


def update_book_metadata(cursor, full_path, cover_image, merged_meta, series_name='', force=False, banner_image=None):
    """Execute merge update for existing book info and local metadata in SQLite"""
    common_args = (
        cover_image,
        cover_image, cover_image,
        banner_image or '',
        banner_image or '', banner_image or '',
        merged_meta['author'],
        merged_meta.get('isbn', ''),
        merged_meta['publisher'],
        merged_meta['link'],
        merged_meta['score'], merged_meta['score'],
        merged_meta['summary'],
        merged_meta['release_date'],
        merged_meta.get('genre', ''),
        merged_meta.get('tags', ''),
        full_path
    )
    if force:
        cursor.execute("""
            UPDATE books SET
                series_name  = CASE WHEN ? IS NOT NULL AND ? != '' THEN ? ELSE series_name END,
                metadata_title = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), metadata_title) ELSE metadata_title END,
                cover_image  = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_image) ELSE cover_image END,
                cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE cover_updated_at END,
                banner_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), banner_image) ELSE banner_image END,
                banner_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE banner_updated_at END,
                author       = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), author) ELSE author END,
                isbn         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), isbn) ELSE isbn END,
                publisher    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publisher) ELSE publisher END,
                link         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), link) ELSE link END,
                score        = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != 0 THEN ? ELSE score END,
                summary      = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), summary) ELSE summary END,
                release_date = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), release_date) ELSE release_date END,
                genre        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), genre) ELSE genre END,
                tags         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), tags) ELSE tags END
            WHERE file_path = ?
        """, (series_name, series_name, series_name, merged_meta.get('title', '')) + common_args)
    else:
        cursor.execute("""
            UPDATE books SET
                series_name  = CASE WHEN ? IS NOT NULL AND ? != '' THEN ? ELSE series_name END,
                metadata_title = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), metadata_title) ELSE metadata_title END,
                cover_image  = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_image) ELSE cover_image END,
                cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE cover_updated_at END,
                banner_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), banner_image) ELSE banner_image END,
                banner_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE banner_updated_at END,
                author       = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), author) ELSE author END,
                isbn         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), isbn) ELSE isbn END,
                publisher    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publisher) ELSE publisher END,
                link         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), link) ELSE link END,
                score        = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != 0 THEN ? ELSE score END,
                summary      = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), summary) ELSE summary END,
                release_date = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), release_date) ELSE release_date END,
                genre        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), genre) ELSE genre END,
                tags         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), tags) ELSE tags END
            WHERE file_path = ?
        """, (series_name, series_name, series_name, merged_meta.get('title', '')) + common_args)

def insert_new_book_v2(cursor, library_id, full_path, filename, file_format, series_name, cover_image, merged_meta, file_mtime=0.0, file_size=0):
    """Insert new book info to DB and return book_id in SQLite"""
    title, _ = os.path.splitext(filename)
    cursor.execute("""
        INSERT INTO books 
        (library_id, title, metadata_title, series_name, author, isbn, file_path, file_format, total_pages, cover_image, publisher, link, score, summary, release_date, genre, tags, file_mtime, file_size)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        library_id, 
        title, 
        merged_meta.get('title', ''),
        series_name, 
        merged_meta['author'], 
        merged_meta.get('isbn', ''),
        full_path, 
        file_format, 
        100 if file_format == 'epub' else 0, 
        cover_image,
        merged_meta['publisher'],
        merged_meta['link'],
        merged_meta['score'],
        merged_meta['summary'],
        merged_meta['release_date'],
        merged_meta.get('genre', ''),
        merged_meta.get('tags', ''),
        file_mtime,
        file_size
    ))
    return cursor.lastrowid

def save_book_offsets(cursor, book_id, filename, offsets_data):
    """Bulk save offset info to DB and update books table summary in SQLite"""
    if not offsets_data:
        return
        
    cursor.execute("DELETE FROM book_offsets WHERE book_id = ?", (book_id,))
    bulk_data = [(book_id, *offset) for offset in offsets_data]
    cursor.executemany("""
        INSERT INTO book_offsets
        (book_id, page_idx, filename, local_header_offset, compress_size, file_size, compress_type, data_offset)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, bulk_data)
    
    cursor.execute("""
        UPDATE books SET total_pages = ?, has_offsets = 1 WHERE id = ?
    """, (len(bulk_data), book_id))
    print(f"[Scanner-Offset-SQLite] '{filename}' offset DB index complete ({len(bulk_data)} pages)")

def bulk_update_books(cursor, update_data_list, force=False):
    """Bulk update existing books in SQLite"""
    if not update_data_list:
        return
    if force:
        cursor.executemany("""
            UPDATE books SET 
                is_deleted   = 0,
                library_id   = CASE WHEN ? IS NOT NULL AND ? > 0 THEN ? ELSE library_id END,
                series_name  = CASE WHEN ? IS NOT NULL AND ? != '' THEN ? ELSE series_name END,
                metadata_title = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), metadata_title) ELSE metadata_title END,
                cover_image  = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_image) ELSE cover_image END,
                cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE cover_updated_at END,
                banner_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), banner_image) ELSE banner_image END,
                banner_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE banner_updated_at END,
                author       = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), author) ELSE author END,
                isbn         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), isbn) ELSE isbn END,
                publisher    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publisher) ELSE publisher END,
                link         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), link) ELSE link END,
                score        = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != 0 THEN ? ELSE score END,
                summary      = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), summary) ELSE summary END,
                release_date = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), release_date) ELSE release_date END,
                genre        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), genre) ELSE genre END,
                tags         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), tags) ELSE tags END,
                books_lv     = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), books_lv) ELSE books_lv END,
                publication_status = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publication_status) ELSE publication_status END,
                cover_artist = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_artist) ELSE cover_artist END,
                teams        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), teams) ELSE teams END,
                locations    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), locations) ELSE locations END,
                characters   = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), characters) ELSE characters END,
                localized_series = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), localized_series) ELSE localized_series END,
                document_series_name = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), document_series_name) ELSE document_series_name END,
                document_volume_index = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(?, document_volume_index) ELSE document_volume_index END,
                document_volume_count = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(?, document_volume_count) ELSE document_volume_count END,
                file_mtime   = ?,
                file_size    = ?
            WHERE file_path = ?
        """, [
            (row[0], row[0], row[0], row[1], row[1], row[1], *row[2:]) for row in update_data_list
        ])

    else:
        cursor.executemany("""
            UPDATE books SET
                is_deleted   = 0,
                library_id   = CASE WHEN ? IS NOT NULL AND ? > 0 THEN ? ELSE library_id END,
                series_name  = CASE WHEN ? IS NOT NULL AND ? != '' THEN ? ELSE series_name END,
                metadata_title = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), metadata_title) ELSE metadata_title END,
                cover_image  = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_image) ELSE cover_image END,
                cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE cover_updated_at END,
                banner_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), banner_image) ELSE banner_image END,
                banner_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != '' AND ? IS NOT NULL THEN CURRENT_TIMESTAMP ELSE banner_updated_at END,
                author       = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), author) ELSE author END,
                isbn         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), isbn) ELSE isbn END,
                publisher    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publisher) ELSE publisher END,
                link         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), link) ELSE link END,
                score        = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND ? != 0 THEN ? ELSE score END,
                summary      = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), summary) ELSE summary END,
                release_date = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), release_date) ELSE release_date END,
                genre        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), genre) ELSE genre END,
                tags         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), tags) ELSE tags END,
                books_lv     = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), books_lv) ELSE books_lv END,
                publication_status = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), publication_status) ELSE publication_status END,
                cover_artist = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), cover_artist) ELSE cover_artist END,
                teams        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), teams) ELSE teams END,
                locations    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), locations) ELSE locations END,
                characters   = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), characters) ELSE characters END,
                localized_series = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), localized_series) ELSE localized_series END,
                document_series_name = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(?, ''), document_series_name) ELSE document_series_name END,
                document_volume_index = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(?, document_volume_index) ELSE document_volume_index END,
                document_volume_count = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(?, document_volume_count) ELSE document_volume_count END,
                file_mtime   = ?,
                file_size    = ?
            WHERE file_path = ?
        """, [
            (row[0], row[0], row[0], row[1], row[1], row[1], *row[2:]) for row in update_data_list
        ])

def bulk_update_book_covers(cursor, cover_update_list):
    """Update only cover references for cached books, preserving all metadata."""
    if not cover_update_list:
        return
    cursor.executemany("""
        UPDATE books
        SET cover_image = ?, cover_updated_at = CURRENT_TIMESTAMP
        WHERE file_path = ? AND library_id = ? AND COALESCE(metadata_locked, 0) = 0
    """, cover_update_list)

def bulk_insert_books(cursor, insert_data_list):
    """Bulk insert or upsert new books when file_path conflicts in SQLite"""
    if not insert_data_list: return
    cursor.executemany("""
        INSERT INTO books
        (library_id, title, metadata_title, series_name, author, isbn, file_path, file_format, total_pages, cover_image, banner_image, publisher, link, score, summary, release_date, genre, tags, books_lv, publication_status, cover_artist, teams, locations, characters, localized_series, document_series_name, document_volume_index, document_volume_count, file_mtime, file_size, is_deleted)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        ON CONFLICT(file_path) DO UPDATE SET
            library_id   = EXCLUDED.library_id,
            is_deleted   = 0,
            title        = EXCLUDED.title,
            metadata_title = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(NULLIF(EXCLUDED.metadata_title, ''), books.metadata_title) ELSE books.metadata_title END,
            series_name  = EXCLUDED.series_name,
            cover_image  = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(NULLIF(EXCLUDED.cover_image, ''), books.cover_image) ELSE books.cover_image END,
            banner_image = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(NULLIF(EXCLUDED.banner_image, ''), books.banner_image) ELSE books.banner_image END,
            localized_series = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(NULLIF(EXCLUDED.localized_series, ''), books.localized_series) ELSE books.localized_series END,
            document_series_name = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(NULLIF(EXCLUDED.document_series_name, ''), books.document_series_name) ELSE books.document_series_name END,
            document_volume_index = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(EXCLUDED.document_volume_index, books.document_volume_index) ELSE books.document_volume_index END,
            document_volume_count = CASE WHEN COALESCE(books.metadata_locked, 0) = 0 THEN COALESCE(EXCLUDED.document_volume_count, books.document_volume_count) ELSE books.document_volume_count END,
            file_mtime   = EXCLUDED.file_mtime,
            file_size    = EXCLUDED.file_size
    """, insert_data_list)

def bulk_save_book_offsets(cursor, offsets_data_list):
    """Bulk save book offsets in SQLite"""
    if not offsets_data_list: return
    
    book_ids = list(set([o[0] for o in offsets_data_list]))
    cursor.executemany("DELETE FROM book_offsets WHERE book_id = ?", [(bid,) for bid in book_ids])
    
    cursor.executemany("""
        INSERT INTO book_offsets
        (book_id, page_idx, filename, local_header_offset, compress_size, file_size, compress_type, data_offset)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, offsets_data_list)
    
    from collections import Counter
    counts = Counter([o[0] for o in offsets_data_list])
    cursor.executemany("""
        UPDATE books SET total_pages = ?, has_offsets = 1 WHERE id = ?
    """, [(count, bid) for bid, count in counts.items()])
