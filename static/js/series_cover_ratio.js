// Shared by core cards and plugin shadow-DOM cards. Preferences are per account.
const data = new Map();
const cards = new Set();
const keys = new Map();
function identity(card) {
  return `${card.dataset.libraryId}\n${card.dataset.seriesName?.trim() || 'book:' + card.dataset.bookId}`;
}
async function keyFor(card) {
  const text = identity(card);
  if (!keys.has(text)) keys.set(text, crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
    .then(bytes => [...new Uint8Array(bytes)].map(b => b.toString(16).padStart(2, '0')).join('')));
  return keys.get(text);
}
function load(type) {
  if (!data.has(type)) data.set(type, Promise.all([
    fetch(`/api/media/series/cover-ratios?type=${encodeURIComponent(type)}`, {cache:'no-store'}).then(r=>r.json()),
    fetch(`/api/media/libraries?type=${encodeURIComponent(type)}`, {cache:'no-store'}).then(r=>r.json()),
  ]).then(([prefs, libs]) => {
    if (!prefs.success || !libs.success) throw new Error('표지 설정을 불러오지 못했습니다.');
    return {ratios:prefs.ratios || {}, libraries:Object.fromEntries((libs.libraries || []).map(l=>[String(l.id),l.cover_aspect_ratio]))};
  }).catch(error=>{data.delete(type);throw error;}));
  return data.get(type);
}
async function apply(card) {
  const type = card.dataset.coverDbType;
  const [settings, key] = await Promise.all([load(type), keyFor(card)]);
  const ratio = settings.ratios[key] || settings.libraries[card.dataset.libraryId];
  card.dataset.coverRatio = type === 'video' || ratio === '16:9' ? '16-9' : '4-3';
  card.dataset.seriesCoverRatio = settings.ratios[key] || 'inherit';
}
export function bindSeriesCoverRatio(card, type) {
  card.dataset.coverDbType = type;
  for (const ref of cards) if (!ref.deref()) cards.delete(ref);
  cards.add(new WeakRef(card));
  apply(card).catch(error=>console.warn('[SeriesCoverRatio]',error.message));
}
export async function saveSeriesCoverRatio(type, bookId, ratio) {
  const response = await fetch('/api/media/series/cover-ratios', {
    method:'POST', headers:{'Content-Type':'application/json'},
    body:JSON.stringify({type,book_id:bookId,ratio}),
  });
  const result = await response.json();
  if (!response.ok || !result.success) throw new Error(result.error || '표지 비율 저장 실패');
  data.delete(type);
  await load(type);
  await Promise.all([...cards].map(ref=>{
    const card=ref.deref();
    return card?.isConnected && card.dataset.coverDbType === type ? apply(card) : null;
  }));
}
