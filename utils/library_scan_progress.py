import os


def format_library_scan_progress(phase, *, count=0, completed=0, total=0, current=''):
    """Format a readable scanner queue stage without exposing full file paths."""
    if phase == 'discover':
        return f'폴더 탐색 중 · {max(0, int(count)):,}개 방문'

    total = max(0, int(total))
    completed = min(total, max(0, int(completed)))
    if total == 0:
        return '처리 대상 도서 파일 없음 · 마무리 중'

    percent = int(completed * 100 / total)
    remaining = total - completed
    stage = f'도서 파일 {completed:,}/{total:,} ({percent}%) · 남음 {remaining:,}권'
    if remaining == 0:
        return f'{stage} · DB 반영 중'
    current_name = os.path.basename(str(current or '').rstrip('/\\'))
    if current_name:
        stage = f'{stage} · {current_name}'
    return stage
