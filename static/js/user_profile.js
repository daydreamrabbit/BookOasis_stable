import { buildFallbackCoverUrl, getBookCoverSrc } from './cover_fallback.js';
import {renderActivityCalendar,applyActivityColor,initActivityColors} from './reading_activity.js';
import {initProfileTooltips} from './profile_tooltip.js';
import {state} from './state.js';
import {initProfileLibrary,showProfileLibraryTab,resetProfileLibrary} from './profile_library.js';
import {initProfileMessages,loadProfileMessages} from './profile_messages.js';
import {initProfileCommunity,loadProfileCommunitySettings} from './profile_guestbook.js';
import {renderProfileBio,initProfileBioEditor,resetProfileBioEditor,previewProfileBio,profileBioIsUploading} from './profile_bio.js';

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
let profileLoadToken = 0;
let savingProfile = false;
let profileCharts=null;

if(typeof window!=='undefined')window.addEventListener('bookoasis:profile-charts-loaded',event=>{
  profileCharts=event.detail;
  if(profileData?.statistics){renderSummary(profileData.statistics);renderGenreOverview();}
});

if(typeof window!=='undefined')window.addEventListener('bookoasis:activity-color-saved',event=>{
  profileLoadToken++;
  if(profileData?.profile)profileData.profile.activity_color=event.detail.color;
});

export function normalizeProfileAppearance(value={}) {
  const bio=value?.bio??'',banner_url=value?.banner_url??'',accent=value?.accent??'#4f8ef0';
  if(typeof bio!=='string'||bio.length>20000)throw new Error('소개는 20,000자 이하로 입력해 주세요.');
  if(new TextEncoder().encode(bio).length>60000)throw new Error('소개 내용은 UTF-8 기준 60KB 이하로 입력해 주세요.');
  if(!/^#[0-9a-f]{6}$/i.test(accent))throw new Error('강조색을 확인해 주세요.');
  if(typeof banner_url!=='string'||banner_url.length>480||/[\s\\]/.test(banner_url))throw new Error('배너 이미지 주소를 확인해 주세요.');
  if(banner_url){
    const parsed=new URL(banner_url,'https://bookoasis.invalid');
    if((!(banner_url.startsWith('/')&&!banner_url.startsWith('//'))&&!banner_url.startsWith('https://'))||parsed.username||parsed.password)throw new Error('https:// 또는 /로 시작하는 이미지 주소를 입력하세요.');
  }
  return {bio,banner_url,accent};
}

function appearanceInput() {
  return normalizeProfileAppearance({bio:document.getElementById('profile-bio-input').value,
    banner_url:document.getElementById('profile-banner-input').value.trim(),accent:document.getElementById('profile-accent-input').value});
}

function previewAppearance() {
  const preview=document.querySelector('.profile-decoration-preview');
  try { const value=appearanceInput();preview.style.backgroundImage=value.banner_url?`url(${JSON.stringify(value.banner_url)})`:'';preview.style.setProperty('--profile-preview-accent',value.accent); }
  catch { preview.style.backgroundImage=''; }
}

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
  applyActivityColor(profile.activity_color);
  initActivityColors();
  document.querySelectorAll('[data-role="account-avatar"]').forEach((el) => applyAvatar(el, profile.avatar, profile.avatar_url));
  const triggerName = document.getElementById('account-display-name');
  const popoverName = document.getElementById('account-popover-display-name');
  const username = document.getElementById('session-username-display');
  if (triggerName) triggerName.textContent = profile.display_name || profile.username || '-';
  if (popoverName) popoverName.textContent = profile.display_name || profile.username || '-';
  if (username) username.textContent = profile.username ? `@${profile.username}` : '-';
}

