"""Isolated regression tests for the selected scanner and cover updates."""
import base64
import json
import os
import sqlite3
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from services import audiobook_scanner as scanner
from services.db_migration_service import _SCHEMA_SQL
from tools.scanner.sync_detector import detect_and_handle_book_movement
from utils.cover_helper import _source_signature


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'utf-32', 'cp949'])
def test_metadata_encoding_and_embedded_poster(tmp_path, encoding):
    data = {'title': '한글 제목', 'images': {'poster': 'hash'},
            'image_blobs': {'hash': {'encoding': 'base64', 'data': base64.b64encode(b'poster').decode()}}}
    path = tmp_path / 'metadata.json'
    path.write_bytes(json.dumps(data, ensure_ascii=False).encode(encoding))
    assert scanner.load_json_any_encoding(path)[0]['title'] == '한글 제목'
    assert scanner.read_metadata_json_cover(path) == b'poster'


def test_same_second_same_size_cover_replacement_invalidates_signature(tmp_path):
    path = tmp_path / 'cover.png'
    path.write_bytes(b'one')
    os.utime(path, ns=(1700000000000000000, 1700000000000000000))
    before = _source_signature(path)
    path.write_bytes(b'two')
    os.utime(path, ns=(1700000000000000001, 1700000000000000001))
    assert before != _source_signature(path)


@pytest.mark.parametrize('locked', [False, True])
def test_renamed_book_keeps_id_and_progress(tmp_path, locked, monkeypatch):
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    old = str(tmp_path / 'old.cbz')
    new = tmp_path / 'new.cbz'
    new.write_bytes(b'archive')
    stat = new.stat()
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('CREATE TABLE books(id INTEGER PRIMARY KEY,title TEXT,file_path TEXT,file_size INT,file_mtime REAL,metadata_locked INT); CREATE TABLE reading_progress(book_id INT,pages_read INT);')
    conn.execute('INSERT INTO books VALUES(1,?,?,?,?,?)', ('old', old, stat.st_size, stat.st_mtime, locked))
    conn.execute('INSERT INTO reading_progress VALUES(1,42)')
    mapping = {old: 1}
    missing = detect_and_handle_book_movement(conn.cursor(), mapping, {str(new)}, set(), set())
    assert not missing
    row = conn.execute('SELECT * FROM books').fetchone()
    assert row['id'] == 1 and row['file_path'] == str(new)
    assert row['title'] == ('old' if locked else 'new')
    assert conn.execute('SELECT pages_read FROM reading_progress WHERE book_id=1').fetchone()[0] == 42
    conn.close()


def test_ambiguous_same_name_moves_never_steal_another_books_history(tmp_path, monkeypatch):
    monkeypatch.setenv('DB_ENGINE', 'sqlite')
    paths = [str(tmp_path / folder / '01.cbz') for folder in ('oldA', 'oldB')]
    new = tmp_path / 'new' / '01.cbz'
    new.parent.mkdir()
    new.write_bytes(b'archive')
    cursor = Mock()
    cursor.fetchall.return_value = []
    missing = detect_and_handle_book_movement(cursor, dict(zip(paths, [1, 2])), {str(new)}, set(), set())
    assert missing == set(paths)
    assert not any(call.args[0].startswith('UPDATE') for call in cursor.execute.call_args_list)


def test_track_rename_preserves_track_id(tmp_path):
    new = tmp_path / 'renamed.mp3'
    new.write_bytes(b'audio')
    stat = new.stat()
    old = str(tmp_path / 'old.mp3')
    repo = SimpleNamespace(get_audiobook_tracks=lambda _: [{'id': 7, 'file_path': old, 'file_size': stat.st_size, 'file_mtime': stat.st_mtime}], update_track_paths=Mock())
    cache = {old: {'duration': 42}}
    assert scanner._keep_renamed_track_ids(repo, 1, str(tmp_path), cache) == 1
    repo.update_track_paths.assert_called_once_with([(7, str(new))])
    assert old not in cache and str(new) in cache


def test_new_schema_contains_audio_manual_metadata_lock():
    conn = sqlite3.connect(':memory:')
    conn.executescript(_SCHEMA_SQL)
    assert 'metadata_locked' in [row[1] for row in conn.execute('PRAGMA table_info(audiobooks)')]
    conn.close()


def test_scan_repository_protects_manual_edits_even_with_stale_scan_metadata(monkeypatch):
    from repositories.sqlite.audiobook_repository import AudiobookRepository as repo
    import database
    class Connection(sqlite3.Connection):
        def close(self):
            pass
    conn = sqlite3.connect(':memory:', factory=Connection)
    conn.row_factory = sqlite3.Row
    conn.executescript(_SCHEMA_SQL)
    monkeypatch.setattr(database, 'get_connection', lambda *_: conn)
    meta = dict(title='title', web_id='old', author='old', publisher='old', code='', poster='old', premiered='', ratings=0,
                author_intro='', description='old', folder_name='book', folder_path='/book', total_duration=0, total_tracks=0, file_type='multi')
    result = repo.save_audiobook_scan('/book', None, meta, [])
    aid = result['audiobook_id']
    assert repo.update_media_detail('title', 'manual', 'manual', 'manual', 'manual', 'manual', audiobook_id=aid)
    repo.save_audiobook_scan('/book', None, meta, [])
    row = conn.execute('SELECT * FROM audiobooks WHERE id=?', (aid,)).fetchone()
    for field in ('author', 'publisher', 'web_id', 'description', 'poster'):
        assert row[field] == 'manual'
    assert repo.unlock_metadata(aid)
    repo.save_audiobook_scan('/book', None, meta, [])
    assert conn.execute('SELECT author FROM audiobooks WHERE id=?', (aid,)).fetchone()[0] == 'old'
    sqlite3.Connection.close(conn)


def test_scan_cancelled_after_walk_never_hides_missing_books(tmp_path, monkeypatch):
    from repositories.audiobook_repository import AudiobookRepository as repo
    monkeypatch.setattr(repo, 'get_folder_rows', lambda _: [])
    monkeypatch.setattr(repo, 'get_track_signatures', lambda _: {})
    monkeypatch.setattr('services.category_service.CategoryService.is_music_library', lambda _: False)
    event = SimpleNamespace(is_set=lambda: True)
    hidden = Mock()
    monkeypatch.setattr(scanner, '_hide_unmatched_missing', hidden)
    monkeypatch.setattr(scanner, '_dispatch_audiobook_new_items_events', lambda *_: None)
    monkeypatch.setattr(scanner.os, 'walk', lambda _: iter(()))
    scanner.scan_audiobook_library(str(tmp_path), 1, cancel_event=event)
    hidden.assert_not_called()
