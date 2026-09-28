import { buildFallbackCoverUrl, getBookCoverSrc } from './cover_fallback.js';

const AVATAR_ICONS = {
  oasis: 'fa-solid fa-book-open', moon: 'fa-solid fa-moon', leaf: 'fa-solid fa-leaf',
  wave: 'fa-solid fa-water', star: 'fa-solid fa-star', cat: 'fa-solid fa-cat',
  paw: 'fa-solid fa-paw', spark: 'fa-solid fa-wand-magic-sparkles',
};

let profileData = null;
let selectedAvatar = 'oasis';
let selectedAvatarUrl = '';
let selectedAvatarFile = null;
let previewObjectUrl = '';
let initialized = false;

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>'"]/g, (char) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;',
  })[char]);
}

function normalizeAvatar(key) {
  return key === 'custom' || Object.prototype.hasOwnProperty.call(AVATAR_ICONS, key) ? key : 'oasis';
}

export function applyAvatar(element, key, avatarUrl = '') {
  if (!element) return;
  const safeKey = normalizeAvatar(key);
  element.dataset.avatar = safeKey;
  if (safeKey === 'custom' && avatarUrl) {
    element.innerHTML = `<img src="${escapeHtml(avatarUrl)}" alt="" aria-hidden="true">`;
  } else {
    const fallbackKey = safeKey === 'custom' ? 'oasis' : safeKey;
    element.dataset.avatar = fallbackKey;
    element.innerHTML = `<i class="${AVATAR_ICONS[fallbackKey]}" aria-hidden="true"></i>`;
  }
}

export function applyProfileToHeader(profile) {
  if (!profile) return;
  document.querySelectorAll('[data-role="account-avatar"]').forEach((el) => applyAvatar(el, profile.avatar, profile.avatar_url));
  const triggerName = document.getElementById('account-display-name');
  const popoverName = document.getElementById('account-popover-display-name');
  const username = document.getElementById('session-username-display');
  if (triggerName) triggerName.textContent = profile.display_name || profile.username || '-';
  if (popoverName) popoverName.textContent = profile.display_name || profile.username || '-';
  if (username) username.textContent = profile.username ? `@${profile.username}` : '-';
}

export async function loadAccountHeaderProfile() {
  try {
    const response = await fetch('/api/account/profile?compact=1', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !data.success) return;
    profileData = data;
    applyProfileToHeader(data.profile);
  } catch (error) {
    console.error('[UserProfile] 헤더 프로필 조회 실패:', error);
  }
}

function formatDuration(seconds) {
  const minutes = Math.max(0, Math.round(Number(seconds || 0) / 60));
  if (minutes < 60) return `${minutes}분`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return rest ? `${hours}시간 ${rest}분` : `${hours}시간`;
}

function formatDate(value) {
  if (!value) return '';
  const parsed = new Date(String(value).replace(' ', 'T'));
  if (Number.isNaN(parsed.getTime())) return String(value).slice(0, 10);
  return new Intl.DateTimeFormat('ko-KR', { year: 'numeric', month: 'short', day: 'numeric' }).format(parsed);
}

function progressPercent(item) {
  if (Number(item.is_completed) === 1 || Number(item.last_epub_percent) >= 99) return 100;
  if (Number(item.last_epub_percent) > 0) return Math.min(99, Number(item.last_epub_percent));
  const total = Number(item.total_pages || 0);
  return total > 0 ? Math.min(99, Math.round((Number(item.pages_read || 0) / total) * 100)) : 0;
}

function coverUrl(item) {
  return getBookCoverSrc({
    coverImage: item.cover_image,
    title: item.series_name || item.title,
    format: item.file_format,
    seed: item.id,
  });
}

