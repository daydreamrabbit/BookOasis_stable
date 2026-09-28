# -*- coding: utf-8 -*-
import hashlib
import html
import io
import json
import os
import re
import shutil
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from PIL import Image
from plugins.metadata.base import BaseMetadataProvider


PLUGIN_VERSION = "1.6.4"
LEGACY_PLUGIN_ID = "naverkakaoridi_meta"
DEFAULT_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"
DETAIL_WORKERS = 4
NOVELPIA_FAILURE_COOLDOWN = 300
RATING_SCALES = {
    "네이버웹툰": 10,
    "네이버시리즈": 10,
    "카카오웹툰": 10,
    "카카오페이지": 10,
    "리디": 5,
}


class NaverkakaoridiMetadataProvider(BaseMetadataProvider):
    id = "naverkakaoridi"
    name = "네카리 웹북 검색"
    version = PLUGIN_VERSION
    is_searchable = True
    config_schema = [
        {
            "key": "SOURCES",
            "label": "세부 검색 사이트(고급)",
            "type": "text",
            "required": False,
            "default": "all",
            "description": "기본값 all. 사용 가능: all, naver_webtoon, naver_series, kakao_webtoon, kakaopage, ridibooks, novelpia, munpia. 여러 개는 콤마로 구분.",
        },
        {
            "key": "SEARCH_NAVER",
            "label": "네이버 검색",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "네이버웹툰과 네이버시리즈를 검색합니다.",
        },
        {
            "key": "SEARCH_KAKAO",
            "label": "카카오 검색",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "카카오웹툰과 카카오페이지를 검색합니다.",
        },
        {
            "key": "SEARCH_RIDI",
            "label": "리디 검색",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "리디를 검색합니다.",
        },
        {
            "key": "SEARCH_NOVELPIA",
            "label": "노벨피아 검색",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "노벨피아를 검색합니다.",
        },
        {
            "key": "SEARCH_MUNPIA",
            "label": "문피아 검색",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "문피아를 검색합니다.",
        },
        {
            "key": "MAX_RESULTS",
            "label": "최대 검색 결과",
            "type": "number",
            "required": False,
            "default": 20,
            "description": "기본값 20. 전체 사이트 결과를 합쳐 반환할 최대 개수.",
        },
        {
            "key": "TIMEOUT",
            "label": "요청 제한 시간",
            "type": "number",
            "required": False,
            "default": 10,
            "description": "기본값 10초. 외부 사이트 응답 대기 시간.",
        },
        {
            "key": "USER_AGENT",
            "label": "User-Agent",
            "type": "text",
            "required": False,
            "default": DEFAULT_USER_AGENT,
            "description": "기본 브라우저 User-Agent. 차단 회피가 필요할 때만 변경.",
        },
        {
            "key": "PROXY_URL",
            "label": "HTTP(S) 프록시 URL",
            "type": "password",
            "required": False,
            "default": "",
            "description": "선택 사항. http://host:port 또는 http://user:password@host:port 형식. 검색과 표지 다운로드에 함께 적용됩니다.",
        },
        {
            "key": "NOVELPIA_TIMEOUT",
            "label": "노벨피아 제한 시간(초)",
            "type": "number",
            "required": False,
            "default": 3,
            "description": "기본값 3초. 시간 초과 시 5분 동안 노벨피아 요청만 건너뜁니다.",
        },
        {
            "key": "SEARCH_EXACT",
            "label": "정확한 제목만",
            "type": "checkbox",
            "required": False,
            "default": False,
            "description": "사용하면 검색어와 제목이 거의 같은 결과만 표시합니다.",
        },
        {
            "key": "INCLUDE_ADULT",
            "label": "성인 결과 포함",
            "type": "checkbox",
            "required": False,
            "default": False,
            "description": "사용하면 19세/성인 플래그가 있는 결과도 포함합니다.",
        },
        {
            "key": "APPLY_COVER_TO_SERIES",
            "label": "같은 시리즈 전체에 표지 적용",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "사용하면 메타데이터 적용 시 같은 보관함·시리즈의 모든 권/화에 선택한 표지를 적용합니다.",
        },
        {
            "key": "APPLY_RATING_TO_SERIES",
            "label": "같은 시리즈 전체에 평점 적용",
            "type": "checkbox",
            "required": False,
            "default": True,
            "description": "사용하면 같은 보관함·시리즈의 모든 권/화에 평점과 평점 출처를 적용합니다.",
        },
        {
            "key": "NAVER_COOKIE",
            "label": "네이버 Cookie",
            "type": "password",
            "required": False,
            "default": "",
            "description": "기본값 공백. 연령 제한/로그인 필요 작품 검색이 필요할 때만 입력.",
        },
        {
            "key": "KAKAO_COOKIE",
            "label": "카카오 Cookie",
            "type": "password",
            "required": False,
            "default": "",
            "description": "기본값 공백. 연령 제한/로그인 필요 작품 검색이 필요할 때만 입력.",
        },
        {
            "key": "RIDI_COOKIE",
            "label": "리디 Cookie",
            "type": "password",
            "required": False,
            "default": "",
            "description": "기본값 공백. 연령 제한/로그인 필요 작품 검색이 필요할 때만 입력.",
        },
        {
            "key": "MUNPIA_COOKIE",
            "label": "문피아 Cookie",
            "type": "password",
            "required": False,
            "default": "",
            "description": "기본값 공백. 연령 제한/로그인 필요 작품 검색이 필요할 때만 입력.",
        },
        {
            "key": "KAKAOPAGE_CATEGORY",
            "label": "카카오페이지 카테고리",
            "type": "text",
            "required": False,
            "default": "all",
            "description": "기본값 all. comic=10, novel=11, book=16 또는 숫자 category_uid 입력 가능.",
        },
    ]
    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/javara999/naverkakaoridi/main",
        "files": ["naverkakaoridi.py", "settings.html", "settings.css", "__init__.py", "README.md", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    SOURCE_ORDER = ("naver_webtoon", "naver_series", "kakao_webtoon", "kakaopage", "ridibooks", "novelpia", "munpia")
    SOURCE_TOGGLES = {
        "naver_webtoon": "SEARCH_NAVER",
        "naver_series": "SEARCH_NAVER",
        "kakao_webtoon": "SEARCH_KAKAO",
        "kakaopage": "SEARCH_KAKAO",
        "ridibooks": "SEARCH_RIDI",
        "novelpia": "SEARCH_NOVELPIA",
        "munpia": "SEARCH_MUNPIA",
    }
    _cache = {}
    _cache_lock = threading.Lock()
    _source_cooldowns = {}

    def search(self, db_type, query):
        query = (query or "").strip()
        if not query:
            return []

        cfg = self._get_config(db_type)
        max_results = self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)
        sources = {
            source
            for source in self._sources(cfg.get("SOURCES"))
            if self._truthy(cfg.get(self.SOURCE_TOGGLES[source], True))
        }

        results = []
        for source in self.SOURCE_ORDER:
            if source not in sources:
                continue
            try:
                if source == "naver_webtoon":
                    results.extend(self._search_naver_webtoon(query, cfg))
                elif source == "naver_series":
                    results.extend(self._search_naver_series(query, cfg))
                elif source == "kakao_webtoon":
                    results.extend(self._search_kakao_webtoon(query, cfg))
                elif source == "kakaopage":
                    results.extend(self._search_kakaopage(query, cfg))
                elif source == "ridibooks":
                    results.extend(self._search_ridibooks(query, cfg))
                elif source == "novelpia":
                    results.extend(self._search_novelpia(query, cfg))
                elif source == "munpia":
                    results.extend(self._search_munpia(query, cfg))
            except Exception as e:
                print(f"[NaverkakaoridiMetadataProvider] {source} search failed: {e}")
            if len(results) >= max_results:
                break

        results = [r for r in results if (r.get("cover") or "").strip()]
        results = self._dedupe(results)
        nq = self._normalize(query)
        if self._truthy(cfg.get("SEARCH_EXACT")):
            results = [r for r in results if self._normalize(r.get("title")) == nq]
        else:
            results = [r for r in results if self._is_relevant(nq, r.get("title"))]
        return [self._with_source_prefix(item) for item in results[:max_results]]

    def _is_relevant(self, normalized_query, title):
        if not normalized_query:
            return True
        nt = self._normalize(title)
        if not nt:
            return False
        if normalized_query in nt or nt in normalized_query:
            return True
        return False

    def _matches_candidate_title(self, normalized_query, title, cfg):
        if not title:
            return True
        if self._truthy(cfg.get("SEARCH_EXACT")):
            return self._normalize(title) == normalized_query
        return self._is_relevant(normalized_query, title)

    def _parallel_map(self, func, values):
        values = list(values)
        if not values:
            return []

        def safe_call(value):
            try:
                return func(value) or {}
            except Exception as e:
                print(f"[NaverkakaoridiMetadataProvider] detail request failed: {e}")
                return {}

        if len(values) == 1:
            return [safe_call(values[0])]
        with ThreadPoolExecutor(max_workers=min(DETAIL_WORKERS, len(values))) as executor:
            return list(executor.map(safe_call, values))

    def apply(self, db_type, book_id, item_data):
        item_data = self._restore_original_title(item_data)
        gateway = self.get_db_gateway(db_type)
        try:
            book = gateway.fetch_one(
                """
                SELECT id, file_path, library_id, series_name
                FROM books
                WHERE id = ? AND COALESCE(is_deleted, 0) = 0
                """,
                (book_id,),
            )
            if not book:
                return False, "대상 도서를 찾을 수 없습니다."

            cfg = self._get_config(db_type)
            cover_filename = self._save_cover(book, item_data.get("cover"), cfg)
            description = self._clean_text(item_data.get("description"))
            author = self._clean_text(item_data.get("author"))
            publisher = self._clean_text(item_data.get("publisher"))
            isbn = self._clean_text(
                item_data.get("isbn") or item_data.get("isbn13") or item_data.get("isbn_13")
            )
            release_date = self._clean_text(item_data.get("pubDate") or item_data.get("release_date"))
            link = item_data.get("link") or ""
            genre = self._clean_text(item_data.get("genre"))
            tags = self._clean_text(item_data.get("tags"))
            score = self._optional_score(item_data.get("score"))
            rating_label = self._clean_text(item_data.get("rating_label"))

            raw_series_name = book["series_name"] or ""
            series_cover_enabled = bool(
                cover_filename
                and self._clean_text(raw_series_name)
                and book["library_id"] is not None
                and self._truthy(cfg.get("APPLY_COVER_TO_SERIES"))
            )
            series_cover_updates = []
            series_cover_failures = 0
            if series_cover_enabled:
                series_cover_updates, series_cover_failures = self._prepare_series_cover_files(
                    gateway,
                    book,
                    raw_series_name,
                )

            series_rating_enabled = bool(
                score is not None
                and rating_label
                and self._clean_text(raw_series_name)
                and book["library_id"] is not None
                and self._truthy(cfg.get("APPLY_RATING_TO_SERIES", True))
            )
            series_rating_updates = []
            if series_rating_enabled:
                series_books = gateway.fetch_all(
                    """
                    SELECT id, summary
                    FROM books
                    WHERE library_id = ?
                      AND series_name = ?
                      AND id <> ?
                      AND COALESCE(is_deleted, 0) = 0
                    """,
                    (book["library_id"], raw_series_name, book_id),
                )
                series_rating_updates = [
                    (
                        score,
                        self._with_rating_label(series_book["summary"] or "", rating_label),
                        series_book["id"],
                        book["library_id"],
                        raw_series_name,
                    )
                    for series_book in series_books
                ]

            series_cover_count = 0
            count = gateway.execute(
                """
                UPDATE books
                SET author = ?,
                    isbn = COALESCE(?, isbn),
                    publisher = ?,
                    summary = ?,
                    link = ?,
                    release_date = COALESCE(?, release_date),
                    genre = COALESCE(?, genre),
                    tags = COALESCE(?, tags),
                    score = COALESCE(?, score),
                    cover_image = COALESCE(?, cover_image),
                    cover_updated_at = CASE
                        WHEN ? IS NOT NULL THEN CURRENT_TIMESTAMP
                        ELSE cover_updated_at
                    END,
                    metadata_locked = 1
                WHERE id = ? AND COALESCE(is_deleted, 0) = 0
                """,
                (
                    author,
                    isbn or None,
                    publisher,
                    description,
                    link,
                    release_date or None,
                    genre or None,
                    tags or None,
                    score,
                    cover_filename or None,
                    cover_filename or None,
                    book_id,
                ),
            )
            if count == 0:
                existing = gateway.fetch_one(
                    "SELECT id FROM books WHERE id = ? AND COALESCE(is_deleted, 0) = 0",
                    (book_id,),
                )
                count = 1 if existing else 0
            if count != 1:
                raise RuntimeError("대상 도서가 삭제되었거나 변경되어 메타데이터를 적용하지 못했습니다.")

            if series_cover_updates:
                gateway.execute_many(
                    """
                    UPDATE books
                    SET cover_image = ?,
                        cover_updated_at = CURRENT_TIMESTAMP
                    WHERE id = ?
                      AND library_id = ?
                      AND series_name = ?
                      AND COALESCE(is_deleted, 0) = 0
                    """,
                    series_cover_updates,
                )
                series_cover_count = len(series_cover_updates)

            if series_rating_updates:
                gateway.execute_many(
                    """
                    UPDATE books
                    SET score = ?, summary = ?, metadata_locked = 1
                    WHERE id = ?
                      AND library_id = ?
                      AND series_name = ?
                      AND COALESCE(is_deleted, 0) = 0
                    """,
                    series_rating_updates,
                )

            title = item_data.get("title") or book_id
            message = f'"{title}" 메타데이터를 {count}개 항목에 반영했습니다.'
            if series_cover_enabled:
                message += f" 표지는 같은 시리즈 {series_cover_count + 1}권/화에 적용했습니다."
                if series_cover_failures:
                    message += f" {series_cover_failures}권/화의 표지 파일 복사에는 실패했습니다."
            if series_rating_enabled:
                message += f" 평점은 같은 시리즈 {len(series_rating_updates) + 1}권/화에 적용했습니다."
            return True, message
        except Exception as e:
            return False, f"DB 업데이트 오류: {e}"

    def _search_naver_webtoon(self, query, cfg):
        url = "https://comic.naver.com/api/search/all?" + urllib.parse.urlencode({"keyword": query})
        data = self._get_json(url, cfg, headers=self._naver_headers(cfg, "https://comic.naver.com/"))
        groups = (
            "searchWebtoonResult",
            "searchBestChallengeResult",
            "searchChallengeResult",
            "searchNbooksComicResult",
        )
        max_results = self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)
        normalized_query = self._normalize(query)
        candidates = []
        seen_ids = set()
        for group in groups:
            for item in self._as_list(data.get(group)):
                title_id = item.get("titleId") or item.get("contentId") or item.get("id")
                title = self._clean_text(item.get("titleName") or item.get("title") or item.get("name"))
                if not title or not title_id:
                    continue
                if self._is_adult(item) and not self._truthy(cfg.get("INCLUDE_ADULT")):
                    continue
                if not self._matches_candidate_title(normalized_query, title, cfg):
                    continue
                title_key = str(title_id)
                if title_key in seen_ids:
                    continue
                seen_ids.add(title_key)
                candidates.append((item, title_id, title))
                if len(candidates) >= max_results:
                    break
            if len(candidates) >= max_results:
                break

        details = self._parallel_map(
            lambda candidate: self._naver_webtoon_detail(candidate[1], cfg),
            candidates,
        )
        results = []
        for (item, title_id, title), detail in zip(candidates, details):
            authors = detail.get("communityArtists") or item.get("communityArtists") or []
            genre_list = detail.get("genreList") or item.get("genreList") or []
            tags = detail.get("curationTagList") or item.get("curationTagList") or []
            results.append(
                self._item(
                    source="네이버웹툰",
                    title=detail.get("titleName") or title,
                    author=self._join_names(authors),
                    publisher="네이버웹툰",
                    cover=detail.get("thumbnailUrl") or item.get("thumbnailUrl"),
                    description=detail.get("synopsis") or item.get("synopsis") or "",
                    link=f"https://comic.naver.com/webtoon/list?titleId={title_id}",
                    genre=self._join_names(genre_list),
                    tags=self._join_names(tags),
                    pub_date="",
                    score=str(detail.get("starScore") or ""),
                )
            )
        return results

    def _naver_webtoon_detail(self, title_id, cfg):
        url = "https://comic.naver.com/api/article/list/info?" + urllib.parse.urlencode({"titleId": title_id})
        detail = {}
        try:
            detail = self._get_json(url, cfg, headers=self._naver_headers(cfg, "https://comic.naver.com/"))
        except Exception:
            pass

        try:
            mobile_url = "https://m.comic.naver.com/webtoon/list?" + urllib.parse.urlencode({"titleId": title_id})
            text = self._get_text(mobile_url, cfg, headers=self._naver_headers(cfg, "https://m.comic.naver.com/"))
            match = re.search(
                r'<span[^>]*class=["\'][^"\']*ico_score[^"\']*["\'][^>]*>.*?'
                r'<span[^>]*class=["\'][^"\']*score[^"\']*["\'][^>]*>\s*([\d.]+)\s*</span>',
                text,
                re.I | re.S,
            )
            if match:
                detail["starScore"] = match.group(1)
        except Exception as e:
            print(f"[NaverkakaoridiMetadataProvider] Naver Webtoon rating fetch failed: {e}")
        return detail

    def _search_naver_series(self, query, cfg):
        params = urllib.parse.urlencode({"t": "all", "fs": "comic", "q": query})
        search_url = f"https://series.naver.com/search/search.series?{params}"
        text = self._get_text(search_url, cfg, headers=self._naver_headers(cfg, "https://series.naver.com/"))
        product_nos = []
        for m in re.finditer(r"/comic/detail\.series\?productNo=(\d+)", text):
            if m.group(1) not in product_nos:
                product_nos.append(m.group(1))

        results = []
        product_nos = product_nos[: self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)]
        details = self._parallel_map(
            lambda product_no: self._naver_series_detail(product_no, cfg),
            product_nos,
        )
        for item in details:
            if item:
                results.append(item)
        return results

    def _naver_series_detail(self, product_no, cfg):
        url = f"https://series.naver.com/comic/detail.series?productNo={product_no}"
        text = self._get_text(url, cfg, headers=self._naver_headers(cfg, "https://series.naver.com/"))
        meta = self._meta_tags(text)
        title = self._clean_text(meta.get("og:title") or "")
        desc = self._clean_text(meta.get("og:description") or "")
        if not title:
            return None

        author = ""
        m = re.search(r"(?:글|그림|작가)\s*[:：]\s*([^,\n]+)", desc)
        if m:
            author = self._clean_text(m.group(1))
        tags = ", ".join(re.findall(r"#([^\s#]+)", desc))
        score_match = re.search(
            r'<div[^>]*class=["\'][^"\']*score_area[^"\']*["\'][^>]*>.*?'
            r'<em[^>]*>\s*([\d.]+)\s*</em>',
            text,
            re.I | re.S,
        )
        return self._item(
            source="네이버시리즈",
            title=title,
            author=author,
            publisher="네이버시리즈",
            cover=meta.get("og:image") or "",
            description=desc,
            link=url,
            genre="",
            tags=tags,
            pub_date="",
            score=score_match.group(1) if score_match else "",
        )

    def _search_kakao_webtoon(self, query, cfg):
        params = urllib.parse.urlencode({"word": query, "offset": 0, "limit": self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)})
        url = f"https://gateway-kw.kakao.com/search/v2/content?{params}"
        data = self._get_json(url, cfg, headers=self._kakao_webtoon_headers(cfg, query))
        contents = ((data.get("data") or {}).get("content")) or []

        normalized_query = self._normalize(query)
        candidates = []
        max_results = self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)
        seen_ids = set()
        for item in contents:
            if item.get("adult") and not self._truthy(cfg.get("INCLUDE_ADULT")):
                continue
            content_id = item.get("id") or item.get("contentId")
            title = self._clean_text(item.get("title"))
            if not content_id or not self._matches_candidate_title(normalized_query, title, cfg):
                continue
            content_key = str(content_id)
            if content_key in seen_ids:
                continue
            seen_ids.add(content_key)
            candidates.append((item, content_id))
            if len(candidates) >= max_results:
                break

        details = self._parallel_map(
            lambda candidate: self._kakao_webtoon_detail(candidate[1], cfg),
            candidates,
        )
        results = []
        for (item, content_id), detail in zip(candidates, details):
            merged = dict(item)
            merged.update(detail)
            title = self._clean_text(merged.get("title"))
            if not title or not content_id:
                continue
            seo_id = urllib.parse.quote(str(merged.get("seoId") or title.replace(" ", "-")), safe="")
            results.append(
                self._item(
                    source="카카오웹툰",
                    title=title,
                    author=self._kakao_author_text(merged.get("authors")),
                    publisher=self._kakao_publisher(merged.get("authors")) or "카카오웹툰",
                    cover=merged.get("thumbnailImage") or merged.get("sharingThumbnailImage") or merged.get("titleImageA") or merged.get("backgroundImage"),
                    description=merged.get("synopsis") or merged.get("catchphraseThreeLines") or merged.get("catchphraseTwoLines") or "",
                    link=f"https://webtoon.kakao.com/content/{seo_id}/{content_id}",
                    genre=merged.get("genre") or "",
                    tags="",
                    pub_date="",
                    score=str(merged.get("rating") or ""),
                )
            )
        return results

    def _kakao_webtoon_detail(self, content_id, cfg):
        url = f"https://gateway-kw.kakao.com/decorator/v2/decorator/contents/{content_id}"
        try:
            data = self._get_json(url, cfg, headers=self._kakao_webtoon_headers(cfg, ""))
            return data.get("data") or {}
        except Exception:
            return {}

    def _search_kakaopage(self, query, cfg):
        category = self._kakaopage_category(cfg.get("KAKAOPAGE_CATEGORY"))
        params = urllib.parse.urlencode(
            {
                "keyword": query,
                "category_uid": category,
                "is_complete": "false",
                "sort_type": "ACCURACY",
                "page": 0,
                "size": self._int(cfg.get("MAX_RESULTS"), 20, 1, 100),
            }
        )
        url = f"https://bff-page.kakao.com/api/gateway/api/v2/search/series?{params}"
        data = self._get_json(url, cfg, headers=self._kakaopage_headers(cfg, query))
        items = ((data.get("result") or {}).get("list")) or []

        normalized_query = self._normalize(query)
        candidates = []
        max_results = self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)
        seen_ids = set()
        for item in items:
            if self._is_kakaopage_adult(item) and not self._truthy(cfg.get("INCLUDE_ADULT")):
                continue
            series_id = item.get("series_id") or item.get("id")
            title = self._clean_text(item.get("title"))
            if not series_id or not self._matches_candidate_title(normalized_query, title, cfg):
                continue
            series_key = str(series_id)
            if series_key in seen_ids:
                continue
            seen_ids.add(series_key)
            candidates.append((item, series_id))
            if len(candidates) >= max_results:
                break

        details = self._parallel_map(
            lambda candidate: self._kakaopage_detail(candidate[1], cfg),
            candidates,
        )
        results = []
        for (item, series_id), detail in zip(candidates, details):
            merged = dict(item)
            merged.update(detail)
            title = self._clean_text(merged.get("title"))
            if not title or not series_id:
                continue
            results.append(
                self._item(
                    source="카카오페이지",
                    title=title,
                    author=self._clean_text(merged.get("authors")),
                    publisher="카카오페이지",
                    cover=self._kakaopage_image(merged.get("thumbnail")),
                    description=merged.get("description") or "",
                    link=f"https://page.kakao.com/content/{series_id}",
                    genre=self._clean_text(merged.get("sub_category") or merged.get("category")),
                    tags=self._clean_text(merged.get("category")),
                    pub_date=merged.get("start_sale_dt") or merged.get("last_slide_added_dt") or "",
                    score=self._kakaopage_score(merged),
                )
            )
        return results

    def _kakaopage_detail(self, series_id, cfg):
        url = "https://bff-page.kakao.com/api/gateway/api/v1/content/overview?" + urllib.parse.urlencode({"series_id": series_id})
        try:
            data = self._get_json(url, cfg, headers=self._kakaopage_headers(cfg, ""))
            return (data.get("result") or {}).get("content") or {}
        except Exception:
            return {}

    def _search_ridibooks(self, query, cfg):
        url = "https://ridibooks.com/search?" + urllib.parse.urlencode({"q": query})
        text = self._get_text(url, cfg, headers=self._ridi_headers(cfg, url))
        data = self._next_data(text)
        cells = (
            (((data.get("props") or {}).get("pageProps") or {}).get("gridData") or {})
            .get("riGrid", {})
            .get("grid", {})
            .get("cells", [])
        )

        books = []
        for cell in cells:
            book_cell = cell.get("cell__SearchBookListWithTab") if isinstance(cell, dict) else None
            if book_cell:
                books.extend(book_cell.get("books") or [])

        results = []
        for item in books[: self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)]:
            book = item.get("book") or {}
            if book.get("isAdultOnly") and not self._truthy(cfg.get("INCLUDE_ADULT")):
                continue
            rid = item.get("id") or book.get("id")
            title = ((book.get("series") or {}).get("title") or (item.get("title") or {}).get("main") or book.get("title"))
            if not rid or not title:
                continue
            authors = book.get("authors") or []
            categories = book.get("categories") or []
            publication = book.get("publicationInfo") or {}
            intro = book.get("introduction") or {}
            thumbnail = (book.get("series") or {}).get("thumbnail") or book.get("thumbnail") or {}
            results.append(
                self._item(
                    source="리디",
                    title=title,
                    author=self._join_names(authors),
                    publisher=publication.get("name") or "리디",
                    cover=thumbnail.get("xxlarge") or thumbnail.get("large") or thumbnail.get("small") or "",
                    description=intro.get("description") or "",
                    link=f"https://ridibooks.com/books/{rid}",
                    genre=self._join_names(categories),
                    tags=(book.get("webTitle") or "").strip("[]"),
                    pub_date="",
                    score=self._ridi_score(book),
                )
            )
        return results

    def _search_novelpia(self, query, cfg):
        proxy_url = self._proxy_url(cfg)
        cooldown_key = ("novelpia", hashlib.sha256(proxy_url.encode("utf-8")).hexdigest())
        with self._cache_lock:
            cooldown_until = self._source_cooldowns.get(cooldown_key, 0)
        if cooldown_until > time.time():
            return []

        url = "https://novelpia.com/proc/novelsearch/" + urllib.parse.quote(query, safe="")
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://novelpia.com/",
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded",
        }
        try:
            body, response = self._request(
                url,
                cfg,
                headers=headers,
                method="POST",
                data=b"",
                timeout=self._int(cfg.get("NOVELPIA_TIMEOUT"), 3, 1, 15),
            )
        except (TimeoutError, urllib.error.URLError) as e:
            with self._cache_lock:
                self._source_cooldowns[cooldown_key] = time.time() + NOVELPIA_FAILURE_COOLDOWN
            raise RuntimeError("request timed out; skipping Novelpia for 5 minutes") from e
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            text = body.decode("utf-8")
        except Exception:
            text = body.decode(charset, errors="replace")
        data = json.loads(text)
        novel_list = ((data.get("data") or {}).get("search_result")) or []

        results = []
        for item in novel_list[: self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)]:
            age = self._int(item.get("novel_age"), 0, 0, 99)
            if age >= 15 and not self._truthy(cfg.get("INCLUDE_ADULT")):
                continue
            novel_no = item.get("novel_no")
            title = self._clean_text(item.get("novel_name"))
            if not novel_no or not title:
                continue
            thumb = item.get("novel_thumb_all") or item.get("novel_thumb") or ""
            if thumb and thumb.startswith("/"):
                thumb = "https://novelpia.com" + thumb
            results.append(
                self._item(
                    source="노벨피아",
                    title=title,
                    author=self._clean_text(item.get("mem_nick")),
                    publisher="노벨피아",
                    cover=thumb,
                    description="",
                    link=f"https://novelpia.com/novel/{novel_no}",
                    genre="",
                    tags="",
                    pub_date=self._clean_text(item.get("content_viewdate")),
                    score="",
                )
            )
        return results

    def _search_munpia(self, query, cfg):
        url = "https://www.munpia.com/api/v1/main/search?" + urllib.parse.urlencode({"query": query})
        data = self._get_json(url, cfg, headers=self._munpia_headers(cfg))
        items = ((data.get("result") or {}).get("searchNovelTabDtos")) or []

        results = []
        for item in items[: self._int(cfg.get("MAX_RESULTS"), 20, 1, 100)]:
            if item.get("adult") and not self._truthy(cfg.get("INCLUDE_ADULT")):
                continue
            novel_id = item.get("novelId")
            title = self._clean_text(item.get("title"))
            if not novel_id or not title:
                continue
            genres = [item.get("mainGenre"), item.get("subGenre")]
            results.append(
                self._item(
                    source="문피아",
                    title=title,
                    author=self._clean_text(item.get("author")),
                    publisher="문피아",
                    cover=item.get("coverUrl") or "",
                    description=item.get("story") or "",
                    link=f"https://www.munpia.com/novel/detail/{novel_id}",
                    genre=", ".join(self._clean_text(value) for value in genres if self._clean_text(value)),
                    tags=self._join_names(item.get("tag") or []),
                    pub_date=self._clean_text(item.get("updateAt")),
                    score="",
                )
            )
        return results

    def _get_config(self, db_type):
        defaults = {f["key"]: f.get("default", "") for f in self.config_schema}
        try:
            stored = self.get_plugin_config(db_type, default={})
            if not stored:
                stored = self.get_db_gateway(db_type).get_plugin_config(LEGACY_PLUGIN_ID, default={})
            if isinstance(stored, dict):
                defaults.update(stored)
        except Exception as e:
            print(f"[NaverkakaoridiMetadataProvider] config load failed: {e}")
        return defaults

    def _get_json(self, url, cfg, headers=None):
        body, response = self._request(url, cfg, headers=headers or {})
        charset = response.headers.get_content_charset() or "utf-8"
        try:
            text = body.decode("utf-8")
        except Exception:
            text = body.decode(charset, errors="replace")
        return json.loads(text)

    def _get_text(self, url, cfg, headers=None):
        body, response = self._request(url, cfg, headers=headers or {})
        charset = response.headers.get_content_charset()
        if charset:
            return body.decode(charset, errors="replace")
        for enc in ("utf-8", "cp949", "euc-kr"):
            try:
                return body.decode(enc)
            except Exception:
                pass
        return body.decode("utf-8", errors="replace")

    def _request(self, url, cfg, headers=None, method=None, data=None, timeout=None):
        ttl = 60
        proxy_url = self._proxy_url(cfg)
        proxy_key = hashlib.sha256(proxy_url.encode("utf-8")).hexdigest() if proxy_url else ""
        key = (url, tuple(sorted((headers or {}).items())), method or "GET", data or b"", proxy_key)
        if method in (None, "GET"):
            with self._cache_lock:
                cached = self._cache.get(key)
                if cached and time.time() - cached[0] < ttl:
                    return cached[1], cached[2]
                if cached:
                    self._cache.pop(key, None)

        merged_headers = {"User-Agent": cfg.get("USER_AGENT") or DEFAULT_USER_AGENT}
        merged_headers.update(headers or {})
        req = urllib.request.Request(url, headers=merged_headers, method=method, data=data)
        try:
            timeout_value = timeout if timeout is not None else cfg.get("TIMEOUT")
            request_timeout = self._int(timeout_value, 10, 1, 60)
            with self._urlopen(req, cfg, timeout=request_timeout) as response:
                body = response.read()
            with self._cache_lock:
                self._cache[key] = (time.time(), body, response)
            return body, response
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:300]
            raise RuntimeError(f"HTTP {e.code}: {detail}") from e

    def _proxy_url(self, cfg):
        proxy_url = self._clean_text((cfg or {}).get("PROXY_URL"))
        if not proxy_url:
            return ""
        parsed = urllib.parse.urlsplit(proxy_url)
        if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
            raise ValueError("PROXY_URL은 http://host:port 형식이어야 합니다.")
        return proxy_url

    def _urlopen(self, request, cfg, timeout):
        proxy_url = self._proxy_url(cfg)
        if not proxy_url:
            return urllib.request.urlopen(request, timeout=timeout)
        handler = urllib.request.ProxyHandler({"http": proxy_url, "https": proxy_url})
        opener = urllib.request.build_opener(handler)
        return opener.open(request, timeout=timeout)

    def _save_cover(self, book, cover_url, cfg):
        if not cover_url:
            return None
        try:
            dest_path, cover_filename = self._cover_location(book["library_id"], book["file_path"])
            os.makedirs(os.path.dirname(dest_path), exist_ok=True)

            req = urllib.request.Request(
                cover_url,
                headers={"User-Agent": cfg.get("USER_AGENT") or DEFAULT_USER_AGENT},
            )
            with self._urlopen(req, cfg, timeout=self._int(cfg.get("TIMEOUT"), 10, 1, 60)) as response:
                img_data = response.read()
            with Image.open(io.BytesIO(img_data)) as img:
                img.save(dest_path, "WEBP", quality=82)
            return cover_filename
        except Exception as e:
            print(f"[NaverkakaoridiMetadataProvider] cover download failed: {e}")
            return None

    def _prepare_series_cover_files(self, gateway, book, series_name):
        series_books = gateway.fetch_all(
            """
            SELECT id, file_path
            FROM books
            WHERE library_id = ?
              AND series_name = ?
              AND id <> ?
              AND COALESCE(is_deleted, 0) = 0
            """,
            (book["library_id"], series_name, book["id"]),
        )
        if not series_books:
            return [], 0

        source_path, _ = self._cover_location(book["library_id"], book["file_path"])
        if not os.path.isfile(source_path):
            print(f"[NaverkakaoridiMetadataProvider] source cover file missing: {source_path}")
            return [], len(series_books)

        updates = []
        failures = 0
        for series_book in series_books:
            try:
                dest_path, cover_filename = self._cover_location(
                    book["library_id"],
                    series_book["file_path"],
                )
                os.makedirs(os.path.dirname(dest_path), exist_ok=True)
                shutil.copyfile(source_path, dest_path)
                updates.append(
                    (
                        cover_filename,
                        series_book["id"],
                        book["library_id"],
                        series_name,
                    )
                )
            except Exception as e:
                failures += 1
                print(
                    "[NaverkakaoridiMetadataProvider] "
                    f"series cover copy failed (book_id={series_book['id']}): {e}"
                )
        return updates, failures

    def _cover_location(self, library_id, file_path):
        if not file_path:
            raise ValueError("표지 파일명을 생성할 도서 경로가 없습니다.")
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
        book_hash = hashlib.md5(str(file_path).encode("utf-8")).hexdigest()
        filename = f"book_{book_hash}.webp"
        relative_path = f"{library_id}/{filename}"
        return os.path.join(base_dir, "covers", str(library_id), filename), relative_path

    def _item(self, source, title, author, publisher, cover, description, link, genre, tags, pub_date, score, isbn=""):
        description = self._clean_text(description)
        rating = self._rating_metadata(source, score)
        if rating:
            rating_label = f"[평점: {rating['value']:g}/{rating['scale']} | 출처: {source}]"
            description = self._with_rating_label(description, rating_label)

        item = {
            "title": self._clean_text(title),
            "author": self._clean_text(author),
            "publisher": self._clean_text(publisher),
            "isbn": self._clean_text(isbn),
            "pubDate": self._clean_text(pub_date),
            "cover": cover or "",
            "description": description,
            "link": link or "",
            "genre": self._clean_text(genre),
            "tags": self._clean_text(tags),
            "score": rating["score"] if rating else "",
            "source": source,
        }
        if rating:
            item.update(
                {
                    "rating_value": rating["value"],
                    "rating_scale": rating["scale"],
                    "rating_source": source,
                    "rating_label": rating_label,
                }
            )
        return item

    @staticmethod
    def _with_rating_label(description, rating_label):
        text = re.sub(r"^\[평점:\s*[^\]]+\]\s*", "", str(description or "")).strip()
        return f"{rating_label} {text}".strip()

    def _rating_metadata(self, source, value):
        scale = RATING_SCALES.get(self._clean_text(source))
        if not scale:
            return None
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        if rating <= 0 or rating > scale:
            return None
        return {
            "value": round(rating, 2),
            "scale": scale,
            "score": max(1, min(100, int(round(rating * 100 / scale)))),
        }

    def _with_source_prefix(self, item):
        result = dict(item)
        source = self._clean_text(result.get("source"))
        title = self._clean_text(result.get("title"))
        result["raw_title"] = title
        prefix = f"[{source}]" if source else ""
        if prefix and title and not title.startswith(prefix):
            result["title"] = f"{prefix} {title}"
        return result

    def _restore_original_title(self, item):
        result = dict(item or {})
        original_title = self._clean_text(result.pop("raw_title", ""))
        if not original_title:
            original_title = self._clean_text(result.pop("_original_title", ""))
        if not original_title:
            title = self._clean_text(result.get("title"))
            source = self._clean_text(result.get("source"))
            prefix = f"[{source}]" if source else ""
            original_title = title[len(prefix):].lstrip() if prefix and title.startswith(prefix) else title
        result["title"] = original_title
        return result

    def _naver_headers(self, cfg, referer):
        headers = {"Accept": "application/json, text/html;q=0.9,*/*;q=0.8", "Referer": referer}
        if cfg.get("NAVER_COOKIE"):
            headers["Cookie"] = cfg.get("NAVER_COOKIE")
        return headers

    def _kakaopage_headers(self, cfg, query):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://page.kakao.com",
            "Referer": "https://page.kakao.com/search/result?" + urllib.parse.urlencode({"keyword": query}),
            "User-Agent": (cfg.get("USER_AGENT") or DEFAULT_USER_AGENT) + " KakaoPageWeb/ssr",
        }
        if cfg.get("KAKAO_COOKIE"):
            headers["Cookie"] = cfg.get("KAKAO_COOKIE")
        return headers

    def _kakao_webtoon_headers(self, cfg, query):
        headers = {
            "Accept": "application/json",
            "Referer": "https://webtoon.kakao.com/search?" + urllib.parse.urlencode({"keyword": query}),
        }
        if cfg.get("KAKAO_COOKIE"):
            headers["Cookie"] = cfg.get("KAKAO_COOKIE")
        return headers

    def _ridi_headers(self, cfg, referer):
        headers = {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": referer,
        }
        if cfg.get("RIDI_COOKIE"):
            headers["Cookie"] = cfg.get("RIDI_COOKIE")
        return headers

    def _munpia_headers(self, cfg):
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": "https://www.munpia.com/",
        }
        if cfg.get("MUNPIA_COOKIE"):
            headers["Cookie"] = cfg.get("MUNPIA_COOKIE")
        return headers

    def _meta_tags(self, text):
        result = {}
        pattern = re.compile(r'<meta\s+([^>]+)>', re.I)
        attr_pattern = re.compile(r'([a-zA-Z_:.-]+)\s*=\s*["\']([^"\']*)["\']')
        for tag in pattern.findall(text):
            attrs = {k.lower(): html.unescape(v) for k, v in attr_pattern.findall(tag)}
            key = attrs.get("property") or attrs.get("name")
            if key and "content" in attrs:
                result[key] = attrs["content"]
        return result

    def _next_data(self, text):
        marker = "__NEXT_DATA__"
        marker_pos = text.find(marker)
        if marker_pos < 0:
            return {}
        start = text.find(">", marker_pos)
        end = text.find("</script>", start)
        if start < 0 or end < 0:
            return {}
        try:
            return json.loads(text[start + 1 : end])
        except Exception:
            return {}

    def _clean_text(self, value):
        if value is None:
            return ""
        if isinstance(value, (list, tuple)):
            value = ", ".join(str(v) for v in value if v)
        value = html.unescape(str(value))
        value = re.sub(r"<[^>]+>", " ", value)
        value = re.sub(r"\s+", " ", value)
        return value.strip()

    def _join_names(self, values):
        if not values:
            return ""
        names = []
        for value in values if isinstance(values, list) else [values]:
            if isinstance(value, dict):
                name = (
                    value.get("name")
                    or value.get("description")
                    or value.get("tagName")
                    or value.get("title")
                    or value.get("displayName")
                )
            else:
                name = value
            name = self._clean_text(name)
            if name and name not in names:
                names.append(name)
        return ", ".join(names)

    def _kakao_author_text(self, authors):
        if isinstance(authors, str):
            return self._clean_text(authors)
        if not isinstance(authors, list):
            return ""
        names = []
        for author in sorted(authors, key=lambda x: x.get("order", 0) if isinstance(x, dict) else 0):
            if not isinstance(author, dict):
                continue
            if author.get("type") == "PUBLISHER":
                continue
            name = self._clean_text(author.get("name"))
            role = self._clean_text(author.get("type"))
            if name:
                names.append(f"{name} ({role})" if role else name)
        return ", ".join(names)

    def _kakao_publisher(self, authors):
        if not isinstance(authors, list):
            return ""
        for author in authors:
            if isinstance(author, dict) and author.get("type") == "PUBLISHER":
                return self._clean_text(author.get("name"))
        return ""

    def _kakaopage_image(self, value):
        if not value:
            return ""
        if str(value).startswith("http"):
            return value
        return "https://page-images.kakaoentcdn.com/download/resource?" + urllib.parse.urlencode({"kid": value})

    def _kakaopage_category(self, value):
        value = (value or "all").strip().lower()
        return {"all": 0, "comic": 10, "webtoon": 10, "novel": 11, "book": 16}.get(value, self._int(value, 0, 0, 9999))

    def _kakaopage_score(self, item):
        prop = item.get("service_property") if isinstance(item, dict) else None
        if not isinstance(prop, dict):
            return ""
        count = prop.get("rating_count") or 0
        total = prop.get("rating_sum") or 0
        if count:
            return f"{round(float(total) / float(count), 2)}"
        return ""

    def _ridi_score(self, book):
        ratings = book.get("ratings") if isinstance(book, dict) else None
        if not isinstance(ratings, list):
            return ""
        count = 0
        total = 0
        for rating in ratings:
            if not isinstance(rating, dict):
                continue
            c = self._int(rating.get("count"), 0, 0, 100000000)
            r = self._int(rating.get("rating"), 0, 0, 5)
            count += c
            total += c * r
        if count:
            return f"{round(float(total) / float(count), 2)}"
        return ""

    def _is_adult(self, item):
        return bool(item.get("adult") or item.get("nineteen") or item.get("isAdult") or str(item.get("age", "")).startswith("19"))

    def _is_kakaopage_adult(self, item):
        return self._int(item.get("age_grade"), 0, 0, 99) >= 19

    def _as_list(self, value):
        if isinstance(value, list):
            return value
        if isinstance(value, dict):
            for key in ("searchViewList", "list", "items", "contents"):
                if isinstance(value.get(key), list):
                    return value.get(key)
        return []

    def _sources(self, value):
        raw = [v.strip().lower() for v in (value or "all").split(",") if v.strip()]
        if not raw or "all" in raw:
            return set(self.SOURCE_ORDER)
        aliases = {
            "naver": "naver_webtoon",
            "series": "naver_series",
            "kakao": "kakao_webtoon",
            "page": "kakaopage",
            "ridi": "ridibooks",
            "ridibooks": "ridibooks",
            "novelpia": "novelpia",
            "munpia": "munpia",
        }
        return {aliases.get(v, v) for v in raw if aliases.get(v, v) in self.SOURCE_ORDER}

    def _dedupe(self, items):
        seen = set()
        result = []
        for item in items:
            key = item.get("link") or (item.get("publisher"), item.get("title"))
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result

    def _normalize(self, value):
        return re.sub(r"\s+", "", self._clean_text(value).lower())

    def _truthy(self, value):
        return str(value).strip().lower() in ("1", "true", "yes", "y", "on")

    def _optional_score(self, value):
        text = self._clean_text(value)
        if not text:
            return None
        try:
            score = int(round(float(text)))
        except (TypeError, ValueError):
            return None
        return max(0, min(100, score))

    def _int(self, value, default, min_value, max_value):
        try:
            value = int(value)
        except Exception:
            value = default
        return max(min_value, min(max_value, value))
