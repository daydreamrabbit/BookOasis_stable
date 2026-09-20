"""Pure helpers for presenting Lazy-Scanner progress across worker restarts."""


def advance_lazy_scan_progress_state(previous_state, current_remaining):
    """Track a stable denominator and candidate reduction between scan batches."""
    try:
        current_remaining = max(0, int(current_remaining))
    except (TypeError, ValueError):
        current_remaining = 0

    previous_state = previous_state if isinstance(previous_state, dict) else {}
    try:
        total = max(0, int(previous_state.get('total', current_remaining)))
    except (TypeError, ValueError):
        total = current_remaining
    try:
        previous_remaining = max(0, int(previous_state.get('remaining', total)))
    except (TypeError, ValueError):
        previous_remaining = total

    # 새로 발견된 후보는 총량에 반영하되, 기존 후보 감소분은 유지한다.
    if current_remaining > previous_remaining:
        total += current_remaining - previous_remaining
    candidate_reduction = max(0, total - current_remaining)
    return {'total': total, 'remaining': current_remaining}, candidate_reduction
