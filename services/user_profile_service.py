# -*- coding: utf-8 -*-
"""현재 로그인 사용자의 프로필 개인화와 독서 통계 집계."""
from __future__ import annotations

import datetime as _dt
import io
import os
from pathlib import Path
import uuid

from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

import database
from repositories.settings_repository import SettingsRepository
from services.settings_service import SettingsService


PROFILE_AVATARS = {
    'oasis': 'fa-solid fa-book-open',
    'moon': 'fa-solid fa-moon',
    'leaf': 'fa-solid fa-leaf',
    'wave': 'fa-solid fa-water',
    'star': 'fa-solid fa-star',
    'cat': 'fa-solid fa-cat',
    'paw': 'fa-solid fa-paw',
    'spark': 'fa-solid fa-wand-magic-sparkles',
}
DEFAULT_PROFILE_AVATAR = 'oasis'
MAX_DISPLAY_NAME_LENGTH = 40
MAX_PROFILE_AVATAR_BYTES = 5 * 1024 * 1024
MAX_PROFILE_AVATAR_PIXELS = 40_000_000
PROFILE_AVATAR_SIZE = 512
MAX_PROFILE_AVATAR_FRAMES = 300
MAX_PROFILE_AVATAR_ANIMATION_PIXELS = 120_000_000


def _profile_avatar_dir(base_dir=None):
    if base_dir is not None:
        return Path(base_dir)
    configured = os.environ.get('PROFILE_AVATAR_DIR', '').strip()
    return Path(configured) if configured else Path.cwd() / 'covers' / 'profile_avatars'


def get_custom_avatar_path(user_id, base_dir=None):
    avatar_dir = _profile_avatar_dir(base_dir)
    stem = f'user_{int(user_id)}'
    animated = avatar_dir / f'{stem}.gif'
    static = avatar_dir / f'{stem}.webp'
    return animated if animated.is_file() else static


def get_custom_avatar_mimetype(user_id, base_dir=None):
    return 'image/gif' if get_custom_avatar_path(user_id, base_dir).suffix.lower() == '.gif' else 'image/webp'


def custom_avatar_url(user_id, base_dir=None):
    path = get_custom_avatar_path(user_id, base_dir)
    if not path.is_file():
        return ''
    return f'/api/account/profile/avatar?v={path.stat().st_mtime_ns}'


