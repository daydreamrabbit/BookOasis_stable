// static/js/settings/users.js – 사용자 관리 탭 모듈
import { state } from '../state.js';

const MAX_USERNAME_LENGTH = 128;
const MAX_PASSWORD_LENGTH = 256;
const MIN_PASSWORD_LENGTH = 4;
const userText = (key, fallback, values = {}) => window.i18n?.t(key, values, fallback) || fallback;

export function formatLastAccess(value, now = Date.now(), timeZone = state.systemSettings?.TIMEZONE || 'Asia/Seoul') {
  if (!value) return null;
  let raw = String(value).trim();
  if (/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(raw)) raw = raw.replace(' ', 'T') + 'Z';
  const date = new Date(raw);
  if (!Number.isFinite(date.getTime())) return null;
  let formatter;
  const locale = window.i18n?.currentLang || 'ko';
  try {
    formatter = new Intl.DateTimeFormat(locale, { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  } catch (_) {
    timeZone = 'Asia/Seoul';
    formatter = new Intl.DateTimeFormat('ko-KR', { timeZone, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
  }
  const seconds = Math.max(0, Math.floor((now - date.getTime()) / 1000));
  const minutes = Math.floor(seconds / 60), hours = Math.floor(seconds / 3600), days = Math.floor(seconds / 86400);
  const relative = seconds < 60 ? userText('settings.user_last_access_now', '방금 전')
    : seconds < 3600 ? userText('settings.user_last_access_minutes', `${minutes}분 전`, {count: minutes})
    : seconds < 86400 ? userText('settings.user_last_access_hours', `${hours}시간 전`, {count: hours})
    : userText('settings.user_last_access_days', `${days}일 전`, {count: days});
  return { relative, absolute: formatter.format(date), iso: date.toISOString(), timeZone };
}

function escapeHtml(value) {
  return String(value ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function initUsersDelegation() {
  if (window.__usersDelegationBound) return;

  document.addEventListener('click', (event) => {
    const target = event && event.target && typeof event.target.closest === 'function'
      ? event.target.closest('[data-role="users-add"], [data-role="user-delete"], [data-role="user-reset-password"], [data-role="user-change-password"], [data-role="user-modal-close"], [data-role="user-reset-modal-close"], [data-role="admin-pwd-modal-close"]')
      : null;
    if (!target) return;

    event.preventDefault();

    const role = target.getAttribute('data-role');
    if (role === 'users-add') {
      openAddUserModal();
      return;
    }
    if (role === 'user-modal-close') {
      closeUserModal();
      return;
    }
    if (role === 'user-reset-modal-close') {
      closeResetPwdModal();
      return;
    }
    if (role === 'admin-pwd-modal-close') {
      closeAdminChangePwdModal();
      return;
    }

    const userId = Number.parseInt(target.getAttribute('data-user-id') || '', 10);
    if (!Number.isFinite(userId) || userId <= 0) return;

    if (role === 'user-delete') {
      deleteUser(userId, String(target.getAttribute('data-username') || ''));
      return;
    }
    if (role === 'user-reset-password') {
      openResetPwdModal(userId);
      return;
    }
    if (role === 'user-change-password') {
      openAdminChangePwdModal(userId);
    }
  }, true);

  document.addEventListener('submit', (event) => {
    const form = event && event.target;
    if (!form) return;
    if (form.id === 'user-crud-form') {
      submitUserForm(event);
      return;
    }
    if (form.id === 'user-reset-pwd-form') {
      submitResetPwdForm(event);
      return;
    }
    if (form.id === 'admin-change-pwd-form') {
      submitAdminChangePwdForm(event);
    }
  }, true);

  window.__usersDelegationBound = true;
}

export async function loadUsersList() {
  initUsersDelegation();
  const tbody = document.getElementById('settings-users-list');
  if (!tbody) return;

  tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding:2rem; color: var(--app-text-muted);"><i class="fa-solid fa-circle-notch fa-spin"></i> 사용자 목록 로드 중...</td></tr>';

  try {
    const res = await fetch(`/api/admin/users?type=${state.currentLibraryType}`);
    const data = await res.json();

    if (data.success) {
      if (data.users.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color: var(--app-text-muted);">${window.i18n ? window.i18n.t('settings.user_no_users') : '등록된 사용자가 없습니다.'}</td></tr>`;
        return;
      }

      tbody.innerHTML = data.users.map(user => {
        const isDefault = user.is_default_password === 1 
          ? `<span style="color:#f97316; font-weight:700;"><i class="fa-solid fa-triangle-exclamation"></i> ${window.i18n ? window.i18n.t('settings.user_pwd_not_changed') : '초기 비밀번호'}</span>` 
          : `<span style="color:#22c55e;"><i class="fa-solid fa-circle-check"></i> ${window.i18n ? window.i18n.t('settings.user_pwd_changed') : '변경완료'}</span>`;

        const myUserId = Number(window.currentUser?.id || 0);
        const isSelf = Number(user.id) === myUserId;
        const safeUsernameAttr = escapeHtml(user.username || '');
        const deleteBtn = isSelf
          ? `<span style="color: var(--app-text-muted); font-size:0.8rem; display:inline-flex; align-items:center; justify-content:center; height:32px; padding:0 0.5rem;">${window.i18n ? window.i18n.t('settings.user_cannot_delete') : '삭제불가'}</span>`
          : `<button data-role="user-delete" data-user-id="${user.id}" data-username="${safeUsernameAttr}" class="btn-settings-action" style="background:#ef4444; color: #fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:0.3rem; height:32px; white-space:nowrap;"><i class="fa-solid fa-trash-can"></i> ${window.i18n ? window.i18n.t('settings.user_delete') : '삭제'}</button>`;

        const resetPwdBtn = user.role === 'admin'
          ? `<button data-role="user-change-password" data-user-id="${user.id}" class="btn-settings-action" style="background:#3b82f6; color: #fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:0.3rem; height:32px; white-space:nowrap;"><i class="fa-solid fa-key"></i> ${window.i18n ? window.i18n.t('settings.admin_change_pwd') : '비번 변경'}</button>`
          : `<button data-role="user-reset-password" data-user-id="${user.id}" class="btn-settings-action" style="background:#f59e0b; color: #fff; border:none; padding:0.4rem 0.75rem; border-radius:6px; font-weight:600; cursor:pointer; display:inline-flex; align-items:center; gap:0.3rem; height:32px; white-space:nowrap;"><i class="fa-solid fa-unlock-keyhole"></i> ${window.i18n ? window.i18n.t('settings.user_reset_pwd') : '초기 비번 재설정'}</button>`;

        return `
          <tr style="border-bottom:1px solid rgba(255,255,255,0.05);">
            <td style="padding:0.8rem 1rem;">${user.id}</td>
            <td style="padding:0.8rem 1rem; font-weight:700; color: var(--app-text-primary);">${escapeHtml(user.username)}</td>
            <td style="padding:0.8rem 1rem;"><span class="badge" style="background:color-mix(in srgb, var(--app-accent) 10%, transparent); color:var(--app-accent-hover); border:1px solid color-mix(in srgb, var(--app-accent) 20%, transparent); padding:0.2rem 0.5rem; border-radius:4px; font-size:0.75rem;">${escapeHtml(user.role)}</span></td>
            <td style="padding:0.8rem 1rem; text-align:center;">${isDefault}</td>
            <td class="user-last-access" style="padding:0.8rem 1rem; white-space:nowrap;">${renderLastAccess(user.last_seen_at)}</td>
            <td style="padding:0.8rem 1rem; text-align:right;">
              <div style="display:inline-flex; align-items:center; justify-content:flex-end; gap:0.5rem; width:100%;">
                ${resetPwdBtn}${deleteBtn}
              </div>
            </td>
          </tr>
        `;
      }).join('');
    } else {
      tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:#ef4444;">${window.i18n ? window.i18n.t('settings.user_fetch_failed') : '조회 실패: '} ${escapeHtml(data.error)}</td></tr>`;
    }
  } catch (err) {
    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:2rem; color:#ef4444;">${window.i18n ? window.i18n.t('settings.users_server_error') : '서버 요청 중 오류가 발생했습니다.'}</td></tr>`;
    console.error(err);
  }
}

function renderLastAccess(value) {
  const seen = formatLastAccess(value);
  if (!seen) return `<span style="color:var(--app-text-muted);">${escapeHtml(userText('settings.user_last_access_unknown', '기록 없음'))}</span>`;
  return `<time datetime="${seen.iso}" title="${escapeHtml(seen.absolute + ' (' + seen.timeZone + ')')}"><span>${seen.relative}</span><small style="display:block; margin-top:4px; color:var(--app-text-muted); font-size:0.75rem;">${escapeHtml(seen.absolute)}</small></time>`;
}

export function openAddUserModal() {
  const modal = document.getElementById('user-form-modal');
  if (modal) {
    modal.style.display = 'flex';
    document.getElementById('user-form-username').value = '';
    document.getElementById('user-form-password').value = '';
    document.getElementById('user-form-role').value = 'user';
    const adultAccess = document.getElementById('user-form-adult-access');
    if (adultAccess) adultAccess.checked = true;
  }
}

export function closeUserModal() {
  const modal = document.getElementById('user-form-modal');
  if (modal) {
    modal.style.display = 'none';
  }
}

export async function submitUserForm(e) {
  e.preventDefault();
  const username = document.getElementById('user-form-username').value.trim();
  const password = document.getElementById('user-form-password').value.trim();
  const role = document.getElementById('user-form-role').value;
  const has_adult_access = document.getElementById('user-form-adult-access').checked;

  if (!username) {
    alert(i18n.t('settings.users_add_fail', {error: '사용자 아이디를 입력해 주세요.'}));
    return;
  }
  if (username.length > MAX_USERNAME_LENGTH) {
    alert(i18n.t('settings.users_add_fail', {error: `사용자 아이디는 최대 ${MAX_USERNAME_LENGTH}자까지 허용됩니다.`}));
    return;
  }
  if (password.length < MIN_PASSWORD_LENGTH) {
    alert(i18n.t('settings.users_add_fail', {error: `비밀번호는 최소 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`}));
    return;
  }
  if (password.length > MAX_PASSWORD_LENGTH) {
    alert(i18n.t('settings.users_add_fail', {error: `비밀번호는 최대 ${MAX_PASSWORD_LENGTH}자까지 허용됩니다.`}));
    return;
  }

  try {
    const res = await fetch(`/api/admin/users?type=${state.currentLibraryType}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username, password, role, has_adult_access })
    });
    const data = await res.json();

    if (data.success) {
      closeUserModal();
      loadUsersList();
    } else {
      alert(data.error ? i18n.t('settings.users_add_fail', {error: data.error}) : i18n.t('settings.users_add_fail', {error: ''}));
    }
  } catch (err) {
    alert(i18n.t('settings.users_server_error'));
    console.error(err);
  }
}

export async function deleteUser(userId, username) {
  if (!confirm(i18n.t('settings.users_del_confirm', {username: username}))) return;

  try {
    const res = await fetch(`/api/admin/users/${userId}?type=${state.currentLibraryType}`, {
      method: 'DELETE'
    });
    const data = await res.json();

    if (data.success) {
      loadUsersList();
    } else {
      alert(data.error ? i18n.t('settings.users_del_fail', {error: data.error}) : i18n.t('settings.users_del_fail', {error: ''}));
    }
  } catch (err) {
    alert(i18n.t('settings.users_server_error'));
    console.error(err);
  }
}

// 글로벌 등록 (인라인 핸들러 바인딩)
window.openAddUserModal = openAddUserModal;
window.closeUserModal = closeUserModal;
window.submitUserForm = submitUserForm;
window.deleteUser = deleteUser;

export function openResetPwdModal(userId) {
  const modal = document.getElementById('user-reset-pwd-modal');
  if (modal) {
    modal.style.display = 'flex';
    document.getElementById('reset-pwd-user-id').value = userId;
    document.getElementById('reset-pwd-new').value = '';
  }
}

export function closeResetPwdModal() {
  const modal = document.getElementById('user-reset-pwd-modal');
  if (modal) modal.style.display = 'none';
}

export async function submitResetPwdForm(e) {
  e.preventDefault();
  const userId = document.getElementById('reset-pwd-user-id').value;
  const newPassword = document.getElementById('reset-pwd-new').value.trim();

  if (newPassword.length < MIN_PASSWORD_LENGTH) {
    alert(`비밀번호는 최소 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`);
    return;
  }
  if (newPassword.length > MAX_PASSWORD_LENGTH) {
    alert(`비밀번호는 최대 ${MAX_PASSWORD_LENGTH}자까지 허용됩니다.`);
    return;
  }

  try {
    const res = await fetch(`/api/admin/users/${userId}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: newPassword })
    });
    const data = await res.json();
    if (data.success) {
      alert(data.message || '변경되었습니다.');
      closeResetPwdModal();
      loadUsersList();
    } else {
      alert(data.error || '오류가 발생했습니다.');
    }
  } catch (err) {
    alert(i18n.t('settings.users_server_error'));
    console.error(err);
  }
}

export function openAdminChangePwdModal(userId) {
  const modal = document.getElementById('admin-change-pwd-modal');
  if (modal) {
    modal.style.display = 'flex';
    document.getElementById('change-pwd-admin-id').value = userId;
    document.getElementById('change-pwd-current').value = '';
    document.getElementById('change-pwd-new').value = '';
  }
}

export function closeAdminChangePwdModal() {
  const modal = document.getElementById('admin-change-pwd-modal');
  if (modal) modal.style.display = 'none';
}

export async function submitAdminChangePwdForm(e) {
  e.preventDefault();
  const userId = document.getElementById('change-pwd-admin-id').value;
  const currentPassword = document.getElementById('change-pwd-current').value.trim();
  const newPassword = document.getElementById('change-pwd-new').value.trim();

  if (currentPassword.length > MAX_PASSWORD_LENGTH || newPassword.length > MAX_PASSWORD_LENGTH) {
    alert(`비밀번호는 최대 ${MAX_PASSWORD_LENGTH}자까지 허용됩니다.`);
    return;
  }
  if (newPassword.length < MIN_PASSWORD_LENGTH) {
    alert(`비밀번호는 최소 ${MIN_PASSWORD_LENGTH}자 이상이어야 합니다.`);
    return;
  }

  try {
    const res = await fetch(`/api/admin/users/${userId}/password`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: currentPassword, new_password: newPassword })
    });
    const data = await res.json();
    if (data.success) {
      alert(data.message || '변경되었습니다.');
      closeAdminChangePwdModal();
      loadUsersList();
    } else {
      alert(data.error || '오류가 발생했습니다.');
    }
  } catch (err) {
    alert(i18n.t('settings.users_server_error'));
    console.error(err);
  }
}

window.openResetPwdModal = openResetPwdModal;
window.closeResetPwdModal = closeResetPwdModal;
window.submitResetPwdForm = submitResetPwdForm;
window.openAdminChangePwdModal = openAdminChangePwdModal;
window.closeAdminChangePwdModal = closeAdminChangePwdModal;
window.submitAdminChangePwdForm = submitAdminChangePwdForm;
