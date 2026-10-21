const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function trashBadgeHtml(id,count,type,name) {
  if (!Number.isInteger(Number(id)) || Number(id)<=0 || !Number.isInteger(count) || count<=0 || !['general','adult','audiobook','video'].includes(type)) return '';
  const label=`${name || '카테고리'} 휴지통 ${count.toLocaleString()}권 · 내역 보기`;
  return `<button type="button" class="category-trash-badge" data-role="category-trash" data-library-id="${Number(id)}" data-db-type="${type}" title="${escape(label)}" aria-label="${escape(label)}" draggable="false" style="display:inline-flex;align-items:center;justify-content:center;gap:4px;min-height:28px;min-width:32px;padding:3px 6px;border:1px solid rgba(245,158,11,.3);border-radius:6px;background:rgba(245,158,11,.1);color:#f59e0b;font-size:11px;cursor:pointer;flex-shrink:0;"><i class="fa-solid fa-trash-can" aria-hidden="true"></i><span>${count.toLocaleString()}</span></button>`;
}
