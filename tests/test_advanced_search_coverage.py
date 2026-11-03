import sqlite3
import pytest
from services.db_migration_service import _SCHEMA_SQL
from services import advanced_search_service as service

@pytest.fixture
def db(tmp_path, monkeypatch):
    path = str(tmp_path / 'search.db')
    def connect(*a, **kw):
        c=sqlite3.connect(path);c.row_factory=sqlite3.Row;return c
    c=connect();c.executescript(_SCHEMA_SQL)
    for lib in (1,2,3):
        c.execute('INSERT INTO libraries(id,name,physical_path) VALUES (?,?,?)',(lib,str(lib),'/'+str(lib)))
    c.executemany('INSERT INTO user_category_permissions(user_id,library_id,has_access) VALUES (?,?,1)',[(1,1),(1,2),(2,3)])
    for row in [
        (1,1,'Alpha','/a/1.cbz','everyone','SF, 판타지','A','Writer','Artist','Pub','1'),
        (2,1,'Alpha','/a/2.cbz','r18','SF','B','Writer','Artist','Pub','1'),
        (3,1,'Beta','/b/1.cbz','everyone','SF','A','다른 작가','Kim','One','2'),
        (4,2,'Gamma','/g/1.cbz','everyone','판타지','B','Writer','Lee','Two','1'),
        (5,3,'Secret','/s/1.cbz','everyone','비밀장르','비밀태그','Hidden','Hidden','SecretPub','3'),
        (6,2,'Literal%_','/l/1.cbz','everyone','SFX','A','Writer','Lee','Two','2')]:
        c.execute('INSERT INTO books(id,library_id,series_name,file_path,books_lv,genre,tags,author,cover_artist,publisher,publication_status,file_format,title,total_pages) VALUES (?,?,?,?,?,?,?,?,?,?,?,\'cbz\',\'Book\',10)',row)
    c.commit();c.close()
    monkeypatch.setattr(service.database,'get_connection',connect)
    monkeypatch.setattr(service.database,'is_mariadb_mode',lambda:False)
    monkeypatch.setattr('services.content_rating_service.ContentRatingService.get_adult_keywords',lambda:[])
    return connect

def names(filters, rating=18, **kw):
    return [r['series_name'] for r in service.search('general',1,rating,filters,**kw)]

def test_highest_series_rating_precedes_filters(db):
    assert 'Alpha' not in names({'genre':['SF']})
    assert 'Alpha' in names({'genre':['SF']},20)

def test_categories_and_permissions(db):
    assert names({'categories':['3']})==[]
    assert set(names({'categories':['1','2']}))=={'Beta','Gamma','Literal%_'}

def test_and_or_and_token_boundaries(db):
    assert names({'genre':['SF','판타지'],'genre_mode':'and'})==[]
    assert names({'genre':['SF','판타지'],'genre_mode':'or'})==['Beta','Gamma']
    assert names({'genre':['SF'],'tags':['B']})==[]

def test_text_and_facets_combine(db):
    assert names({'author':'writer','cover_artist':'Lee','publisher':['Two'],'publication_status':['1']})==['Gamma']
    assert names({'series':'%_'})==['Literal%_']
    assert names({'series':"' OR 1=1 --"})==[]

def test_options_respect_categories_permissions_and_rating(db):
    options=service.options('general',1,18,['1'])
    assert options['publisher']==['One']
    assert options['genre']==['SF']
    assert options['rating']==['0']
    assert 'SecretPub' not in service.options('general',1,20,[])['publisher']
    assert service.options('general',1,18,['3'])['publisher']==[]

def test_totals_page_and_index_agree(db):
    f={'genre':['SF','판타지'],'genre_mode':'or'}
    totals=service.search('general',1,18,f,totals=True)
    assert totals['total_series_count']==2
    assert totals['total_book_count']==2
    assert names(f,index=True)==['Beta','Gamma']
    assert names(f,page=2,limit=1)==['Gamma']

def test_missing_volumes_are_not_completed_and_options_agree(db):
    c=db()
    c.execute('UPDATE books SET document_volume_count=3,document_volume_index=1 WHERE id=3')
    c.commit();c.close()
    assert names({'publication_status':['missing']})==['Beta']
    assert names({'publication_status':['2']})==['Literal%_']
    assert names({'publication_status':['missing']},index=True)==['Beta']
    assert service.search('general',1,18,{'publication_status':['missing']},totals=True)['total_series_count']==1
    assert 'missing' in service.options('general',1,18,['1'])['publication_status']
    assert '2' not in service.options('general',1,18,['1'])['publication_status']

def test_unknown_is_distinct_from_missing(db):
    c=db();c.execute('UPDATE books SET publication_status=NULL WHERE id=3');c.commit();c.close()
    assert names({'publication_status':['unknown']})==['Beta']
    assert names({'publication_status':['missing']})==[]

