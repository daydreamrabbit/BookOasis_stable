# -*- coding: utf-8 -*-
"""
book_scan_repository.py – MariaDB 전용 도서(books) 및 오프셋(book_offsets) 백그라운드 스캔 데이터 액세스 레이어
"""
import database

class BookScanRepository:
    @staticmethod
    def get_book_basic_info_raw(db_type, book_id):
        conn = database.get_connection(db_type)
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT b.id, b.library_id, b.title, b.series_name, b.file_path, b.file_format,
                   b.cover_image, COALESCE(l.is_remote, 0) AS library_is_remote
            FROM books b
            LEFT JOIN libraries l ON l.id = b.library_id
            WHERE b.id = %s
            """,
            (book_id,)
        )
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def update_book_scanned_metadata(db_type, book_id, series_name, cover_image, meta, banner_image=None):
        conn = database.get_connection(db_type)
        cursor = conn.cursor()
        try:
            cursor.execute(
                """
                UPDATE books SET 
                    series_name  = COALESCE(NULLIF(%s, ''), series_name),
                    metadata_title = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), metadata_title) ELSE metadata_title END,
                    cover_image  = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND %s IS NOT NULL AND %s != '' THEN %s ELSE cover_image END,
                    cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND %s != '' AND %s IS NOT NULL THEN CURRENT_TIMESTAMP ELSE cover_updated_at END,
                    banner_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND %s IS NOT NULL AND %s != '' THEN %s ELSE banner_image END,
                    banner_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND %s IS NOT NULL AND %s != '' THEN CURRENT_TIMESTAMP ELSE banner_updated_at END,
                    author       = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), author) ELSE author END,
                    isbn         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), isbn) ELSE isbn END,
                    publisher    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), publisher) ELSE publisher END,
                    link         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), link) ELSE link END,
                    score        = CASE WHEN COALESCE(metadata_locked, 0) = 0 AND %s != 0 THEN %s ELSE score END,
                    summary      = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), summary) ELSE summary END,
                    release_date = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), release_date) ELSE release_date END,
                    genre        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), genre) ELSE genre END,
                    tags         = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), tags) ELSE tags END,
                    books_lv     = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), books_lv) ELSE books_lv END,
                    cover_artist = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), cover_artist) ELSE cover_artist END,
                    teams        = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), teams) ELSE teams END,
                    locations    = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), locations) ELSE locations END,
                    characters   = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), characters) ELSE characters END,
                    localized_series = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), localized_series) ELSE localized_series END,
                    document_series_name = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(NULLIF(%s, ''), document_series_name) ELSE document_series_name END,
                    document_volume_index = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(%s, document_volume_index) ELSE document_volume_index END,
                    document_volume_count = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN COALESCE(%s, document_volume_count) ELSE document_volume_count END
                WHERE id = %s
                """,
                (
                    series_name,
                    meta.get('title', ''),
                    cover_image, cover_image, cover_image,
                    cover_image, cover_image,
                    banner_image, banner_image, banner_image,
                    banner_image, banner_image,
                    meta['author'],
                    meta.get('isbn', ''),
                    meta['publisher'],
                    meta['link'],
                    meta['score'], meta['score'],
                    meta['summary'],
                    meta['release_date'],
                    meta.get('genre', ''),
                    meta.get('tags', ''),
                    meta.get('books_lv', ''),
                    meta.get('cover_artist', ''),
                    meta.get('teams', ''),
                    meta.get('locations', ''),
                    meta.get('characters', ''),
                    meta.get('localized_series', ''),
                    meta.get('document_series_name', ''),
                    meta.get('document_volume_index'),
                    meta.get('document_volume_count'),
                    book_id
                )
            )

            cursor.execute("SELECT library_id, series_name FROM books WHERE id = %s", (book_id,))
            row = cursor.fetchone()
            if row and row['series_name'] and cover_image:
                lib_id = row['library_id']
                s_name = row['series_name']
                try:
                    cursor.execute(
                        """
                        UPDATE series SET 
                            cover_image = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN %s ELSE cover_image END,
                            cover_updated_at = CASE WHEN COALESCE(metadata_locked, 0) = 0 THEN CURRENT_TIMESTAMP ELSE cover_updated_at END
                        WHERE name = %s AND library_id = %s
                        """,
                        (cover_image, s_name, lib_id)
                    )
                except Exception:
                    pass

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @staticmethod
    def sync_book_offsets_transaction(db_type, book_id, offsets_data):
        conn = database.get_connection(db_type)
        cursor = conn.cursor()
        try:
            cursor.execute("DELETE FROM book_offsets WHERE book_id = %s", (book_id,))
            bulk_data = [(book_id, *offset) for offset in offsets_data]
            cursor.executemany(
                """
                INSERT INTO book_offsets
                (book_id, page_idx, filename, local_header_offset, compress_size, file_size, compress_type, data_offset)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                bulk_data
            )
            cursor.execute(
                """
                UPDATE books SET total_pages = %s, has_offsets = 1 WHERE id = %s
                """,
                (len(bulk_data), book_id)
            )
            conn.commit()
            return len(bulk_data)
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
