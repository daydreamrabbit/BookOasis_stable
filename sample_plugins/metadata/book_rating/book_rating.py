# -*- coding: utf-8 -*-
"""
book_rating.py -- 도서 상세 페이지 헤더의 정적 점수 별을 커뮤니티 별점으로 대체하는 샘플 플러그인.

- plugin_data_relay(이 리포 안, fly.io "bo-plugin-relay"로 배포)에 관리자가 사전에 1회
  /register로 등록해둔 plugin_id("bookoasis_ratings", 필드 book_key/rating/submitter_domain,
  daily_write_limit=20)를 그대로 사용한다. 이 플러그인 코드는 스키마를 새로 만들지 않고
  이미 승인된 plugin_id를 호출하기만 한다.
- 도서 식별(book_key)은 ISBN이 있으면 ISBN, 없으면 (제목+작가), 작가도 없으면 제목
  단독으로 계산한다(앞뒤 공백만 제거, 판본 자동 병합은 하지 않음).
- submitter_domain은 어뷰징 방지용 "신원 문자열"일 뿐이라 relay가 검증하지 않는다 -
  관리자가 설정에 직접 입력한 값을 그대로 신뢰해서 보낸다(자동 감지 로직 없음, 단순함 우선).
- 시리즈당 1회/하루 20회 상한은 이 플러그인이 아니라 relay가 최종 강제한다
  (unique_by=["book_key"]로 재제출 시 덮어쓰기, daily_write_limit=20으로 429).
- 성인 서재/오디오북/영상 강좌에는 노출하지 않는다 - rating_widget.sessions를 'general'로만
  선언해 코어의 _resolve_plugin_sessions()가 자동으로 배제해준다.
"""
import logging
import hashlib
import json
import uuid
from concurrent.futures import ThreadPoolExecutor

import requests

from plugins.metadata.base import BaseMetadataProvider

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 3
SUBMIT_TIMEOUT = 5
WIDGET_CACHE_TTL = 300
FAILURE_BACKOFF_TTL = 120
RELAY_PLUGIN_ID = "bookoasis_ratings"
VERIFY_CACHE_TTL = 60 * 60 * 24  # 하루 - 인증이 여전히 유효한지 재확인하는 주기


