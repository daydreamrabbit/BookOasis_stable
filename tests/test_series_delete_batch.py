"""Run only against disposable databases; never delete production records."""
import os
import pytest

pytestmark = pytest.mark.skipif(os.getenv('BOOKOASIS_TEST_WATCH_DB') != '1', reason='disposable DB required')


@pytest.fixture
def books(tmp_path):
    import database
    database.init_databases()
    with database.connection('general') as conn:
        libraries = [conn.execute('INSERT INTO libraries(name,physical_path) VALUES (?,?)',
                     (str(tmp_path / str(i)), str(tmp_path / str(i)))).lastrowid for i in range(2)]
        ids = []
        for i, (library, series, cover) in enumerate([
            (libraries[0], 'one', 'shared.jpg'), (libraries[0], 'one', 'only.jpg'),
            (libraries[0], 'two', 'shared.jpg'), (libraries[1], 'one', 'shared.jpg'),
        ]):
            path = tmp_path / f'{i}.txt'
            path.write_text('original')
            ids.append(conn.execute('INSERT INTO books(library_id,title,series_name,file_path,file_format,total_pages,cover_image) '
                       'VALUES (?,?,?,?,?,10,?)', (library, series, series, str(path), 'txt', cover)).lastrowid)
        for book_id in ids:
            conn.execute('INSERT INTO user_progress(book_id,user_id,pages_read) VALUES (?,1,3)', (book_id,))
            conn.execute('INSERT INTO epub_bookmarks(book_id,user_id,format,chapter_idx,label) VALUES (?,1,\'txt\',2,\'note\')', (book_id,))
        conn.commit()
    return libraries, ids, tmp_path


def test_batch_deduplicates_and_preserves_other_library_shared_cover_originals(books):
    import database
    from repositories.series_delete_repository_shared import delete_series_batch
    libraries, ids, path = books
    result = delete_series_batch('general', [dict(book_id=i, library_id=libraries[0]) for i in ids[:3]], '?')
    assert sum(item['result']['deleted_count'] for item in result['results']) == 3
    assert result['unreferenced_media'] == ['only.jpg']
    with database.connection('general') as conn:
        assert conn.execute('SELECT id FROM books WHERE id=?', (ids[3],)).fetchone()
        for table in ('books', 'user_progress', 'epub_bookmarks'):
            field = 'id' if table == 'books' else 'book_id'
            assert not conn.execute(f'SELECT * FROM {table} WHERE {field} IN (?,?,?)', ids[:3]).fetchall()
    assert len(list(path.glob('*.txt'))) == 4


def test_library_mismatch_aborts_entire_batch_before_deleting(books):
    import database
    from repositories.series_delete_repository_shared import delete_series_batch
    libraries, ids, _ = books
    with pytest.raises(ValueError):
        delete_series_batch('general', [dict(book_id=ids[0], library_id=libraries[0]),
                           dict(book_id=ids[3], library_id=libraries[0])], '?')
    with database.connection('general') as conn:
        assert len(conn.execute('SELECT id FROM books WHERE id IN (?,?,?,?)', ids).fetchall()) == 4


def test_missing_anchor_does_not_block_valid_targets(books):
    from repositories.series_delete_repository_shared import delete_series_batch
    libraries, ids, _ = books
    result = delete_series_batch('general', [dict(book_id=99999999, library_id=libraries[0]),
                               dict(book_id=ids[0], library_id=libraries[0])], '?')
    assert not result['results'][0]['success']
    assert result['results'][1]['result']['deleted_count'] == 2


@pytest.mark.parametrize('targets', [None, [], [{}], [{'book_id': True, 'library_id': 1}],
    [{'book_id': 1, 'library_id': 1}] * 101])
def test_invalid_batch_rejected_before_lock(targets, monkeypatch):
    import services.series_delete_service as module
    monkeypatch.setattr(module, 'redis_acquire_lock', lambda *a, **kw: pytest.fail('invalid request took lock'))
    with pytest.raises(ValueError):
        module.SeriesDeleteService.delete_series_batch('general', targets)


def test_service_invalidates_caches_once_per_batch(books, monkeypatch):
    import services.series_delete_service as module
    libraries, ids, _ = books
    calls = []
    monkeypatch.setattr(module, 'redis_acquire_lock', lambda *a, **kw: 'token')
    monkeypatch.setattr(module, 'redis_release_lock', lambda *a: None)
    monkeypatch.setattr(module.SeriesDeleteService, '_delete_generated_media', lambda paths: ([], []))
    monkeypatch.setattr(module.SeriesService, 'invalidate_all_books_cache', lambda **kw: calls.append('invalidate'))
    monkeypatch.setattr(module, 'redis_delete_pattern', lambda pattern: calls.append(pattern))
    result = module.SeriesDeleteService.delete_series_batch('general',
             [dict(book_id=i, library_id=libraries[0]) for i in (ids[0], ids[2])])
    assert len(result['results']) == 2
    assert calls.count('invalidate') == 1
    assert len(calls) == 4


def test_sql_failure_rolls_back_prior_dependent_deletes(books, monkeypatch):
    import database
    import repositories.series_delete_repository_shared as module
    libraries, ids, _ = books
    monkeypatch.setattr(module, '_BOOK_DEPENDENT_TABLES', ('user_progress', 'nonexistent_test_table'))
    with pytest.raises(Exception):
        module.delete_series_batch('general', [dict(book_id=ids[0], library_id=libraries[0])], '?')
    with database.connection('general') as conn:
        assert conn.execute('SELECT * FROM user_progress WHERE book_id=?', (ids[0],)).fetchone()
        assert conn.execute('SELECT * FROM books WHERE id=?', (ids[0],)).fetchone()


def test_hundred_series_use_one_commit_and_eight_dependent_deletes(books, monkeypatch):
    import database
    from repositories.series_delete_repository_shared import delete_series_batch
    libraries, _, path = books
    targets = []
    with database.connection('general') as conn:
        for i in range(100):
            identifier = conn.execute('INSERT INTO books(library_id,title,series_name,file_path,file_format,total_pages) '
                'VALUES (?,?,?,?,\'txt\',1)', (libraries[0], f'batch{i}', f'batch{i}', str(path / f'batch{i}.txt'))).lastrowid
            targets.append(dict(book_id=identifier, library_id=libraries[0]))
        conn.commit()
    real_get = database.get_connection
    statements = []
    def traced(db_type):
        conn = real_get(db_type)
        conn.set_trace_callback(statements.append)
        return conn
    monkeypatch.setattr(database, 'get_connection', traced)
    result = delete_series_batch('general', targets, '?')
    assert sum(item['result']['deleted_count'] for item in result['results']) == 100
    assert sum(sql == 'COMMIT' for sql in statements) == 1
    assert sum('WHERE book_id IN' in sql for sql in statements) == 8


def test_generated_media_cannot_remove_original_outside_covers(tmp_path, monkeypatch):
    import services.series_delete_service as module
    covers = tmp_path / 'covers'
    covers.mkdir()
    original = tmp_path / 'original.txt'
    original.write_text('keep')
    (covers / 'generated.jpg').write_bytes(b'test')
    monkeypatch.setattr(module, 'get_covers_dir', lambda: str(covers))
    deleted, warnings = module.SeriesDeleteService._delete_generated_media(['../original.txt', 'generated.jpg'])
    assert original.read_text() == 'keep'
    assert deleted == ['generated.jpg'] and len(warnings) == 1
