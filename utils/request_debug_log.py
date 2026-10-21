# -*- coding: utf-8 -*-
"""느린 요청·서버 오류를 별도 파일(logs/request_debug.log)에 남기는 진단용 훅 (2.9.5).

.env에 DEBUG_REQUEST_LOG=true일 때만 켜진다(기본 꺼짐 - 공개 배포판의 일반 사용자에게는 훅 자체가 등록되지 않는다).
  DEBUG_REQUEST_LOG=true
  DEBUG_REQUEST_LOG_MS=500      # 이 시간(ms) 이상 걸린 요청을 남긴다(기본 500)

한 줄에 남기는 값과 읽는 법:
  wall   = 요청 처리 시간(스트리밍 응답은 본문 전송 전까지)
  cpu    = 이 요청 스레드가 실제로 CPU를 쓴 시간(time.thread_time)
  inflight = 이 요청이 시작될 때 이미 처리 중이던 다른 요청 수
  → cpu가 wall에 가까우면 그 요청 자체가 무겁고, cpu는 작은데 inflight가 크면 다른 요청과 겹쳐(단일 워커 GIL) 밀린 것이다
    (2026-10-17 history 206ms = load-status의 CPU 작업과 겹친 사례).
요약: python tools/summarize_request_debug_log.py  또는 MCP get_request_debug_summary
"""
import os
import time
import threading
import logging
from logging.handlers import RotatingFileHandler

from flask import g, request, session

_LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'request_debug.log')

# 원래 오래 걸리는 요청은 소음이라 제외한다: 파일 통째 전송(PDF·다운로드), 오디오/영상 스트림, 외부 사이트 프록시.
# 만화 페이지(/api/media/stream)·표지·EPUB 이미지는 읽는 체감 그 자체라 남긴다.
_SKIP_PREFIXES = (
    '/static/',
    '/health',
    '/api/media/pdf',
    '/app-opds/api/media/pdf',
    '/app-opds-adult/api/media/pdf',
    '/api/webview/',            # 외부 사이트 프록시·HLS 프록시·다운로드(인터넷 지연)
    '/opds/download/',
    '/app-opds/download/',
    '/api/media/tts/audio/',
)
# 오디오 트랙·영상 스트림(/tracks/<id>/stream, /episodes/<id>/stream), 영상 HLS 조각, 책 다운로드
_SKIP_SUFFIXES = ('/download',)
# 키 이름 전체 또는 _로 끝나는 꼬리로 판단한다(부분 문자열로 보면 author가 auth에 걸려 가려졌다)
_SENSITIVE_QUERY_KEYS = {'token', 'password', 'passwd', 'pw', 'secret', 'key', 'apikey', 'api_key', 'auth', 'authorization', 'signature', 'sig', 'code'}
_SENSITIVE_QUERY_SUFFIXES = ('_token', '_key', '_secret', '_password')


def _is_sensitive_key(key):
    k = key.lower().replace('-', '_')
    return k in _SENSITIVE_QUERY_KEYS or k.endswith(_SENSITIVE_QUERY_SUFFIXES)

_inflight = 0
_inflight_lock = threading.Lock()
_logger = None
_logger_lock = threading.Lock()


def _log_value(value, limit=200):
    return ' '.join(str(value).split())[:limit]


def is_enabled(environ=None):
    env = os.environ if environ is None else environ
    return str(env.get('DEBUG_REQUEST_LOG', 'false')).strip().lower() in ('1', 'true', 'yes', 'on')


def _threshold_ms(environ=None):
    env = os.environ if environ is None else environ
    try:
        return max(0, int(str(env.get('DEBUG_REQUEST_LOG_MS', '500')).strip()))
    except ValueError:
        return 500


def should_skip(path):
    if path.startswith(_SKIP_PREFIXES) or path.endswith(_SKIP_SUFFIXES):
        return True
    # 오디오 트랙 스트림·영상 스트림/HLS 조각만 제외(트랙 가사·진행률 같은 일반 API는 남긴다)
    if '/tracks/' in path and path.endswith('/stream'):
        return True
    if '/episodes/' in path and (path.endswith('/stream') or '/hls-segment/' in path):
        return True
    return False


def safe_query(args):
    parts = []
    for key in list(args.keys())[:8]:
        if key == '_':  # 캐시 무력화용 타임스탬프
            continue
        value = '***' if _is_sensitive_key(key) else str(args.get(key, ''))[:40]
        parts.append(f"{_log_value(key, 60)}={_log_value(value, 40)}")
    return '&'.join(parts)


def format_line(kind, wall_ms, cpu_ms, inflight, method, rule, path, status, user_id, query):
    """요약 도구가 다시 읽는 형식(탭 구분 key=value). 바꾸면 services/request_debug_summary.py도 같이 바꾼다."""
    return '\t'.join([
        time.strftime('%Y-%m-%d %H:%M:%S'),
        kind,
        f"wall={wall_ms:.0f}",
        f"cpu={cpu_ms:.0f}",
        f"inflight={inflight}",
        f"status={status}",
        f"method={method}",
        f"rule={_log_value(rule)}",
        f"path={_log_value(path)}",
        f"user={_log_value(user_id, 60)}",
        f"q={_log_value(query, 800)}",
    ])


def _get_logger():
    global _logger
    with _logger_lock:
        if _logger is None:
            os.makedirs(os.path.dirname(_LOG_FILE), exist_ok=True)
            logger = logging.getLogger('bookoasis.request_debug')
            logger.setLevel(logging.INFO)
            logger.propagate = False
            handler = RotatingFileHandler(_LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            logger.addHandler(handler)
            _logger = logger
    return _logger


def init_app(app, environ=None):
    """켜져 있을 때만 훅을 등록한다. 꺼져 있으면 아무것도 하지 않는다(요청당 비용 0)."""
    if not is_enabled(environ):
        return False
    threshold = _threshold_ms(environ)

    @app.before_request
    def _request_debug_start():
        global _inflight
        if should_skip(request.path):
            return
        with _inflight_lock:
            g._rdl_inflight = _inflight
            _inflight += 1
        g._rdl_t0 = time.perf_counter()
        g._rdl_cpu0 = time.thread_time()

    @app.after_request
    def _request_debug_status(response):
        if hasattr(g, '_rdl_t0'):
            g._rdl_status = response.status_code
        return response

    @app.teardown_request
    def _request_debug_end(exc):
        global _inflight
        start = g.pop('_rdl_t0', None)
        if start is None:
            return
        with _inflight_lock:
            _inflight = max(0, _inflight - 1)
        try:
            wall_ms = (time.perf_counter() - start) * 1000
            cpu_ms = (time.thread_time() - g._rdl_cpu0) * 1000
            status = getattr(g, '_rdl_status', 500 if exc is not None else 0)
            if wall_ms < threshold and status < 500:
                return
            kind = 'ERROR' if status >= 500 else 'SLOW'
            rule = request.url_rule.rule if request.url_rule is not None else '-'
            user_id = session.get('user_id', '-') if session else '-'
            _get_logger().info(format_line(kind, wall_ms, cpu_ms, g._rdl_inflight, request.method, rule,
                                           request.path, status, user_id, safe_query(request.args)))
        except Exception:
            pass  # 진단 훅이 응답에 영향을 주면 안 된다

    print(f"[RequestDebugLog] enabled: >= {threshold}ms or 5xx -> {_LOG_FILE}")
    return True
