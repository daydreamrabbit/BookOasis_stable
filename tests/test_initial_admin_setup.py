from unittest.mock import patch

from flask import Flask

from api import auth


def _app():
    app = Flask(__name__)
    app.secret_key = 'test-secret'
    return app


def test_initial_setup_is_only_required_when_every_user_table_is_empty():
    with patch.object(auth.UserRepository, 'get_all_users', return_value=[]):
        assert auth._initial_setup_required() is True

    def users_for(db_type):
        return [{'id': 1}] if db_type == 'adult' else []

    with patch.object(auth.UserRepository, 'get_all_users', side_effect=users_for):
        assert auth._initial_setup_required() is False


def test_initial_setup_uses_the_chosen_credentials_without_default_password_flag():
    created = []

    def add_user(db_type, username, password_hash, role, *flags, **kwargs):
        created.append((db_type, username, role, kwargs.get('is_default_password')))
        return 1

    app = _app()
    with app.test_request_context(
        '/setup', method='POST',
        json={'username': 'chosen-owner', 'password': 'safe-password', 'confirm_password': 'safe-password'},
    ), patch.object(auth, '_initial_setup_required', return_value=True), patch.object(
        auth.UserRepository, 'add_user', side_effect=add_user
    ):
        response = auth.setup_initial_admin()

    assert response.json == {'success': True}
    assert [row[0] for row in created] == list(auth.ACCOUNT_DB_TYPES)
    assert all(row[1:] == ('chosen-owner', 'admin', 0) for row in created)


def test_initial_setup_refuses_to_replace_an_existing_installation():
    app = _app()
    with app.test_request_context(
        '/setup', method='POST',
        json={'username': 'owner', 'password': 'safe-password', 'confirm_password': 'safe-password'},
    ), patch.object(auth, '_initial_setup_required', return_value=False), patch.object(
        auth.UserRepository, 'add_user'
    ) as add_user:
        response, status = auth.setup_initial_admin()

    assert status == 409
    assert response.json['success'] is False
    add_user.assert_not_called()
