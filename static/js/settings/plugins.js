// plugins.js - 메타데이터 플러그인 설정 제어 모듈
import { state } from '../state.js';
import * as api from '../api.js';

const PLUGIN_SETTINGS_ORDER_STORAGE_KEY = 'bookoasis:pluginSettingsOrder';
const PLUGIN_SETTINGS_ORDER_SETTING_KEY = 'PLUGIN_SETTINGS_ORDER';

function parsePluginOrder(rawValue) {
  if (Array.isArray(rawValue)) return rawValue.map(String);
  if (typeof rawValue !== 'string' || !rawValue.trim()) return [];
  try {
    const parsed = JSON.parse(rawValue);
    return Array.isArray(parsed) ? parsed.map(String) : [];
  } catch (e) {
    return [];
  }
}

function getLocalPluginSettingsOrder() {
  let savedOrder = [];
  try {
    savedOrder = parsePluginOrder(localStorage.getItem(PLUGIN_SETTINGS_ORDER_STORAGE_KEY) || '[]');
  } catch (e) {}
  return savedOrder;
}

async function loadSyncedPluginSettingsOrder() {
  const localOrder = getLocalPluginSettingsOrder();
  try {
    const response = typeof window.syncPluginDeskPreferences === 'function'
      ? await window.syncPluginDeskPreferences(true)
      : await api.fetchUserSettings();
    const overrides = response?.overrides || {};
    if (Object.prototype.hasOwnProperty.call(overrides, PLUGIN_SETTINGS_ORDER_SETTING_KEY)) {
      const serverOrder = parsePluginOrder(overrides[PLUGIN_SETTINGS_ORDER_SETTING_KEY]);
      localStorage.setItem(PLUGIN_SETTINGS_ORDER_STORAGE_KEY, JSON.stringify(serverOrder));
      return serverOrder;
    }
    // 기존 브라우저에만 저장돼 있던 순서는 서버 설정이 없는 최초 한 번에 이관한다.
    if (localOrder.length > 0) {
      api.updateUserSetting(PLUGIN_SETTINGS_ORDER_SETTING_KEY, JSON.stringify(localOrder)).catch((error) => {
        console.error('[Plugins-Settings] 기존 플러그인 순서 서버 이관 실패:', error);
      });
    }
  } catch (error) {
    console.warn('[Plugins-Settings] 서버 플러그인 순서 조회 실패, 로컬 값을 사용합니다.', error);
  }
  return localOrder;
}

function sortPluginsBySavedOrder(plugins, savedOrder) {
  if (savedOrder.length === 0) return [...plugins];
  const rank = new Map(savedOrder.map((pluginId, index) => [pluginId, index]));
  return [...plugins].sort((left, right) => {
    const leftRank = rank.has(String(left.id)) ? rank.get(String(left.id)) : Number.MAX_SAFE_INTEGER;
    const rightRank = rank.has(String(right.id)) ? rank.get(String(right.id)) : Number.MAX_SAFE_INTEGER;
    return leftRank - rightRank;
  });
}

