# -*- coding: utf-8 -*-
"""MariaDB image viewer drawing layer CRUD."""
import database


class ImageDrawingRepository:
    @staticmethod
    def get_book_drawings(db_type, book_id, user_id):
        conn = database.get_connection(db_type)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT page_key, strokes_json, updated_at
                FROM image_drawings
                WHERE book_id = %s AND user_id = %s
                ORDER BY page_key ASC
                """,
                (book_id, user_id),
            )
            return [dict(row) for row in cursor.fetchall()]
        finally:
            conn.close()

    @staticmethod
    def save_page_drawing(db_type, book_id, user_id, page_key, strokes_json):
        conn = database.get_connection(db_type)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO image_drawings
                    (book_id, user_id, page_key, strokes_json)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    strokes_json = VALUES(strokes_json),
                    updated_at = CURRENT_TIMESTAMP
                """,
                (book_id, user_id, page_key, strokes_json),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    @staticmethod
    def delete_page_drawing(db_type, book_id, user_id, page_key):
        conn = database.get_connection(db_type)
        try:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM image_drawings WHERE book_id = %s AND user_id = %s AND page_key = %s",
                (book_id, user_id, page_key),
            )
            conn.commit()
            return cursor.rowcount > 0
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
