from contextlib import nullcontext
import sqlite3
from unittest.mock import patch

import pytest
from flask import Flask
from repositories.sqlite.book_repository import BookRepository
from services.library_service import LibraryService
from api.routes.plugin_webview_routes import plugin_webview_bp
from api.routes.book_routes import book_routes_bp


@pytest.fixture
def facet_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE books (id INTEGER, library_id INTEGER, tags TEXT, genre TEXT,
                            books_lv INTEGER, is_deleted INTEGER DEFAULT 0);
        CREATE TABLE user_category_permissions (user_id INTEGER, library_id INTEGER, has_access INTEGER);
        CREATE TABLE user_favorites (user_id INTEGER, book_id INTEGER);
        CREATE TABLE user_progress (user_id INTEGER, book_id INTEGER, last_read_at TEXT);
        INSERT INTO user_category_permissions VALUES (7, 1, 1), (7, 2, 0);
        INSERT INTO books VALUES (1,1,'safe','fiction',0,0),
          (2,1,'adult','restricted',19,0), (3,2,'private','private-genre',0,0),
          (4,1,'keyword','adult-genre',0,0), (5,1,'deleted','deleted-genre',0,1);
        INSERT INTO user_favorites VALUES (7,1);
        INSERT INTO user_progress VALUES (7,4,'2026-09-23'), (8,1,'2026-09-23'), (7,2,NULL);
    ''')
    with patch('repositories.sqlite.book_repository.database.connection', side_effect=lambda _: nullcontext(conn)), \
         patch('services.library_service.BookRepository', BookRepository), \
         patch('services.content_rating_service.ContentRatingService.get_adult_keywords', return_value=['adult-genre']):
        yield conn
    conn.close()


def test_facets_keep_ratings_and_library_permissions(facet_db):
    assert LibraryService.get_media_tags('general', 'all', 15, 7) == ['safe']
    assert LibraryService.get_media_genres('general', 'all', 15, 7) == ['fiction']
    assert LibraryService.get_media_tags('general', 'all', 20, 7) == ['adult', 'keyword', 'safe']
    assert LibraryService.get_media_tags('general', 2, 20, 7) == []


def test_facets_do_not_reuse_cache_after_permission_revocation(facet_db):
    assert LibraryService.get_media_tags('general', 'all', 15, 7) == ['safe']
    facet_db.execute('UPDATE user_category_permissions SET has_access = 0')
    assert LibraryService.get_media_tags('general', 'all', 15, 7) == []


def test_favorite_facets_and_legacy_repository_contract(facet_db):
    assert LibraryService.get_media_tags('general', 'favorite', 20, 7) == ['safe']
    assert all(isinstance(row, str) for row in BookRepository.get_media_tags('general', 1))


def test_category_facets_do_not_include_other_accessible_categories(facet_db):
    facet_db.execute('UPDATE user_category_permissions SET has_access = 1')
    assert LibraryService.get_media_tags('general', 1, 20, 7) == ['adult', 'keyword', 'safe']
    assert LibraryService.get_media_tags('general', 2, 20, 7) == ['private']
    assert LibraryService.get_media_genres('general', 2, 20, 7) == ['private-genre']
    assert LibraryService.get_media_tags('general', 'history', 20, 7) == ['keyword']


@pytest.fixture
def client():
    app = Flask(__name__)
    app.secret_key = 'isolated-test-only'
    app.register_blueprint(plugin_webview_bp)
    app.register_blueprint(book_routes_bp)
    return app.test_client()


def sign_in(client, rating=15, role='user'):
    with client.session_transaction() as session:
        session.update(user_id=7, role=role, content_rating_max=rating)


@pytest.mark.parametrize('rating', [0, 15, 18, 19, 'invalid'])
@pytest.mark.parametrize('path,method', [('proxy','GET'), ('proxy','POST'), ('hls-proxy','GET'),
                                      ('hls-proxy','POST'), ('logo-cache','GET'), ('download','POST'), ('check','GET')])
def test_external_direct_links_cannot_bypass_rating(client, rating, path, method):
    sign_in(client, rating)
    with patch('api.routes.plugin_webview_routes.fetch_with_redirect_revalidation') as fetch:
        result = client.open('/api/webview/' + path + '?url=https://example.com', method=method)
    assert result.status_code == 403
    assert result.json['error'] == 'content_rating_restricted'
    fetch.assert_not_called()


def test_whitelist_admin_only_but_unrestricted_user_can_check_one_url(client):
    sign_in(client, 20)
    assert client.get('/api/webview/whitelist').status_code == 403
    with patch('api.routes.plugin_webview_routes.DomainWhitelistService.is_host_whitelisted', return_value=True):
        response = client.get('/api/webview/check?url=https://example.com')
    assert response.json == {'success': True, 'allowed': True}
    sign_in(client, 15, 'admin')
    with patch('api.routes.plugin_webview_routes.DomainWhitelistService.get_whitelist', return_value=[]):
        assert client.get('/api/webview/whitelist').status_code == 200


@pytest.mark.parametrize('endpoint', ['info', 'reader-info'])
def test_reader_deep_links_reject_restricted_book(client, endpoint):
    sign_in(client)
    with patch('api.routes.book_routes.check_book_rating_permission', return_value=False), \
         patch('api.routes.book_routes.BookInfoService') as service:
        response = client.get('/api/media/books/1/' + endpoint)
    assert response.status_code == 403
    service.get_reader_info.assert_not_called()
    service.get_viewer_info.assert_not_called()
