import sqlite3
import os
import unittest
from unittest.mock import patch
from repositories import rated_series_page as repo
from services.content_rating_service import ContentRatingService


class RatedPageTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:')
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript('''
            CREATE TABLE books(id INTEGER PRIMARY KEY,library_id INTEGER,series_name TEXT,
            title TEXT,title_alias TEXT,file_path TEXT,file_format TEXT,created_at TEXT,
            cover_image TEXT,cover_updated_at TEXT,cover_align TEXT,author TEXT,genre TEXT,
            tags TEXT,books_lv TEXT,publication_status TEXT,series_alias TEXT,metadata_locked INTEGER,
            is_deleted INTEGER,total_pages INTEGER DEFAULT 0);
            CREATE TABLE user_category_permissions(library_id INTEGER,user_id INTEGER,has_access INTEGER);
            CREATE TABLE user_favorites(book_id INTEGER,user_id INTEGER);
            CREATE TABLE user_progress(book_id INTEGER,user_id INTEGER,pages_read INTEGER,is_completed INTEGER);
            INSERT INTO user_category_permissions VALUES(1,1,1),(2,1,0);
        ''')
        # Keep the production close() path, but do not close this fixture per query.
        outer = self.conn
        class Connection:
            def __getattr__(self, name): return getattr(outer, name)
            def close(self): pass
        self.patches = [patch.object(repo.database,'get_connection',return_value=Connection()),
                        patch.object(repo.database,'is_mariadb_mode',return_value=False),
                        patch.object(ContentRatingService,'get_adult_keywords',return_value=['adult'])]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        self.addCleanup(self.conn.close)

    def add(self, id, series, rating='', lib=1, directory='/books/a', genre='', fmt='zip', cover=None):
        self.conn.execute('INSERT INTO books(id,library_id,series_name,title,title_alias,file_path,file_format,created_at,cover_image,cover_updated_at,cover_align,author,genre,tags,books_lv,publication_status,series_alias,metadata_locked,is_deleted) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
            (id,lib,series,str(id),'',directory+'/'+('__folder__.imgdir' if fmt=='imgdir' else str(id)+'.zip'),fmt,
             '2026-01-01',cover,'','center','author',genre,'',rating,'0','',0,0))

    def test_filter_before_grouping_and_paging(self):
        self.add(1,'[tag] A','adult only 18+',cover='hidden')
        self.add(2,'[tag] A','everyone')
        self.add(3,'[tag] A','everyone',cover='visible')
        self.add(4,'B','everyone',lib=2)
        self.add(5,'C','unknown')
        self.add(6,'D','everyone',genre='adult')
        self.add(7,'E','everyone',cover='allowed')
        rows=repo.fetch('general','all',1,15,limit=1)
        self.assertEqual(len(rows),1)
        self.assertEqual((rows[0]['id'],rows[0]['series_book_count'],rows[0]['cover_image']),(7,1,'allowed'))
        self.assertEqual(repo.fetch('general','all',1,15,totals=True),{'total_series_count':1,'total_book_count':1})
        self.assertEqual(repo.level_for_book('general',2),20)
        self.assertEqual(repo.fetch('general',1,1,20)[0]['series_level'],20)

    def test_sort_jump_and_different_folders_agree(self):
        for i, (name, folder) in enumerate([('B','a'),('[x] A','b'),('B','c'),('가','d')],1):
            self.add(i,name,directory='/'+folder)
        index=repo.fetch('general',1,1,18,index=True)
        pages=[repo.fetch('general',1,1,18,limit=1,offset=i)[0]['id'] for i in range(4)]
        self.assertEqual(pages,[r['id'] for r in index])
        self.assertEqual(pages,[2,1,3,4])
        self.assertEqual(repo.fetch('general',1,1,18,totals=True)['total_series_count'],4)

    def test_imgdir_siblings_and_favorites(self):
        self.add(1,'Images',directory='/series/01',fmt='imgdir')
        self.add(2,'Images',directory='/series/02',fmt='imgdir')
        self.assertEqual(repo.fetch('general',1,1,18)[0]['series_book_count'],2)
        self.conn.execute('INSERT INTO user_favorites VALUES(2,1)')
        self.assertEqual(repo.fetch('general','favorite',1,18)[0]['id'],2)

    def test_recent_badges_follow_authorized_folder_groups(self):
        from services import series_service
        from services.series_service import SeriesService
        self.add(1, 'A', 'everyone', directory='/allowed')
        self.add(2, 'A', 'everyone', directory='/allowed')
        self.add(3, 'A', 'adult only', directory='/hidden')
        self.add(4, 'A', 'everyone', directory='/hidden')
        self.add(5, 'A', 'everyone', lib=2, directory='/other-library')
        self.add(6, 'Old', 'everyone')
        self.conn.execute("UPDATE books SET created_at=datetime('now','-30 days')")
        self.conn.execute("UPDATE books SET created_at=datetime('now','-1 days') WHERE id IN (2,4,5)")
        visible = repo.fetch('general', 'all', 1, 15)
        entries = [{'representative_book_id': row['id']} for row in visible]
        series_service._RECENT_ADDED_CACHE.clear()
        self.addCleanup(series_service._RECENT_ADDED_CACHE.clear)
        with patch.object(series_service, '_sync_local_books_cache_with_shared_epoch'):
            decorated = SeriesService.annotate_recent_additions('general', entries)
        self.assertEqual([e['representative_book_id'] for e in decorated], [1, 6])
        self.assertEqual(decorated[0]['recent_added_count'], 1)
        self.assertFalse(decorated[0]['is_new_series'])

    def test_large_library_only_returns_requested_groups(self):
        self.conn.executemany("INSERT INTO books(id,library_id,series_name,title,file_path,file_format,books_lv) VALUES (?,1,?,'t','/books/file.zip','zip','everyone')",
                              ((i,'series%05d' % i) for i in range(1,10001)))
        self.assertEqual(len(repo.fetch('general',1,1,18,limit=31)),31)
        self.assertEqual(repo.fetch('general',1,1,18,totals=True)['total_book_count'],10000)

    def test_bare_adult_only_is_18_not_porn(self):
        self.add(1, 'A', 'adult only')
        self.assertEqual(repo.level_for_book('general', 1), 18)
        self.assertEqual(len(repo.fetch('general', 1, 1, 18)), 1)
        self.assertEqual(repo.fetch('general', 1, 1, 15), [])

    def test_unfavorited_high_rating_volume_blocks_entire_series(self):
        self.add(1,'A','everyone')
        self.add(2,'A','adult only 18+')
        self.conn.execute('INSERT INTO user_progress VALUES(1,1,10,1)')
        self.conn.execute('INSERT INTO user_favorites VALUES(1,1)')
        self.assertEqual(repo.fetch('general',1,1,18),[])
        self.assertEqual(repo.fetch('general','favorite',1,18),[])
        row=repo.fetch('general',1,1,20)[0]
        self.assertEqual((row['all_completed'],row['has_progress'],row['is_favorite']),(0,1,1))
        self.conn.execute('UPDATE books SET is_deleted=1 WHERE id=2')
        self.assertEqual(repo.fetch('general',1,1,18)[0]['series_level'],0)

    def test_root_directory_and_relative_file_do_not_merge(self):
        self.add(1,'A',directory='')
        self.add(2,'A',directory='relative')
        self.conn.execute("UPDATE books SET file_path='relative.zip' WHERE id=2")
        self.assertEqual(repo.fetch('general',1,1,18,totals=True)['total_series_count'],2)

    def test_low_volume_search_and_direct_link_cannot_bypass_series_rating(self):
        from services.series_service import _filter_rows_by_content_rating
        self.add(1,'A','everyone')
        self.add(2,'A','r18')
        low={'id':1,'library_id':1,'series_name':'A','file_path':'/books/a/1.zip','file_format':'zip','books_lv':'everyone'}
        self.assertEqual(_filter_rows_by_content_rating('general',[low],18),[])
        allowed=_filter_rows_by_content_rating('general',[low],19)
        self.assertEqual(allowed[0]['series_level'],19)
        with patch('repositories.book_repository.BookRepository.get_book_rating_info', return_value={'books_lv':'everyone'}):
            self.assertFalse(ContentRatingService.can_view_book('general',1,18))
            self.assertTrue(ContentRatingService.can_view_book('general',1,19))


