import contextlib,json,os,pathlib,sqlite3,tempfile,unittest
from unittest.mock import patch
from services import task_failure_reports as service

class FailureReports(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)/'fixture.sqlite';self.maria=os.environ.get('TEST_BACKEND')=='mariadb'
  if self.maria:
   import pymysql
   self.driver=pymysql
   with self.connection(False) as c:
    c.cursor().execute('CREATE DATABASE IF NOT EXISTS failure_report_test');c.commit()
  with contextlib.closing(self.connection()) as c:
   cur=c.cursor();cur.execute('DROP TABLE IF EXISTS scan_history');cur.execute('CREATE TABLE scan_history (id INTEGER PRIMARY KEY,task_type VARCHAR(40),status VARCHAR(20),kwargs TEXT,started_at VARCHAR(30),finished_at VARCHAR(30),error_message TEXT)')
   rows=[(1,'folder_watch','failed',json.dumps({'db_type':'general','library_id':2}),'2026-11-04 04:40:46','2026-11-04 04:40:52','대기 중 파일이 다시 변경되었습니다. 안정화 후 재시도합니다.\nTraceback (most recent call last):\nSECRET'),(2,'library_scan','failed',json.dumps({'db_type':'adult','library_id':2}),'2026-11-04','2026-11-04','성인 오류'),(3,'folder_watch','completed',json.dumps({'db_type':'general','library_id':2}),'2026-11-04','2026-11-04',None),(4,'folder_watch','failed','broken json','2026-11-04','2026-11-04','bad'),(5,'library_scan','cancelled',json.dumps({'library_id':2}),'2026-11-04','2026-11-04',None)]
   ph='%s' if self.maria else '?';cur.executemany('INSERT INTO scan_history VALUES ('+','.join([ph]*7)+')',rows);c.commit()
  self.patches=[patch.object(service.database,'is_mariadb_mode',return_value=self.maria),patch.object(service.database,'connection',side_effect=lambda db:self.context())]
  for p in self.patches:p.start()
 def connection(self,selected=True):
  if self.maria:return self.driver.connect(host='127.0.0.1',user='root',password=os.environ['TEST_DB_PASSWORD'],database='failure_report_test' if selected else None,cursorclass=self.driver.cursors.DictCursor,autocommit=False,charset='utf8mb4')
  c=sqlite3.connect(self.path);c.row_factory=sqlite3.Row;return c
 @contextlib.contextmanager
 def context(self):
  c=self.connection()
  try:yield c
  finally:c.close()
 def tearDown(self):
  for p in reversed(self.patches):p.stop()
  self.tmp.cleanup()
 def test_scope_status_and_historical_report(self):
  reports=service.list_task_reports('general',2);self.assertEqual({r['filename'] for r in reports},{'task-general-2-1.json','task-general-2-5.json'})
  report=service.task_report('task-general-2-1.json');self.assertIn('대기 중 파일',report['errors'][0]['message']);self.assertNotIn('SECRET',str(report));self.assertEqual(report['errors'][0]['error_type'],'작업 중단')
  self.assertIsNone(service.task_report('task-adult-2-1.json'));self.assertIsNone(service.task_report('task-general-3-1.json'));self.assertIsNone(service.task_report('task-general-2-3.json'))
  self.assertIn('저장된 상세 원인',service.task_report('task-general-2-5.json')['errors'][0]['message'])
  with contextlib.closing(self.connection()) as c:cur=c.cursor();cur.execute('SELECT COUNT(*) AS n FROM scan_history');self.assertEqual(cur.fetchone()['n'],5)
 def test_invalid_and_redaction(self):
  for value in ['task-general-2-1.json/../../x','task-bad-2-1.json','task-general-0-1.json']:
   with self.assertRaises(ValueError):service.task_report(value)
  text=service.failure_reason("failed '/private/some folder/book.cbz' token=abc123 https://u:p@example.test/x\nTraceback (most recent call last): secret",hide_paths=True)
  self.assertNotIn('/private',text);self.assertNotIn('abc123',text);self.assertNotIn('u:p',text);self.assertNotIn('secret',text)
 def test_admin_routes_file_and_task_reports(self):
  from flask import Flask
  from api.routes.report_routes import report_bp
  from utils import report_helper
  app=Flask('failure-route');app.secret_key='fixture';app.register_blueprint(report_bp);c=app.test_client()
  with patch.object(report_helper,'REPORTS_DIR',self.tmp.name):
   file=pathlib.Path(self.tmp.name)/'general-2_20261104040000.json';file.write_text(json.dumps({'errors_count':1,'errors':[{'filename':'original.cbz','error_type':'NoCover','message':'existing error'}]}))
   self.assertIn(c.get('/api/media/libraries/2/reports').status_code,[401,302])
   with c.session_transaction() as s:s.update(user_id=1,role='user')
   self.assertEqual(c.get('/api/media/libraries/2/reports').status_code,403)
   with c.session_transaction() as s:s['role']='admin'
   listing=c.get('/api/media/libraries/2/reports?type=general');self.assertEqual(listing.status_code,200);self.assertEqual(len(listing.json['reports']),3)
   detail=c.get('/api/media/libraries/reports/view?file=task-general-2-1.json');self.assertEqual(detail.status_code,200);self.assertIn('대기 중 파일',detail.json['report']['errors'][0]['message'])
   self.assertEqual(c.get('/api/media/libraries/reports/view?file=task-adult-2-1.json').status_code,404)
   old=c.get('/api/media/libraries/reports/view?file=general-2_20261104040000.json');self.assertEqual(old.json['report']['errors'][0]['filename'],'original.cbz')
   self.assertEqual(c.get('/api/media/libraries/2/reports?type=invalid').status_code,400)

if __name__=='__main__':unittest.main(verbosity=2)
