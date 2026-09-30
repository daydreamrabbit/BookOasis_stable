# -*- coding: utf-8 -*-
from flask import Blueprint, request, jsonify, session, redirect, url_for, render_template, g, send_file
from functools import wraps
import ipaddress
import os
import threading
import database
from werkzeug.security import generate_password_hash, check_password_hash
from services.settings_service import SettingsService
from services.content_rating_service import LEVEL_PORN, get_user_content_rating_max
from repositories.user_repository import UserRepository
from services.user_profile_service import (
    MAX_PROFILE_AVATAR_BYTES,
    PROFILE_AVATARS,
    UserProfileService,
    get_custom_avatar_mimetype,
    get_custom_avatar_path,
    save_custom_avatar_image,
)

from utils.i18n_helper import get_available_languages
from utils.i18n import _t

auth_bp = Blueprint('auth', __name__)

MAX_AUTH_REQUEST_BYTES = 16 * 1024
MAX_USERNAME_LENGTH = 128
MAX_PASSWORD_LENGTH = 256
ACCOUNT_DB_TYPES = ('general', 'adult', 'audiobook', 'video')
_initial_admin_lock = threading.Lock()


def _initial_setup_required():
    """사용자 테이블이 모두 비어 있는 완전한 신규 설치에서만 최초 설정을 허용한다."""
    try:
        return all(len(UserRepository.get_all_users(db_type)) == 0 for db_type in ACCOUNT_DB_TYPES)
    except Exception:
        return False


def _as_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _get_security_option(key, default=''):
    val = SettingsService.get(key, '')
    if str(val).strip() != '':
        return val
    return os.environ.get(key, default)


def _iter_trusted_proxy_networks(raw_list):
    for item in str(raw_list or '').split(','):
        token = item.strip()
        if not token:
            continue
        try:
            if '/' in token:
                yield ipaddress.ip_network(token, strict=False)
            else:
                yield ipaddress.ip_network(token + '/32', strict=False)
        except ValueError:
            print(f"[Auth WARNING] Invalid PROXY_HEADER_TRUSTED_IPS entry ignored: {token}")


def _request_from_trusted_proxy():
    trusted_raw = _get_security_option('PROXY_HEADER_TRUSTED_IPS', '').strip()
    if not trusted_raw:
        # 보안 강화: 신뢰할 수 있는 IP 목록이 비어있으면 프록시 헤더 인증 거부
        return False

    remote_addr = request.remote_addr
    if not remote_addr:
        return False
    try:
        remote_ip = ipaddress.ip_address(remote_addr)
    except ValueError:
        return False

    for network in _iter_trusted_proxy_networks(trusted_raw):
        if remote_ip in network:
            return True
    return False


def _looks_like_proxy_request():
    return any([
        request.headers.get('X-Forwarded-For'),
        request.headers.get('X-Forwarded-Proto'),
        request.headers.get('X-Real-IP'),
        request.headers.get('Forwarded'),
    ])


def _reject_oversized_auth_request():
    cl = request.content_length
    if cl is not None and cl > MAX_AUTH_REQUEST_BYTES:
        return jsonify({'success': False, 'error': 'Request payload too large'}), 413
    return None


def _validate_username_password_lengths(username, password):
    u = str(username or '')
    p = str(password or '')
    if len(u) > MAX_USERNAME_LENGTH:
        return jsonify({'success': False, 'error': f'Username too long (max {MAX_USERNAME_LENGTH})'}), 400
    if len(p) > MAX_PASSWORD_LENGTH:
        return jsonify({'success': False, 'error': f'Password too long (max {MAX_PASSWORD_LENGTH})'}), 400
    return None


def _validate_password_length_only(password):
    p = str(password or '')
    if len(p) > MAX_PASSWORD_LENGTH:
        return jsonify({'success': False, 'error': f'Password too long (max {MAX_PASSWORD_LENGTH})'}), 400
    return None


