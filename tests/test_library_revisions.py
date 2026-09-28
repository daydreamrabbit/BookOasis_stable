from flask import Flask


def test_revision_endpoint_requires_login_and_returns_only_tokens(monkeypatch):
    from api.routes.system_routes import system_bp
    import services.series_service as service
    monkeypatch.setattr(service, '_read_shared_books_cache_epoch', lambda kind: '123')
    app = Flask(__name__)
    app.secret_key = 'test'
    app.register_blueprint(system_bp)
    client = app.test_client()
    assert client.get('/api/system/library-revisions').status_code in (302, 401)
    with client.session_transaction() as session:
        session.update(user_id=2, role='user', is_default_password=0)
    response = client.get('/api/system/library-revisions')
    assert response.status_code == 200
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.get_json() == {'success': True, 'revisions': {
        kind: '123' for kind in ('general', 'adult', 'audiobook', 'video')}}