class BookRatingMetadataProvider(BaseMetadataProvider):
    """도서 상세 헤더 별점을 plugin_data_relay 기반 커뮤니티 별점으로 대체하는 플러그인."""

    id = "book_rating"
    name = "커뮤니티 별점"
    is_searchable = False

    config_schema = [
        {
            "key": "RELAY_DOMAIN_URL",
            "label": "plugin_data_relay 배포 URL",
            "type": "text",
            "default": "https://bo-plugin-relay.fly.dev",
            "required": True,
        },
        {
            "key": "RELAY_USER_ID",
            "label": "이 설치(install) 식별 ID",
            "type": "text",
            "required": True,
        },
        {
            "key": "RELAY_SECRET_TOKEN",
            "label": "이 설치(install)의 32자리 비밀 토큰",
            "type": "password",
            "required": True,
        },
        {
            "key": "SUBMITTER_DOMAIN",
            "label": "내 BookOasis 도메인 (없으면 IP를 직접 입력)",
            "type": "text",
            "required": True,
            "description": "relay는 이 값을 검증하지 않고 그대로 신뢰합니다. 어뷰징 방지용 표시값일 뿐이니 정확한 값을 입력하세요.",
        },
    ]

    # 도서 상세 페이지 헤더의 정적 점수 별(.detail-score)을 이 플러그인이 대체한다.
    # 일반 도서 서재에만 노출 - 성인/오디오북/영상 강좌는 별점 기능 자체를 노출하지 않는다.
    rating_widget = {"title": "커뮤니티 별점", "order": 10, "sessions": "general"}

    update_manifest = {
        "enabled": True,
        "provider": "github-raw",
        "raw_base_url": "https://raw.githubusercontent.com/leeyj/BookOasis_stable/main/sample_plugins/metadata/book_rating",
        "files": ["book_rating.py", "__init__.py", "VERSION"],
        "version_file": "VERSION",
        "version_key": "plugin version",
        "show_sample_update_button": True,
    }

    # ------------------------------------------------------------------
    # 필수 계약 (검색형 메타데이터 기능은 사용하지 않음 - 별점 위젯 전용)
    # ------------------------------------------------------------------
    def search(self, db_type, query):
        return []

    def apply(self, db_type, book_id, item_data):
        return False, "커뮤니티 별점 플러그인은 도서 메타데이터 적용을 지원하지 않습니다."

    # ------------------------------------------------------------------
    # 설정/식별 헬퍼
    # ------------------------------------------------------------------
    def _relay_config(self, db_type):
        cfg = self.get_plugin_config(db_type, default={}) or {}
        domain_url = str(cfg.get("RELAY_DOMAIN_URL") or "").strip().rstrip("/")
        user_id = str(cfg.get("RELAY_USER_ID") or "").strip()
        secret_token = str(cfg.get("RELAY_SECRET_TOKEN") or "").strip()
        submitter_domain = str(cfg.get("SUBMITTER_DOMAIN") or "").strip()
        return domain_url, user_id, secret_token, submitter_domain

    def _book_key(self, context):
        """ISBN -> (제목+작가) -> 제목 단독 순으로 도서를 식별한다. 판본 자동 병합은 하지
        않으므로(완전판/초회판 등은 제목 자체가 다르면 별개 도서로 취급) 여기서 별도의
        정규화(괄호 제거 등)는 하지 않고 trim만 한다."""
        title = str(context.get("series_name") or "").strip()
        author = str(context.get("author") or "").strip()
        from utils.isbn import normalize_isbn
        isbn = normalize_isbn(context.get("isbn"))

        if isbn:
            return f"isbn:{isbn}"
        if author:
            return f"ta:{title}|{author}"
        return f"t:{title}"

    def _sort_cache_key(self, db_type):
        domain, user, _, _ = self._relay_config(db_type)
        identity = hashlib.sha256((domain + '|' + user).encode()).hexdigest()
        epoch = self.cache_get('sort-epoch:' + identity) or 'initial'
        return 'sort-own-v2:' + identity + ':' + str(epoch)

    def invalidate_sort_ratings(self, db_type):
        self.cache_delete(self._sort_cache_key(db_type))
        domain, user, _, _ = self._relay_config(db_type)
        identity = hashlib.sha256((domain + '|' + user).encode()).hexdigest()
        self.cache_set('sort-epoch:' + identity, uuid.uuid4().hex, ttl=86400)

    def get_sort_ratings(self, db_type):
        """Export this installation's votes in one request, not one per book."""
        try:
            cache_key = self._sort_cache_key(db_type)
            cached = self.cache_get(cache_key)
            if cached:
                return json.loads(cached)
            domain, user, secret, _ = self._relay_config(db_type)
            if not all((domain, user, secret)) or not self._ensure_verified(domain, user, secret):
                return {'success': False, 'error': '별점 플러그인 인증을 확인해 주세요.'}
            def fetch():
                return requests.get(f'{domain}/api/{RELAY_PLUGIN_ID}/records',
                    params={'user_id': user, 'secret_token': secret, 'filter_field': 'user_id',
                            'filter_value': user, 'limit': 200}, timeout=REQUEST_TIMEOUT)
            response = self._retry_after_unauthorized(fetch(), fetch, domain, user, secret)
            body = response.json()
            if not response.ok or not body.get('success'):
                return {'success': False, 'error': '정렬용 별점 조회에 실패했습니다.'}
            rows = body.get('records') or []
            # This relay has no pagination. Never silently sort an incomplete export.
            if len(rows) >= 200:
                return {'success': False, 'error': '별점 서버의 200건 조회 제한으로 전체 별점을 정렬할 수 없습니다.'}
            values = {}
            for row in rows:
                if str(row.get('user_id')) != user or not row.get('book_key'):
                    continue
                key = str(row['book_key'])
                if key.startswith('isbn:'):
                    from utils.isbn import normalize_isbn
                    isbn = normalize_isbn(key[5:])
                    if not isbn:
                        continue  # Ambiguous historical votes are preserved, not reassigned.
                    key = 'isbn:' + isbn
                value = float(row.get('rating'))
                if value in {step / 2 for step in range(1, 11)}:
                    values[hashlib.sha256(key.encode()).hexdigest()] = value
            result = {'success': True, 'identity': 'book_key', 'ratings': values}
            self.cache_set(cache_key, json.dumps(result), ttl=60)
            return result
        except (requests.RequestException, ValueError, TypeError):
            return {'success': False, 'error': '정렬용 플러그인 별점을 불러오지 못했습니다.'}

    def _ensure_verified(self, domain_url, user_id, secret_token, force=False):
        """relay에 이 설치(install)가 등록돼 있는지 확인/자동 등록한다. 매 요청마다 왕복하지
        않도록 결과를 하루 동안 플러그인 전용 Redis 캐시에 남긴다."""
        cache_key = 'verified:' + self._scope_hash(domain_url, user_id, secret_token)
        if not force and self.cache_get(cache_key) == "1":
            return True

        resp = requests.post(
            f"{domain_url}/api/{RELAY_PLUGIN_ID}/verify",
            json={"user_id": user_id, "secret_token": secret_token},
            timeout=REQUEST_TIMEOUT,
        )
        ok = resp.ok and resp.json().get("success")
        if ok:
            self.cache_set(cache_key, "1", ttl=VERIFY_CACHE_TTL)
        return ok

    def _retry_after_unauthorized(self, response, request_again, domain_url, user_id, secret_token):
        """Relay registration can disappear before the local verify cache expires."""
        if response.status_code == 401 and self._ensure_verified(
            domain_url, user_id, secret_token, force=True
        ):
            return request_again()
        return response

    @staticmethod
    def _scope_hash(*parts):
        return hashlib.sha256('|'.join(map(str, parts)).encode()).hexdigest()[:24]

    def _widget_cache_key(self, domain, user, book):
        return 'widget-v2:' + self._scope_hash(domain, user, book)

    def _backoff_key(self, domain, user):
        return 'backoff-v2:' + self._scope_hash(domain, user)

    def _invalidate_widget(self, domain, user, book):
        self.cache_delete(self._widget_cache_key(domain, user, book))
        self.cache_delete(self._backoff_key(domain, user))

    # ------------------------------------------------------------------
    # rating_widget 계약 구현
    # ------------------------------------------------------------------
    def get_rating_widget_data(self, db_type, context):
        if db_type != "general":
            return {"success": False, "error": "성인/오디오북/영상 강좌는 별점 기능을 지원하지 않습니다."}

        domain_url, user_id, secret_token, _submitter_domain = self._relay_config(db_type)
        if not domain_url or not user_id or not secret_token:
            return {"success": False, "error": "커뮤니티 별점 플러그인 설정이 완료되지 않았습니다."}

        book_key = self._book_key(context)
        cache_key = self._widget_cache_key(domain_url, user_id, book_key)
        cached = self.cache_get(cache_key)
        if cached:
            try:
                result = json.loads(cached)
                if isinstance(result, dict) and result.get('success'):
                    return result
            except (ValueError, TypeError):
                pass
        backoff_key = self._backoff_key(domain_url, user_id)
        if self.cache_get(backoff_key):
            return {'success':False, 'error':'별점 서버 응답이 지연되어 잠시 후 다시 확인합니다.'}
        try:
            if not self._ensure_verified(domain_url, user_id, secret_token):
                self.cache_set(backoff_key, '1', ttl=FAILURE_BACKOFF_TTL)
                return {"success": False, "error": "relay 인증에 실패했습니다."}

            auth = {"user_id": user_id, "secret_token": secret_token}

            def get_aggregate():
                return requests.get(
                    f"{domain_url}/api/{RELAY_PLUGIN_ID}/records/aggregate",
                    params={**auth, "agg_field": "rating", "filter_field": "book_key", "filter_value": book_key},
                    timeout=REQUEST_TIMEOUT,
                )
            with ThreadPoolExecutor(max_workers=2) as pool:
                mine = pool.submit(self._find_my_rating, domain_url, auth, book_key, user_id, strict=True)
                aggregate = pool.submit(get_aggregate)
                agg_resp = self._retry_after_unauthorized(
                    aggregate.result(), get_aggregate, domain_url, user_id, secret_token)
                my_rating = mine.result()
            agg = agg_resp.json() if agg_resp.ok else {}
            if not agg.get("success"):
                self.cache_set(backoff_key, '1', ttl=FAILURE_BACKOFF_TTL)
                return {"success": False, "error": agg.get("message") or "별점 집계 조회에 실패했습니다."}
            result = {
                "success": True,
                "average": round(float(agg.get("avg") or 0), 1),
                "count": int(agg.get("count") or 0),
                "my_rating": my_rating,
            }
            self.cache_set(cache_key, json.dumps(result), ttl=WIDGET_CACHE_TTL)
            return result
        except (requests.RequestException, ValueError, TypeError) as e:
            self.cache_set(backoff_key, '1', ttl=FAILURE_BACKOFF_TTL)
            logger.warning("[book_rating] 별점 조회 실패: %s", e)
            return {"success": False, "error": "커뮤니티 별점 서버에 연결할 수 없습니다."}

    def submit_rating(self, db_type, context, rating):
        if db_type != "general":
            return {"success": False, "error": "성인/오디오북/영상 강좌는 별점 기능을 지원하지 않습니다."}

        domain_url, user_id, secret_token, submitter_domain = self._relay_config(db_type)
        if not domain_url or not user_id or not secret_token:
            return {"success": False, "error": "커뮤니티 별점 플러그인 설정이 완료되지 않았습니다."}

        try:
            if not self._ensure_verified(domain_url, user_id, secret_token):
                return {"success": False, "error": "relay 인증에 실패했습니다."}

            # 0.5 단위로 정규화 - 라우트에서 이미 반올림해 보내지만 provider 단독 호출 경로도
            # 대비해 여기서도 한 번 더 맞춘다.
            rating = round(float(rating) * 2) / 2

            book_key = self._book_key(context)
            def post_rating():
                return requests.post(
                    f"{domain_url}/api/{RELAY_PLUGIN_ID}/records",
                    json={
                        "user_id": user_id,
                        "secret_token": secret_token,
                        "values": {"book_key": book_key, "rating": rating, "submitter_domain": submitter_domain},
                        "unique_by": ["book_key"],
                    },
                    timeout=SUBMIT_TIMEOUT,
                )
            resp = self._retry_after_unauthorized(
                post_rating(), post_rating, domain_url, user_id, secret_token)
            body = resp.json() if resp.content else {}
            if not resp.ok or not body.get("success"):
                return {"success": False, "error": body.get("message") or "별점 제출에 실패했습니다."}

            self._invalidate_widget(domain_url, user_id, book_key)
            self.invalidate_sort_ratings(db_type)

            auth = {"user_id": user_id, "secret_token": secret_token}
            agg_resp = requests.get(
                f"{domain_url}/api/{RELAY_PLUGIN_ID}/records/aggregate",
                params={**auth, "agg_field": "rating", "filter_field": "book_key", "filter_value": book_key},
                timeout=REQUEST_TIMEOUT,
            )
            agg = agg_resp.json() if agg_resp.ok else {}

            return {
                "success": True,
                "average": round(float(agg.get("avg") or rating), 1),
                "count": int(agg.get("count") or 1),
                "my_rating": rating,
            }
        except requests.RequestException as e:
            logger.warning("[book_rating] 별점 제출 실패: %s", e)
            return {"success": False, "error": "커뮤니티 별점 서버에 연결할 수 없습니다."}

    def cancel_rating(self, db_type, context):
        """Delete only this installation's vote; zero is never a community vote."""
        if db_type != 'general':
            return {'success': False, 'error': '일반도서 별점만 취소할 수 있습니다.'}
        domain_url, user_id, secret_token, _ = self._relay_config(db_type)
        if not all((domain_url, user_id, secret_token)):
            return {'success': False, 'error': '커뮤니티 별점 플러그인 설정이 완료되지 않았습니다.'}
        try:
            if not self._ensure_verified(domain_url, user_id, secret_token):
                return {'success': False, 'error': 'relay 인증에 실패했습니다.'}
            book_key = self._book_key(context)
            auth = {'user_id': user_id, 'secret_token': secret_token}
            def get_records():
                return requests.get(f'{domain_url}/api/{RELAY_PLUGIN_ID}/records',
                    params={**auth, 'filter_field': 'book_key', 'filter_value': book_key, 'limit': 200},
                    timeout=REQUEST_TIMEOUT)
            response = self._retry_after_unauthorized(get_records(), get_records, domain_url, user_id, secret_token)
            body = response.json()
            if not response.ok or not body.get('success'):
                return {'success': False, 'error': body.get('message') or '내 별점 조회에 실패했습니다.'}
            records = body.get('records') or []
            own = [record for record in records if str(record.get('user_id')) == user_id
                   and record.get('book_key') == book_key]
            if not own and len(records) >= 200:
                return {'success': False, 'error': '별점 조회 범위를 초과해 내 평점을 확인하지 못했습니다. 취소하지 않았습니다.'}
            for record in own:
                record_id = int(record['id'])
                def delete_record():
                    return requests.delete(f'{domain_url}/api/{RELAY_PLUGIN_ID}/records/{record_id}',
                        json=auth, timeout=REQUEST_TIMEOUT)
                deleted = self._retry_after_unauthorized(delete_record(), delete_record, domain_url, user_id, secret_token)
                result = deleted.json()
                if not deleted.ok or not result.get('success'):
                    return {'success': False, 'error': result.get('message') or '평점 취소에 실패했습니다.'}
            self._invalidate_widget(domain_url, user_id, book_key)
            self.invalidate_sort_ratings(db_type)
            result = self.get_rating_widget_data(db_type, context)
            if result.get('success'):
                result['my_rating'] = None
            return result
        except (requests.RequestException, ValueError, KeyError, TypeError) as error:
            logger.warning('[book_rating] 별점 취소 실패: %s', type(error).__name__)
            return {'success': False, 'error': '커뮤니티 별점 서버에서 평점 취소를 확인하지 못했습니다.'}

    def _find_my_rating(self, domain_url, auth, book_key, user_id, strict=False):
        """list_records는 user_id로 필터링되지 않으므로(같은 book_key의 다른 사용자 레코드도
        함께 온다), 응답에서 내 user_id와 일치하는 행만 찾아 my_rating으로 쓴다."""
        try:
            def get_records():
                return requests.get(
                    f"{domain_url}/api/{RELAY_PLUGIN_ID}/records",
                    params={**auth, "filter_field": "book_key", "filter_value": book_key, "limit": 200},
                    timeout=REQUEST_TIMEOUT,
                )
            resp = self._retry_after_unauthorized(
                get_records(), get_records, domain_url, user_id, auth['secret_token'])
            if not resp.ok:
                if strict:
                    raise requests.RequestException('own rating lookup failed')
                return None
            payload = resp.json()
            if strict and not payload.get('success'):
                raise requests.RequestException('own rating lookup failed')
            records = payload.get("records") or []
            for record in records:
                if record.get("user_id") == user_id:
                    return float(record.get("rating"))
        except (requests.RequestException, TypeError, ValueError):
            if strict:
                raise
            pass
        return None
