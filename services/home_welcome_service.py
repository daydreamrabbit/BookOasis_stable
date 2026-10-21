"""Small user-owned banner preferences and daily reading-log aggregate."""
import datetime
import json
import re
from urllib.parse import urlsplit
import database


def validate_welcome_config(value):
    data = json.loads(value)
    if not isinstance(data, dict):
        raise ValueError('올바른 배너 설정이 아닙니다.')
    for key, limit in (('eyebrow', 80), ('title', 200), ('subtitle', 200)):
        if not isinstance(data.get(key), str) or len(data[key]) > limit:
            raise ValueError('배너 문구 길이를 확인해 주세요.')
    images = data.get('images')
    if not isinstance(images, list) or not 1 <= len(images) <= 6:
        raise ValueError('배경 이미지는 1~6개로 설정해 주세요.')
    for image in images:
        if not isinstance(image, str) or len(image) > 480 or re.search(r'[\s\\]', image):
            raise ValueError('이미지 주소를 확인해 주세요.')
        url = urlsplit(image)
        local = image.startswith('/') and not image.startswith('//')
        if not local and not (url.scheme == 'https' and url.hostname):
            raise ValueError('https:// 또는 /로 시작하는 이미지 주소만 사용할 수 있습니다.')
        if url.username or url.password:
            raise ValueError('인증 정보가 포함된 주소는 사용할 수 없습니다.')
    goal = data.get('goal_minutes', 60)
    quote = data.get('quote', '조금씩이라도 계속 읽는 것이 중요합니다.')
    if isinstance(goal, bool) or not isinstance(goal, int) or not 1 <= goal <= 1440:
        raise ValueError('하루 목표 시간은 1~1440분으로 입력해 주세요.')
    if not isinstance(quote, str) or len(quote) > 160:
        raise ValueError('독서 문구는 160자 이하로 입력해 주세요.')
    normalized = {key: data[key] for key in ('eyebrow', 'title', 'subtitle', 'images')}
    if 'goal_minutes' in data or 'quote' in data:
        normalized.update(goal_minutes=goal, quote=quote)
    return json.dumps(normalized, ensure_ascii=False)


def get_today_reading(db_type, user_id, today=None):
    today = today or datetime.date.today()
    start = today.isoformat()
    end = (today + datetime.timedelta(days=1)).isoformat()
    with database.connection(db_type) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT COALESCE(SUM(l.duration_seconds),0) AS duration_seconds,
            COALESCE(SUM(l.pages_read_delta),0) AS pages, COUNT(DISTINCT l.book_id) AS books
            FROM user_reading_log l JOIN books b ON b.id=l.book_id
            WHERE l.user_id=? AND l.read_date>=? AND l.read_date<? AND COALESCE(b.is_deleted,0)=0
            AND EXISTS (SELECT 1 FROM user_category_permissions p WHERE p.user_id=l.user_id
                AND p.library_id=b.library_id AND p.has_access=1)''', (user_id, start, end))
        row = dict(cursor.fetchone())
    return {key: max(0, int(row[key] or 0)) for key in ('duration_seconds', 'pages', 'books')}


def get_reading_activity(db_type, user_id, year=None):
    today = datetime.date.today()
    year = int(year or today.year)
    if not 2000 <= year <= 2100:
        raise ValueError('조회 연도가 올바르지 않습니다.')
    with database.connection(db_type) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT DATE(l.read_date) AS activity_date,
            COALESCE(SUM(l.duration_seconds),0) AS duration_seconds,
            COALESCE(SUM(l.pages_read_delta),0) AS pages_read,
            COUNT(DISTINCT l.book_id) AS book_count
            FROM user_reading_log l JOIN books b ON b.id=l.book_id
            WHERE l.user_id=? AND l.read_date>=? AND l.read_date<? AND COALESCE(b.is_deleted,0)=0
            AND EXISTS (SELECT 1 FROM user_category_permissions p WHERE p.user_id=l.user_id
                AND p.library_id=b.library_id AND p.has_access=1)
            GROUP BY DATE(l.read_date) ORDER BY activity_date''', (user_id, f'{year}-01-01', f'{year+1}-01-01'))
        daily = [dict(row) for row in cursor.fetchall()]
    return {'year': year, 'today': today.isoformat(), 'daily': [
        {'date': str(row['activity_date'])[:10], **{key: max(0, int(row[key] or 0))
         for key in ('duration_seconds', 'pages_read', 'book_count')}} for row in daily]}
