# -*- coding: utf-8 -*-
"""
content_rating_service.py – 도서 콘텐츠 등급(books_lv) 및 성인 장르/태그 기반 열람 권한 판정

books_lv 컬럼(국내외 등급 표기 혼재: everyone/ma15+/m/r18/adult only/일반/15세/18세,
+ ComicInfo.xml/Kavita YAML 표준 AgeRating 어휘)을 3단계(전체이용가/15세이상/18세이상)로
정규화하고, 관리자가 설정한 "성인 장르/태그 키워드" 목록과 책의 genre/tags 텍스트를
대조해 실질 등급을 산출한다.

ComicInfo.xml AgeRating 표준값도 인식하도록 매핑을 넓혀뒀다 - core 스캐너 파서가
AgeRating을 books_lv로 채워 넣을 때 별도 수정 없이 바로 동작하게 하기 위함(2026-09-15,
tools/scanner/metadata/kavita_yaml.py가 최초로 연결됨 - 이 값은 Kavita YAML의 "Age
Rating" 숫자 코드를 자체 매핑 테이블로 이 어휘로 변환해서 채운다. comicinfo_xml.py/
series_json.py는 아직 미연결, 커뮤니티 협의 진행 중). 이 어휘 매핑이 없으면 "Teen"/
"PG" 같은 미인식 값이 안전 기본값(18)으로 떨어져 전체이용가 도서까지 성인 취급되는
역효과가 난다.
"""
from services.settings_service import SettingsService

LEVEL_EVERYONE = 0
LEVEL_15 = 15
LEVEL_18 = 18

_BOOKS_LV_LEVEL_MAP = {
    # 자체 표기 (관리자 편집 UI 드롭다운에서 사용하는 값)
    'everyone': LEVEL_EVERYONE,
    '일반': LEVEL_EVERYONE,
    'ma15+': LEVEL_15,
    'm': LEVEL_15,
    '15세': LEVEL_15,
    'r18': LEVEL_18,
    'adult only': LEVEL_18,
    '18세': LEVEL_18,

    # ComicInfo.xml / Kavita YAML 표준 AgeRating 어휘 (대소문자 무시하고 매칭됨)
    'early childhood': LEVEL_EVERYONE,
    'everyone 10+': LEVEL_EVERYONE,
    'g': LEVEL_EVERYONE,
    'kids to adults': LEVEL_EVERYONE,
    'pg': LEVEL_EVERYONE,
    'teen': LEVEL_15,
    'mature 15+': LEVEL_15,
    'mature 17+': LEVEL_18,
    'adults only 18+': LEVEL_18,
    'r18+': LEVEL_18,
    'x18+': LEVEL_18,
    # 'unknown'과 'rating pending'은 의도적으로 미포함 - 실제로 등급을 알 수 없다는
    # 뜻이므로, 다른 미인식 값과 마찬가지로 안전 기본값(18)으로 떨어지게 둔다.
}

# 관리자 편집 UI/서버 검증에서 재사용하는 books_lv 허용값 (원본 표기 그대로).
# ComicInfo 표준 어휘는 파서가 직접 써넣는 값이라 관리자 드롭다운에는 노출하지 않는다 -
# 정규화 매핑에는 포함돼 있어 파서가 연결되면 검증 없이도 바로 인식된다.
ALLOWED_BOOKS_LV_VALUES = ('everyone', 'ma15+', 'm', 'r18', 'adult only', '일반', '15세', '18세')


class ContentRatingService:
    @staticmethod
    def normalize_books_lv(books_lv):
        """books_lv 원문 값을 3단계(0/15/18) 등급으로 정규화.
        비어있으면(NULL) everyone(0), 인식할 수 없는 값은 안전을 위해 최고 등급(18)으로 취급."""
        if not books_lv:
            return LEVEL_EVERYONE
        key = str(books_lv).strip().lower()
        if key in _BOOKS_LV_LEVEL_MAP:
            return _BOOKS_LV_LEVEL_MAP[key]
        return LEVEL_18

    @staticmethod
    def get_adult_keywords():
        """관리자가 설정한 "성인 장르/태그 키워드" 목록 (콤마 구분, 소문자 정규화)"""
        raw = SettingsService.get('ADULT_GENRE_TAG_KEYWORDS', '')
        return [kw.strip().lower() for kw in raw.split(',') if kw.strip()]

    @staticmethod
    def genre_tag_matches_adult(genre, tags):
        keywords = ContentRatingService.get_adult_keywords()
        if not keywords:
            return False
        combined = f"{genre or ''} {tags or ''}".lower()
        return any(kw in combined for kw in keywords)

    @staticmethod
    def compute_effective_level(books_lv, genre, tags):
        """books_lv와 성인 장르/태그 키워드 매치 결과 중 더 높은 등급을 최종 등급으로 채택"""
        level = ContentRatingService.normalize_books_lv(books_lv)
        if ContentRatingService.genre_tag_matches_adult(genre, tags):
            level = max(level, LEVEL_18)
        return level

    @staticmethod
    def can_view_book(db_type, book_id, user_max_level):
        """단일 도서 열람 가능 여부 판정. 도서가 존재하지 않으면 이후 로직(404)에서
        처리하도록 True를 반환한다."""
        try:
            book_id = int(book_id)
        except (TypeError, ValueError):
            return True

        from repositories.book_repository import BookRepository
        row = BookRepository.get_book_rating_info(db_type, book_id)
        if not row:
            return True
        effective_level = ContentRatingService.compute_effective_level(
            row.get('books_lv'), row.get('genre'), row.get('tags')
        )
        try:
            max_level = int(user_max_level)
        except (TypeError, ValueError):
            max_level = LEVEL_18
        return max_level >= effective_level
