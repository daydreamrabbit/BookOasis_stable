"""Opt-in member profiles and guestbooks; private notes and reading data stay private."""
import datetime
import uuid
import database
from services.profile_messages import _validate_id
from services.user_profile_service import UserProfileService

PUBLIC_SETTING='PROFILE_GUESTBOOK_ENABLED'


def _enabled(cursor,user_id):
    cursor.execute('SELECT value FROM user_settings WHERE user_id=? AND `key`=?',(user_id,PUBLIC_SETTING))
    row=cursor.fetchone()
    return bool(row and row['value']=='1')


def public_setting(user_id):
    with database.connection('general') as conn:
        return _enabled(conn.cursor(),user_id)


def save_public_setting(user_id,enabled):
    if type(enabled) is not bool:
        raise ValueError('공개 설정을 확인해 주세요.')
    with database.connection('general') as conn:
        cursor=conn.cursor()
        try:
            _target(cursor,user_id,user_id)
            sql='INSERT INTO user_settings(user_id,`key`,value,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) '
            sql+=('ON DUPLICATE KEY UPDATE value=VALUES(value),updated_at=CURRENT_TIMESTAMP' if database.is_mariadb_mode()
                  else 'ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP')
            cursor.execute(sql,(user_id,PUBLIC_SETTING,'1' if enabled else '0'))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return enabled


def _target(cursor,owner_id,viewer_id):
    cursor.execute('SELECT id,username FROM users WHERE id=?',(owner_id,))
    row=cursor.fetchone()
    if not row or (owner_id!=viewer_id and not _enabled(cursor,owner_id)):
        raise LookupError('공개된 프로필을 찾을 수 없습니다.')
    return dict(row)


def member_profile(owner_id,viewer_id):
    with database.connection('general') as conn:
        user=_target(conn.cursor(),owner_id,viewer_id)
    preferences=UserProfileService.get_preferences(owner_id,user['username'])
    avatar_url=preferences['avatar_url']
    if avatar_url:
        avatar_url=f'/api/account/community/profiles/{owner_id}/avatar'+('?' + avatar_url.split('?',1)[1] if '?' in avatar_url else '')
    # Deliberate allow-list: no username, role, permissions, statistics, reading or private posts.
    return dict(id=owner_id,display_name=preferences['display_name'],avatar=preferences['avatar'],
        avatar_url=avatar_url,appearance=preferences['appearance'],is_owner=owner_id==viewer_id)


def member_directory(query='',page=1):
    with database.connection('general') as conn:
        cursor=conn.cursor()
        name="COALESCE(NULLIF(n.value,''),u.username)"
        base=f'''FROM users u JOIN user_settings flag ON flag.user_id=u.id AND flag.`key`=? AND flag.value='1'
            LEFT JOIN user_settings n ON n.user_id=u.id AND n.`key`='PROFILE_DISPLAY_NAME'
            WHERE INSTR(LOWER({name}),LOWER(?))>0'''
        cursor.execute('SELECT COUNT(*) AS count '+base,(PUBLIC_SETTING,query))
        total=int(cursor.fetchone()['count'])
        cursor.execute(f'SELECT u.id,{name} AS display_name '+base+' ORDER BY '+name+',u.id LIMIT ? OFFSET ?',
                       (PUBLIC_SETTING,query,20,(page-1)*20))
        items=[dict(row) for row in cursor.fetchall()]
    return dict(items=items,total=total,page=page,page_size=20)


def _ensure_schema(conn):
    index=',INDEX idx_guestbook_author_time(author_id,created_at)' if database.is_mariadb_mode() else ''
    sql='''CREATE TABLE IF NOT EXISTS profile_guestbook (
        owner_id BIGINT NOT NULL,author_id BIGINT NOT NULL,id CHAR(32) NOT NULL,
        body TEXT NOT NULL,created_at VARCHAR(40) NOT NULL,PRIMARY KEY(owner_id,id),
        FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE,
        FOREIGN KEY(author_id) REFERENCES users(id) ON DELETE CASCADE'''+index+')'
    if database.is_mariadb_mode():
        sql+=' ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_bin'
    conn.cursor().execute(sql)
    if not database.is_mariadb_mode():
        conn.cursor().execute('CREATE INDEX IF NOT EXISTS idx_guestbook_author_time ON profile_guestbook(author_id,created_at)')
    conn.commit()


