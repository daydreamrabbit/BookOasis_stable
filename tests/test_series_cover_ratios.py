import sqlite3
from contextlib import contextmanager
from flask import Flask
import pytest
import database
from api.routes import book_routes as routes
from services.category_service import CategoryService


@pytest.fixture
def client(monkeypatch):
    dbs = {}
    for kind in ('general','adult'):
        db = sqlite3.connect(':memory:'); db.row_factory = sqlite3.Row
        db.executescript("CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT); CREATE TABLE books(id INTEGER,library_id INTEGER,series_name TEXT,is_deleted INTEGER); INSERT INTO books VALUES(1,3,'series',0),(2,3,'series',0),(3,4,'series',0);")
        dbs[kind] = db
    @contextmanager
    def connection(kind):
        yield dbs[kind]
    monkeypatch.setattr(database,'connection',connection)
    monkeypatch.setattr(database,'is_mariadb_mode',lambda:False)
    monkeypatch.setattr(routes,'check_adult_permission',lambda kind:True)
    monkeypatch.setattr(routes,'check_book_rating_permission',lambda kind,book:True)
    monkeypatch.setattr(CategoryService,'get_libraries',lambda *a,**kw:[{'id':3}])
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(routes.book_routes_bp)
    with app.test_client() as client:
        with client.session_transaction() as s:s.update(user_id=1,role='admin',is_default_password=0)
        yield client
    for db in dbs.values():db.close()


@pytest.mark.parametrize('kind',['general','adult'])
def test_save_series_shared_by_volumes_and_reset(client,kind):
    url='/api/media/series/cover-ratios'
    one=client.post(url,json={'type':kind,'book_id':1,'ratio':'16:9'}).get_json()
    two=client.post(url,json={'type':kind,'book_id':2,'ratio':'16:9'}).get_json()
    assert one['success'] and one['key']==two['key']
    assert client.get(url+'?type='+kind).get_json()['ratios']=={one['key']:'16:9'}
    other='adult' if kind=='general' else 'general'
    assert client.get(url+'?type='+other).get_json()['ratios']=={}
    with client.session_transaction() as s:s['user_id']=2
    assert client.get(url+'?type='+kind).get_json()['ratios']=={}
    with client.session_transaction() as s:s['user_id']=1
    assert client.post(url,json={'type':kind,'book_id':1,'ratio':'inherit'}).get_json()['success']
    assert client.get(url+'?type='+kind).get_json()['ratios']=={}


def test_access_and_input_validation(client,monkeypatch):
    url='/api/media/series/cover-ratios'
    assert client.post(url,json={'type':'general','book_id':3,'ratio':'16:9'}).status_code==403
    assert client.post(url,json={'type':'general','book_id':1,'ratio':'x'}).status_code==400
    assert client.get(url+'?type=unknown').status_code==400
    monkeypatch.setattr(routes,'check_adult_permission',lambda kind:False)
    assert client.get(url+'?type=adult').status_code==403