function renderSummary(statistics) {
  const target = document.getElementById('profile-summary-stats');
  if (!target) return;
  const items = [
    ['fa-solid fa-book', '완독 도서', statistics.completed_books, '권'],
    ['fa-solid fa-book-open-reader', '읽기 시작', statistics.started_books, '권'],
    ['fa-regular fa-file-lines', '읽은 페이지', Number(statistics.pages_read || 0).toLocaleString('ko-KR'), 'p'],
    ['fa-regular fa-clock', '기록된 독서 시간', formatDuration(statistics.duration_seconds), ''],
    ['fa-solid fa-users', '읽은 작가', statistics.author_count, '명'],
    ['fa-solid fa-calendar-check', '활동일', statistics.active_days, '일'],
  ];
  target.innerHTML = items.map(([icon, label, value, unit]) => `
    <article><i class="${icon}" aria-hidden="true"></i><span>${label}</span><strong>${escapeHtml(value)}<small>${unit}</small></strong></article>
  `).join('');
}

function recentCard(item) {
  const pct = progressPercent(item);
  const title = item.series_name || item.title || '제목 없음';
  const fallback = buildFallbackCoverUrl({ title, format: item.file_format, seed: item.id });
  return `<article class="user-profile-recent-card">
    <img src="${escapeHtml(coverUrl(item))}" data-fallback-src="${escapeHtml(fallback)}" alt="" loading="lazy" onerror="this.onerror=null;this.src=this.dataset.fallbackSrc">
    <div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(String(item.file_format || '').toUpperCase())} · ${escapeHtml(formatDate(item.last_read_at))}</span>
      <div class="user-profile-progress"><i style="width:${pct}%"></i></div><small>${pct}%</small></div>
  </article>`;
}

function renderRecent(statistics) {
  const recent = Array.isArray(statistics.recent_activity) ? statistics.recent_activity : [];
  const overview = document.getElementById('profile-recent-overview');
  const activity = document.getElementById('profile-activity-list');
  const empty = '<div class="user-profile-empty"><i class="fa-solid fa-book-open"></i><span>아직 저장된 독서 기록이 없습니다.</span></div>';
  if (overview) overview.innerHTML = recent.length ? recent.slice(0, 6).map(recentCard).join('') : empty;
  if (activity) activity.innerHTML = recent.length ? recent.map((item) => {
    const pct = progressPercent(item);
    const title = item.series_name || item.title || '제목 없음';
    const fallback = buildFallbackCoverUrl({ title, format: item.file_format, seed: item.id });
    return `<article class="user-profile-activity-item"><img src="${escapeHtml(coverUrl(item))}" data-fallback-src="${escapeHtml(fallback)}" alt="" loading="lazy" onerror="this.onerror=null;this.src=this.dataset.fallbackSrc"><div><strong>${escapeHtml(title)}</strong><span>${escapeHtml(formatDate(item.last_read_at))}</span></div><b>${pct}%</b></article>`;
  }).join('') : empty;
}

function renderHeatmap(statistics) {
  const target = document.getElementById('profile-heatmap');
  if (!target) return;
  const year = Number(statistics.year);
  const daily = new Map((statistics.daily || []).map((item) => [item.date, item]));
  const first = new Date(year, 0, 1);
  const last = new Date(year, 11, 31);
  const leading = first.getDay();
  const cells = [];
  for (let i = 0; i < leading; i += 1) cells.push('<i class="profile-heatmap-cell is-empty"></i>');
  for (let date = new Date(first); date <= last; date.setDate(date.getDate() + 1)) {
    const key = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    const entry = daily.get(key) || {};
    const pages = Number(entry.pages_read || 0);
    const seconds = Number(entry.duration_seconds || 0);
    const score = Math.max(pages, Math.round(seconds / 60));
    const level = score <= 0 ? 0 : score < 10 ? 1 : score < 30 ? 2 : score < 80 ? 3 : 4;
    const title = `${key} · ${pages}페이지 · ${formatDuration(seconds)}`;
    cells.push(`<i class="profile-heatmap-cell" data-level="${level}" title="${escapeHtml(title)}"></i>`);
  }
  target.innerHTML = cells.join('');
  target.style.setProperty('--heatmap-weeks', String(Math.ceil((leading + (last - first) / 86400000 + 1) / 7)));
  const title = document.getElementById('profile-heatmap-title');
  if (title) title.textContent = `${year}년 독서 활동`;
}

