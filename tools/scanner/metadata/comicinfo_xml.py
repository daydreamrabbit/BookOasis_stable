# -*- coding: utf-8 -*-
import html
import io
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
import zipfile

TARGET_FILENAME = 'ComicInfo.xml'

HTML_TAG_RE = re.compile(r'<[^>]*>')


class NetworkCircuitBreaker:
    def __init__(self, max_failures=3, reset_timeout=60):
        self.failures = 0
        self.max_failures = max_failures
        self.reset_timeout = reset_timeout
        self.last_failure_time = 0
        self._lock = threading.Lock()

    def is_tripped(self):
        with self._lock:
            if self.failures >= self.max_failures:
                if time.time() - self.last_failure_time > self.reset_timeout:
                    self.failures = 0
                    return False
                return True
            return False

    def record_failure(self):
        with self._lock:
            self.failures += 1
            self.last_failure_time = time.time()

    def record_success(self):
        with self._lock:
            if self.failures > 0:
                self.failures = 0


_circuit_breaker = NetworkCircuitBreaker(max_failures=3, reset_timeout=60)


def clean_html_tags(text):
    if not text:
        return ''
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'</p\s*>', '\n', text, flags=re.IGNORECASE)
    text = re.sub(r'<p\s*>', '', text, flags=re.IGNORECASE)
    cleaned = HTML_TAG_RE.sub('', text)
    return html.unescape(cleaned).strip()


def normalize_metadata_token(token):
    if token is None:
        return ''
    return re.sub(r'\s{2,}', ' ', str(token).strip(" \t\r\n'\"[](),")).strip()


def normalize_metadata_list_field(value):
    if not value:
        return ''

    tokens = [normalize_metadata_token(part) for part in str(value).split(',')]
    tokens = [t for t in tokens if t]

    normalized = []
    seen = set()
    for token in tokens:
        key = token.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(token)

    return ', '.join(normalized)


def parse(target_path, is_remote=False):
    return parse_comicinfo_from_cbz(target_path)


def parse_comicinfo_from_cbz(file_path):
    """Parse ComicInfo.xml inside CBZ/ZIP file and return metadata."""
    meta = {
        'author': '',
        'cover_artist': '',
        'teams': '',
        'locations': '',
        'characters': '',
        'books_lv': '',
        'publisher': '',
        'summary': '',
        'release_date': '',
        'genre': '',
        'tags': '',
        'cover_b64': None,
    }

    if not file_path.lower().endswith(('.cbz', '.zip')):
        return meta

    try:
        with zipfile.ZipFile(file_path, 'r') as zf:
            names_lower = {n.lower(): n for n in zf.namelist()}
            comicinfo_key = names_lower.get('comicinfo.xml')
            if not comicinfo_key:
                return meta

            xml_data = zf.read(comicinfo_key)
            root = ET.fromstring(xml_data)

            def _get(tag):
                elem = root.find(tag)
                return elem.text.strip() if elem is not None and elem.text else ''

            # Writer(글 작가)만 author로 채운다 - Penciller(그림 작가)를 author 폴백으로
            # 섞으면 표지/그림 담당자가 글 작가로 잘못 표기된다. 그림 작가는 아래
            # cover_artist에 별도로 보존한다.
            meta['author'] = _get('Writer')

            # 명시적 <CoverArtist> 태그가 있으면 우선 사용하고, 없으면 <Penciller>를
            # 호환값으로 사용한다(존재하는 쪽 우선) - 일부 저작 도구는 CoverArtist 개념을
            # Penciller에 저장하는 관례가 있어 두 태그 다 표지 작가 후보로 취급한다.
            meta['cover_artist'] = _get('CoverArtist') or _get('Penciller')

            meta['teams'] = normalize_metadata_list_field(_get('Teams'))
            meta['locations'] = normalize_metadata_list_field(_get('Locations'))
            meta['characters'] = normalize_metadata_list_field(_get('Characters'))

            # AgeRating 원문을 그대로 books_lv에 채운다 - services/content_rating_service.py의
            # _BOOKS_LV_LEVEL_MAP이 ComicInfo 표준 어휘(M/MA15+/R18+/Teen 등)를 이미
            # 대소문자 무시하고 인식하므로 별도 매핑 테이블이 필요 없다(Kavita YAML의 숫자
            # 코드와 달리 ComicInfo AgeRating은 이미 사람이 읽는 표준 문자열이기 때문).
            meta['books_lv'] = _get('AgeRating')

            meta['publisher'] = _get('Publisher')
            meta['summary'] = clean_html_tags(_get('Summary'))
            meta['genre'] = normalize_metadata_list_field(_get('Genre'))
            meta['tags'] = normalize_metadata_list_field(_get('Tags'))

            year = _get('Year')
            month = _get('Month').zfill(2) if _get('Month') else ''
            day = _get('Day').zfill(2) if _get('Day') else ''
            if year:
                meta['release_date'] = f"{year}-{month or '01'}-{day or '01'}"

    except zipfile.BadZipFile:
        pass
    except Exception as e:
        print(f"[Scanner] ComicInfo.xml parsing error ({file_path}): {e}")

    meta['genre'] = normalize_metadata_list_field(meta.get('genre', ''))
    meta['tags'] = normalize_metadata_list_field(meta.get('tags', ''))

    return meta