# -*- coding: utf-8 -*-
"""
user_problem_report_service.py – 일반 사용자의 [관리자에게 알리기] 접수 (알림센터 5단계)

설계: docs/plan_unified_notification_queue.md 2장 / 8장 5단계.
뷰어에서 도서를 열다 오류가 나면 그 자리에 [관리자에게 알리기]가 뜬다. 누르면 문제 기록에
code='user_report', source='viewer', severity='notice'로 남고, 관리자 알림센터의 일반 문제 카드
("사용자 신고 · <카테고리> · N권")로 보인다. 같은 도서를 다시 신고하면 횟수만 늘어난다.

- 신고한 사람이 볼 수 있는 도서만 받는다 (카테고리 권한·성인 권한 확인).
- 관리자 카드 상태만 바꾸는 통로라 쓰기량을 묶어 둔다: 사용자별 1시간 REPORTS_PER_HOUR건.
"""
import threading
import time

from services.problem_service import CODE_USER_REPORT, ProblemService, SEVERITY_NOTICE, make_series_key

REPORT_DB_TYPES = ('general', 'adult')
REPORTS_PER_HOUR = 30
_MESSAGE_MAX = 300
_WHERE_VALUES = ('viewer',)

_recent = {}
_lock = threading.Lock()


class ReportRejected(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _throttle(user_id):
    now = time.time()
    with _lock:
        stamps = [t for t in _recent.get(user_id, []) if now - t < 3600]
        if len(stamps) >= REPORTS_PER_HOUR:
            _recent[user_id] = stamps
            return False
        stamps.append(now)
        _recent[user_id] = stamps
        return True


def _visible_book(db_type, book_id, user_id, role):
    import database
    from repositories.user_repository import UserRepository
    from services.content_rating_service import ContentRatingService, get_user_content_rating_max
    from utils.permission_clause import build_library_permission_clause
    # Session roles/adult flags may be stale. Direct service callers must also
    # pass current account, category and highest-series-rating authorization.
    user = UserRepository.find_by_id('general', user_id) if user_id else None
    if not user:
        return None
    if db_type == 'adult' and user.get('has_adult_access') != 1:
        return None
    clause, params = build_library_permission_clause(user_id, user.get('role'), alias='b')
    with database.connection(db_type) as conn:
        cursor = conn.cursor()
        cursor.execute(
            f"SELECT b.id, b.title, b.file_path, b.library_id, b.series_name FROM books b WHERE b.id = ?{clause}",
            (int(book_id), *params),
        )
        row = cursor.fetchone()
    if not row or not ContentRatingService.can_view_book(db_type, book_id, get_user_content_rating_max(user)):
        return None
    return dict(row)


def report_book_problem(*, user_id, username, role, db_type, book_id, where='viewer', message='', file_format=''):
    """신고를 기록한다. 반환: {'book_id', 'title'}. 받을 수 없으면 ReportRejected."""
    db_type = str(db_type or 'general').strip().lower()
    if db_type not in REPORT_DB_TYPES:
        raise ReportRejected('지원하지 않는 도서 종류입니다.')
    try:
        book_id = int(book_id)
    except (TypeError, ValueError):
        raise ReportRejected('book_id가 필요합니다.')
    where = where if where in _WHERE_VALUES else 'viewer'
    book = _visible_book(db_type, book_id, user_id, role)
    if not book:
        raise ReportRejected('도서를 찾을 수 없습니다.', 404)
    if not _throttle(user_id):
        raise ReportRejected('잠시 후 다시 시도해 주세요.', 429)
    saved = ProblemService.report(
        CODE_USER_REPORT, 'book', book_id, db_type=db_type, library_id=book.get('library_id'),
        severity=SEVERITY_NOTICE, source=where, target_path=book.get('file_path'),
        series_key=make_series_key(book.get('library_id'), book.get('series_name')),
        message=str(message or '')[:_MESSAGE_MAX] or None,
        context={'reporter': username or str(user_id), 'reporter_id': user_id, 'where': where,
                 'format': str(file_format or '')[:16]},
    )
    if not saved:
        raise ReportRejected('신고를 저장하지 못했습니다. 잠시 후 다시 시도해 주세요.', 503)
    return {'book_id': book_id, 'title': book.get('title')}