function renderYearOptions(currentYear) {
  const select = document.getElementById('profile-year-select');
  if (!select) return;
  const now = new Date().getFullYear();
  select.innerHTML = '';
  for (let year = now; year >= now - 5; year -= 1) {
    const option = document.createElement('option');
    option.value = String(year);
    option.textContent = `${year}년`;
    option.selected = year === Number(currentYear);
    select.appendChild(option);
  }
}

function renderProfile(data) {
  profileData = data;
  const profile = data.profile || {};
  const stats = data.statistics || {};
  selectedAvatar = normalizeAvatar(profile.avatar);
  selectedAvatarUrl = profile.avatar_url || '';
  applyProfileToHeader(profile);
  applyAvatar(document.querySelector('[data-role="profile-avatar"]'), selectedAvatar, selectedAvatarUrl);
  document.getElementById('profile-display-name').textContent = profile.display_name || profile.username || '-';
  document.getElementById('profile-username').textContent = `@${profile.username || '-'}`;
  document.getElementById('profile-role-badge').textContent = profile.role === 'admin' ? '관리자' : '사용자';
  const joined = document.getElementById('profile-joined-at');
  joined.textContent = profile.created_at ? `가입 ${formatDate(profile.created_at)}` : '';
  renderSummary(stats);
  renderRecent(stats);
  renderYearOptions(stats.year);
  renderHeatmap(stats);
  document.getElementById('profile-loading').hidden = true;
  switchProfileTab(document.querySelector('[data-profile-tab].active')?.dataset.profileTab || 'overview');
}

async function fetchProfile(year) {
  const suffix = year ? `?year=${encodeURIComponent(year)}` : '';
  const response = await fetch(`/api/account/profile${suffix}`, { cache: 'no-store' });
  const data = await response.json();
  if (!response.ok || !data.success) throw new Error(data.error || '프로필을 불러오지 못했습니다.');
  return data;
}

export async function loadUserProfile({ year = null, headerOnly = false } = {}) {
  const loading = document.getElementById('profile-loading');
  const error = document.getElementById('profile-error');
  if (!headerOnly && loading) loading.hidden = false;
  if (error) error.hidden = true;
  try {
    const data = await fetchProfile(year);
    if (headerOnly) applyProfileToHeader(data.profile);
    else renderProfile(data);
  } catch (reason) {
    if (loading) loading.hidden = true;
    if (error) {
      error.textContent = reason.message || '프로필을 불러오지 못했습니다.';
      error.hidden = false;
    }
  }
}

function switchProfileTab(tabName) {
  document.querySelectorAll('[data-profile-tab]').forEach((button) => button.classList.toggle('active', button.dataset.profileTab === tabName));
  document.querySelectorAll('[data-profile-panel]').forEach((panel) => { panel.hidden = panel.dataset.profilePanel !== tabName; });
}

function openEditDialog() {
  if (!profileData) return;
  const dialog = document.getElementById('profile-edit-dialog');
  const input = document.getElementById('profile-display-name-input');
  const options = document.getElementById('profile-avatar-options');
  if (!dialog || !input || !options) return;
  input.value = profileData.profile.display_name || profileData.profile.username || '';
  selectedAvatar = normalizeAvatar(profileData.profile.avatar);
  selectedAvatarUrl = profileData.profile.avatar_url || '';
  selectedAvatarFile = null;
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = '';
  renderAvatarOptions();
  dialog.hidden = false;
  document.body.classList.add('profile-dialog-open');
  input.focus();
}

