# -*- coding: utf-8 -*-
"""
mcp_pending_changes_repository.py – MariaDB 전용 MCP Tier B(대량/파괴적 작업) 제안 큐 데이터
액세스 레이어. settings 테이블과 동일하게 general DB 커넥션 하나만 사용한다.
"""
import database


class McpPendingChangesRepository:
    @staticmethod
    def create(tool_name, db_type, target, payload_json, preview_json):
        conn = database.get_connection('general')
        cursor = conn.cursor()
        try:
            cursor.execute("""
                INSERT INTO mcp_pending_changes (tool_name, db_type, target, payload, preview, status)
                VALUES (%s, %s, %s, %s, %s, 'pending')
            """, (tool_name, db_type, target, payload_json, preview_json))
            conn.commit()
            return cursor.lastrowid
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    @staticmethod
    def list(status=None):
        conn = database.get_connection('general')
        cursor = conn.cursor()
        if status:
            cursor.execute("SELECT * FROM mcp_pending_changes WHERE status = %s ORDER BY id DESC", (status,))
        else:
            cursor.execute("SELECT * FROM mcp_pending_changes ORDER BY id DESC")
        rows = cursor.fetchall()
        conn.close()
        return [dict(row) for row in rows]

    @staticmethod
    def get(change_id):
        conn = database.get_connection('general')
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM mcp_pending_changes WHERE id = %s", (change_id,))
        row = cursor.fetchone()
        conn.close()
        return dict(row) if row else None

    @staticmethod
    def update_status(change_id, status, decided_by, decision_note=None):
        conn = database.get_connection('general')
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE mcp_pending_changes
                SET status = %s, decided_at = CURRENT_TIMESTAMP, decided_by = %s, decision_note = %s
                WHERE id = %s
            """, (status, decided_by, decision_note, change_id))
            conn.commit()
            return cursor.rowcount > 0
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
