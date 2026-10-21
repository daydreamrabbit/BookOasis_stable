import contextlib
import sqlite3
import unittest
from unittest.mock import patch

from services import embedded_metadata_refresh as refresh


class EmbeddedRefreshTest(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.db.execute('CREATE TABLE books (id INTEGER PRIMARY KEY,library_id INTEGER,series_name TEXT,title TEXT,file_path TEXT,file_format TEXT,metadata_locked INTEGER,is_deleted INTEGER,'+','.join(f'{f} TEXT' for f in refresh.FIELDS)+')')
        for ident,library,locked in [(1,10,0),(2,10,0),(3,20,0),(4,10,1)]:
            self.db.execute("INSERT INTO books(id,library_id,series_name,title,file_path,file_format,metadata_locked,is_deleted,genre,summary) VALUES(?,?,'series','title','file.epub','epub',?,0,'해외라이트노벨','수동 소개')",(ident,library,locked))
        self.db.commit()
        @contextlib.contextmanager
        def connection(*args):
            yield self.db
        self.connection = patch.object(refresh.database, 'connection', connection)
        self.connection.start()
        self.reader = patch.object(refresh, 'read_source', return_value={'genre':'라이트노벨, 해외라이트노벨'})
        self.reader.start()
        self.cache = patch('services.series_service.SeriesService.invalidate_all_books_cache')
        self.cache.start()
        self.redis = patch('utils.redis_helper.redis_delete_pattern')
        self.redis.start()
        self.payload={'type':'general','book_ids':[1],'scope':'series','fields':['genre'],'mode':'replace'}

    def tearDown(self):
        self.redis.stop();self.cache.stop();self.reader.stop();self.connection.stop();self.db.close()

    def approved(self):
        return {**self.payload,'approved':refresh.preview(self.payload)['entries']}

    def test_preview_and_apply_exact_scope_and_fields(self):
        payload=self.approved()
        self.assertEqual([e['id'] for e in payload['approved']],[1,2,4])
        self.assertEqual(self.db.execute('SELECT genre FROM books WHERE id=1').fetchone()[0],'해외라이트노벨')
        result=refresh.apply(payload)
        self.assertEqual(result['updated'],2)
        self.assertEqual(self.db.execute('SELECT genre FROM books WHERE id=3').fetchone()[0],'해외라이트노벨')
        self.assertEqual(self.db.execute('SELECT summary FROM books WHERE id=1').fetchone()[0],'수동 소개')
        self.assertEqual(self.db.execute('SELECT genre FROM books WHERE id=4').fetchone()[0],'해외라이트노벨')
        self.assertEqual(refresh.apply(self.approved())['updated'],0)

    def test_changed_database_is_not_overwritten(self):
        payload=self.approved()
        self.db.execute("UPDATE books SET genre='수동 변경' WHERE id=1");self.db.commit()
        result=refresh.apply(payload)
        self.assertEqual(result['updated'],1)
        self.assertEqual(self.db.execute('SELECT genre FROM books WHERE id=1').fetchone()[0],'수동 변경')

    def test_changed_source_and_new_lock_are_protected(self):
        payload=self.approved()
        with patch.object(refresh,'read_source',return_value={'genre':'다른 원본'}):
            self.assertEqual(refresh.apply(payload)['updated'],0)
        self.db.execute('UPDATE books SET metadata_locked=1 WHERE id=1');self.db.commit()
        self.assertEqual(refresh.apply(payload)['updated'],1)

    def test_missing_values_do_not_clear_and_failures_are_reported(self):
        with patch.object(refresh,'read_source',return_value={}):
            self.assertFalse(refresh.preview(self.payload)['entries'][0]['changes'])
        with patch.object(refresh,'read_source',side_effect=ValueError('원본 없음')):
            self.assertIn('원본 없음',refresh.preview(self.payload)['entries'][0]['error'])

    def test_merge_preserves_custom_genres(self):
        self.db.execute("UPDATE books SET genre='사용자 장르' WHERE id=1");self.db.commit()
        self.payload['mode']='merge'
        refresh.apply(self.approved())
        self.assertEqual(self.db.execute('SELECT genre FROM books WHERE id=1').fetchone()[0],'사용자 장르, 라이트노벨, 해외라이트노벨')

    def test_invalid_fields_and_targets_rejected(self):
        for values in [{'fields':['file_path']},{'book_ids':[True]},{'type':'other'},{'fields':['author'],'mode':'merge'}]:
            with self.assertRaises(ValueError):refresh.preview({**self.payload,**values})
        payload=self.approved();payload['approved'].append({'id':3,'changes':{}})
        with self.assertRaises(ValueError):refresh.apply(payload)

    def test_route_requires_admin_and_valid_action(self):
        from flask import Flask
        from api.routes.scan_routes import scan_bp
        app=Flask(__name__);app.config.update(TESTING=True,SECRET_KEY='refresh-test')
        app.register_blueprint(scan_bp);client=app.test_client()
        with client.session_transaction() as session:
            session['user_id']=1;session['role']='user';session['is_default_password']=0
        self.assertEqual(client.post('/api/media/books/embedded-metadata-refresh',json={**self.payload,'action':'preview'}).status_code,403)
        with client.session_transaction() as session:session['role']='admin'
        self.assertEqual(client.post('/api/media/books/embedded-metadata-refresh',json={**self.payload,'action':'preview'}).status_code,200)
        self.assertEqual(client.post('/api/media/books/embedded-metadata-refresh',json={**self.payload,'action':'invalid'}).status_code,400)


if __name__=='__main__':unittest.main()
