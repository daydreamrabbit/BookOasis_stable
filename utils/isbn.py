"""Normalize ISBN-10/13 with check digit validation."""
import re


def normalize_isbn(value):
    value = re.sub(r'^ISBN(?:-1[03])?\s*[:：]?\s*', '', str(value or '').strip(), flags=re.I)
    value = re.sub(r'[\s\-‐‑‒–—]+', '', value).upper()
    if re.fullmatch(r'97[89]\d{10}', value):
        return value if sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(value)) % 10 == 0 else ''
    if re.fullmatch(r'\d{9}[\dX]', value) and value != '0000000000':
        return value if sum((10 if c == 'X' else int(c)) * (10-i) for i, c in enumerate(value)) % 11 == 0 else ''
    return ''


def mariadb_valid_isbn_expression(column):
    """SQL equivalent of normalize_isbn; never merge placeholder ISBNs."""
    # Avoid literal '?' even inside regexes: the DB adapter translates them
    # into bound placeholders before sending SQL to MariaDB.
    cleaned = f"REGEXP_REPLACE(REGEXP_REPLACE(UPPER(TRIM(COALESCE({column},''))), '^ISBN(-1[03]){{0,1}}[[:space:]]*[:：]{{0,1}}[[:space:]]*', ''), '[[:space:]‐‑‒–—-]+', '')"
    checksum13 = '+'.join(f'CAST(SUBSTRING({cleaned},{i},1) AS UNSIGNED)*{1 if i % 2 else 3}' for i in range(1,14))
    checksum10 = '+'.join(f'CAST(SUBSTRING({cleaned},{i},1) AS UNSIGNED)*{11-i}' for i in range(1,10))
    checksum10 += f"+IF(RIGHT({cleaned},1)='X',10,CAST(RIGHT({cleaned},1) AS UNSIGNED))"
    return f"CASE WHEN ({cleaned} REGEXP '^97[89][0-9]{{10}}$' AND MOD({checksum13},10)=0) OR ({cleaned} REGEXP '^[0-9]{{9}}[0-9X]$' AND {cleaned}<>'0000000000' AND MOD({checksum10},11)=0) THEN {cleaned} ELSE '' END"
