"""Explicit opt-in against a disposable MariaDB, with no production credentials."""
import os
import uuid
import pytest

pytestmark = pytest.mark.skipif(os.getenv('BOOKOASIS_DISPOSABLE_MARIADB') != '1', reason='disposable MariaDB required')


def test_mariadb_bulk_transaction_and_shared_media(monkeypatch):
    import pymysql
    import database
    from repositories.series_delete_repository_shared import delete_series_batch, _BOOK_DEPENDENT_TABLES
    name = 'delete_test_' + uuid.uuid4().hex
    options = dict(host='127.0.0.1', user='root', password='', cursorclass=pymysql.cursors.DictCursor)
    admin = pymysql.connect(**options, autocommit=True)
    admin.cursor().execute(f'CREATE DATABASE {name}')
    try:
        def connect(_db_type):
            return pymysql.connect(**options, database=name, autocommit=False)
        monkeypatch.setattr(database, 'get_connection', connect)
        conn = connect('general')
        with conn.cursor() as cur:
            cur.execute('CREATE TABLE books (id INT PRIMARY KEY, library_id INT, title VARCHAR(255), '
                        'series_name VARCHAR(255), file_path VARCHAR(255), cover_image VARCHAR(255), '
                        'banner_image VARCHAR(255), is_deleted INT DEFAULT 0)')
            for table in _BOOK_DEPENDENT_TABLES:
                cur.execute(f'CREATE TABLE {table} (book_id INT)')
                cur.executemany(f'INSERT INTO {table} VALUES (%s)', [(i,) for i in range(1, 102)])
            cur.execute('CREATE TABLE folder_mtimes (folder_path VARCHAR(255))')
            cur.execute('CREATE TABLE series_summary (library_id INT, series_key VARCHAR(255))')
            cur.execute('CREATE TABLE collections (cover_image VARCHAR(255))')
            cur.executemany('INSERT INTO books(id,library_id,title,series_name,file_path,cover_image) '
                            'VALUES (%s,1,%s,%s,%s,%s)',
                            [(i, f's{i}', f's{i}', f'/original/{i}.txt', 'shared.jpg' if i % 2 else 'unique.jpg')
                             for i in range(1, 102)])
        conn.commit()
        targets = [dict(book_id=i, library_id=1) for i in range(1, 101)]
        with pytest.raises(ValueError):
            delete_series_batch('general', targets + [dict(book_id=101, library_id=2)], '%s')
        result = delete_series_batch('general', targets, '%s')
        assert sum(item['result']['deleted_count'] for item in result['results']) == 100
        assert result['unreferenced_media'] == ['unique.jpg']
        with conn.cursor() as cur:
            cur.execute('SELECT id FROM books')
            assert cur.fetchall() == [{'id': 101}]
            for table in _BOOK_DEPENDENT_TABLES:
                cur.execute(f'SELECT book_id FROM {table}')
                assert cur.fetchall() == [{'book_id': 101}]
        conn.close()
    finally:
        admin.cursor().execute(f'DROP DATABASE {name}')
        admin.close()
