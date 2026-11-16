"""Computed holdings only; never rewrite publication metadata or inspect archives."""
from decimal import Decimal, InvalidOperation
import re

MAX_ORDINAL = 1000000
# Existing standalone/special sort keys start at 100000; they are not volume ordinals.
MAX_VOLUME_ORDINAL = 99999
AMBIGUOUS_MARKERS = ('합본', '전권', '옴니버스', 'omnibus', '~', '～', '–', '—', '-', '_', '상권', '하권', '중권')
EXTRA_MARKERS = ('외전', '번외', '특별편')


def ordinal(value):
    try:
        number = Decimal(str(value))
        return int(number) if number.is_finite() and 1 <= number <= MAX_ORDINAL and number == number.to_integral_value() else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def _label(row):
    text = str(row.get('metadata_title') or row.get('title') or '').replace(str(row.get('series_name') or ''), '')
    return text.strip().lower()


def coverage(rows, publication_status=''):
    rows = list(rows)
    main = [r for r in rows if not any(marker in _label(r) for marker in EXTRA_MARKERS)]
    if any(any(marker in _label(r) for marker in AMBIGUOUS_MARKERS) for r in main):
        return dict(holdings_status='unknown', holdings_label='', missing_ranges=[], coverage_basis='ambiguous')
    volumes = {n for r in main if (n := ordinal(r.get('document_volume_index'))) is not None and n <= MAX_VOLUME_ORDINAL}
    chapters = {n for r in main if (n := ordinal(r.get('document_number'))) is not None}
    seen, unit = (volumes, '권') if volumes else (chapters, '화')
    expected = max((ordinal(r.get('document_volume_count')) or 0 for r in main), default=0)
    if not seen:
        if expected and str(publication_status) not in ('0', '1') and len(rows) < expected:
            return dict(holdings_status='missing', holdings_label=f'보유 {len(rows)}/{expected}개 · 누락', missing_ranges=[], coverage_basis='count')
        return dict(holdings_status='unknown', holdings_label='', missing_ranges=[], coverage_basis='unknown')
    upper = max(seen)
    if str(publication_status) not in ('0', '1'):
        upper = max(upper, expected)
    missing = []
    cursor = 1
    for n in sorted(seen):
        if n > cursor:
            missing.append([cursor, n - 1])
        cursor = n + 1
    if cursor <= upper:
        missing.append([cursor, upper])
    label = ', '.join(str(a) if a == b else f'{a}~{b}' for a,b in missing[:8])
    if len(missing) > 8:
        label += f' 외 {len(missing)-8}구간'
    return dict(holdings_status='missing' if missing else 'available',
                holdings_label=f'{label}{unit} 누락' if missing else '',
                missing_ranges=missing[:100], coverage_basis='volume' if volumes else 'chapter')


def coverage_sql(alias='m', mariadb=False):
    cast = 'SIGNED' if mariadb else 'INTEGER'
    label = f"LOWER(TRIM(REPLACE(COALESCE(NULLIF({alias}.metadata_title,''),{alias}.title,''),COALESCE({alias}.series_name,''),'')))"
    def contains(markers):
        return '('+' OR '.join(f"INSTR({label},'{marker}')>0" for marker in markers)+')'
    extra = contains(EXTRA_MARKERS)
    ambiguous = contains(AMBIGUOUS_MARKERS)
    def number(field):
        expr = f'{alias}.{field}'
        upper = MAX_VOLUME_ORDINAL if field == 'document_volume_index' else MAX_ORDINAL
        return f'CASE WHEN NOT {extra} AND {expr} BETWEEN 1 AND {upper} AND {expr}=CAST({expr} AS {cast}) THEN {expr} END'
    volume, chapter, expected = (number(k) for k in ('document_volume_index','document_number','document_volume_count'))
    return f'''MAX(COALESCE({expected},0)) AS expected,
               MAX(COALESCE({volume},0)) AS last_volume,
               COUNT(*) AS files,
               COUNT(DISTINCT {volume}) AS volumes,
               COUNT(DISTINCT {chapter}) AS chapters,
               MAX(COALESCE({chapter},0)) AS last_chapter,
               MAX(CASE WHEN NOT {extra} AND {ambiguous} THEN 1 ELSE 0 END) AS ambiguous'''


def missing_sql(alias='c'):
    return (f"({alias}.ambiguous=0 AND (({alias}.volumes>0 AND {alias}.volumes<{alias}.last_volume) "
            f"OR ({alias}.volumes=0 AND {alias}.chapters>0 AND {alias}.chapters<{alias}.last_chapter)))")


def resolve_status_label(rows, publication_status='', book_count=None):
    """Resolve display status from saved source status and file-level evidence."""
    rows = list(rows or ())
    try:
        count = int(book_count) if book_count is not None else len(rows)
    except (TypeError, ValueError, OverflowError):
        count = len(rows)

    standalone = re.compile(r'[（(]\s*단편\s*[)）]')
    completed = re.compile(r'[（(]\s*완결\s*[)）]')
    paths = [str(row.get('file_path') or '') for row in rows]
    titles = [str(row.get(field) or '') for row in rows
              for field in ('title', 'metadata_title', '_volume_title')]
    if count == 1 and any(standalone.search(value) for value in paths + titles):
        return '단편'
    if any(completed.search(path) for path in paths):
        return '완결'

    volumes = {
        value for row in rows
        if (value := ordinal(row.get('document_volume_index'))) is not None
        and value <= MAX_VOLUME_ORDINAL
    }
    expected = max((ordinal(row.get('document_volume_count')) or 0 for row in rows), default=0)
    expected_volumes = {value for value in volumes if value <= expected}
    if expected > 0 and len(expected_volumes) == expected:
        return '완결'

    labels = {'0': '연재', '1': '휴재', '2': '완결'}
    status = str(publication_status or '').strip()
    if status in labels:
        return labels[status]

    has_volume_or_chapter = False
    for row in rows:
        for field, maximum in (('document_volume_index', MAX_VOLUME_ORDINAL),
                               ('document_number', MAX_ORDINAL)):
            try:
                value = Decimal(str(row.get(field)))
            except (InvalidOperation, ValueError, TypeError):
                continue
            if value.is_finite() and 0 < value <= maximum:
                has_volume_or_chapter = True
                break
        if has_volume_or_chapter:
            break
    return '연재' if has_volume_or_chapter else '알 수 없음'
