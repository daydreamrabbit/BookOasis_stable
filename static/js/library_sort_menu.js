// Keep the existing sort choices and add metadata score sorting, without
// replacing the custom search/filter state or introducing upstream read filters.
import { bindFloatingMenuOutsideClose, hideFloatingMenu, isFloatingMenuOpen, positionMenuAtElement } from './context_menu_manager.js';
import { state } from './state.js';

export const SORT_OPTIONS = [
  { value: 'asc', key: 'book_list.sort_asc', icon: 'fa-sort-alpha-down' },
  { value: 'desc', key: 'book_list.sort_desc', icon: 'fa-sort-alpha-up' },
  { value: 'date_desc', key: 'book_list.sort_date_desc', icon: 'fa-sort-numeric-down-alt' },
  { value: 'date_asc', key: 'book_list.sort_date_asc', icon: 'fa-sort-numeric-up' },
  { value: 'rating_desc', label: '내 별점 높은 순', icon: 'fa-star' },
  { value: 'rating_asc', label: '내 별점 낮은 순', icon: 'fa-star-half-stroke' },
];

export function toggleLibrarySortMenu(anchor, { current, onSelect }) {
  let menu = document.getElementById('library-sort-menu');
  if (!menu) {
    menu = document.createElement('div');
    menu.id = 'library-sort-menu';
    menu.className = 'context-menu library-sort-menu';
    menu.style.display = 'none';
    document.body.append(menu);
    bindFloatingMenuOutsideClose(menu, {
      shouldIgnoreEvent: event => !!event.target?.closest?.('[data-role="library-sort-toggle"]'),
    });
  }
  if (isFloatingMenuOpen(menu)) { hideFloatingMenu(menu); return; }
  const list = document.createElement('ul');
  list.className = 'context-menu-list';
  for (const option of SORT_OPTIONS) {
    if (option.value.startsWith('rating_') && !['general','adult'].includes(state.currentLibraryType)) continue;
    const item = document.createElement('li');
    item.className = 'context-menu-item';
    item.dataset.sort = option.value;
    item.classList.toggle('active', option.value === current);
    item.setAttribute('role', 'menuitemradio');
    item.setAttribute('aria-checked', String(option.value === current));
    const icon = document.createElement('i');
    icon.className = `fa-solid ${option.icon}`;
    const label = document.createElement('span');
    label.textContent = option.label || i18n.t(option.key);
    item.append(icon, label);
    item.addEventListener('click', () => {
      hideFloatingMenu(menu);
      if (option.value !== current) onSelect(option.value);
    });
    list.append(item);
  }
  menu.replaceChildren(list);
  positionMenuAtElement(menu, anchor, { zIndex: 20050 });
}
