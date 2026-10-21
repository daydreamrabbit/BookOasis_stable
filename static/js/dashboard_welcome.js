// Presentation only: keep the existing navigation, permissions and widget APIs.
import {selectCategory} from './category_navigation.js?rev=20260920-library-content-kind-v2';
import './home_welcome_banner.js';

if (!window.__bookoasisWelcomeBound) {
  window.__bookoasisWelcomeBound = true;
  window.addEventListener('bookoasis:view-changing',event=>{
    document.documentElement.classList.toggle('bookoasis-home',event.detail?.viewName === 'dashboard');
  });
  document.addEventListener('click',event=>{
    const button=event.target.closest?.('[data-home-shortcut]');
    if (!button) return;
    const action=button.dataset.homeShortcut;
    if (!['search','favorite','history','profile'].includes(action)) return;
    event.preventDefault();
    if (action === 'search') {
      const input=document.getElementById('library-search');
      input?.scrollIntoView({block:'nearest'});
      input?.focus({preventScroll:true});
      return;
    }
    selectCategory(action);
  });
}
