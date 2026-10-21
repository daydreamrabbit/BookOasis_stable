# -*- coding: utf-8 -*-
"""느린 요청·서버 오류 기록(logs/request_debug.log) 요약 - 읽기 전용.

기록은 .env에 DEBUG_REQUEST_LOG=true일 때만 쌓인다(utils/request_debug_log.py). 웹 서비스가 도는 서버에서 실행:

    python tools/summarize_request_debug_log.py              # 최근 24시간
    python tools/summarize_request_debug_log.py --hours 72 --top 30
    python tools/summarize_request_debug_log.py --all        # 남아 있는 기록 전체
"""
import argparse
import os
import sys

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from utils.encoding_helper import force_utf8_stdio
force_utf8_stdio()

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(PROJECT_ROOT, '.env'))
except Exception:
    pass

from services.request_debug_summary import summarize, format_table


def main():
    parser = argparse.ArgumentParser(description='느린 요청·서버 오류 기록 요약 (읽기 전용)')
    parser.add_argument('--hours', type=float, default=24, help='최근 N시간 (기본 24)')
    parser.add_argument('--all', action='store_true', help='남아 있는 기록 전체')
    parser.add_argument('--top', type=int, default=20, help='경로 패턴 상위 N개 (기본 20)')
    args = parser.parse_args()
    print(format_table(summarize(None if args.all else args.hours, args.top)))


if __name__ == '__main__':
    main()
