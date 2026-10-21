const escape = value => String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export function genreNames(value) {
  const raw=Array.isArray(value)?value:String(value || '').split(/[,;|\n]+/);
  return [...new Set(raw.filter(v=>typeof v==='string').map(v=>v.trim().replace(/^[\s"'\[\]]+|[\s"'\[\]]+$/g,'')).filter(Boolean))];
}
export function genreBadgesHtml(value) {
  const names=genreNames(value);
  if (!names.length) return '';
  const visible=names.map(name=>`<span class="book-card-genre" title="${escape(name)}">${escape(name)}</span>`).join('');
  return `<div class="book-card-genres" tabindex="0" aria-label="장르: ${escape(names.join(', '))} (좌우로 이동)">${visible}</div>`;
}