export async function loadAccountHeaderProfile() {
  const token=profileLoadToken;
  try {
    const response = await fetch('/api/account/profile?compact=1', { cache: 'no-store' });
    const data = await response.json();
    if (!response.ok || !data.success || token!==profileLoadToken) return;
    profileData = {...profileData,...data};
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
  const c=profileCharts;
  const seconds=Number(c?.duration_seconds??statistics.duration_seconds??0);
  const hours=seconds/3600;
  const pages=c?.pages_read??statistics.pages_read??0;
  const items = [
    ['읽은 작품',c?.read??'—','작품'],['독서 시간',seconds>=3600?Math.round(hours*10)/10:Math.round(seconds/60),seconds>=3600?'시간':'분'],['평균 별점',c?.average_rating??'—',''],
    ['완독 도서',c?.completed_volumes??statistics.completed_books??0,'권'],
    ['읽은 페이지',Number(pages).toLocaleString('ko-KR'),'p'],['읽은 작가',c?.staff?.length??statistics.author_count??0,'명'],
  ];
  const milestones=(value,base,unit)=>{
    const max=Math.max(base,Math.ceil(value/base)*base),ticks=[.2,.6,1].map(part=>Math.round(max*part));
    return `<div class="profile-summary-milestones" data-profile-tip="${unit}" data-profile-tip-detail="${value} / ${max} 누적" tabindex="0"><div>${ticks.map(tick=>`<span>${tick.toLocaleString('ko-KR')}</span>`).join('')}</div><div class="profile-summary-track" role="progressbar" aria-label="${unit} 누적" aria-valuemin="0" aria-valuemax="${max}" aria-valuenow="${Math.min(max,value)}"><i style="width:${Math.min(100,value/max*100)}%"></i></div></div>`;
  };
  target.setAttribute('aria-label','전체 기간 독서 통계 요약');
  target.innerHTML = [items.slice(0,3),items.slice(3)].map((group,index)=>`<div class="profile-stat-group">${group.map(([label,value,unit])=>`
    <article><strong>${escapeHtml(value)}<small>${unit}</small></strong><span>${label}</span></article>
  `).join('')}${index===0?milestones(c?.read??0,50,'읽은 작품 수'):milestones(c?.completed_volumes??statistics.completed_books??0,50,'완독 권수')}</div>`).join('');
}


function tipAttributes(title,detail){return `data-profile-tip="${escapeHtml(title)}" data-profile-tip-detail="${escapeHtml(detail)}"`;}

function renderReadingOverview(overview={},error=''){
  const empty=`<p class="profile-overview-empty">${escapeHtml(error||'표시할 독서 기록이 없습니다.')}</p>`;
  const books=document.getElementById('profile-books-overview');
  books.innerHTML=overview.books?.length?overview.books.map((item,index)=>{
    const format=String(item.file_format||'').toUpperCase();
    const detail=[item.publication_year?`${item.publication_year}년 출간`:'',format,`${item.count}권 읽음`].filter(Boolean).join(' · ');
    return `<button type="button" class="profile-poster" data-profile-overview-kind="books" data-profile-overview-index="${index}" ${tipAttributes(item.name,detail)} aria-label="${escapeHtml(item.name)}"><img draggable="false" src="${escapeHtml(coverUrl({...item,series_name:item.name}))}" alt="" loading="lazy" data-fallback-src="${escapeHtml(buildFallbackCoverUrl({title:item.name,format:item.file_format,seed:item.id}))}" onerror="this.onerror=null;this.src=this.dataset.fallbackSrc"></button>`;
  }).join(''):empty;
  const staff=document.getElementById('profile-staff-overview');
  staff.innerHTML=overview.staff?.length?overview.staff.map((item,index)=>`<button type="button" class="profile-staff-item" data-profile-overview-kind="staff" data-profile-overview-index="${index}" ${tipAttributes(item.name,`${(item.roles||[]).join('·')} 작가 · ${item.count}권 읽음`)}><span class="profile-staff-avatar" aria-hidden="true">${escapeHtml(item.name.slice(0,2))}</span><strong>${escapeHtml(item.name)}</strong><small>${item.count}권</small></button>`).join(''):empty;
  const publishers=document.getElementById('profile-publishers-overview');
  publishers.innerHTML=overview.publishers?.length?overview.publishers.map((item,index)=>`<button type="button" data-profile-overview-kind="publishers" data-profile-overview-index="${index}" ${tipAttributes(item.name,`${item.count}권 읽음`)}><strong>${escapeHtml(item.name)}</strong><small>${item.count}권</small></button>`).join(''):empty;
  const colors=['#68b95b','#519dda','#9769ce','#d676a0','#d58964','#b7a64b'];
  const genres=document.getElementById('profile-genre-overview');
  genres.innerHTML=overview.genres?.length?`<div class="profile-genre-distribution">${overview.genres.map((item,index)=>`<button type="button" style="flex-grow:${Math.max(1,Number(item.count)||1)};background:${colors[index%colors.length]}" data-profile-overview-kind="genres" data-profile-overview-index="${index}" ${tipAttributes(item.name,`${item.count}권 · ${item.percent}%`)} aria-label="${escapeHtml(item.name)} ${item.count}권"></button>`).join('')}</div><div class="profile-genre-entries">${overview.genres.map((item,index)=>`<button type="button" style="--genre-color:${colors[index%colors.length]}" data-profile-overview-kind="genres" data-profile-overview-index="${index}" ${tipAttributes(item.name,`${item.count}권 · ${item.percent}%`)}><span>${escapeHtml(item.name)}</span><small>${item.count}권</small></button>`).join('')}</div>`:empty;
}

async function navigateOverview(event,button){
  const kind=button.dataset.profileOverviewKind,index=Number(button.dataset.profileOverviewIndex),item=profileData?.overview?.[kind]?.[index];
  if(!item)return;
  if(item.is_other)return;
  event.preventDefault();
  if(item.db_type&&state.currentLibraryType!==item.db_type){await window.switchLibraryType?.(item.db_type);}
  if(kind==='books'){
    window.openBookDetail?.(event,item.series_name,item.library_id,item.id,item.name);return;
  }
  let field=kind==='publishers'?'publisher':kind==='genres'?'genre':(item.roles?.includes('글')?'author':'cover_artist');
  const advancedSearch={categories:[],[field]:['publisher','genre'].includes(field)?[item.name]:item.name};
  await window.selectCategory?.('all',false,{preserveSearch:true,searchNavigation:true,searchQuery:'',advancedSearch});
}

function renderHeatmap(statistics) {
  const year = Number(statistics.year);
  renderActivityCalendar(document.getElementById('profile-overview-calendar'),year,statistics.daily||[],statistics.today);
}

function renderGenreOverview(){
  const target=document.getElementById('profile-genre-overview');
  const rows=profileCharts?.breakdowns?.genres;if(!target||!rows)return;
  const colors=['#68b95b','#29a4e7','#9265e6','#ed739e','#ee9368'];
  target.innerHTML=rows.length?`<div class="profile-genre-entries">${rows.slice(0,5).map((row,i)=>`<div style="--genre-color:${colors[i]}"><span>${escapeHtml(row.name)}</span><small>${row.count}작품</small></div>`).join('')}</div><div class="profile-genre-distribution">${rows.slice(0,5).map((row,i)=>`<span style="flex:${row.count};background:${colors[i]}" ${tipAttributes(row.name,`${row.count}작품 · ${row.volumes}권 읽음`)} tabindex="0"></span>`).join('')}</div><small class="profile-genre-basis">읽거나 평가한 작품 · 상위 5개 장르</small>`:'<p class="profile-overview-empty">표시할 작품이 없습니다.</p>';
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
  resetProfileLibrary();
  profileCharts=null;
  profileData = data;
  const profile = data.profile || {};
  const stats = data.statistics || {};
  const appearance=normalizeProfileAppearance(profile.appearance||{});
  document.getElementById('user-profile-view').style.setProperty('--profile-accent',appearance.accent);
  renderProfileBio(document.getElementById('profile-bio'),appearance.bio,'프로필 편집에서 나의 독서 취향을 소개해 보세요.');
  document.querySelector('.user-profile-banner').style.backgroundImage=appearance.banner_url?`url(${JSON.stringify(appearance.banner_url)})`:'';
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
  loadProfileMessages();
  loadProfileCommunitySettings();
  renderReadingOverview(data.overview||{},data.overview_error);
  renderYearOptions(stats.year);
  document.getElementById('profile-loading').hidden = true;
  switchProfileTab(document.querySelector('[data-profile-tab].active')?.dataset.profileTab || 'overview');
}

async function fetchProfile(year) {
  const suffix = year ? `?year=${encodeURIComponent(year)}` : '';
  const response = await fetch(`/api/account/profile${suffix}`, { cache: 'no-store' });
  if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('프로필 서버 응답을 확인하지 못했습니다. 다시 시도해 주세요.');
  const data = await response.json();
  if (!response.ok || !data.success) throw new Error(data.error || '프로필을 불러오지 못했습니다.');
  return data;
}

export async function loadUserProfile({ year = null, headerOnly = false } = {}) {
  const token=++profileLoadToken;
  const loading = document.getElementById('profile-loading');
  const error = document.getElementById('profile-error');
  if (!headerOnly && loading) loading.hidden = false;
  if (error) error.hidden = true;
  try {
    const data = await fetchProfile(year);
    if(token!==profileLoadToken)return;
    if (headerOnly) applyProfileToHeader(data.profile);
    else renderProfile(data);
  } catch (reason) {
    if(token!==profileLoadToken)return;
    if (loading) loading.hidden = true;
    if (error) {
      error.textContent = reason.message || '프로필을 불러오지 못했습니다.';
      error.hidden = false;
    }
  }
}

function switchProfileTab(tabName) {
  window.dispatchEvent(new Event('bookoasis:profile-rendering'));
  document.querySelectorAll('[data-profile-tab]').forEach((button) => button.classList.toggle('active', button.dataset.profileTab === tabName));
  document.querySelectorAll('[data-profile-panel]').forEach((panel) => { panel.hidden = panel.dataset.profilePanel !== tabName; });
  if(profileData?.statistics)renderHeatmap(profileData.statistics);
  showProfileLibraryTab(tabName);
}

function openEditDialog() {
  if (!profileData) return;
  const dialog = document.getElementById('profile-edit-dialog');
  const input = document.getElementById('profile-display-name-input');
  const options = document.getElementById('profile-avatar-options');
  if (!dialog || !input || !options) return;
  input.value = profileData.profile.display_name || profileData.profile.username || '';
  const appearance=normalizeProfileAppearance(profileData.profile.appearance||{});
  resetProfileBioEditor();
  document.getElementById('profile-bio-input').value=appearance.bio;
  document.getElementById('profile-bio-status').hidden=true;
  previewProfileBio();
  document.getElementById('profile-banner-input').value=appearance.banner_url;
  document.getElementById('profile-accent-input').value=appearance.accent;
  previewAppearance();
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
  if(savingProfile)return;
  resetProfileBioEditor();
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
  if(savingProfile)return;
  const save = event.currentTarget.querySelector('.profile-edit-save');
  const message = document.getElementById('profile-edit-message');
  if (save) save.disabled = true;
  if (message) message.hidden = true;
  try {
    if(profileBioIsUploading())throw new Error('소개 이미지 업로드가 끝난 뒤 저장해 주세요.');
    const appearance=appearanceInput();savingProfile=true;
    let response;
    if (selectedAvatar === 'custom' && selectedAvatarFile) {
      const form = new FormData();
      form.append('avatar', selectedAvatarFile);
      form.append('display_name', document.getElementById('profile-display-name-input').value);
      form.append('appearance',JSON.stringify(appearance));
      response = await fetch('/api/account/profile/avatar', { method: 'POST', body: form });
    } else {
      response = await fetch('/api/account/profile', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ display_name: document.getElementById('profile-display-name-input').value, avatar: selectedAvatar, appearance }),
      });
    }
    if(!response.headers.get('content-type')?.includes('application/json'))throw new Error('저장 응답을 확인하지 못했습니다. 다시 시도해 주세요.');
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '저장하지 못했습니다.');
    await loadUserProfile({ year: document.getElementById('profile-year-select')?.value });
    savingProfile=false;closeEditDialog();
  } catch (reason) {
    if (message) { message.textContent = reason.message; message.hidden = false; }
  } finally {
    savingProfile=false;
    if (save) save.disabled = false;
  }
}

