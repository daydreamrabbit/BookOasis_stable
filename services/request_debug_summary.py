# -*- coding: utf-8 -*-
"""logs/request_debug.log(DEBUG_REQUEST_LOG=true일 때 쌓임) 요약 - CLI(tools/summarize_request_debug_log.py)와 MCP가 함께 쓴다.

경로 패턴(rule)별로 건수·느림/오류 수·처리 시간 분포·CPU 비중·겹친 요청 수를 묶는다.
  cpu_share   = cpu/wall 평균. 1에 가까우면 그 요청 자체가 CPU를 쓰는 것(코드 개선 대상)
  contention  = CPU는 거의 안 썼는데(<30%) 다른 요청이 2개 이상 처리 중이던 건 - 단일 워커 GIL/대기열로 밀린 것으로 의심
"""
import os
import time
from datetime import datetime, timedelta

LOG_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs', 'request_debug.log')


def _parse_line(line):
    parts = line.rstrip('\n').split('\t')
    if len(parts) < 3:
        return None
    try:
        row = {'ts': datetime.strptime(parts[0], '%Y-%m-%d %H:%M:%S'), 'kind': parts[1]}
    except ValueError:
        return None
    for part in parts[2:]:
        key, _, value = part.partition('=')
        row[key] = value
    try:
        row['wall'] = float(row.get('wall', 0))
        row['cpu'] = float(row.get('cpu', 0))
        row['inflight'] = int(row.get('inflight', 0))
        row['status'] = int(row.get('status', 0))
    except ValueError:
        return None
    return row


def _percentile(sorted_values, pct):
    if not sorted_values:
        return 0.0
    index = min(len(sorted_values) - 1, max(0, int(round((pct / 100.0) * (len(sorted_values) - 1)))))
    return sorted_values[index]


def read_rows(hours=None, log_file=LOG_FILE):
    files = [f"{log_file}.{i}" for i in (3, 2, 1)] + [log_file]  # RotatingFileHandler 순서(오래된 것부터)
    since = datetime.now() - timedelta(hours=hours) if hours else None
    rows = []
    for path in files:
        if not os.path.isfile(path):
            continue
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                row = _parse_line(line)
                if row and (since is None or row['ts'] >= since):
                    rows.append(row)
    return rows


def summarize(hours=24, top=20, log_file=LOG_FILE):
    enabled = str(os.environ.get('DEBUG_REQUEST_LOG', 'false')).strip().lower() in ('1', 'true', 'yes', 'on')
    rows = read_rows(hours, log_file)
    groups = {}
    for row in rows:
        key = f"{row.get('method', '-')} {row.get('rule', '-')}"
        groups.setdefault(key, []).append(row)

    endpoints = []
    for key, items in groups.items():
        walls = sorted(r['wall'] for r in items)
        shares = [min(1.0, r['cpu'] / r['wall']) for r in items if r['wall'] > 0]
        contention = sum(1 for r in items if r['wall'] > 0 and r['cpu'] / r['wall'] < 0.3 and r['inflight'] >= 2)
        statuses = sorted({r['status'] for r in items if r['status'] >= 500})
        endpoints.append({
            'endpoint': key,
            'count': len(items),
            'slow': sum(1 for r in items if r['kind'] == 'SLOW'),
            'errors': sum(1 for r in items if r['kind'] == 'ERROR'),
            'error_statuses': statuses,
            'p50_ms': round(_percentile(walls, 50)),
            'p95_ms': round(_percentile(walls, 95)),
            'max_ms': round(walls[-1]) if walls else 0,
            'cpu_share': round(sum(shares) / len(shares), 2) if shares else 0.0,
            'avg_inflight': round(sum(r['inflight'] for r in items) / len(items), 1),
            'contention': contention,
            'example_path': items[-1].get('path', ''),
        })
    endpoints.sort(key=lambda e: (e['errors'], e['count'] * e['p50_ms']), reverse=True)

    return {
        'enabled': enabled,
        'log_file': log_file,
        'hours': hours,
        'total': len(rows),
        'slow': sum(1 for r in rows if r['kind'] == 'SLOW'),
        'errors': sum(1 for r in rows if r['kind'] == 'ERROR'),
        'first_at': rows[0]['ts'].strftime('%Y-%m-%d %H:%M:%S') if rows else None,
        'last_at': rows[-1]['ts'].strftime('%Y-%m-%d %H:%M:%S') if rows else None,
        'endpoints': endpoints[:max(1, int(top))],
        'generated_at': time.strftime('%Y-%m-%d %H:%M:%S'),
    }


def format_table(summary):
    lines = []
    state = '켜짐' if summary['enabled'] else '꺼짐(.env DEBUG_REQUEST_LOG=true로 켜야 쌓임)'
    period = f"최근 {summary['hours']:g}시간" if summary['hours'] else '남은 기록 전체'
    lines.append(f"기록: {state} | {period} | 전체 {summary['total']}건 (느림 {summary['slow']}, 오류 {summary['errors']})"
                 + (f" | {summary['first_at']} ~ {summary['last_at']}" if summary['total'] else ''))
    if not summary['endpoints'] or not summary['total']:
        lines.append('기록된 요청이 없습니다.')
        return '\n'.join(lines)
    lines.append(f"{'endpoint':58} {'건수':>4} {'오류':>4} {'p50':>6} {'p95':>6} {'max':>6} {'CPU비중':>7} {'겹침평균':>8} {'경합의심':>8}")
    for e in summary['endpoints']:
        lines.append(f"{e['endpoint'][:58]:58} {e['count']:>4} {e['errors']:>4} {e['p50_ms']:>6} {e['p95_ms']:>6} {e['max_ms']:>6} "
                     f"{e['cpu_share']:>7} {e['avg_inflight']:>8} {e['contention']:>8}")
    lines.append('읽는 법: CPU비중이 1에 가까우면 그 요청 자체가 무거움(코드 개선), CPU비중은 낮고 경합의심이 많으면 다른 요청과 겹쳐 밀린 것.')
    return '\n'.join(lines)