function renderAvatarOptions() {
  const options = document.getElementById('profile-avatar-options');
  if (!options || !profileData) return;
  const customUrl = previewObjectUrl || selectedAvatarUrl;
  const customChoice = customUrl
    ? `<button type="button" data-avatar-choice="custom" class="${selectedAvatar === 'custom' ? 'selected' : ''}" aria-label="내 이미지"><span class="user-avatar" data-avatar="custom"><img src="${escapeHtml(customUrl)}" alt=""></span></button>`
    : '';
  options.innerHTML = customChoice + (profileData.avatars || []).map(({ key, icon }) => `<button type="button" data-avatar-choice="${escapeHtml(key)}" class="${key === selectedAvatar ? 'selected' : ''}" aria-label="${escapeHtml(key)}"><span class="user-avatar" data-avatar="${escapeHtml(key)}"><i class="${escapeHtml(icon)}"></i></span></button>`).join('');
}

function closeEditDialog() {
  const dialog = document.getElementById('profile-edit-dialog');
  if (dialog) dialog.hidden = true;
  const fileInput = document.getElementById('profile-avatar-file');
  if (fileInput) fileInput.value = '';
  selectedAvatarFile = null;
  if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
  previewObjectUrl = '';
  document.body.classList.remove('profile-dialog-open');
}

async function submitProfile(event) {
  event.preventDefault();
  const save = event.currentTarget.querySelector('.profile-edit-save');
  const message = document.getElementById('profile-edit-message');
  if (save) save.disabled = true;
  if (message) message.hidden = true;
  try {
    let response;
    if (selectedAvatar === 'custom' && selectedAvatarFile) {
      const form = new FormData();
      form.append('avatar', selectedAvatarFile);
      form.append('display_name', document.getElementById('profile-display-name-input').value);
      response = await fetch('/api/account/profile/avatar', { method: 'POST', body: form });
    } else {
      response = await fetch('/api/account/profile', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: document.getElementById('profile-display-name-input').value, avatar: selectedAvatar }),
      });
    }
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '저장하지 못했습니다.');
    closeEditDialog();
    await loadUserProfile({ year: document.getElementById('profile-year-select')?.value });
  } catch (reason) {
    if (message) { message.textContent = reason.message; message.hidden = false; }
  } finally {
    if (save) save.disabled = false;
  }
}

export function initUserProfile() {
  if (initialized) return;
  initialized = true;
  document.addEventListener('click', (event) => {
    const tab = event.target.closest('[data-profile-tab]');
    if (tab) return switchProfileTab(tab.dataset.profileTab);
    if (event.target.closest('#profile-edit-button, #profile-avatar-edit')) return openEditDialog();
    if (event.target.closest('#profile-avatar-upload-button')) return document.getElementById('profile-avatar-file')?.click();
    if (event.target.closest('[data-profile-edit-close]')) return closeEditDialog();
    const avatar = event.target.closest('[data-avatar-choice]');
    if (avatar) {
      selectedAvatar = normalizeAvatar(avatar.dataset.avatarChoice);
      document.querySelectorAll('[data-avatar-choice]').forEach((button) => button.classList.toggle('selected', button === avatar));
    }
  });
  document.getElementById('profile-edit-form')?.addEventListener('submit', submitProfile);
  document.getElementById('profile-avatar-file')?.addEventListener('change', (event) => {
    const file = event.target.files?.[0];
    const message = document.getElementById('profile-edit-message');
    if (!file) return;
    if (!file.type.startsWith('image/') || file.size > 5 * 1024 * 1024) {
      if (message) {
        message.textContent = file.size > 5 * 1024 * 1024 ? '프로필 이미지는 5MB 이하만 사용할 수 있습니다.' : '이미지 파일만 선택할 수 있습니다.';
        message.hidden = false;
      }
      event.target.value = '';
      return;
    }
    if (previewObjectUrl) URL.revokeObjectURL(previewObjectUrl);
    previewObjectUrl = URL.createObjectURL(file);
    selectedAvatarFile = file;
    selectedAvatar = 'custom';
    if (message) message.hidden = true;
    renderAvatarOptions();
  });
  document.getElementById('profile-year-select')?.addEventListener('change', (event) => loadUserProfile({ year: event.target.value }));
  loadAccountHeaderProfile();
}
