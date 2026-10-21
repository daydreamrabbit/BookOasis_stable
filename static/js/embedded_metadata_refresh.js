const labels={genre:'장르',tags:'태그',author:'작가',translator:'번역가',publisher:'출판사',summary:'소개',isbn:'ISBN'};
const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function openEmbeddedMetadataRefresh(type,bookIds,scope='book',onUpdated=()=>{}) {
 const existing=document.getElementById('embedded-refresh-modal');
 if(existing){existing.querySelector('button')?.focus();return;}
 const modal=document.createElement('div');modal.id='embedded-refresh-modal';modal.className='diagnose-modal';
 modal.innerHTML=`<section class="diagnose-dialog" role="dialog" aria-modal="true" aria-labelledby="embedded-refresh-title"><header class="diagnose-header"><strong id="embedded-refresh-title">EPUB 원본 메타데이터 갱신</strong><button type="button" class="diagnose-close" data-refresh="close" aria-label="닫기">×</button></header><div class="diagnose-body"><p class="embedded-refresh-intro">원본 EPUB에서 선택한 항목만 다시 읽습니다.</p><p class="embedded-refresh-hint">표지·독서 기록은 유지하고 잠긴 도서는 건너뜁니다.<br>원본에 없는 값은 지우지 않습니다.</p><fieldset class="embedded-refresh-group"><legend>갱신할 항목</legend><div class="embedded-refresh-fields">${Object.entries(labels).map(([key,label])=>`<label class="embedded-refresh-field"><input type="checkbox" value="${key}" ${key==='genre'?'checked':''}><span><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 8 3 3 7-7"/></svg>${label}</span></label>`).join('')}</div></fieldset><fieldset class="embedded-refresh-group"><legend>갱신 방식</legend><div class="embedded-refresh-modes"><label class="embedded-refresh-mode"><input type="radio" name="embedded-refresh-mode" data-refresh-mode value="replace" checked><span><strong>원본 값으로 교체</strong><small>선택한 항목을 EPUB 원본과 동일하게 맞춥니다.</small></span></label><label class="embedded-refresh-mode"><input type="radio" name="embedded-refresh-mode" data-refresh-mode value="merge"><span><strong>누락 항목만 추가</strong><small>기존 장르·태그를 유지하고 원본 값을 추가합니다.</small></span></label></div></fieldset><div data-refresh-results role="status" aria-live="polite"></div></div><footer class="diagnose-footer"><button type="button" class="embedded-refresh-button" data-refresh="preview">변경 전후 확인</button><button type="button" class="embedded-refresh-button is-primary" data-refresh="apply" disabled>확인한 변경 적용</button></footer></section>`;
 document.body.appendChild(modal);
 let preview=null,requestController=null,busy=false;
 const applyButton=modal.querySelector('[data-refresh="apply"]'),body=modal.querySelector('[data-refresh-results]');
 const close=()=>{if(busy)return;requestController?.abort();document.removeEventListener('keydown',keydown,true);modal.remove();};
 const keydown=event=>{if(event.key==='Escape'){event.stopImmediatePropagation();close();}};
 document.addEventListener('keydown',keydown,true);
 const invalidate=()=>{preview=null;applyButton.disabled=true;body.textContent='항목이 변경됐습니다. 다시 확인해 주세요.';};
 modal.addEventListener('change',invalidate);
 modal.addEventListener('click',async event=>{
  event.stopPropagation();
  if(event.target===modal){close();return;}
  const action=event.target.closest('[data-refresh]')?.dataset.refresh;
  if(!action||busy)return;
  if(action==='close'){close();return;}
  const fields=[...modal.querySelectorAll('input[type="checkbox"]:checked')].map(n=>n.value),mode=modal.querySelector('[data-refresh-mode]:checked').value;
  if(!fields.length){body.textContent='항목을 선택해 주세요.';return;}
  if(action==='apply'&&!preview)return;
  busy=true;modal.querySelectorAll('button,input,select').forEach(n=>n.disabled=true);body.textContent='원본 메타데이터를 읽는 중…';requestController=new AbortController();
  const target={type,book_ids:bookIds,scope,fields,mode};
  try {
   const response=await fetch('/api/media/books/embedded-metadata-refresh',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...target,action,approved:action==='apply'?preview.entries.filter(n=>!n.error):undefined}),signal:requestController.signal});
   const data=await response.json();if(!response.ok||!data.success)throw new Error(data.error||'원본 갱신에 실패했습니다.');
   if(action==='preview'){
    preview=data;
    body.innerHTML=data.entries.map(row=>`<article class="embedded-refresh-result"><strong>${escape(row.title)}</strong>${row.error?`<p>${escape(row.error)}</p>`:Object.keys(row.changes).length?Object.entries(row.changes).map(([key,value])=>`<p>${escape(labels[key])}: ${escape(value.before||'(비어 있음)')} → ${escape(value.after)}</p>`).join(''):'<p>변경 없음 (원본에 없는 항목은 유지)</p>'}</article>`).join('');
   }else{
    preview=null;body.textContent=`${data.updated}권 갱신 완료`+data.results.filter(n=>n.status==='skipped').map(n=>`\nID ${n.id}: ${n.error||'잠금 또는 동시 변경으로 건너뜀'}`).join('');
    await onUpdated();
   }
  }catch(error){preview=null;body.textContent=error.message;}
  finally{busy=false;modal.querySelectorAll('button,input,select').forEach(n=>n.disabled=false);applyButton.disabled=!preview?.entries.some(n=>!n.error&&Object.keys(n.changes).length);}
 });
 modal.querySelector('[data-refresh="preview"]').focus();
}
