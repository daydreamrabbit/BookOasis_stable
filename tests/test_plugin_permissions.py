from unittest.mock import patch

from flask import Flask

from api.routes.permission_routes import permission_bp


def _create_app():
    app = Flask(__name__)
    app.config.update(TESTING=True, SECRET_KEY='test-plugin-permissions')
    app.register_blueprint(permission_bp)
    return app


def _login_admin(client):
    with client.session_transaction() as session:
        session['user_id'] = 1
        session['role'] = 'admin'
        session['is_default_password'] = 0


def test_plugin_permission_accepts_string_library_id():
    client = _create_app().test_client()
    _login_admin(client)

    with patch(
        'api.routes.permission_routes.SettingsRepository.set_value'
    ) as set_value, patch(
        'api.routes.permission_routes.UserRepository.update_category_permission'
    ) as update_category_permission:
        response = client.post(
            '/api/admin/permissions/update',
            json={
                'user_id': 7,
                'library_id': 'plugin_stats_dashboard',
                'has_access': False,
                'target_db': 'plugin',
            },
        )

    assert response.status_code == 200
    assert response.get_json()['success'] is True
    set_value.assert_called_once_with(
        'general', 'PERM_CATEGORY_7_plugin_stats_dashboard', '0'
    )
    update_category_permission.assert_not_called()


def test_bulk_update_applies_mixed_changes_and_reports_partial_failure():
    client = _create_app().test_client()
    _login_admin(client)

    changes = [
        {'user_id': 7, 'library_id': 3, 'has_access': True, 'target_db': 'general'},
        {'user_id': 7, 'library_id': 'plugin_stats_dashboard', 'has_access': False, 'target_db': 'plugin'},
        {'user_id': 7, 'library_id': '', 'has_access': True, 'target_db': 'general'},  # invalid -> error
    ]

    with patch(
        'api.routes.permission_routes.SettingsRepository.set_value'
    ) as set_value, patch(
        'api.routes.permission_routes.UserRepository.update_category_permission'
    ) as update_category_permission:
        response = client.post('/api/admin/permissions/bulk-update', json={'changes': changes})

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['applied'] == 2
    assert len(data['errors']) == 1
    assert data['errors'][0]['index'] == 2
    update_category_permission.assert_called_once_with('general', 7, 3, 1)
    set_value.assert_called_once_with('PERM_CATEGORY_7_plugin_stats_dashboard', '0')


def test_bulk_update_rejects_empty_changes():
    client = _create_app().test_client()
    _login_admin(client)

    response = client.post('/api/admin/permissions/bulk-update', json={'changes': []})
    assert response.status_code == 400
    assert response.get_json()['success'] is False


def test_copy_from_user_applies_source_permissions_to_targets():
    client = _create_app().test_client()
    _login_admin(client)

    libraries = [{'id': 1, 'name': 'Lib A'}, {'id': 2, 'name': 'Lib B'}]
    perm_rows = [
        {'user_id': 5, 'library_id': 1, 'has_access': 1},
        {'user_id': 5, 'library_id': 2, 'has_access': 0},
    ]

    with patch(
        'api.routes.permission_routes.CategoryRepository.get_all_libraries', return_value=libraries
    ), patch(
        'api.routes.permission_routes.UserRepository.get_all_category_permissions', return_value=perm_rows
    ), patch(
        'api.routes.permission_routes.UserRepository.update_category_permission'
    ) as update_category_permission:
        response = client.post(
            '/api/admin/permissions/copy-from-user',
            json={'source_user_id': 5, 'target_user_ids': [8, 9], 'target_db': 'audiobook'},
        )

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['applied'] == 4
    assert data['errors'] == []
    update_category_permission.assert_any_call('audiobook', 8, 1, 1)
    update_category_permission.assert_any_call('audiobook', 8, 2, 0)
    update_category_permission.assert_any_call('audiobook', 9, 1, 1)
    update_category_permission.assert_any_call('audiobook', 9, 2, 0)


def test_copy_from_user_requires_targets():
    client = _create_app().test_client()
    _login_admin(client)

    response = client.post(
        '/api/admin/permissions/copy-from-user',
        json={'source_user_id': 5, 'target_user_ids': [], 'target_db': 'general'},
    )
    assert response.status_code == 400
    assert response.get_json()['success'] is False