def _refresh_content_rating_session():
    """DB에서 현재 사용자의 최신 콘텐츠 등급을 읽어 세션을 동기화한다.

    관리자가 다른 브라우저에서 권한을 변경하면 Flask 세션 쿠키에는 이전
    content_rating_max가 남을 수 있다. 등급은 노출 여부를 결정하는 보안
    값이므로, 목록/검색 API가 실행되기 전에 DB의 현재 값을 우선한다.
    """
    user_id = session.get('user_id')
    if not user_id:
        return
    try:
        user = UserRepository.find_by_id('general', int(user_id))
        if user:
            session['content_rating_max'] = get_user_content_rating_max(user)
    except Exception as exc:
        # 인증 자체를 실패시키지는 않고 기존 세션값을 유지한다. DB 일시 오류
        # 때문에 로그인 사용자가 앱 전체에서 차단되는 것을 피한다.
        print(f"[Auth WARNING] Failed to refresh content rating session: {exc}")

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': _t('api.login_required')}), 401
            return redirect(url_for('media_api.auth.login'))
        
        # 기본 비밀번호 상태인데 비밀번호 변경 요청이 아닌 경우 차단
        if session.get('is_default_password') == 1 and request.endpoint != 'auth.change_password':
            # index 페이지(SPA 로더)는 허용하되, 데이터 조회용 API는 차단
            if request.path.startswith('/api/'):
                return jsonify({'success': False, 'error': _t('api.default_pw_change_required')}), 403
            
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    @login_required
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return jsonify({'success': False, 'error': _t('api.admin_required')}), 403
        return f(*args, **kwargs)
    return decorated_function

def verify_webhook_token(token):
    """
    외부 연동 프로그램(gd-poller 등 CLI/스크립트)용 공용 웹훅 토큰(WEBHOOK_TOKEN) 검증.
    브라우저 세션 없이 호출하는 read-only 외부 API에서 재사용한다 — 새 토큰을 발급하지 않고
    기존 스캔 웹훅(/api/webhook/scan)과 동일한 시스템 설정값(WEBHOOK_TOKEN)을 공유한다.
    """
    sys_token = SettingsService.get('WEBHOOK_TOKEN', '') or os.environ.get('WEBHOOK_TOKEN')
    return bool(sys_token) and bool(token) and token == sys_token