function initPluginSettingsCardSorting(container) {
  if (!container) return;

  const locked = document.querySelector('[data-role="plugin-desk-lock-toggle"]')?.dataset.locked !== '0';
  container.classList.toggle('plugin-settings-cards-unlocked', !locked);
  if (container.__pluginSettingsSortable) {
    container.__pluginSettingsSortable.option('disabled', locked);
    return;
  }
  if (typeof Sortable === 'undefined') return;

  const scrollContainer = container.closest('.library-main-content') || true;
  container.__pluginSettingsSortable = Sortable.create(container, {
    animation: 180,
    draggable: '.plugin-settings-card',
    handle: '.plugin-settings-card-drag-handle',
    ghostClass: 'plugin-settings-card-sortable-ghost',
    disabled: locked,
    // 설정 화면은 window가 아니라 .library-main-content가 스크롤됩니다. 자동 탐지에만
    // 맡기면 포인터가 현재 보이는 카드 영역을 벗어나는 순간 스크롤 대상이 끊길 수 있으므로
    // 실제 스크롤 컨테이너를 명시하고, 마우스와 터치 모두 폴리필 자동 스크롤을 사용합니다.
    scroll: scrollContainer,
    scrollSensitivity: 110,
    scrollSpeed: 18,
    bubbleScroll: true,
    forceAutoScrollFallback: true,
    onEnd: () => {
      const order = Array.from(container.querySelectorAll(':scope > .plugin-settings-card'))
        .map(card => card.dataset.pluginSettingsCardId)
        .filter(Boolean);
      try {
        localStorage.setItem(PLUGIN_SETTINGS_ORDER_STORAGE_KEY, JSON.stringify(order));
      } catch (e) {}
      api.updateUserSetting(PLUGIN_SETTINGS_ORDER_SETTING_KEY, JSON.stringify(order))
        .then((result) => {
          if (!result?.success) throw new Error(result?.error || '플러그인 순서 저장 실패');
          if (typeof window.syncPluginDeskPreferences === 'function') {
            window.syncPluginDeskPreferences(true);
          }
        })
        .catch((error) => {
          console.error('[Plugins-Settings] 플러그인 순서 서버 저장 실패:', error);
          if (typeof window.showToast === 'function') {
            window.showToast('플러그인 순서를 서버에 저장하지 못했습니다.', 'error');
          }
        });
    },
  });
}

