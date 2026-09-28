"""Shared cancellation signal for scanner jobs.

The queue worker and the scanner engine need to agree that a scan was
cancelled. Keeping the exception in a small dependency-free module avoids a
circular import between the worker and the scanner engine.
"""


class ScanCancelledError(Exception):
    """사용자 요청으로 스캔이 안전하게 중단되었음을 나타내는 예외."""

