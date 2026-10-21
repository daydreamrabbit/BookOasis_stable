import { state } from '../state.js';

export const CORE_DETAIL_OPTION_KEYS = new Set([
  'DETAIL_VOLUME_GRID_VIEW', 'COLLAPSE_DETAIL_GENRE_TAGS',
  'SHOW_CONTENT_RATING_BADGE', 'SHOW_TXT_NO_COVER_INFO_BANNER', 'BOOK_RECOMMEND_ENABLED',
  'SMART_RECOMMEND_ENABLED',
]);

export function syncCoreDetailOptions() {
  const hidden = state.activeDetailViewProviders?.[state.currentLibraryType || 'general'] === 'rabbit_plugins';
  for (const key of CORE_DETAIL_OPTION_KEYS) {
    const input = document.querySelector(`input[name="${key}"]`);
    const row = input?.closest('.settings-checkbox-row');
    if (row) {
      row.hidden = hidden;
      row.style.display = hidden ? 'none' : '';
      row.dataset.coreDetailOptionHidden = hidden ? '1' : '0';
    }
  }
}

export function shouldSaveCoreDetailOption(key) {
  if (!CORE_DETAIL_OPTION_KEYS.has(key)) return true;
  return state.activeDetailViewProviders?.[state.currentLibraryType || 'general'] !== 'rabbit_plugins';
}
