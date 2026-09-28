# -*- coding: utf-8 -*-
"""시리즈 DB 데이터와 BookOasis 생성 이미지만 안전하게 삭제한다."""
import os

from repositories.series_delete_repository import SeriesDeleteRepository
from services.cover_storage_service import get_covers_dir
from services.series_service import SeriesService
from utils.redis_helper import (
    redis_acquire_lock,
    redis_delete_pattern,
    redis_release_lock,
)


class SeriesDeleteService:
    SUPPORTED_DB_TYPES = ('general', 'adult')

    @classmethod
    def delete_series_batch(cls, db_type, targets):
        if db_type not in cls.SUPPORTED_DB_TYPES:
            raise ValueError('일반 도서 또는 성인 도서 시리즈만 삭제할 수 있습니다.')
        if not isinstance(targets, list) or not 1 <= len(targets) <= 100:
            raise ValueError('한 번에 1~100개 시리즈를 선택해 주세요.')
        normalized = []
        for target in targets:
            if not isinstance(target, dict) or any(
                type(target.get(key)) is not int or target[key] <= 0
                for key in ('book_id', 'library_id')
            ):
                raise ValueError('올바른 도서 및 라이브러리 ID가 필요합니다.')
            normalized.append({'book_id': target['book_id'], 'library_id': target['library_id']})
        lock_key = f'lock:db_write:{db_type}'
        token = redis_acquire_lock(lock_key, ttl=120, wait_timeout=10.0)
        if not token:
            raise RuntimeError('다른 데이터베이스 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.')
        try:
            result = SeriesDeleteRepository.delete_series_batch(db_type, normalized)
            deleted, warnings = cls._delete_generated_media(result.pop('unreferenced_media', []))
        finally:
            redis_release_lock(lock_key, token)
        if any(item['success'] for item in result['results']):
            SeriesService.invalidate_all_books_cache(db_type=db_type)
            for pattern in (f'cache:history*:{db_type}:*', f'cache:recent_added*:{db_type}:*',
                            f'cache:recommendations*:{db_type}:*'):
                redis_delete_pattern(pattern)
        result.update(deleted_media_count=len(deleted), warnings=warnings)
        return result

    @staticmethod
    def _delete_generated_media(media_paths):
        covers_root = os.path.realpath(get_covers_dir())
        deleted = []
        warnings = []

        try:
            from services.generated_media_service import reference_snapshot, normalized_reference
            references, _ = reference_snapshot()
        except Exception as exc:
            return [], [f'이미지 참조 확인 실패로 파일 정리를 보류했습니다: {exc}']

        for media_path in media_paths or []:
            if normalized_reference(media_path) in references:
                continue
            raw_path = str(media_path or '').strip().replace('\\', '/')
            clean_path = raw_path.lstrip('/')
            if clean_path.startswith('covers/'):
                clean_path = clean_path[len('covers/'):]
            if not clean_path:
                continue

            candidate = os.path.realpath(os.path.join(covers_root, clean_path.replace('/', os.sep)))
            try:
                if os.path.commonpath((covers_root, candidate)) != covers_root:
                    warnings.append(f'커버 저장 경로 밖의 파일은 삭제하지 않았습니다: {raw_path}')
                    continue
            except ValueError:
                warnings.append(f'잘못된 이미지 경로는 삭제하지 않았습니다: {raw_path}')
                continue

            try:
                if os.path.isfile(candidate):
                    os.remove(candidate)
                    deleted.append(raw_path)
                    parent = os.path.dirname(candidate)
                    while parent != covers_root and os.path.commonpath((covers_root, parent)) == covers_root:
                        try:
                            os.rmdir(parent)
                        except OSError:
                            break
                        parent = os.path.dirname(parent)
            except OSError as exc:
                warnings.append(f'이미지 파일 삭제 실패 ({raw_path}): {exc}')

        return deleted, warnings

    @classmethod
    def delete_series_data(cls, db_type, book_id, library_id=None):
        db_type = str(db_type or '').strip().lower()
        if db_type not in cls.SUPPORTED_DB_TYPES:
            raise ValueError('일반 도서 또는 성인 도서 시리즈만 삭제할 수 있습니다.')

        lock_key = f'lock:db_write:{db_type}'
        lock_token = redis_acquire_lock(lock_key, ttl=120, wait_timeout=10.0)
        if not lock_token:
            raise RuntimeError('다른 데이터베이스 작업이 진행 중입니다. 잠시 후 다시 시도해 주세요.')

        try:
            result = SeriesDeleteRepository.delete_series_by_anchor(
                db_type,
                int(book_id),
                int(library_id) if library_id is not None else None,
            )
        finally:
            redis_release_lock(lock_key, lock_token)

        if not result:
            return None

        deleted_media, warnings = cls._delete_generated_media(result.get('unreferenced_media'))
        SeriesService.invalidate_all_books_cache(db_type=db_type)
        for pattern in (
            f'cache:history*:{db_type}:*',
            f'cache:recent_added*:{db_type}:*',
            f'cache:recommendations*:{db_type}:*',
        ):
            redis_delete_pattern(pattern)

        return {
            **result,
            'deleted_media_count': len(deleted_media),
            'warnings': warnings,
        }