// 플러그인 목록 조회 및 동적 UI 생성
export async function loadPluginsSettings() {
  console.log('[Plugins-Settings] loadPluginsSettings() 함수 진입');
  const container = document.getElementById('settings-plugins-container');
  console.log('[Plugins-Settings] container 엘리먼트 검색 결과:', container);
  if (!container) {
    console.warn('[Plugins-Settings] 경고: #settings-plugins-container 엘리먼트를 찾을 수 없습니다.');
    return;
  }

  container.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--app-accent);"><i class="fa-solid fa-circle-notch fa-spin fa-2x"></i><br><br>플러그인 목록 로드 중...</div>';

  try {
    console.log('[Plugins-Settings] api.fetchMetadataPluginsForManagement() API 호출 시작');
    const [data, savedOrder] = await Promise.all([
      api.fetchMetadataPluginsForManagement(),
      loadSyncedPluginSettingsOrder(),
    ]);
    console.log('[Plugins-Settings] API 응답 데이터 수신 완료:', data);
    if (data.success && data.plugins && data.plugins.length > 0) {
      container.innerHTML = '';
      const orderedPlugins = sortPluginsBySavedOrder(data.plugins, savedOrder);
      orderedPlugins.forEach(p => {
        const schema = p.config_schema || [];
        const config = p.config || {};
        const hasCustomSettingsUi = !!(p.settings_ui && p.settings_ui.html);
        const updateManifest = p.update_manifest || null;
        const showSampleUpdateButton = !!(
          updateManifest &&
          updateManifest.enabled &&
          updateManifest.show_sample_update_button
        );

        const hasConfigurableBody = hasCustomSettingsUi || schema.length > 0 || showSampleUpdateButton;

        const card = document.createElement('div');
        card.className = 'plugin-settings-card';
        card.dataset.pluginSettingsCardId = String(p.id);

        // 접힌 상태에서는 플러그인 이름과 활성화 토글만 보이고, 헤더를 눌렀을 때 설정 본문을 펼칩니다.
        card.innerHTML = `
              <div class="plugin-settings-card-header" data-role="plugin-card-toggle" data-plugin-id="${p.id}">
                  <div class="plugin-settings-card-title-wrap">
                      <i class="fa-solid fa-chevron-right plugin-settings-card-chevron" data-plugin-chevron="${p.id}"></i>
                      <div class="plugin-settings-card-title-content">
                          <h4 class="plugin-settings-card-title">
                              ${escapeHtmlText(p.name)}
                              ${hasConfigurableBody ? '<span class="plugin-settings-card-badge">설정 있음</span>' : ''}
                          </h4>
                          <span class="plugin-settings-card-id">플러그인 고유 ID: ${escapeHtmlText(p.id)}</span>
                      </div>
                  </div>
                  <div class="plugin-toggle-zone" data-role="plugin-toggle-zone">
                      <button type="button" class="plugin-settings-card-drag-handle" title="플러그인 설정 순서 이동" aria-label="${escapeHtmlAttr(p.name)} 플러그인 설정 순서 이동">
                          <i class="fa-solid fa-grip-vertical" aria-hidden="true"></i>
                      </button>
                      <span id="plugin-status-text-${p.id}" class="plugin-toggle-status ${p.enabled ? 'is-enabled' : 'is-disabled'}">
                          ${p.enabled ? '활성화됨' : '비활성화됨'}
                      </span>
                      <label class="plugin-toggle-switch">
                          <input type="checkbox" class="plugin-toggle-checkbox" data-plugin-id="${p.id}" ${p.enabled ? 'checked' : ''}>
                          <span class="toggle-slider"></span>
                      </label>
                  </div>
              </div>

              <div class="plugin-settings-card-body" data-plugin-body="${p.id}">
                  <form class="plugin-config-form" data-plugin-id="${p.id}">
                      ${hasCustomSettingsUi ? `
                      <div class="plugin-settings-ui-root" data-plugin-settings-root="${p.id}" data-plugin-config='${escapeHtmlAttr(JSON.stringify(config))}'>
                        ${p.settings_ui.html}
                      </div>
                      ` : (schema.length > 0 ? schema.map(f => {
                        const curVal = config[f.key];
                        return renderSchemaField(f, curVal);
                      }).join('') : '<p class="plugin-settings-empty">이 플러그인은 별도의 추가 설정값이 필요하지 않습니다.</p>')}

                      ${(hasCustomSettingsUi || schema.length > 0) ? `
                      <div class="plugin-config-actions">
                          <button type="submit" class="btn-submit plugin-config-save">
                              <i class="fa-regular fa-floppy-disk"></i> 설정 저장
                          </button>
                      </div>
                      ` : ''}

                      ${showSampleUpdateButton ? `
                      <div class="plugin-sample-update-panel">
                        <button type="button" class="plugin-sample-update-btn" data-plugin-id="${p.id}">
                          <i class="fa-solid fa-cloud-arrow-down"></i> 샘플 업데이트 (${p.id})
                        </button>
                        <span id="plugin-sample-update-status-${p.id}" class="plugin-sample-update-status">업데이트 가능 조건: 현재 버전 &lt; GitHub 버전</span>
                      </div>
                      ` : ''}
                  </form>
              </div>
        `;
        container.appendChild(card);
      });

      injectPluginSettingsStyles(data.plugins);
      applyConfigValues(container, data.plugins);
      initPluginSettingsScripts(container, data.plugins);

      // 이벤트 바인딩
      bindPluginEvents();
      initPluginSettingsCardSorting(container);
      loadDetailViewProviderSettings(data.plugins);
    } else {
      container.innerHTML = '<div style="text-align: center; padding: 2rem; color: var(--app-text-muted);">로드된 메타데이터 플러그인이 없습니다.</div>';
      loadDetailViewProviderSettings([]);
    }
  } catch (err) {
    console.error('플러그인 목록 조회 에러:', err);
    container.innerHTML = '<div style="text-align: center; padding: 2rem; color: #f43f5e;">서버와 통신 중 오류가 발생했습니다.</div>';
  }

  initSamplePluginsModal();
}

// category_tab/detail_sidebar_widget과 동일한 세션 노출 규칙(utils/plugin_session_helper.py의
// resolve_plugin_sessions 서버측 로직을 그대로 반영): 생략 시 general만, 'all'이면 4개 세션 전체,
// 배열이면 그 세션들만.
const DETAIL_VIEW_SESSIONS = ['general', 'adult', 'audiobook', 'video'];
function resolvePluginSessionsClient(manifest) {
  const sessions = manifest && manifest.sessions;
  if (sessions === 'all') return DETAIL_VIEW_SESSIONS;
  if (Array.isArray(sessions) && sessions.length > 0) {
    return sessions.filter((s) => DETAIL_VIEW_SESSIONS.includes(s));
  }
  return ['general'];
}