@unittest.skipUnless(os.environ.get('TEST_RATED_MARIADB') == '1', 'optional real MariaDB temporary-table test')
class MariaRatedPageTests(RatedPageTests):
    def setUp(self):
        real = repo.database.get_connection('general')
        super().setUp()
        sqlite = self.conn
        cursor = real.cursor()
        for table in ('books','user_category_permissions','user_favorites','user_progress'):
            schema = sqlite.execute('SELECT sql FROM sqlite_master WHERE name=?',(table,)).fetchone()[0]
            cursor.execute(schema.replace('CREATE TABLE','CREATE TEMPORARY TABLE',1))
        cursor.execute('INSERT INTO user_category_permissions VALUES(1,1,1),(2,1,0)')
        class Connection:
            def execute(self, sql, params=()): return real.cursor().execute(sql, params)
            def executemany(self, sql, params): return real.cursor().executemany(sql, params)
            def cursor(self): return real.cursor()
            def close(self): pass
        self.conn = Connection()
        self.patches[0].stop()
        self.patches[1].stop()
        for p in [patch.object(repo.database,'get_connection',return_value=self.conn),
                  patch.object(repo.database,'is_mariadb_mode',return_value=True)]:
            p.start();self.addCleanup(p.stop)
        # Temporary tables disappear with this connection and never replace real data.
        def cleanup():
            for table in ('books','user_category_permissions','user_favorites','user_progress'):
                real.cursor().execute('DROP TEMPORARY TABLE IF EXISTS '+table)
            real.close()
        self.addCleanup(cleanup)


if __name__=='__main__': unittest.main()
