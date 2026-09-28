import time
from repositories.book_repository import BookRepository

_GENRE_CACHE = {}
_TAG_CACHE = {}
_CACHE_TTL = 30.0  # 30초 동안 인메모리 초고속 캐싱

class LibraryService:
    @staticmethod
    def get_media_tags(db_type, library_id=None, content_rating_max=None, user_id=None):
        now = time.time()
        cache_key = f"{db_type}:{library_id}:{content_rating_max}"
        if user_id is None and cache_key in _TAG_CACHE:
            ts, val = _TAG_CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                return val

        tags_raw = BookRepository.get_media_tags(db_type, library_id, user_id=user_id, include_rating=True)
        adult_keywords = _get_adult_keywords(db_type, content_rating_max)

        unique_tags = set()
        for r in tags_raw:
            if isinstance(r, dict):
                raw_value = r.get('tags')
                books_lv, genre = r.get('books_lv'), r.get('genre')
            elif isinstance(r, (tuple, list)):
                raw_value = r[0] if r else None
                books_lv = r[1] if len(r) > 1 else None
                genre = r[2] if len(r) > 2 else None
            else:
                raw_value, books_lv, genre = r, None, None
            if raw_value and not _rating_row_visible(db_type, content_rating_max, books_lv, genre, raw_value, adult_keywords):
                continue
            if raw_value:
                for tag in str(raw_value).split(','):
                    clean_tag = tag.strip()
                    if clean_tag:
                        unique_tags.add(clean_tag)

        result = sorted(unique_tags)
        if user_id is None:
            _TAG_CACHE[cache_key] = (now, result)
        return result

    @staticmethod
    def get_media_genres(db_type, library_id=None, content_rating_max=None, user_id=None):
        now = time.time()
        cache_key = f"{db_type}:{library_id}:{content_rating_max}"
        if user_id is None and cache_key in _GENRE_CACHE:
            ts, val = _GENRE_CACHE[cache_key]
            if now - ts < _CACHE_TTL:
                return val

        genres_raw = BookRepository.get_media_genres(db_type, library_id, user_id=user_id, include_rating=True)
        adult_keywords = _get_adult_keywords(db_type, content_rating_max)

        unique_genres = set()
        for r in genres_raw:
            if isinstance(r, dict):
                raw_value = r.get('genre')
                books_lv, tags = r.get('books_lv'), r.get('tags')
            elif isinstance(r, (tuple, list)):
                raw_value = r[0] if r else None
                books_lv = r[1] if len(r) > 1 else None
                tags = r[2] if len(r) > 2 else None
            else:
                raw_value, books_lv, tags = r, None, None
            if raw_value and not _rating_row_visible(db_type, content_rating_max, books_lv, raw_value, tags, adult_keywords):
                continue
            if raw_value:
                for genre in str(raw_value).split(','):
                    clean_genre = genre.strip()
                    if clean_genre:
                        unique_genres.add(clean_genre)

        result = sorted(unique_genres)
        if user_id is None:
            _GENRE_CACHE[cache_key] = (now, result)
        return result


def _get_adult_keywords(db_type, content_rating_max):
    if db_type not in ('general', 'adult') or content_rating_max is None:
        return None
    from services.content_rating_service import ContentRatingService
    return ContentRatingService.get_adult_keywords()


def _rating_row_visible(db_type, content_rating_max, books_lv, genre, tags, adult_keywords=None):
    if db_type not in ('general', 'adult') or content_rating_max is None:
        return True
    try:
        max_level = max(0, min(20, int(content_rating_max)))
    except (TypeError, ValueError):
        max_level = 18
    from services.content_rating_service import ContentRatingService
    return ContentRatingService.compute_effective_level(
        books_lv, genre, tags, adult_keywords
    ) <= max_level