const DETAIL_VIEW_SESSION_LABELS = {
  general: '일반 도서',
  adult: '성인 도서',
  audiobook: '오디오북',
  video: '영상강좌',
};

// 세션별 도서 상세페이지 렌더러 선택 UI 로드 (detail_view를 선언한 플러그인 + 코어 기본값)
export async function loadDetailViewProviderSettings(plugins) {
  const container = document.getElementById('settings-detail-view-provider-rows');
  if (!container) return;

  const detailViewPlugins = (plugins || []).filter((p) => p.enabled && p.detail_view && typeof p.detail_view === 'object');

  let currentValues = {};
  try {
    const settingsRes = await api.fetchSystemSettings();
    if (settingsRes && settingsRes.success) {
      currentValues = settingsRes.settings || {};
    }
  } catch (err) {
    console.error('[Plugins-Settings] 상세페이지 렌더러 현재 설정값 조회 실패:', err);
  }

  container.innerHTML = DETAIL_VIEW_SESSIONS.map((sessionKey) => {
    const settingKey = `DETAIL_VIEW_PROVIDER_${sessionKey.toUpperCase()}`;
    const currentVal = currentValues[settingKey] || 'core';
    const eligiblePlugins = detailViewPlugins.filter((p) => resolvePluginSessionsClient(p.detail_view).includes(sessionKey));
    const options = ['<option value="core">기본(코어)</option>']
      .concat(eligiblePlugins.map((p) => `<option value="${escapeHtmlAttr(p.id)}" ${String(currentVal) === p.id ? 'selected' : ''}>${escapeHtmlText(p.detail_view.title || p.name)}</option>`));
    // 현재 저장된 값이 더 이상 유효하지 않은 플러그인 id면(비활성화/삭제) 코어로 표시
    const coreSelected = currentVal === 'core' || !eligiblePlugins.some((p) => p.id === currentVal);
    if (coreSelected) {
      options[0] = '<option value="core" selected>기본(코어)</option>';
    }
    return `
      <div class="library-form-group-row" style="display: flex; align-items: center; gap: 0.8rem; flex-wrap: wrap;">
        <label style="font-weight: 700; color: var(--app-text-primary); font-size: 0.88rem; min-width: 90px;">${DETAIL_VIEW_SESSION_LABELS[sessionKey]}</label>
        <select class="detail-view-provider-select" data-session="${sessionKey}" data-setting-key="${settingKey}" style="flex: 1; min-width: 200px; max-width: 360px; background: rgba(var(--app-panel-rgb), 0.6); border: 1px solid rgba(var(--app-panel-border-rgb), 0.1); color: var(--app-text-primary); padding: 0.5rem 0.7rem; border-radius: 6px;">
          ${options.join('')}
        </select>
        ${eligiblePlugins.length === 0 ? '<span style="font-size: 0.76rem; color: var(--app-text-muted);">이 세션에서 detail_view를 선언한 활성 플러그인이 없습니다.</span>' : ''}
      </div>
    `;
  }).join('');

  container.querySelectorAll('.detail-view-provider-select').forEach((select) => {
    select.addEventListener('change', async (e) => {
      const sessionKey = e.target.dataset.session;
      const settingKey = e.target.dataset.settingKey;
      const value = e.target.value;
      try {
        const res = await api.updateSystemSetting(settingKey, value);
        if (res.success) {
          // 저장 직후 새로고침 없이 바로 반영되도록 메모리 상태도 즉시 갱신
          // (안 그러면 openBookDetail()이 여전히 페이지 로드 시점의 구값을 참조해
          // "선택은 했는데 화면이 안 바뀐다"는 혼란을 준다).
          state.detailViewProviders[sessionKey] = value;
          if (typeof window.showToast === 'function') window.showToast('저장되었습니다. 도서 상세페이지를 다시 열면 반영됩니다.', 'success');
        } else {
          alert(res.error || '저장 실패');
        }
      } catch (err) {
        console.error('[Plugins-Settings] 상세페이지 렌더러 설정 저장 에러:', err);
        alert('서버와 통신 중 오류가 발생했습니다.');
      }
    });
  });
}

