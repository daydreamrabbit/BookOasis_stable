import ast,contextlib,importlib.metadata as metadata,io,json,os,pathlib,tempfile,types,unittest
from unittest.mock import patch
from flask import Flask
from PIL import Image,UnidentifiedImageError
from utils.safe_image import open_image
from utils.safe_media import book_resource_response

APP_ROOT = pathlib.Path(__file__).resolve().parents[1]

class SecurityTests(unittest.TestCase):
 def test_resource_types(self):
  with Flask('resource').app_context():
   for mime in ['text/html','application/xhtml+xml','application/javascript','text/plain','application/pdf',None]:
    self.assertEqual(book_resource_response(b'fixture',mime)[1],415)
   for mime in ['image/png','image/jpeg','image/webp','image/gif','image/bmp','image/avif']:
    r=book_resource_response(b'fixture',mime);self.assertEqual(r.status_code,200);self.assertEqual(r.headers['X-Content-Type-Options'],'nosniff')
   svg=book_resource_response(b'<svg/>','image/svg+xml');self.assertIn('sandbox;',svg.headers['Content-Security-Policy']);self.assertIn("default-src 'none'",svg.headers['Content-Security-Policy'])
 def test_decoder_content_not_extension(self):
  for fmt in ['JPEG','PNG','WEBP','GIF','BMP']:
   buf=io.BytesIO();Image.new('RGB',(16,8)).save(buf,fmt);buf.seek(0)
   with open_image(buf) as im:self.assertEqual(im.size,(16,8))
  with tempfile.TemporaryDirectory() as d:
   p=pathlib.Path(d)/'fake.png';Image.new('RGB',(8,8)).save(p,'TIFF')
   with self.assertRaises(UnidentifiedImageError):open_image(p)
 def test_real_epub_route(self):
  import api.stream as stream
  app=Flask('epub');app.secret_key='isolated-test';app.register_blueprint(stream.stream_bp)
  with patch.object(stream,'check_adult_permission',return_value=True),patch.object(stream,'check_book_rating_permission',return_value=True),patch.object(stream.StreamService,'get_file_path',return_value='fixture.epub'),patch.object(stream.StreamService,'extract_epub_resource',return_value=(b'<p>fixture</p>','text/html',None)):
   client=app.test_client()
   self.assertEqual(client.get('/api/media/epub-image?book_id=1&path=f.html').status_code,401)
   with client.session_transaction() as s:s.update(user_id=1,role='admin')
   self.assertEqual(client.get('/api/media/epub-image?book_id=1&path=f.html').status_code,415)
   with patch.object(stream,'check_book_rating_permission',return_value=False):self.assertEqual(client.get('/api/media/epub-image?book_id=1&path=f.html').status_code,403)
 def test_download_redirect_permissions_and_incremental_scan(self):
  import api.routes.plugin_webview_routes as route
  from services.ssrf_guard import SSRFBlockedError
  app=Flask('download');app.secret_key='isolated-test';app.register_blueprint(route.plugin_webview_bp)
  with tempfile.TemporaryDirectory() as d:
   upstream=types.SimpleNamespace(headers={},url='https://fixture.test/pg11.epub',close=lambda:None)
   def writer(response,path,limit):pathlib.Path(path).write_bytes(b'fixture epub')
   with patch.object(route.CategoryRepository,'get_library_by_id',return_value={'physical_path':d}),patch.object(route.CategoryRepository,'check_user_category_access',return_value=True),patch.object(route.DomainWhitelistService,'get_patterns',return_value=['fixture.test']),patch.object(route,'fetch_with_redirect_revalidation',return_value=upstream),patch.object(route,'write_capped_to_file',side_effect=writer),patch('tools.scanner.core.scan_library_path') as scan,patch('services.scan_refresh_service.track_direct_scan',side_effect=lambda *a:contextlib.nullcontext()) as track:
    c=app.test_client();payload={'url':'https://fixture.test/11.epub.noimages','library_id':1}
    self.assertEqual(c.post('/api/webview/download',json=payload).status_code,401)
    with c.session_transaction() as s:s.update(user_id=1,role='admin',content_rating_max=20)
    r=c.post('/api/webview/download',json=payload);self.assertEqual(r.status_code,200);self.assertEqual(r.json['filename'],'pg11.epub');self.assertTrue(r.json['imported_as_book']);self.assertNotIn('folder',r.json)
    self.assertFalse(scan.call_args.kwargs['force']);self.assertTrue(track.called)
    r=c.post('/api/webview/download',json=payload);self.assertEqual(r.json['filename'],'pg11_1.epub')
    upstream.headers={'Content-Disposition':'attachment; filename="chosen.pdf"'}
    r=c.post('/api/webview/download',json=payload);self.assertEqual(r.json['filename'],'chosen.pdf')
    upstream.headers={};upstream.url='';payload['url']='https://fixture.test/original.epub'
    self.assertEqual(c.post('/api/webview/download',json=payload).json['filename'],'original.epub')
    old=len(list(pathlib.Path(d).iterdir()))
    with patch.object(route.CategoryRepository,'check_user_category_access',return_value=False):self.assertEqual(c.post('/api/webview/download',json=payload).status_code,403)
    self.assertEqual(len(list(pathlib.Path(d).iterdir())),old)
    with c.session_transaction() as s:s['content_rating_max']=18
    self.assertEqual(c.post('/api/webview/download',json=payload).status_code,403)
 def test_profile_avif_and_animated_avatar_preserved(self):
  from services import profile_bio_images as bio,user_profile_service as profile
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'PROFILE_BIO_IMAGE_DIR':d}),patch.object(bio.SettingsService,'get_user_value',return_value=''):
   b=io.BytesIO();Image.new('RGB',(64,32)).save(b,'AVIF');b.seek(0)
   url=bio.save_image(9,b);self.assertIn('/api/account/profile/bio-images/',url)
   frames=[Image.new('RGB',(32,32),color) for color in ['red','blue']];b=io.BytesIO();frames[0].save(b,'GIF',save_all=True,append_images=frames[1:],duration=[100,150],loop=0);b.seek(0)
   profile.save_custom_avatar_image(9,b,base_dir=d)
   p=profile.get_custom_avatar_path(9,base_dir=d)
   with Image.open(p) as im:self.assertTrue(im.is_animated);self.assertEqual(im.n_frames,2)
 def test_changed_python_syntax(self):
  for name in ['core.py','api/stream.py','api/routes/experimental_routes.py','api/routes/plugin_webview_routes.py','services/text_epub_content_service.py','tools/scanner/cover.py','tools/convert_covers_to_webp.py','tools/lazy_scanner.py','tools/migrator.py','utils/cover_helper.py','utils/safe_image.py','utils/safe_media.py']:
   p=APP_ROOT/name;ast.parse(p.read_text(encoding='utf8'),filename=str(p))
 def test_tts_isolation_embed_and_book_permissions(self):
  from api import api_bp
  app=Flask('tts',template_folder=str(APP_ROOT/'templates'));app.secret_key='isolated-tts';app.register_blueprint(api_bp)
  app.context_processor(lambda:{'static_asset_url':lambda n,**kw:'/static/'+n})
  c=app.test_client();self.assertEqual(c.get('/listen').status_code,302)
  with c.session_transaction() as s:s.update(user_id=1,role='user',is_default_password=0,has_adult_access=0)
  with patch('api.routes.tts_routes.check_book_rating_permission',return_value=True):
   for embed in [False,True]:
    r=c.get('/listen?book_id=1&db_type=general'+('&embed=1&autoplay=1' if embed else ''))
    self.assertEqual(r.status_code,200);self.assertEqual(r.headers['Cross-Origin-Opener-Policy'],'same-origin');self.assertEqual(r.headers['Cross-Origin-Embedder-Policy'],'require-corp');self.assertIn('data-embed="'+str(embed).lower()+'"',r.get_data(as_text=True))
  with patch('api.routes.tts_routes.check_book_rating_permission',return_value=False):self.assertEqual(c.get('/listen?book_id=1&db_type=general').status_code,403)

if __name__=='__main__':unittest.main(verbosity=2)