def guestbook_entries(owner_id,viewer_id,page=1):
    with database.connection('general') as conn:
        cursor=conn.cursor();_target(cursor,owner_id,viewer_id)
        enabled=_enabled(cursor,owner_id)
        _ensure_schema(conn)
        cursor.execute('SELECT COUNT(*) AS count FROM profile_guestbook WHERE owner_id=?',(owner_id,))
        total=int(cursor.fetchone()['count'])
        cursor.execute('''SELECT g.id,g.author_id,g.body,g.created_at,COALESCE(NULLIF(n.value,''),u.username) AS author_name
            FROM profile_guestbook g JOIN users u ON u.id=g.author_id
            LEFT JOIN user_settings n ON n.user_id=u.id AND n.`key`='PROFILE_DISPLAY_NAME'
            WHERE g.owner_id=? ORDER BY g.created_at DESC,g.id DESC LIMIT ? OFFSET ?''',(owner_id,20,(page-1)*20))
        items=[dict(row) for row in cursor.fetchall()]
    for item in items:
        item['can_delete']=viewer_id in (owner_id,item['author_id'])
        # IDs enable own-post attribution/deletion, not access to hidden author profiles.
    return dict(items=items,total=total,page=page,page_size=20,can_post=enabled,is_owner=owner_id==viewer_id)


def create_guest_entry(owner_id,author_id,body,message_id=None):
    if not isinstance(body,str) or not body.strip() or len(body)>2000:
        raise ValueError('메시지는 1~2000자로 입력해 주세요.')
    message_id=_validate_id(message_id if message_id is not None else uuid.uuid4().hex)
    now=datetime.datetime.now(datetime.timezone.utc)
    with database.connection('general') as conn:
        cursor=conn.cursor();_target(cursor,owner_id,author_id)
        if not _enabled(cursor,owner_id):
            raise ValueError('프로필 공개 설정을 먼저 켜 주세요.')
        _ensure_schema(conn)
        try:
            if database.is_mariadb_mode():
                cursor.execute('SELECT id FROM users WHERE id=? FOR UPDATE',(author_id,))
            else:
                cursor.execute('BEGIN IMMEDIATE')
                cursor.execute('SELECT id FROM users WHERE id=?',(author_id,))
            if not cursor.fetchone():raise LookupError('사용자를 찾을 수 없습니다.')
            cursor.execute('SELECT id,author_id,body,created_at FROM profile_guestbook WHERE owner_id=? AND id=?',(owner_id,message_id))
            existing=cursor.fetchone()
            if existing:
                if existing['author_id']!=author_id or existing['body']!=body.strip():
                    raise ValueError('이미 사용된 게시 요청입니다.')
                conn.commit();return dict(existing)
            cursor.execute('SELECT COUNT(*) AS count FROM profile_guestbook WHERE author_id=? AND created_at>=?',
                           (author_id,(now-datetime.timedelta(minutes=1)).isoformat()))
            if int(cursor.fetchone()['count'])>=10:
                raise ValueError('메시지는 1분에 10개까지 남길 수 있습니다. 잠시 후 다시 시도해 주세요.')
            cursor.execute('INSERT INTO profile_guestbook(owner_id,author_id,id,body,created_at) VALUES(?,?,?,?,?)',
                           (owner_id,author_id,message_id,body.strip(),now.isoformat()))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    return dict(id=message_id,author_id=author_id,body=body.strip(),created_at=now.isoformat())


def delete_guest_entry(owner_id,viewer_id,message_id):
    message_id=_validate_id(message_id)
    with database.connection('general') as conn:
        _ensure_schema(conn);cursor=conn.cursor()
        try:
            cursor.execute('DELETE FROM profile_guestbook WHERE owner_id=? AND id=? AND (owner_id=? OR author_id=?)',
                           (owner_id,message_id,viewer_id,viewer_id))
            removed=cursor.rowcount>0;conn.commit()
        except Exception:
            conn.rollback();raise
    return removed
