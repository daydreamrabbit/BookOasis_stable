import contextlib,json,os,pathlib,sqlite3,tempfile,unittest
from unittest.mock import patch
from services.series_coverage import coverage
from services import advanced_search_service as service

class CoverageTest(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.filename=pathlib.Path(self.tmp.name)/'coverage.sqlite';self.maria=os.environ.get('TEST_BACKEND')=='mariadb'
  if self.maria:
   import pymysql
   self.driver=pymysql
   with contextlib.closing(self.connection(False)) as c:c.cursor().execute('CREATE DATABASE IF NOT EXISTS coverage_test');c.commit()
  with contextlib.closing(self.connection()) as c:
   q=c.cursor();q.execute('DROP TABLE IF EXISTS books');q.execute('CREATE TABLE books(id INTEGER PRIMARY KEY,library_id INTEGER,series_name VARCHAR(50),folder VARCHAR(50),title VARCHAR(200),metadata_title VARCHAR(100),document_volume_index DECIMAL(20,4),document_number DECIMAL(20,4),document_volume_count DECIMAL(20,4),publication_status VARCHAR(10))');c.commit()
  self.p=patch.object(service.database,'is_mariadb_mode',return_value=self.maria);self.p.start()
 def connection(self,selected=True):
  if self.maria:return self.driver.connect(host='127.0.0.1',user='root',password=os.environ['TEST_DB_PASSWORD'],database='coverage_test' if selected else None,cursorclass=self.driver.cursors.DictCursor,autocommit=False,charset='utf8mb4')
  c=sqlite3.connect(self.filename);c.row_factory=sqlite3.Row;return c
 def tearDown(self):self.p.stop();self.tmp.cleanup()
 def load(self,rows,status='0',count=None):
  with contextlib.closing(self.connection()) as c:
   q=c.cursor();q.execute('DELETE FROM books');ph='%s' if self.maria else '?'
   values=[(i+1,r.get('library_id',2),'Test',r.get('folder','/a'),r.get('title','Book'),r.get('metadata_title',''),r.get('document_volume_index'),r.get('document_number'),r.get('document_volume_count',count),status) for i,r in enumerate(rows)]
   q.executemany('INSERT INTO books VALUES ('+','.join([ph]*10)+')',values);c.commit()
 def sql_status(self):
  prefix="WITH scoped AS (SELECT id,library_id,series_name AS group_name,folder AS group_dir FROM books), grouped AS (SELECT MIN(id) AS representative_id,MIN(id) AS publication_status_id,library_id,series_name AS group_name,folder AS group_dir FROM books GROUP BY library_id,series_name,folder)"
  with contextlib.closing(self.connection()) as c:
   q=c.cursor();q.execute(service.status_query(prefix)+' SELECT representative_id,status FROM search_status ORDER BY representative_id');return [dict(r) for r in q.fetchall()]
 def test_31_only_and_metadata_untouched(self):
  rows=[{'document_volume_index':31}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'0')['holdings_label'],'1~30권 누락')
  with contextlib.closing(self.connection()) as c:q=c.cursor();q.execute('SELECT publication_status FROM books');self.assertEqual(q.fetchone()['publication_status'],'0')
 def test_all_numbered_and_ongoing_future_total(self):
  rows=[{'document_volume_index':v} for v in range(1,32)];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'0');self.assertEqual(coverage(rows,'0')['holdings_status'],'available')
  rows=[{'document_volume_index':1,'document_volume_count':5}]
  for status in ['0','1']:
   self.load(rows,status);self.assertEqual(self.sql_status()[0]['status'],status);self.assertEqual(coverage(rows,status)['holdings_status'],'available')
 def test_duplicate_fractional_extra_and_zero_do_not_fill_main_gap(self):
  rows=[{'document_volume_index':n} for n in [0,1,1,1.5,3]]+[{'document_volume_index':2,'metadata_title':'외전 2권'}]
  self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'0')['missing_ranges'],[[2,2]])
 def test_completed_tail_and_unknown_count(self):
  rows=[{'document_volume_index':1,'document_volume_count':3}]
  for status in ['2','']:
   self.load(rows,status);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,status)['missing_ranges'],[[2,3]])
  rows=[{'document_volume_count':3}];self.load(rows,'2');self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'2')['coverage_basis'],'count')
 def test_ambiguous_omnibus_not_false_missing(self):
  for title in ['1~3권 합본','1-3권','전권','상권','omnibus']:
   rows=[{'document_volume_index':3,'document_volume_count':3,'metadata_title':title}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'0',title);self.assertEqual(coverage(rows,'0')['holdings_status'],'unknown')
 def test_units_and_scope(self):
  rows=[{'document_number':31}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'0')['holdings_label'],'1~30화 누락')
  rows=[{'document_volume_index':1,'document_number':31}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'0');self.assertEqual(coverage(rows,'0')['holdings_status'],'available')
  rows=[{'document_volume_index':31}]+[{'document_volume_index':v,'folder':'/other'} for v in range(1,31)]
  self.load(rows);self.assertEqual([r['status'] for r in self.sql_status()],['missing','0'])
 def test_unknown_and_invalid(self):
  for number in [None,-1,'NaN','Infinity',1000001]:
   self.assertEqual(coverage([{'document_volume_index':number}],'0')['holdings_status'],'unknown')

 def test_standalone_sort_sentinels_are_not_volume_numbers(self):
  for number in [100000,100001,999999]:
   rows=[{'document_volume_index':number,'document_volume_count':1}]
   for status in [None,'','2']:
    self.load(rows,status);self.assertEqual(self.sql_status()[0]['status'],'2');self.assertNotEqual(coverage(rows,status)['holdings_status'],'missing')
 def test_sentinel_does_not_hide_real_31_gap_or_inflate_complete_series(self):
  rows=[{'document_volume_index':31,'document_volume_count':1}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'0')['holdings_label'],'1~30권 누락')
  rows=[{'document_volume_index':n} for n in range(1,32)]+[{'document_volume_index':100000,'document_volume_count':1}]
  self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'0');self.assertEqual(coverage(rows,'0')['holdings_status'],'available')
 def test_high_real_chapter_numbers_keep_their_own_range(self):
  rows=[{'document_number':100000}];self.load(rows);self.assertEqual(self.sql_status()[0]['status'],'missing');self.assertEqual(coverage(rows,'0')['coverage_basis'],'chapter')

if __name__=='__main__':unittest.main(verbosity=2)