def webhook_token_required(f):
    """쿼리스트링/폼(token) 또는 X-Webhook-Token 헤더로 전달된 WEBHOOK_TOKEN을 검증하는 데코레이터"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.args.get('token') or request.form.get('token') or request.headers.get('X-Webhook-Token')
        if not verify_webhook_token(token):
            return jsonify({'success': False, 'error': 'Invalid webhook token.'}), 401
        return f(*args, **kwargs)
    return decorated_function

def check_adult_permission(db_type):
    if db_type == 'adult':
        if session.get('has_adult_access') == 1:
            return True
        return False

    if db_type == 'audiobook':
        if session.get('has_audiobook_access') == 1:
            return True
        return False

    if db_type == 'video':
        if session.get('has_video_access') == 1:
            return True
        return False

    return True

def check_download_permission():
    """역할과 관계없이 저장된 파일 다운로드 권한을 판별한다."""
    return session.get('has_download_access') == 1

def check_book_rating_permission(db_type, book_id):
    """역할과 관계없이 개별 도서의 콘텐츠 등급 열람 권한을 판별한다."""
    from services.content_rating_service import ContentRatingService
    return ContentRatingService.can_view_book(db_type, book_id, session.get('content_rating_max', 18))

@auth_bp.before_app_request
def check_authentication():
    # i18n 언어 스캔 API는 세션 예외
    if request.path == '/api/i18n/languages':
        return
        
    # 예외 대상 경로 리스트
    exempt_paths = [
        url_for('media_api.auth.login'),
        '/login',
        '/setup',
        '/logout',
        '/change-password',
        # /tv 페이지 셸은 민감 데이터가 없어 비로그인 상태에서도 렌더링을 허용하고,
        # 화면 안에서 킷오스크용 팝업 로그인 폼을 띄운다(전체 페이지 /login 이동 대신).
        # 실제 데이터는 /api/media/* 가 각자 인증을 요구하므로 안전하다.
        '/tv'
    ]
    
    # static 폴더, health 체크, OPDS/cover, 웹훅 경로 예외
    if (request.path.startswith('/static/')
            or request.path in ('/health', '/favicon.ico')
            or request.path.startswith('/opds')
            or request.path.startswith('/app-opds')   # 타치요미 전용 엔드포인트 (자체 인증 처리)
            or request.path.startswith('/covers')
            or request.path.startswith('/api/webhook/')):
        return
        
    # 예외 경로 검사
    if request.path in exempt_paths:
        return

    proxy_header_auth_enabled = _as_bool(_get_security_option('PROXY_HEADER_AUTH', '0'))
    proxy_deny_direct_enabled = _as_bool(_get_security_option('PROXY_HEADER_DENY_DIRECT', '0'))

    # [선택 옵션] Proxy Header Auth 사용 시, 프록시 헤더가 없는 직접 접근을 차단할 수 있음
    if proxy_header_auth_enabled and proxy_deny_direct_enabled and not _looks_like_proxy_request():
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': 'Direct access denied. Please use reverse proxy.'}), 403
        return jsonify({'success': False, 'error': 'Direct access denied. Please use reverse proxy.'}), 403
        
    # [프록시 헤더 인증 처리]
    if 'user_id' not in session:
        if proxy_header_auth_enabled:
            remote_user = request.headers.get('Remote-User') or request.headers.get('X-Forwarded-User')
            if remote_user:
                if not _request_from_trusted_proxy():
                    print(f"[Auth WARNING] Ignored proxy auth header from untrusted source IP: {request.remote_addr}")
                else:
                    user = UserRepository.find_by_username('general', remote_user)
                    if user:
                        session['user_id'] = user['id']
                        session['username'] = user['username']
                        session['role'] = user['role']
                        session['is_default_password'] = user['is_default_password']
                        session['has_adult_access'] = user['has_adult_access']
                        session['has_audiobook_access'] = user.get('has_audiobook_access', 1)
                        session['has_video_access'] = user.get('has_video_access', 1)
                        session['has_download_access'] = user.get('has_download_access', 1)
                        session['content_rating_max'] = get_user_content_rating_max(user)

    # 권한 관리 화면에서 변경한 최대 등급이 다른 브라우저의 기존 세션에도
    # 즉시 반영되도록, 프록시 로그인/일반 로그인 모두 DB의 최신 값을 동기화한다.
    _refresh_content_rating_session()

    # 1. 미로그인 시 차단
    if 'user_id' not in session:
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': _t('api.login_required')}), 401
        return redirect(url_for('media_api.auth.login'))
        
    # 2. 기본 비밀번호 상태 시 일반 API 조회 차단
    if session.get('is_default_password') == 1:
        # index(SPA 로드)는 허용하여 변경 모달이 뜰 수 있도록 함
        if request.path in ['/', '/media-library']:
            return
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'is_default': True, 'error': _t('api.default_pw_change_required')}), 403

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        oversized = _reject_oversized_auth_request()
        if oversized:
            return oversized

        # JSON 요청과 일반 Form 요청 모두 대응
        remember_me = False
        if request.is_json:
            data = request.get_json()
            username = data.get('username')
            password = data.get('password')
            remember_me = data.get('remember_me', False)
        else:
            username = request.form.get('username')
            password = request.form.get('password')
            remember_me = request.form.get('remember_me') == 'on'

        length_error = _validate_username_password_lengths(username, password)
        if length_error:
            return length_error
            
        if not username or not password:
            return jsonify({'success': False, 'error': _t('api.username_password_required')}), 400
            
        user = UserRepository.find_by_username('general', username)
        
        if user and check_password_hash(user['password_hash'], password):
            session.clear() # 세션 고정 취약점 방지
            
            # 자동 로그인이 체크된 경우 세션 만료기간을 연장 (기본적으로 Flask에서는 app.permanent_session_lifetime 에 따름, 보통 31일)
            if remember_me:
                session.permanent = True
                
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['role'] = user['role']
            session['is_default_password'] = user['is_default_password']
            session['has_adult_access'] = user['has_adult_access']
            session['has_audiobook_access'] = user.get('has_audiobook_access', 1)
            session['has_video_access'] = user.get('has_video_access', 1)
            session['has_download_access'] = user.get('has_download_access', 1)
            content_rating_max = get_user_content_rating_max(user)
            session['content_rating_max'] = content_rating_max

            return jsonify({
                'success': True,
                'role': user['role'],
                'is_default_password': user['is_default_password'],
                'has_adult_access': user.get('has_adult_access', 0),
                'has_audiobook_access': user.get('has_audiobook_access', 1),
                'has_video_access': user.get('has_video_access', 1),
                'has_download_access': user.get('has_download_access', 1),
                'content_rating_max': content_rating_max
            })
        else:
            return jsonify({'success': False, 'error': _t('api.invalid_credentials')}), 401
            
    # GET 요청 시 로그인 템플릿 반환
    if 'user_id' in session:
        return redirect(url_for('media_api.media_admin.system.index'))
    return render_template('login.html', setup_required=_initial_setup_required())


@auth_bp.route('/setup', methods=['POST'])
def setup_initial_admin():
    """빈 신규 설치에서 사용자가 지정한 최초 관리자 계정을 모든 미디어 DB에 동기화한다."""
    oversized = _reject_oversized_auth_request()
    if oversized:
        return oversized

    data = request.get_json() or {}
    username = str(data.get('username') or '').strip()
    password = str(data.get('password') or '')
    confirm_password = str(data.get('confirm_password') or '')
    length_error = _validate_username_password_lengths(username, password)
    if length_error:
        return length_error
    if not username or not password:
        return jsonify({'success': False, 'error': '관리자 아이디와 비밀번호를 입력해주세요.'}), 400
    if len(password) < 4:
        return jsonify({'success': False, 'error': _t('api.password_length_error')}), 400
    if password != confirm_password:
        return jsonify({'success': False, 'error': '비밀번호 확인이 일치하지 않습니다.'}), 400

    created = []
    with _initial_admin_lock:
        if not _initial_setup_required():
            return jsonify({'success': False, 'error': '최초 관리자 설정이 이미 완료되었습니다.'}), 409
        password_hash = generate_password_hash(password)
        try:
            expected_user_id = None
            for db_type in ACCOUNT_DB_TYPES:
                user_id = UserRepository.add_user(
                    db_type, username, password_hash, 'admin', 1, 1, 1, 1,
                    is_default_password=0,
                )
                created.append((db_type, user_id))
                if expected_user_id is None:
                    expected_user_id = user_id
                elif user_id != expected_user_id:
                    raise RuntimeError('미디어 DB별 사용자 ID가 일치하지 않습니다.')
        except Exception as exc:
            for db_type, user_id in reversed(created):
                try:
                    UserRepository.delete_user(db_type, user_id)
                except Exception:
                    pass
            return jsonify({'success': False, 'error': f'관리자 계정 생성에 실패했습니다: {exc}'}), 500

    session.clear()
    session['user_id'] = expected_user_id
    session['username'] = username
    session['role'] = 'admin'
    session['is_default_password'] = 0
    session['has_adult_access'] = 1
    session['has_audiobook_access'] = 1
    session['has_video_access'] = 1
    session['has_download_access'] = 1
    session['content_rating_max'] = LEVEL_PORN
    return jsonify({'success': True})

@auth_bp.route('/logout', methods=['GET'])
def logout():
    session.clear()
    return redirect(url_for('media_api.auth.login'))

@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    oversized = _reject_oversized_auth_request()
    if oversized:
        return oversized

    data = request.get_json() or {}
    new_password = data.get('new_password')

    length_error = _validate_password_length_only(new_password)
    if length_error:
        return length_error
    
    if not new_password or len(new_password.strip()) < 4:
        return jsonify({'success': False, 'error': _t('api.new_password_length_error')}), 400
        
    user_id = session['user_id']
    new_hash = generate_password_hash(new_password.strip())

    # 두 DB 모두 계정을 동기화하여 비밀번호 변경 반영 (세션 일치)
    try:
        for db_type in ['general', 'adult', 'audiobook', 'video']:
            UserRepository.update_password(db_type, user_id, new_hash)
    except Exception as e:
        return jsonify({'success': False, 'error': _t('api.password_change_failed', error=str(e))}), 500

    session['is_default_password'] = 0
    return jsonify({'success': True, 'message': _t('api.password_changed_success')})


@auth_bp.route('/api/account/profile', methods=['GET'])
@login_required
def get_account_profile():
    """현재 로그인 사용자의 표시 정보와 실제 독서 기록 기반 통계를 반환한다."""
    user_id = session['user_id']
    username = session.get('username', '')
    user = UserRepository.find_by_id('general', user_id) or {}
    preferences = UserProfileService.get_preferences(user_id, username)
    compact = request.args.get('compact') == '1'
    year = request.args.get('year', type=int)
    if year is not None and (year < 2000 or year > 2100):
        return jsonify({'success': False, 'error': '조회 연도가 올바르지 않습니다.'}), 400
    payload = {
        'success': True,
        'profile': {
            'username': username,
            'role': session.get('role', 'user'),
            'created_at': str(user.get('created_at') or ''),
            **preferences,
        },
        'avatars': [
            {'key': key, 'icon': icon} for key, icon in PROFILE_AVATARS.items()
        ],
    }
    if not compact:
        payload['statistics'] = UserProfileService.get_statistics(
            user_id,
            include_adult=session.get('has_adult_access') == 1,
            year=year,
        )
    return jsonify(payload)


@auth_bp.route('/api/account/profile', methods=['POST'])
@login_required
def update_account_profile():
    """표시 이름과 서버 동기화되는 프리셋 프로필 이미지를 저장한다."""
    oversized = _reject_oversized_auth_request()
    if oversized:
        return oversized
    data = request.get_json(silent=True) or {}
    display_name = str(data.get('display_name') or '').strip()
    avatar = str(data.get('avatar') or '').strip().lower()
    if len(display_name) > 40:
        return jsonify({'success': False, 'error': '표시 이름은 40자까지 입력할 수 있습니다.'}), 400
    if avatar not in PROFILE_AVATARS and not (avatar == 'custom' and get_custom_avatar_path(session['user_id']).is_file()):
        return jsonify({'success': False, 'error': '지원하지 않는 프로필 이미지입니다.'}), 400
    profile = UserProfileService.save_preferences(
        session['user_id'], session.get('username', ''), display_name, avatar
    )
    return jsonify({'success': True, 'profile': profile})


@auth_bp.route('/api/account/profile/avatar', methods=['GET'])
@login_required
def get_account_profile_avatar():
    """현재 로그인 계정의 사용자 업로드 프로필 이미지를 반환한다."""
    path = get_custom_avatar_path(session['user_id'])
    if not path.is_file():
        return jsonify({'success': False, 'error': '등록된 프로필 이미지가 없습니다.'}), 404
    return send_file(path, mimetype=get_custom_avatar_mimetype(session['user_id']), conditional=True, max_age=86400)


@auth_bp.route('/api/account/profile/avatar', methods=['POST'])
@login_required
def upload_account_profile_avatar():
    """사용자 이미지를 정규화하여 계정별 프로필 이미지로 저장한다."""
    # multipart 경계/필드 오버헤드를 감안하되 실제 이미지 데이터는 서비스에서 다시 5MB로 제한한다.
    if request.content_length is not None and request.content_length > MAX_PROFILE_AVATAR_BYTES + 256 * 1024:
        return jsonify({'success': False, 'error': '프로필 이미지는 5MB 이하만 사용할 수 있습니다.'}), 413
    upload = request.files.get('avatar')
    if upload is None:
        return jsonify({'success': False, 'error': '이미지 파일을 선택해 주세요.'}), 400
    display_name = str(request.form.get('display_name') or '').strip()
    if len(display_name) > 40:
        return jsonify({'success': False, 'error': '표시 이름은 40자까지 입력할 수 있습니다.'}), 400
    try:
        save_custom_avatar_image(session['user_id'], upload.stream)
        profile = UserProfileService.save_preferences(
            session['user_id'], session.get('username', ''), display_name, 'custom'
        )
    except ValueError as error:
        return jsonify({'success': False, 'error': str(error)}), 400
    return jsonify({'success': True, 'profile': profile})

# --- 어드민 전용 사용자 관리 API ---

@auth_bp.route('/api/admin/users', methods=['GET'])
@login_required
def get_users():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': _t('api.admin_required')}), 403
        
    users = UserRepository.get_all_users('general')
    return jsonify({'success': True, 'users': users})

@auth_bp.route('/api/admin/users', methods=['POST'])
@login_required
def add_user():
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': _t('api.admin_required')}), 403

    oversized = _reject_oversized_auth_request()
    if oversized:
        return oversized
        
    data = request.get_json() or {}
    username = data.get('username', '').strip()
    password = data.get('password', '').strip()
    role = data.get('role', 'user').strip()
    has_adult_access = 1 if data.get('has_adult_access', True) else 0
    has_audiobook_access = 1 if data.get('has_audiobook_access', True) else 0
    has_video_access = 1 if data.get('has_video_access', True) else 0
    has_download_access = 1 if data.get('has_download_access', True) else 0

    length_error = _validate_username_password_lengths(username, password)
    if length_error:
        return length_error
    
    if not username or not password:
        return jsonify({'success': False, 'error': _t('api.username_password_initial_required')}), 400
        
    if len(password) < 4:
        return jsonify({'success': False, 'error': _t('api.password_length_error')}), 400
        
    password_hash = generate_password_hash(password)
    
    try:
        # 동기화를 위해 두 데이터베이스에 모두 사용자 추가
        for db_type in ['general', 'adult', 'audiobook', 'video']:
            UserRepository.add_user(db_type, username, password_hash, role, has_adult_access, has_audiobook_access, has_video_access, has_download_access)
    except Exception as e:
        if 'UNIQUE' in str(e):
            return jsonify({'success': False, 'error': _t('api.username_exists')}), 409
        return jsonify({'success': False, 'error': _t('api.add_user_failed', error=str(e))}), 500
        
    return jsonify({'success': True, 'message': _t('api.user_added_success')})

@auth_bp.route('/api/admin/users/<int:target_user_id>', methods=['DELETE'])
@login_required
def delete_user(target_user_id):
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': _t('api.admin_required')}), 403
        
    if session.get('user_id') == target_user_id:
        return jsonify({'success': False, 'error': _t('api.delete_self_error')}), 400

    target_user = UserRepository.find_by_id('general', target_user_id)
    if not target_user:
        return jsonify({'success': False, 'error': _t('api.user_not_found', default='사용자를 찾을 수 없습니다.')}), 404

    if target_user.get('role') == 'admin':
        admin_count = UserRepository.count_by_role('general', 'admin')
        if admin_count <= 1:
            return jsonify({
                'success': False,
                'error': _t('api.delete_last_admin_error', default='마지막 관리자 계정은 삭제할 수 없습니다.')
            }), 400
        
    # 두 데이터베이스 모두에서 삭제
    for db_type in ['general', 'adult', 'audiobook', 'video']:
        UserRepository.delete_user(db_type, target_user_id)
        
    return jsonify({'success': True, 'message': _t('api.user_deleted_success')})

@auth_bp.route('/api/admin/users/<int:target_user_id>/password', methods=['PUT'])
@login_required
def reset_user_password(target_user_id):
    if session.get('role') != 'admin':
        return jsonify({'success': False, 'error': _t('api.admin_required')}), 403

    oversized = _reject_oversized_auth_request()
    if oversized:
        return oversized
        
    data = request.get_json() or {}
    new_password = data.get('new_password', '').strip()
    current_password = data.get('current_password', '').strip()

    length_error = _validate_password_length_only(new_password)
    if length_error:
        return length_error
    current_length_error = _validate_password_length_only(current_password)
    if current_length_error:
        return current_length_error
    
    if len(new_password) < 4:
        return jsonify({'success': False, 'error': _t('api.new_password_length_error')}), 400
        
    target_user = UserRepository.find_by_id('general', target_user_id)
    if not target_user:
        return jsonify({'success': False, 'error': 'User not found'}), 404
        
    set_default = 1
    if target_user['role'] == 'admin':
        if not current_password:
            return jsonify({'success': False, 'error': _t('api.current_password_required', default='현재 비밀번호를 입력해주세요.')}), 400
        if not check_password_hash(target_user['password_hash'], current_password):
            return jsonify({'success': False, 'error': _t('api.invalid_current_password', default='현재 비밀번호가 일치하지 않습니다.')}), 401
        set_default = 0
        
    new_hash = generate_password_hash(new_password)

    try:
        for db_type in ['general', 'adult', 'audiobook', 'video']:
            UserRepository.admin_reset_password(db_type, target_user_id, new_hash, set_default)
    except Exception as e:
        return jsonify({'success': False, 'error': _t('api.password_change_failed', error=str(e))}), 500

    return jsonify({'success': True, 'message': _t('api.password_changed_success')})

@auth_bp.route('/api/i18n/languages', methods=['GET'])
def get_languages():
    try:
        langs = get_available_languages()
        return jsonify({'success': True, 'languages': langs})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500
