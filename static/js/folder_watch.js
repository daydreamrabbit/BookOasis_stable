function escape(value) {
  return String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}

export function watchSummary(watch) {
  if (!watch) return '';
  const enabled = watch.config?.enabled;
  const checked = watch.last_check ? new Date(watch.last_check * 1000).toLocaleString() : '아직 확인 전';
  return `<small style="display:block;margin-top:6px;color:var(--app-text-muted)" title="${escape(watch.error || `최근 확인: ${checked}`)}">폴더 감시: ${escape(enabled ? watch.status : '꺼짐')}${watch.error && enabled ? ' ⚠' : ''}</small>`;
}

export async function openFolderWatch(libraryId, type, onSaved) {
  document.getElementById('folder-watch-dialog')?.remove();
  const dialog = document.createElement('dialog');
  dialog.id = 'folder-watch-dialog';
  dialog.style.cssText = 'width:min(480px,calc(100vw - 32px));max-height:80dvh;overflow:auto;box-sizing:border-box;padding:20px;border:1px solid var(--app-border,#555);border-radius:12px;background:var(--app-panel,#222);color:var(--app-text-primary,#eee);';
  dialog.innerHTML = '<p>폴더 감시 설정을 불러오는 중…</p><button type="button">닫기</button>';
  dialog.querySelector('button').onclick = () => dialog.remove();
  document.body.append(dialog);dialog.showModal();
  const url = `/api/media/libraries/${libraryId}/watch?type=${encodeURIComponent(type)}`;
  try {
    const response = await fetch(url, {cache:'no-store'});const data = await response.json();
    if (!response.ok || !data.success) throw Error(data.error || '조회 실패');
    if (!dialog.isConnected) return;
    const c = data.watch.config;
    dialog.innerHTML = `<form style="display:grid;gap:14px">
      <h3 style="margin:0">폴더 감시</h3>
      <label><input name="enabled" type="checkbox" ${c.enabled?'checked':''}> 이 라이브러리 감시</label>
      <label>감지 방식 <select name="mode">
        <option value="auto">자동 (로컬 이벤트 / NAS·Drive 목록 비교)</option>
        <option value="local">로컬 이벤트 + 주기적 재확인</option>
        <option value="poll">NAS / 마운트 목록 비교</option>
        <option value="rclone">rclone 원격 목록 비교</option>
      </select></label>
      <label>확인 주기(초) <input name="interval" type="number" min="10" max="86400" required value="${Number(c.interval)}"></label>
      <label>변경 후 안정화 대기(초) <input name="settle" type="number" min="10" max="3600" required value="${Number(c.settle)}"></label>
      <label>rclone 원격 경로 <textarea name="rclone_remote" rows="2" placeholder="remote:books">${escape(c.rclone_remote)}</textarea></label>
      <small>자동 방식은 rclone 마운트의 여러 경로도 자동 연결합니다. 수동 rclone 방식은 라이브러리 경로 순서대로 원격 경로를 한 줄씩 입력하세요. 공개 Drive 폴더는 서버의 API 키를 사용합니다.</small>
      <label><input name="reflect_deletions" type="checkbox" ${c.reflect_deletions?'checked':''}> 사라진 도서를 라이브러리 휴지통으로 이동</label>
      <small>원본 파일은 삭제하지 않습니다. 전체/대량 누락은 연결 장애로 판단해 보류합니다. 처음 켤 때는 기준 목록만 저장합니다.</small>
      <p role="status" style="white-space:pre-wrap;margin:0"></p>
      <div style="display:flex;gap:10px;justify-content:flex-end"><button type="button" data-close>닫기</button><button type="submit">저장</button></div>
    </form>`;
    const form=dialog.querySelector('form');form.elements.mode.value=c.mode;
    const checked=data.watch.last_check?new Date(data.watch.last_check*1000).toLocaleString():'아직 확인 전';
    form.querySelector('[role=status]').textContent=`${data.watch.status}\n최근 확인: ${checked}\n${data.watch.error || ''}`;
    form.querySelector('[data-close]').onclick=()=>dialog.remove();
    form.onsubmit=async e=>{
      e.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try {
        const body={enabled:form.elements.enabled.checked,mode:form.elements.mode.value,
          interval:Number(form.elements.interval.value),settle:Number(form.elements.settle.value),
          reflect_deletions:form.elements.reflect_deletions.checked,rclone_remote:form.elements.rclone_remote.value};
        const res=await fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
        const result=await res.json();if(!res.ok||!result.success)throw Error(result.error||'저장 실패');
        dialog.remove();onSaved?.();
      } catch(error) {form.querySelector('[role=status]').textContent=error.message;}
      finally {submit.disabled=false;}
    };
  } catch(error) {dialog.querySelector('p').textContent=error.message;}
}