export function initUserProfile() {
  if (initialized) return;
  initialized = true;
  initProfileTooltips();
  initProfileLibrary();
  initProfileMessages();
  initProfileBioEditor();
  initProfileCommunity(applyAvatar);
  document.addEventListener('click', (event) => {
    const overview=event.target.closest('[data-profile-overview-kind]');
    if(overview){navigateOverview(event,overview).catch(error=>console.error('[UserProfile] 통계 항목 이동 실패:',error));return;}
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
  document.addEventListener('keydown',event=>{
    const dialog=document.getElementById('profile-edit-dialog');if(!dialog||dialog.hidden)return;
    if(event.key==='Escape'){event.preventDefault();closeEditDialog();document.getElementById('profile-edit-button')?.focus();}
    if(event.key==='Tab'){
      const controls=[...dialog.querySelectorAll('button:not([disabled]),input:not([type=file]),textarea,[contenteditable=true]')].filter(el=>el.getClientRects().length);
      const first=controls[0],last=controls.at(-1);
      if(event.shiftKey&&document.activeElement===first){event.preventDefault();last?.focus();}
      if(!event.shiftKey&&document.activeElement===last){event.preventDefault();first?.focus();}
    }
  });
  for(const id of ['profile-bio-input','profile-banner-input','profile-accent-input'])document.getElementById(id)?.addEventListener('input',previewAppearance);
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