function escapeHtmlAttr(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function escapeHtmlText(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;');
}

function renderSchemaField(f, curVal) {
  const label = f.label || f.key;
  const required = !!f.required;
  const descHtml = f.description ? `<p style="font-size: 0.76rem; color: var(--app-text-muted); margin: 0.4rem 0 0 0;">${f.description}</p>` : '';
  const key = f.key || '';
  const type = (f.type || 'text').toLowerCase();

  if (type === 'checkbox') {
    const checked = curVal === true || curVal === '1' || curVal === 1 || curVal === 'true';
    return `
      <div class="library-form-group" style="margin: 0;">
        <label style="font-weight: 700; color: var(--app-text-primary); font-size: 0.88rem; margin-bottom: 0.4rem; display: block;">
          ${label} ${required ? '<span style="color:#f43f5e;">*</span>' : ''}
        </label>
        <label style="display:flex; align-items:center; gap:0.5rem; color: var(--app-text-muted);">
          <input type="checkbox" name="${key}" ${checked ? 'checked' : ''}>
          <span>사용</span>
        </label>
        ${descHtml}
      </div>
    `;
  }

  if (type === 'select') {
    const options = Array.isArray(f.options) ? f.options : [];
    const cur = curVal ?? f.default ?? '';
    return `
      <div class="library-form-group" style="margin: 0;">
        <label style="font-weight: 700; color: var(--app-text-primary); font-size: 0.88rem; margin-bottom: 0.4rem; display: block;">
          ${label} ${required ? '<span style="color:#f43f5e;">*</span>' : ''}
        </label>
        <select name="${key}" ${required ? 'required' : ''} style="width: 100%; max-width: 480px; background: rgba(var(--app-panel-rgb), 0.6); border: 1px solid rgba(var(--app-panel-border-rgb), 0.1); color: var(--app-text-primary); padding: 0.6rem 0.8rem; border-radius: 6px; outline: none; transition: border-color 0.2s;">
          ${options.map(opt => {
            const val = typeof opt === 'object' ? opt.value : opt;
            const text = typeof opt === 'object' ? (opt.label || opt.value) : opt;
            const selected = String(cur) === String(val) ? 'selected' : '';
            return `<option value="${escapeHtmlAttr(val)}" ${selected}>${escapeHtmlText(text)}</option>`;
          }).join('')}
        </select>
        ${descHtml}
      </div>
    `;
  }

  const inputType = (type === 'number' || type === 'password' || type === 'text') ? type : 'text';
  const value = curVal ?? f.default ?? '';
  return `
    <div class="library-form-group" style="margin: 0;">
      <label style="font-weight: 700; color: var(--app-text-primary); font-size: 0.88rem; margin-bottom: 0.4rem; display: block;">
        ${label} ${required ? '<span style="color:#f43f5e;">*</span>' : ''}
      </label>
      <input type="${inputType}" name="${key}" value="${escapeHtmlAttr(value)}" ${required ? 'required' : ''} style="width: 100%; max-width: 480px; background: rgba(var(--app-panel-rgb), 0.6); border: 1px solid rgba(var(--app-panel-border-rgb), 0.1); color: var(--app-text-primary); padding: 0.6rem 0.8rem; border-radius: 6px; outline: none; transition: border-color 0.2s;">
      ${descHtml}
    </div>
  `;
}

function injectPluginSettingsStyles(plugins) {
  plugins.forEach((p) => {
    if (!p.settings_ui || !p.settings_ui.css) return;
    const styleId = `plugin-settings-style-${p.id}`;
    const existing = document.getElementById(styleId);
    if (existing) {
      existing.textContent = p.settings_ui.css;
      return;
    }
    const style = document.createElement('style');
    style.id = styleId;
    style.textContent = p.settings_ui.css;
    document.head.appendChild(style);
  });
}

function applyConfigValues(container, plugins) {
  plugins.forEach((p) => {
    const form = container.querySelector(`form.plugin-config-form[data-plugin-id="${p.id}"]`);
    if (!form) return;
    const config = p.config || {};
    Object.keys(config).forEach((key) => {
      const el = form.querySelector(`[name="${CSS.escape(key)}"]`);
      if (!el) return;
      if (el.type === 'checkbox') {
        el.checked = config[key] === true || config[key] === '1' || config[key] === 1 || config[key] === 'true';
      } else {
        el.value = config[key] ?? '';
      }
    });
  });
}

function initPluginSettingsScripts(container, plugins) {
  plugins.forEach((p) => {
    if (!p.settings_ui || !p.settings_ui.js) return;
    const root = container.querySelector(`[data-plugin-settings-root="${p.id}"]`);
    if (!root || root.dataset.pluginScriptInited === '1') return;
    try {
      const fn = new Function('window', 'pluginId', 'root', 'config', p.settings_ui.js);
      fn(window, p.id, root, p.config || {});
      root.dataset.pluginScriptInited = '1';
    } catch (e) {
      console.error(`[Plugins-Settings] custom script init failed (${p.id}):`, e);
    }
  });
}

function buildPluginReloadStatusText(res) {
  const base = `업데이트 완료 (${res.local_version} -> ${res.github_version})`;
  const reload = res.reload || null;
  if (!reload) return base;

  if (reload.reload_ok) {
    return `${base} | 핫리로드 완료 (모듈 ${reload.removed_count || 0}개 반영)`;
  }

  return `${base} | 업데이트는 완료됐지만 핫리로드 실패`;
}

// 플러그인 이벤트 핸들러 바인딩
function bindPluginEvents() {
  const container = document.getElementById('settings-plugins-container');
  if (!container) return;

  if (!window.__pluginsStaticDelegationBound) {
    document.addEventListener('click', (event) => {
      const guide = event && event.target && typeof event.target.closest === 'function'
        ? event.target.closest('[data-role="plugins-contrib-guide"]')
        : null;
      if (!guide) return;
      event.preventDefault();
      alert('준비 중인 기여 항목입니다. GitHub 기여 가이드를 확인해 주세요!');
    }, true);
    window.__pluginsStaticDelegationBound = true;
  }

  // 0. 카드 헤더 클릭 시 설정 본문 펼치기/접기 (토글 스위치 영역 클릭은 제외)
  container.querySelectorAll('.plugin-settings-card-header').forEach(header => {
    header.addEventListener('click', (e) => {
      if (e.target.closest('[data-role="plugin-toggle-zone"]')) return;
      const pluginId = header.dataset.pluginId;
      const body = container.querySelector(`[data-plugin-body="${CSS.escape(pluginId)}"]`);
      const chevron = container.querySelector(`[data-plugin-chevron="${CSS.escape(pluginId)}"]`);
      if (!body) return;
      // 최초 렌더에서는 CSS 클래스가 본문을 숨기므로 body.style.display는 빈 문자열이다.
      // 인라인 값만 보면 첫 클릭을 열린 상태로 오인해 다시 숨기게 되므로 계산된 상태를 사용한다.
      const isOpen = window.getComputedStyle(body).display !== 'none';
      body.style.display = isOpen ? 'none' : 'flex';
      if (chevron) chevron.classList.toggle('plugin-settings-card-chevron-open', !isOpen);
    });
  });

  // 1. 활성/비활성 스위치 토글 이벤트
  container.querySelectorAll('.plugin-toggle-checkbox').forEach(chk => {
    chk.addEventListener('change', async (e) => {
      const pluginId = e.target.dataset.pluginId;
      const isEnabled = e.target.checked;
      const statusText = document.getElementById(`plugin-status-text-${pluginId}`);
      
      try {
        const res = await api.toggleMetadataPlugin(state.currentLibraryType, pluginId, isEnabled);
        if (res.success) {
          if (statusText) {
            statusText.innerText = isEnabled ? '활성화됨' : '비활성화됨';
            statusText.classList.toggle('is-enabled', isEnabled);
            statusText.classList.toggle('is-disabled', !isEnabled);
          }
          
          // 플러그인 활성 토글에 따른 전역 검색 플러그인 캐시 무효화 처리
          if (typeof window.invalidateMetadataPluginsCache === 'function') {
            window.invalidateMetadataPluginsCache();
          }

          if (typeof window.showToast === 'function') {
            window.showToast(res.message, 'success');
          }
        } else {
          alert(i18n.t('settings.plugins_toggle_fail', {error: res.error}));
        }
      } catch (err) {
        console.error('플러그인 활성 토글 에러:', err);
      }
    });
  });

  // 2. 각 플러그인의 설정 저장 폼 이벤트
  container.querySelectorAll('.plugin-config-form').forEach(form => {
    form.addEventListener('submit', async (e) => {
      e.preventDefault();
      const pluginId = form.dataset.pluginId;
      
      // 폼 데이터를 딕셔너리로 취합
      const configData = {};
      const inputs = form.querySelectorAll('input, select, textarea');
      inputs.forEach(inp => {
        if (inp.name) {
          if (inp.type === 'checkbox') {
            configData[inp.name] = !!inp.checked;
          } else {
            configData[inp.name] = String(inp.value ?? '').trim();
          }
        }
      });

      try {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = true;
          submitBtn.innerText = '저장 중...';
        }
        
        const res = await api.saveMetadataPluginConfig(state.currentLibraryType, pluginId, configData);
        if (res.success) {
          if (typeof window.showToast === 'function') {
            window.showToast(res.message, 'success');
          } else {
            alert(res.message);
          }
        } else {
          alert(i18n.t('settings.plugins_save_fail', {error: res.error}));
        }
      } catch (err) {
        console.error('플러그인 설정 저장 에러:', err);
        alert(i18n.t('settings.plugins_server_error'));
      } finally {
        const submitBtn = form.querySelector('button[type="submit"]');
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.innerHTML = '<i class="fa-regular fa-floppy-disk"></i> 설정 저장';
        }
      }
    });
  });

  // 3. 샘플 업데이트 버튼 (plugin update_manifest.show_sample_update_button 기반)
  container.querySelectorAll('.plugin-sample-update-btn').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      const pluginId = e.currentTarget.dataset.pluginId;
      const statusEl = document.getElementById(`plugin-sample-update-status-${pluginId}`);
      const prevText = btn.innerHTML;
      try {
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 업데이트 중...';
        if (statusEl) {
          statusEl.textContent = '업데이트 확인/적용 진행 중...';
          statusEl.style.color = '#38bdf8';
        }

        const res = await api.sampleUpdateMetadataPlugin(pluginId);
        if (res.success) {
          const msg = buildPluginReloadStatusText(res);
          if (statusEl) {
            statusEl.textContent = msg;
            statusEl.style.color = (res.reload && res.reload.reload_ok === false) ? '#f59e0b' : '#4ade80';
          }
          if (typeof window.showToast === 'function') {
            window.showToast(msg, 'success');
          }

          if (res.reload && res.reload.reload_ok === false) {
            const warn = `핫리로드 실패: ${res.reload.reload_error || '원인 미상'} (필요 시 컨테이너 재시작)`;
            if (statusEl) {
              statusEl.textContent = `${msg} | ${warn}`;
              statusEl.style.color = '#f59e0b';
            }
            if (typeof window.showToast === 'function') {
              window.showToast(warn, 'error');
            }
          }
        } else {
          const err = res.error || '업데이트 실패';
          if (statusEl) {
            statusEl.textContent = err;
            statusEl.style.color = '#f43f5e';
          }
          if (typeof window.showToast === 'function') {
            window.showToast(err, 'error');
          } else {
            alert(err);
          }
        }
      } catch (err) {
        console.error('샘플 플러그인 업데이트 에러:', err);
        if (statusEl) {
          statusEl.textContent = '서버 통신 오류';
          statusEl.style.color = '#f43f5e';
        }
      } finally {
        btn.disabled = false;
        btn.innerHTML = prevText;
      }
    });
  });
}

