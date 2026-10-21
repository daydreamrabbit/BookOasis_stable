"""Private profile posts in their own table, never mixed into user settings."""
import datetime
import re
import uuid
import database

def _validate_id(message_id):
    if not isinstance(message_id,str) or not re.fullmatch(r'[0-9a-f]{32}',message_id):
        raise ValueError('메시지 식별자가 올바르지 않습니다.')
    return message_id


def _ensure_schema(conn):
    # Additive and independent of library migrations; multiple workers may run it.
    sql='''CREATE TABLE IF NOT EXISTS profile_messages (
        user_id BIGINT NOT NULL,id CHAR(32) NOT NULL,body TEXT NOT NULL,
        created_at VARCHAR(40) NOT NULL,PRIMARY KEY(user_id,id),
        FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE)'''
    if database.is_mariadb_mode():
        sql+=' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin'
    conn.cursor().execute(sql)
    conn.commit()


def list_messages(user_id,page=1):
    with database.connection('general') as conn:
        _ensure_schema(conn)
        cursor=conn.cursor()
        cursor.execute('SELECT COUNT(*) AS count FROM profile_messages WHERE user_id=?',(user_id,))
        total=int(cursor.fetchone()['count'])
        cursor.execute('''SELECT id,body,created_at FROM profile_messages WHERE user_id=?
            ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?''',(user_id,20,(page-1)*20))
        items=[dict(row) for row in cursor.fetchall()]
    return dict(items=items,total=total,page=page,page_size=20)


def create_message(user_id,body,message_id=None):
    if not isinstance(body,str) or not body.strip() or len(body)>2000:
        raise ValueError('메시지는 1~2000자로 입력해 주세요.')
    message_id=_validate_id(message_id if message_id is not None else uuid.uuid4().hex)
    timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat()
    with database.connection('general') as conn:
        _ensure_schema(conn)
        cursor=conn.cursor()
        try:
            sql='''INSERT INTO profile_messages(user_id,id,body,created_at) VALUES(?,?,?,?) '''
            sql+=('ON DUPLICATE KEY UPDATE id=VALUES(id)' if database.is_mariadb_mode()
                  else 'ON CONFLICT(user_id,id) DO NOTHING')
            cursor.execute(sql,(user_id,message_id,body.strip(),timestamp))
            cursor.execute('SELECT id,body,created_at FROM profile_messages WHERE user_id=? AND id=?',(user_id,message_id))
            stored=dict(cursor.fetchone())
            if stored['body']!=body.strip():
                raise ValueError('이미 사용된 요청입니다. 페이지를 새로고침해 주세요.')
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return stored


def delete_message(user_id,message_id):
    message_id=_validate_id(message_id)
    with database.connection('general') as conn:
        _ensure_schema(conn)
        cursor=conn.cursor()
        try:
            cursor.execute('DELETE FROM profile_messages WHERE user_id=? AND id=?',(user_id,message_id))
            removed=cursor.rowcount>0
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return removed
