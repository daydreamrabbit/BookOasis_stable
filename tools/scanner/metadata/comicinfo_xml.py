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
DEFAULT_REMOTE_PARSE_TIMEOUT_SECONDS = 15.0


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


def _empty_meta():
    return {
        'title': '',
        'author': '',
        'localized_series': '',
        'cover_artist': '',
        'link': '',
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


def _remote_parse_timeout_seconds():
    """Bound a potentially blocking ZIP read through an rclone/FUSE mount."""
    try:
        configured = float(os.getenv(
            'COMICINFO_REMOTE_TIMEOUT_SECONDS',
            str(DEFAULT_REMOTE_PARSE_TIMEOUT_SECONDS)
        ))
        return max(1.0, min(configured, 120.0))
    except (TypeError, ValueError):
        return DEFAULT_REMOTE_PARSE_TIMEOUT_SECONDS


def parse(target_path, is_remote=False):
    return parse_comicinfo_from_cbz(target_path, is_remote=is_remote)


def _parse_comicinfo_from_cbz_local(file_path):
    """Read one archive in the calling thread; remote callers isolate this in a worker."""
    meta = _empty_meta()
    file_path = os.fspath(file_path)
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
                if elem is None:
                    elem = next(
                        (child for child in root.iter()
                         if child.tag.rsplit('}', 1)[-1] == tag),
                        None
                    )
                return elem.text.strip() if elem is not None and elem.text else ''

            # Writer(글 작가)만 author로 채운다 - Penciller(그림 작가)를 author 폴백으로
            # 섞으면 표지/그림 담당자가 글 작가로 잘못 표기된다. 그림 작가는 아래
            # cover_artist에 별도로 보존한다.
            meta['title'] = _get('Title')
            meta['author'] = _get('Writer')
            meta['localized_series'] = _get('LocalizedSeries')

            # 명시적 <CoverArtist> 태그가 있으면 우선 사용하고, 없으면 <Penciller>를
            # 호환값으로 사용한다(존재하는 쪽 우선) - 일부 저작 도구는 CoverArtist 개념을
            # Penciller에 저장하는 관례가 있어 두 태그 다 표지 작가 후보로 취급한다.
            meta['cover_artist'] = _get('CoverArtist') or _get('Penciller')

            meta['teams'] = normalize_metadata_list_field(_get('Teams'))
            meta['locations'] = normalize_metadata_list_field(_get('Locations'))
            meta['characters'] = normalize_metadata_list_field(_get('Characters'))

            # AgeRating 원문을 그대로 저장하고 등급 단계 변환은 ContentRatingService에 맡긴다.
            meta['books_lv'] = _get('AgeRating')
            # ComicInfo 표준 Web 필드가 작품 관련 링크다. 일부 생성기는 WebLink를 쓰므로
            # 호환 폴백으로 함께 읽는다.
            meta['link'] = _get('Web') or _get('WebLink')

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
        return meta

    meta['genre'] = normalize_metadata_list_field(meta.get('genre', ''))
    meta['tags'] = normalize_metadata_list_field(meta.get('tags', ''))

    return meta


def parse_comicinfo_from_cbz(file_path, is_remote=False, timeout=None):
    """Parse ComicInfo.xml locally or with a bounded wait for remote VFS files."""
    meta = _empty_meta()
    if not file_path or not str(file_path).lower().endswith(('.cbz', '.zip')):
        return meta

    if not is_remote:
        try:
            return _parse_comicinfo_from_cbz_local(file_path)
        except Exception as error:
            print(f"[Scanner] ComicInfo.xml parsing error ({file_path}): {error}")
            return meta

    if _circuit_breaker.is_tripped():
        print(f"[Scanner-ComicInfo] ⚠️ 원격 ComicInfo 읽기 일시 중지(최근 VFS 시간 초과): {file_path}")
        return meta

    result = []

    def _parse_remote():
        try:
            result.append(_parse_comicinfo_from_cbz_local(file_path))
        except Exception as error:
            result.append(error)

    timeout_seconds = timeout if timeout is not None else _remote_parse_timeout_seconds()
    try:
        timeout_seconds = max(1.0, min(float(timeout_seconds), 120.0))
    except (TypeError, ValueError):
        timeout_seconds = DEFAULT_REMOTE_PARSE_TIMEOUT_SECONDS

    worker = threading.Thread(target=_parse_remote, daemon=True)
    worker.start()
    worker.join(timeout_seconds)

    if worker.is_alive():
        _circuit_breaker.record_failure()
        print(f"[Scanner-ComicInfo] ⚠️ 원격 CBZ ComicInfo 읽기 시간 초과 ({timeout_seconds:.1f}s): {file_path}")
        return meta

    if not result:
        _circuit_breaker.record_failure()
        return meta

    parsed = result[0]
    if isinstance(parsed, Exception):
        _circuit_breaker.record_failure()
        print(f"[Scanner-ComicInfo] 원격 ComicInfo 파싱 실패(무시): {file_path}: {parsed}")
        return meta

    _circuit_breaker.record_success()
    return parsed