@pytest.mark.parametrize('column', ['document_volume_index', 'document_number'])
@pytest.mark.parametrize('total', [None, 0])
def test_empty_status_with_numbered_books_is_ongoing(db, column, total):
    c=db()
    c.execute(f"UPDATE books SET publication_status='',{column}=1,document_volume_count=? WHERE id=3", (total,))
    c.commit();c.close()
    f={'series':'Beta','publication_status':['0']}
    assert names(f)==['Beta']
    assert names({'series':'Beta','publication_status':['unknown']})==[]
    assert names(f,index=True)==['Beta']
    assert service.search('general',1,18,f,totals=True)['total_series_count']==1
    assert service.options('general',1,18,['1'])['publication_status']==['0']

@pytest.mark.parametrize('status', ['1','2'])
def test_explicit_status_precedes_numbered_book_fallback(db, status):
    c=db();c.execute('UPDATE books SET publication_status=?,document_volume_index=1 WHERE id=3',(status,));c.commit();c.close()
    assert names({'series':'Beta','publication_status':[status]})==['Beta']
    assert names({'series':'Beta','publication_status':['0']})==[]

def test_excluded_terms_hidden_and_cannot_search_stale_selection(db):
    import json
    c=db();c.execute('INSERT INTO settings (`key`,value) VALUES (?,?)',
        ('PLUGIN_CONFIG_rabbit_plugins',json.dumps({'exclude_genres':'sf','exclude_tags':'A'})))
    c.commit();c.close()
    options=service.options('general',1,18,[])
    assert 'SF' not in options['genre']
    assert 'SFX' in options['genre']
    assert 'A' not in options['tags']
    with pytest.raises(ValueError,match='제외'):
        names({'genre':['SF']})
    assert names({'genre':['SFX']})==['Literal%_']

def test_in_progress_remains_in_progress_with_partial_volumes(db):
    c=db();c.execute('UPDATE books SET document_volume_count=5,document_volume_index=1,publication_status=\'0\' WHERE id=4');c.commit();c.close()
    assert names({'publication_status':['0']})==['Gamma']
    assert names({'publication_status':['missing']})==[]

@pytest.mark.parametrize('value',[{'categories':['all']},{'rating':['999']},{'tags':'SF'},{'tags':['x']*201}])
def test_invalid_filters_rejected(value):
    with pytest.raises(ValueError):service.normalize(value)

def test_route_authentication_and_scoping(db):
    from flask import Flask
    from api.routes.advanced_search_routes import advanced_search_bp
    app=Flask(__name__);app.secret_key='test';app.register_blueprint(advanced_search_bp)
    client=app.test_client()
    assert client.get('/api/media/advanced-search/totals').status_code in (302,401)
    with client.session_transaction() as s:s.update(user_id=1,role='admin',is_default_password=0,content_rating_max=18)
    response=client.get('/api/media/advanced-search/totals')
    assert response.status_code==200
    assert response.json['total_series_count']==3
    assert client.get('/api/media/advanced-search/list?filters=bad').status_code==400

def test_single_late_volume_missing_on_all_search_paths(db):
    c=db();c.execute("UPDATE books SET publication_status='0',document_volume_index=31 WHERE id=3");c.commit();c.close()
    f={'series':'Beta','publication_status':['missing']}
    assert names(f)==['Beta']
    assert names(f,index=True)==['Beta']
    assert service.search('general',1,18,f,totals=True)['total_series_count']==1
    assert 'missing' in service.options('general',1,18,['1'])['publication_status']
    assert names({'series':'Beta','publication_status':['0']})==[]
    c=db();assert c.execute('SELECT publication_status FROM books WHERE id=3').fetchone()[0]=='0';c.close()

def test_detail_returns_separate_missing_badge_and_original_publication(db,monkeypatch,tmp_path):
    from services import book_detail_service as detail
    c=db();c.execute("UPDATE books SET publication_status='0',document_volume_index=31,metadata_title='31권' WHERE id=3");c.commit();c.close()
    monkeypatch.setattr(detail,'get_covers_dir',lambda:str(tmp_path))
    monkeypatch.setattr(detail,'resolve_series_cover',lambda **kwargs:None)
    meta,books=detail.BookDetailService.get_media_detail('general','Beta',1,1,role='admin',content_rating_max=18)
    assert meta['publication_status']=='0'
    assert meta['publication_status_label']=='연재'
    assert meta['holdings_status']=='missing'
    assert meta['holdings_label']=='1~30권 누락'
    assert meta['missing_ranges']==[[1,30]]
    assert [b['id'] for b in books]==[3]
