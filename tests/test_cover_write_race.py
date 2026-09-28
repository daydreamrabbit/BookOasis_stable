"""Exercise the actual Lazy Scanner SQL against concurrent cover/path changes."""
import ast
import sqlite3
from pathlib import Path
import pytest


@pytest.mark.parametrize('winner', ['external.webp', 'moved', 'locked', 'unchanged'])
def test_lazy_cover_compare_and_swap(winner):
    tree = ast.parse(Path('tools/lazy_scanner.py').read_text())
    queries = [node.value for node in ast.walk(tree) if isinstance(node, ast.Constant)
               and isinstance(node.value, str) and 'UPDATE books SET' in node.value
               and "AND file_path = ? AND COALESCE(cover_image, '') = ?" in node.value]
    assert len(queries) == 2
    for query in queries:
        with sqlite3.connect(':memory:') as db:
            db.execute('CREATE TABLE books(id INTEGER, file_path TEXT, cover_image TEXT, metadata_locked INTEGER, cover_updated_at TEXT)')
            path = '/new' if winner == 'moved' else '/old'
            cover = 'external.webp' if winner == 'external.webp' else ''
            db.execute('INSERT INTO books VALUES(1,?,?,?,NULL)', (path, cover, int(winner == 'locked')))
            result = db.execute(query, ('internal.webp', 1, '/old', ''))
            assert result.rowcount == int(winner == 'unchanged')
            assert db.execute('SELECT cover_image FROM books').fetchone()[0] == ('internal.webp' if winner == 'unchanged' else cover)
