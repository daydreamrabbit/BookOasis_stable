import ast,pathlib,unittest,types,sqlite3,functools
from flask import Flask,request,session,jsonify
ROOT=pathlib.Path(__file__).resolve().parents[1]
def extract(path,name):
 node=next(n for n in ast.walk(ast.parse((ROOT/path).read_text())) if isinstance(n,ast.FunctionDef) and n.name==name)
 node.decorator_list=[];return node
def bind(path,name,scope):
 exec(compile(ast.fix_missing_locations(ast.Module(body=[extract(path,name)],type_ignores=[])),str(path),'exec'),scope);return scope[name]
class Changes(unittest.TestCase):
 def setUp(self):
  self.app=Flask('isolated');self.app.secret_key='test';self.calls=[]
  self.scope={'request':request,'session':session,'jsonify':jsonify,'SUPPORTED_CONTENT_RATING_LEVELS':[0,15,18,19,20]}
  calls=self.calls
  class Repo:
   @staticmethod
   def update_adult_access(*args):calls.append(('adult',args))
   @staticmethod
   def update_download_access(*args):calls.append(('download',args))
   @staticmethod
   def update_content_rating_max(*args):calls.append(('rating',args))
   @staticmethod
   def update_audiobook_access(*args):calls.append(('audiobook',args))
   @staticmethod
   def update_video_access(*args):calls.append(('video',args))
  self.scope['UserRepository']=Repo
 def test_existing_permission_routes_sync_four_dbs_and_self_session(self):
  for name,field,value in [('adult','has_adult_access',0),('download','has_download_access',1),('content_rating','content_rating_max',15),('audiobook','has_audiobook_access',0),('video','has_video_access',1)]:
   fn=bind('api/routes/permission_routes.py','update_'+name+'_permission',self.scope);self.calls.clear()
   with self.app.test_request_context(json={'user_id':3,field:value}):
    session.update(user_id=3,role='admin');response=fn()
    self.assertFalse(isinstance(response,tuple),(name,response[0].json if isinstance(response,tuple) else ''))
    self.assertTrue(response.json['success']);self.assertEqual(session[field],value)
   self.assertEqual([r[1][0] for r in self.calls],['general','adult','audiobook','video'])
 def test_invalid_rating_and_missing_user_do_not_write(self):
  for name,data in [('video',{}),('content_rating',{'user_id':3,'content_rating_max':999})]:
   fn=bind('api/routes/permission_routes.py','update_'+name+'_permission',self.scope)
   with self.app.test_request_context(json=data):self.assertEqual(fn()[1],400)
  self.assertEqual(self.calls,[])
 def test_new_video_route_retains_admin_and_login_protection(self):
  # The real decorator delegates login checks; isolate authentication side effects.
  scope={**self.scope,'wraps':functools.wraps,'login_required':lambda f:f,'_t':lambda key:key}
  admin=bind('api/auth.py','admin_required',scope)
  fn=admin(bind('api/routes/permission_routes.py','update_video_permission',self.scope))
  with self.app.test_request_context(json={'user_id':3,'has_video_access':True}):
   session.update(user_id=3,role='user');self.assertEqual(fn()[1],403)
  self.assertFalse(self.calls)
  tree=ast.parse((ROOT/'api/routes/permission_routes.py').read_text());node=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='update_video_permission')
  self.assertTrue(any(isinstance(d,ast.Name) and d.id=='admin_required' for d in node.decorator_list))
 def test_video_repository_query_and_rollback_for_both_engines(self):
  for engine,placeholder in [('sqlite','?'),('mariadb','%s')]:
   records=[]
   class Conn:
    def cursor(self):return self
    def execute(self,sql,params):records.append((sql,params))
    def commit(self):records.append('commit')
    def rollback(self):records.append('rollback')
    def close(self):records.append('close')
   conn=Conn();fn=bind('repositories/'+engine+'/user_repository.py','update_video_access',{'database':types.SimpleNamespace(get_connection=lambda db:conn)})
   self.assertTrue(fn('video',3,0));self.assertIn(placeholder,records[0][0]);self.assertEqual(records[0][1],(0,3));self.assertEqual(records[-2:],['commit','close'])
   def fail(*args):raise RuntimeError('failure')
   conn.execute=fail;records.clear()
   with self.assertRaises(RuntimeError):fn('video',3,1)
   self.assertEqual(records,['rollback','close'])
 def test_username_conflict_translation_without_database_writes(self):
  for error,expected in [(Exception(1062,'Duplicate entry'),409),(sqlite3.IntegrityError('UNIQUE constraint failed'),409),(Exception('offline'),500)]:
   def fail(*args):raise error
   scope={**self.scope,'UserRepository':types.SimpleNamespace(add_user=fail),'_reject_oversized_auth_request':lambda:None,'_validate_username_password_lengths':lambda *a:None,'generate_password_hash':lambda p:'fixture','_t':lambda key,**kwargs:key}
   fn=bind('api/auth.py','add_user',scope)
   with self.app.test_request_context(json={'username':'fixture','password':'fixture'}):
    session['role']='admin';self.assertEqual(fn()[1],expected)
 def test_adult_cancel_uses_own_db_and_queue_uses_general(self):
  source=(ROOT/'tools/scanner/engine.py').read_text();a=source.index('                is_cancelled = False',source.index('# Detect manual cancel'));b=source.index('                if is_cancelled:',a)
  body='def check():\n'+''.join(' '+line[16:]+'\n' for line in source[a:b].splitlines())+' return is_cancelled\n'
  for general,adult,queue,expected in [('cancelling','scanning',False,False),('scanning','cancelling',False,True),('scanning','scanning',True,True)]:
   calls=[]
   class Conn:
    def __init__(self,db):self.db=db
    def cursor(self):return self
    def execute(self,sql,args):self.sql=sql;calls.append((self.db,sql))
    def fetchone(self):return {'scan_status':adult if self.db=='adult' else general} if 'scan_status' in self.sql else ({'status':'cancelled'} if queue else None)
    def close(self):pass
   ns={'database':types.SimpleNamespace(get_connection=Conn),'db_type':'adult','library_id':3};exec(body,ns)
   self.assertEqual(ns['check'](),expected);self.assertEqual(calls[0][0],'adult')
   self.assertTrue(all(db=='general' for db,sql in calls if 'scanner_tasks' in sql))
if __name__=='__main__':unittest.main()