// ── 샘플 플러그인 설치 모달 ──────────────────────────────

function openSamplePluginsModal() {
  const modal = document.getElementById('sample-plugins-modal');
  if (!modal) return;
  modal.style.display = 'flex';
  loadSamplePluginsList();
}

function closeSamplePluginsModal() {
  const modal = document.getElementById('sample-plugins-modal');
  if (modal) modal.style.display = 'none';
}

async function loadSamplePluginsList() {
  const list = document.getElementById('sample-plugins-list');
  if (!list) return;
  list.innerHTML = '<div style="text-align: center; padding: 1.5rem; color: var(--app-accent);"><i class="fa-solid fa-circle-notch fa-spin"></i></div>';

  try {
    const data = await api.fetchSamplePlugins();
    if (!data.success || !data.samples || data.samples.length === 0) {
      list.innerHTML = '<div style="text-align: center; padding: 1.5rem; color: var(--app-text-muted);">설치 가능한 샘플 플러그인이 없습니다.</div>';
      return;
    }

    list.innerHTML = data.samples.map((s) => `
      <div class="sample-plugin-item" style="display: flex; justify-content: space-between; align-items: center; gap: 1rem; padding: 0.9rem 1rem; background: rgba(var(--app-panel-rgb), 0.4); border: 1px solid rgba(var(--app-panel-border-rgb), 0.08); border-radius: 8px;">
        <div style="min-width: 0;">
          <div style="color: var(--app-text-primary); font-weight: 600; font-size: 0.92rem;">${escapeHtmlText(s.name)}</div>
          <div style="color: var(--app-text-muted); font-size: 0.75rem;">${escapeHtmlText(s.id)}</div>
        </div>
        ${s.installed
          ? `<span style="flex-shrink: 0; font-size: 0.8rem; color: #4ade80; font-weight: 600; display: inline-flex; align-items: center; gap: 0.35rem;"><i class="fa-solid fa-check"></i> 설치됨</span>`
          : `<button type="button" class="sample-plugin-install-btn" data-plugin-id="${escapeHtmlAttr(s.id)}" style="flex-shrink: 0; padding: 0.45rem 0.9rem; font-size: 0.8rem; border-radius: 6px; border: 1px solid rgba(168,85,247,0.5); background: rgba(168,85,247,0.18); color: #e9d5ff; cursor: pointer; display: inline-flex; align-items: center; gap: 0.4rem;">
              <i class="fa-solid fa-download"></i> 설치
            </button>`
        }
      </div>
    `).join('');

    list.querySelectorAll('.sample-plugin-install-btn').forEach((btn) => {
      btn.addEventListener('click', async () => {
        const pluginId = btn.dataset.pluginId;
        const prevText = btn.innerHTML;
        btn.disabled = true;
        btn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i> 설치 중...';
        try {
          const res = await api.installSamplePlugin(pluginId);
          if (res.success) {
            if (typeof window.showToast === 'function') {
              window.showToast(res.message, 'success');
            }
            await loadSamplePluginsList();
            await loadPluginsSettings();
          } else {
            if (typeof window.showToast === 'function') {
              window.showToast(res.error || '설치 실패', 'error');
            } else {
              alert(res.error || '설치 실패');
            }
            btn.disabled = false;
            btn.innerHTML = prevText;
          }
        } catch (err) {
          console.error('샘플 플러그인 설치 에러:', err);
          btn.disabled = false;
          btn.innerHTML = prevText;
        }
      });
    });
  } catch (err) {
    console.error('샘플 플러그인 목록 조회 에러:', err);
    list.innerHTML = '<div style="text-align: center; padding: 1.5rem; color: #f43f5e;">서버와 통신 중 오류가 발생했습니다.</div>';
  }
}

function initSamplePluginsModal() {
  if (window.__samplePluginsModalBound) return;
  window.__samplePluginsModalBound = true;

  document.addEventListener('click', (event) => {
    const openBtn = event.target.closest('[data-role="open-sample-plugins-modal"]');
    if (openBtn) {
      event.preventDefault();
      openSamplePluginsModal();
      return;
    }
    const closeBtn = event.target.closest('[data-role="close-sample-plugins-modal"]');
    if (closeBtn) {
      event.preventDefault();
      closeSamplePluginsModal();
    }
  });
}