def save_custom_avatar_image(user_id, stream, base_dir=None):
    raw = stream.read(MAX_PROFILE_AVATAR_BYTES + 1)
    if not raw:
        raise ValueError('이미지 파일을 선택해 주세요.')
    if len(raw) > MAX_PROFILE_AVATAR_BYTES:
        raise ValueError('프로필 이미지는 5MB 이하만 사용할 수 있습니다.')

    try:
        with Image.open(io.BytesIO(raw)) as source:
            source.seek(0)
            if source.width * source.height > MAX_PROFILE_AVATAR_PIXELS:
                raise ValueError('프로필 이미지 해상도가 너무 큽니다.')
            is_animated_gif = source.format == 'GIF' and bool(getattr(source, 'is_animated', False))
            frame_count = int(getattr(source, 'n_frames', 1))
            if is_animated_gif:
                if frame_count > MAX_PROFILE_AVATAR_FRAMES:
                    raise ValueError(f'움직이는 GIF는 {MAX_PROFILE_AVATAR_FRAMES}프레임 이하만 사용할 수 있습니다.')
                if source.width * source.height * frame_count > MAX_PROFILE_AVATAR_ANIMATION_PIXELS:
                    raise ValueError('움직이는 GIF의 전체 해상도가 너무 큽니다.')
                frames = []
                durations = []
                for frame in ImageSequence.Iterator(source):
                    frames.append(ImageOps.fit(
                        frame.convert('RGBA'),
                        (PROFILE_AVATAR_SIZE, PROFILE_AVATAR_SIZE),
                        method=Image.Resampling.LANCZOS,
                        centering=(0.5, 0.5),
                    ))
                    durations.append(max(20, int(frame.info.get('duration', source.info.get('duration', 100)) or 100)))
                avatar = frames[0]
                extra_frames = frames[1:]
                animation_loop = int(source.info.get('loop', 0) or 0)
            else:
                normalized = ImageOps.exif_transpose(source)
                normalized.thumbnail((4096, 4096), Image.Resampling.LANCZOS)
                avatar = ImageOps.fit(
                    normalized.convert('RGBA'),
                    (PROFILE_AVATAR_SIZE, PROFILE_AVATAR_SIZE),
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError('지원하지 않거나 손상된 이미지입니다.') from exc

    avatar_dir = _profile_avatar_dir(base_dir)
    suffix = '.gif' if is_animated_gif else '.webp'
    target = avatar_dir / f'user_{int(user_id)}{suffix}'
    stale = avatar_dir / f'user_{int(user_id)}{(".webp" if is_animated_gif else ".gif")}'
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.parent / f'.{target.name}.{uuid.uuid4().hex}.tmp'
    try:
        if is_animated_gif:
            avatar.save(
                temporary,
                format='GIF',
                save_all=True,
                append_images=extra_frames,
                duration=durations,
                loop=animation_loop,
                disposal=2,
            )
        else:
            avatar.save(temporary, format='WEBP', quality=88, method=6)
        os.replace(temporary, target)
        if stale.is_file():
            stale.unlink()
    finally:
        if temporary.exists():
            temporary.unlink()
    return target


def normalize_display_name(value, fallback=''):
    value = ' '.join(str(value or '').strip().split())
    if not value:
        return str(fallback or '').strip()
    return value[:MAX_DISPLAY_NAME_LENGTH]


def normalize_avatar_key(value):
    value = str(value or '').strip().lower()
    return value if value in PROFILE_AVATARS else DEFAULT_PROFILE_AVATAR


class UserProfileService:
    @staticmethod
    def get_preferences(user_id, username):
        raw_avatar = SettingsService.get_user_value(user_id, 'PROFILE_AVATAR', DEFAULT_PROFILE_AVATAR)
        has_custom_avatar = get_custom_avatar_path(user_id).is_file()
        avatar = 'custom' if str(raw_avatar).strip().lower() == 'custom' and has_custom_avatar else normalize_avatar_key(raw_avatar)
        return {
            'display_name': normalize_display_name(
                SettingsService.get_user_value(user_id, 'PROFILE_DISPLAY_NAME', username),
                username,
            ),
            'avatar': avatar,
            'avatar_url': custom_avatar_url(user_id) if avatar == 'custom' else '',
        }

    @staticmethod
    def save_preferences(user_id, username, display_name, avatar):
        display_name = normalize_display_name(display_name, username)
        requested_avatar = str(avatar or '').strip().lower()
        avatar = 'custom' if requested_avatar == 'custom' and get_custom_avatar_path(user_id).is_file() else normalize_avatar_key(requested_avatar)
        # 저장 실패를 성공으로 숨기지 않도록 Repository 예외를 API까지 전달한다.
        SettingsRepository.set_user_value(user_id, 'PROFILE_DISPLAY_NAME', display_name)
        SettingsRepository.set_user_value(user_id, 'PROFILE_AVATAR', avatar)
        return {
            'display_name': display_name,
            'avatar': avatar,
            'avatar_url': custom_avatar_url(user_id) if avatar == 'custom' else '',
        }

    @staticmethod
    def get_statistics(user_id, include_adult=False, year=None):
        year = int(year or _dt.date.today().year)
        db_types = ['general'] + (['adult'] if include_adult else [])
        totals = {
            'completed_books': 0,
            'started_books': 0,
            'pages_read': 0,
            'duration_seconds': 0,
            'authors': set(),
            'active_dates': set(),
        }
        daily = {}
        recent = []

        for db_type in db_types:
            UserProfileService._collect_book_statistics(
                db_type, user_id, year, totals, daily, recent
            )

        recent.sort(key=lambda item: item.get('last_read_at') or '', reverse=True)
        return {
            'year': year,
            'completed_books': totals['completed_books'],
            'started_books': totals['started_books'],
            'pages_read': totals['pages_read'],
            'duration_seconds': totals['duration_seconds'],
            'author_count': len(totals['authors']),
            'active_days': len(totals['active_dates']),
            'daily': [daily[key] for key in sorted(daily)],
            'recent_activity': recent[:16],
        }

    @staticmethod
    def _collect_book_statistics(db_type, user_id, year, totals, daily, recent):
        maria = database.is_mariadb_mode()
        placeholder = '%s' if maria else '?'
        year_expression = "DATE_FORMAT(l.read_date, '%%Y')" if maria else "strftime('%Y', l.read_date)"
        permission_join = (
            'JOIN user_category_permissions ucp '
            'ON ucp.library_id = b.library_id AND ucp.user_id = p.user_id AND ucp.has_access = 1'
        )
        log_permission_join = (
            'JOIN user_category_permissions ucp '
            'ON ucp.library_id = b.library_id AND ucp.user_id = l.user_id AND ucp.has_access = 1'
        )

        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            cursor.execute(f"""
                SELECT
                    COUNT(DISTINCT CASE WHEN COALESCE(p.is_completed, 0) = 1
                        OR COALESCE(p.last_epub_percent, 0) >= 99 THEN p.book_id END) AS completed_books,
                    COUNT(DISTINCT CASE WHEN COALESCE(p.pages_read, 0) > 0
                        OR COALESCE(p.last_epub_percent, 0) > 0
                        OR COALESCE(p.is_completed, 0) = 1 THEN p.book_id END) AS started_books
                FROM user_progress p
                JOIN books b ON b.id = p.book_id
                {permission_join}
                WHERE p.user_id = {placeholder} AND COALESCE(b.is_deleted, 0) = 0
            """, (user_id,))
            row = cursor.fetchone() or {}
            totals['completed_books'] += int(row['completed_books'] or 0)
            totals['started_books'] += int(row['started_books'] or 0)

            cursor.execute(f"""
                SELECT COALESCE(SUM(l.pages_read_delta), 0) AS pages_read,
                       COALESCE(SUM(l.duration_seconds), 0) AS duration_seconds
                FROM user_reading_log l
                JOIN books b ON b.id = l.book_id
                {log_permission_join}
                WHERE l.user_id = {placeholder} AND COALESCE(b.is_deleted, 0) = 0
            """, (user_id,))
            row = cursor.fetchone() or {}
            totals['pages_read'] += int(row['pages_read'] or 0)
            totals['duration_seconds'] += int(row['duration_seconds'] or 0)

            cursor.execute(f"""
                SELECT DATE(l.read_date) AS activity_date,
                       COALESCE(SUM(l.pages_read_delta), 0) AS pages_read,
                       COALESCE(SUM(l.duration_seconds), 0) AS duration_seconds,
                       COUNT(DISTINCT l.book_id) AS book_count
                FROM user_reading_log l
                JOIN books b ON b.id = l.book_id
                {log_permission_join}
                WHERE l.user_id = {placeholder}
                  AND {year_expression} = {placeholder}
                  AND COALESCE(b.is_deleted, 0) = 0
                GROUP BY DATE(l.read_date)
                ORDER BY activity_date
            """, (user_id, str(year)))
            for row in cursor.fetchall():
                date_key = str(row['activity_date'])[:10]
                totals['active_dates'].add(date_key)
                entry = daily.setdefault(date_key, {
                    'date': date_key, 'pages_read': 0, 'duration_seconds': 0, 'book_count': 0,
                })
                entry['pages_read'] += int(row['pages_read'] or 0)
                entry['duration_seconds'] += int(row['duration_seconds'] or 0)
                entry['book_count'] += int(row['book_count'] or 0)

            cursor.execute(f"""
                SELECT DISTINCT b.author
                FROM user_progress p
                JOIN books b ON b.id = p.book_id
                {permission_join}
                WHERE p.user_id = {placeholder}
                  AND COALESCE(b.is_deleted, 0) = 0
                  AND b.author IS NOT NULL AND TRIM(b.author) <> ''
                  AND (COALESCE(p.pages_read, 0) > 0 OR COALESCE(p.last_epub_percent, 0) > 0
                       OR COALESCE(p.is_completed, 0) = 1)
            """, (user_id,))
            for row in cursor.fetchall():
                for author in str(row['author'] or '').replace(';', ',').split(','):
                    author = author.strip()
                    if author:
                        totals['authors'].add(author.casefold())

            cursor.execute(f"""
                SELECT b.id, b.title, b.series_name, b.cover_image, b.file_format,
                       p.pages_read, b.total_pages, p.is_completed, p.last_epub_percent,
                       p.last_read_at
                FROM user_progress p
                JOIN books b ON b.id = p.book_id
                {permission_join}
                WHERE p.user_id = {placeholder} AND COALESCE(b.is_deleted, 0) = 0
                  AND (COALESCE(p.pages_read, 0) > 0 OR COALESCE(p.last_epub_percent, 0) > 0
                       OR COALESCE(p.is_completed, 0) = 1)
                ORDER BY p.last_read_at DESC
                LIMIT 16
            """, (user_id,))
            for row in cursor.fetchall():
                item = dict(row)
                item['db_type'] = db_type
                item['last_read_at'] = str(item.get('last_read_at') or '')
                recent.append(item)
