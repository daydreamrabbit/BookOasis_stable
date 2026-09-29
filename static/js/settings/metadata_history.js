const labels = {running:'수집 중', completed:'완료', failed:'실패', interrupted:'중단', searching:'검색 중', applied:'적용', not_matched:'미매칭', skipped:'적용 보류'};
let page = 1, runId = '', timer, controller, generation = 0, bound = false;
const el = id => document.getElementById(`metadata-history-${id}`);
const visible = () => !!document.getElementById('settings-tab-metadata-history')?.getClientRects().length;
const date = value => new Date(value * 1000).toLocaleString();
function statuses() {
  const select = el('filters').elements.status;
  select.replaceChildren(new Option('전체 상태', ''));
  (runId ? ['searching','applied','not_matched','skipped','failed','interrupted'] : ['running','completed','failed','interrupted']).forEach(key => select.add(new Option(labels[key], key)));
  el('back').hidden = !runId;
  for (const key of ['type','library_id']) el('filters').elements[key].disabled = !!runId;
}
export function stopMetadataHistory() {
  clearTimeout(timer); controller?.abort(); generation++;
}
async function refresh() {
  stopMetadataHistory();
  if (!visible()) return;
  const serial = generation;
  controller = new AbortController();
  const params = new URLSearchParams(new FormData(el('filters')));
  params.set('page', page); if (runId) params.set('run_id', runId);
  try {
    const response = await fetch(`/api/system/metadata-history?${params}`, {signal:controller.signal, cache:'no-store'});
    const data = await response.json();
    if (!response.ok || !data.success) throw new Error(data.error || '이력을 불러오지 못했습니다.');
    if (serial !== generation || !visible()) return;
    if (data.libraries) {
      const select = el('filters').elements.library_id, selected = select.value;
      select.replaceChildren(new Option('전체 카테고리', ''));
      const seen = new Set();
      data.libraries.filter(item => !params.get('type') || item.db_type === params.get('type')).forEach(item => {
        if (seen.has(item.library_id)) return;
        seen.add(item.library_id);
        select.add(new Option(`${item.library_name || '카테고리'} (#${item.library_id})`, item.library_id));
      });
      select.value = selected;
    }
    const headers = runId ? ['작품명','상태','수집원','결과 / 사유','갱신 시각'] : ['시작 시각','카테고리','상태','검색 / 전체 · 매칭 · 적용','상세'];
    const head = document.createElement('tr');
    headers.forEach(text => { const cell = document.createElement('th'); cell.textContent = text; head.append(cell); });
    el('head').replaceChildren(head);
    el('rows').replaceChildren();
    data.items.forEach(item => {
      const row = document.createElement('tr');
      const values = runId ? [item.title, labels[item.status] || item.status, item.sources, item.reason, date(item.updated)] : [date(item.started), `${item.library_name || '카테고리'} (#${item.library_id ?? '전체'}) · ${item.db_type}`, labels[item.status] || item.status, `${item.processed}/${item.total} · ${item.matched} · ${item.applied}`];
      values.forEach(text => { const cell = document.createElement('td'); cell.textContent = text || '—'; cell.style.padding = '.6rem'; row.append(cell); });
      if (!runId) {
        const cell = document.createElement('td'), button = document.createElement('button');
        button.textContent = '작품별 결과'; button.dataset.run = item.id; cell.append(button); row.append(cell);
      }
      el('rows').append(row);
    });
    el('summary').textContent = data.run ? `${labels[data.run.status]} · 검색 ${data.run.processed}/${data.run.total} · 매칭 ${data.run.matched} · 적용 ${data.run.applied}${data.run.current_title ? ' · 현재: ' + data.run.current_title : ''}` : (data.total ? '작품별 결과 버튼을 눌러 상세 이력을 확인하세요.' : '기록된 수집 이력이 없습니다.');
    el('page').textContent = `${page} / ${Math.max(1, Math.ceil(data.total / 50))} 페이지 · ${data.total}건`;
    el('prev').disabled = page <= 1; el('next').disabled = page * 50 >= data.total;
    if (data.run?.status === 'running' || data.items.some(item => item.status === 'running')) {
      timer = setTimeout(() => { if (!document.hidden && visible()) refresh(); }, 5000);
    }
  } catch (error) {
    if (error.name !== 'AbortError' && serial === generation) el('summary').textContent = error.message;
  }
}
export function openMetadataHistory() {
  if (!bound) {
    bound = true; statuses();
    el('filters').elements.type.addEventListener('change', () => { el('filters').elements.library_id.value = ''; page = 1; refresh(); });
    el('filters').addEventListener('submit', event => { event.preventDefault(); page = 1; refresh(); });
    el('rows').addEventListener('click', event => {
      const button = event.target.closest('button[data-run]'); if (!button) return;
      runId = button.dataset.run; page = 1; el('filters').elements.q.value = ''; statuses(); refresh();
    });
    el('back').addEventListener('click', () => { runId = ''; page = 1; statuses(); refresh(); });
    el('prev').addEventListener('click', () => { if(page > 1) { page--; refresh(); } });
    el('next').addEventListener('click', () => { page++; refresh(); });
    document.addEventListener('visibilitychange', () => { if (!document.hidden && visible()) refresh(); else stopMetadataHistory(); });
  }
  refresh();
}
