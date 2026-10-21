# -*- coding: utf-8 -*-
"""쓰기 API 실패를 서버 로그(logs/media_server.log)에 한 줄로 남긴다.

메타 적용·정보 수정·표지 업로드처럼 가끔 쓰는 쓰기 경로는 실패해도 화면 토스트 한 줄뿐이라,
사용자 신고가 와도 로그에서 원인을 찾을 수 없었다(2026-10-11: 알라딘 적용이 1.7.8부터 항상 실패,
오디오북 표지 업로드 1054 등). 알림센터는 이미 내용이 많다는 피드백이 있어 로그에만 남긴다.

- 대상: /api/ 아래 POST·PUT·PATCH·DELETE 중 응답이 4xx/5xx이거나 200이라도 JSON success=false.
- 401(세션 만료)은 소음이라 남기지 않는다. 요청 본문은 남기지 않는다(비밀번호 등).
- 이 훅 자체가 실패해도 응답은 그대로 나간다.
"""
from flask import request, session

WRITE_METHODS = ('POST', 'PUT', 'PATCH', 'DELETE')
_SKIP_STATUS = (401,)
_MAX_ERROR_LEN = 300


def _request_field(name):
    try:
        if request.is_json:
            value = (request.get_json(silent=True) or {}).get(name)
        else:
            value = request.values.get(name)
        return ' '.join(str(value).split())[:60] if value not in (None, '') else ''
    except Exception:
        return ''


def _response_failure(response):
    """(실패 여부, 오류 문구). 스트리밍/파일 응답은 본문을 읽지 않는다."""
    status = response.status_code
    data = None
    if response.is_json and not response.direct_passthrough and not response.is_streamed:
        data = response.get_json(silent=True)
    if isinstance(data, dict):
        failed = status >= 400 or data.get('success') is False
        detail = data.get('error') or data.get('message') or ''
        return failed, str(detail)
    return status >= 400, ''


def log_failed_write_request(response):
    try:
        if request.method not in WRITE_METHODS or not request.path.startswith('/api/'):
            return response
        if response.status_code in _SKIP_STATUS:
            return response
        failed, detail = _response_failure(response)
        if not failed:
            return response
        parts = [f"[API-FAIL] {request.method} {request.path} -> {response.status_code}",
                 f"user={session.get('username') or session.get('user_id') or '-'}"]
        for name in ('type', 'source'):
            value = _request_field(name)
            if value:
                parts.append(f"{name}={value}")
        detail = ' '.join(detail.split())[:_MAX_ERROR_LEN]
        if detail:
            parts.append(f"error={detail}")
        print(' '.join(parts))
    except Exception as e:
        print(f"[API-FAIL] logging failed for {getattr(request, 'path', '?')}: {e}")
    return response
