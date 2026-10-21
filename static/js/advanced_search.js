import {state} from './state.js';
import {closeLibrarySearchPreview} from './library_search_preview.js?rev=20260921-search-preview-v1';

const names={categories:'카테고리',series:'시리즈명',author:'글 작가',cover_artist:'그림 작가',publisher:'출판사',publication_status:'연재상태',genre:'장르',tags:'태그',rating:'연령등급'};
const ratings={'0':'전체이용가','15':'15세이상','18':'18세이상(성인)','19':'성인망가','20':'포르노'};
const statuses={'0':'연재','1':'휴재','2':'완결','missing':'누락','unknown':'알 수 없음'};
const empty=()=>({categories:[],series:'',author:'',cover_artist:'',publisher:[],publication_status:[],genre:[],tags:[],rating:[],genre_mode:'and',tags_mode:'and'});
const copy=value=>JSON.parse(JSON.stringify(value));
let panel,button,form,message,submit,draft=empty(),choices={},request,serial=0,busy=false,openedType;
function el(tag,text,cls){const n=document.createElement(tag);if(text!==undefined)n.textContent=text;if(cls)n.className=cls;return n;}
function label(key,value){return key==='categories'?(choices.categories||[]).find(v=>v.value===value)?.label||value:key==='rating'?ratings[value]||value:key==='publication_status'?statuses[value]||value:value;}
async function json(url,signal){const r=await fetch(url,{signal,cache:'no-store'});if(!r.ok||!r.headers.get('content-type')?.includes('application/json'))throw Error('검색 조건을 불러오지 못했습니다. 다시 열어 주세요.');const d=await r.json();if(!d.success)throw Error(d.error||'조회 실패');return d;}
function position(){if(!panel||panel.hidden)return;const r=button.closest('.library-search-box').getBoundingClientRect();if(innerWidth>640){const top=Math.max(8,Math.min(r.bottom+8,innerHeight-200));panel.style.top=top+'px';panel.style.maxHeight=Math.max(120,innerHeight-top-8)+'px';panel.style.left=Math.max(8,Math.min(r.left,innerWidth-Math.min(860,innerWidth-16)-8))+'px';}else{panel.style.top='auto';panel.style.left='8px';panel.style.maxHeight='85dvh';}}
function close(){if(!panel)return;panel.hidden=true;button.setAttribute('aria-expanded','false');request?.abort();serial++;button.focus();}
function renderChoices(key,loading=false){
  const field=form.querySelector(`[data-field="${key}"]`);if(!field)return;
  field.replaceChildren();const summary=el('summary');field.append(summary);
  const updateSummary=()=>{summary.replaceChildren(el('span',names[key]+' · '),el('span',draft[key].length?draft[key].length+'개 선택':'전체','advanced-selection-count'));field.classList.toggle('has-selection',draft[key].length>0);summary.title=draft[key].map(v=>label(key,v)).join(', ')||'전체';};updateSummary();
  const input=el('input');input.type='search';input.placeholder=names[key]+' 값 찾기';input.setAttribute('aria-label',input.placeholder);field.append(input);
  const list=el('div',undefined,'advanced-choice-list');field.append(list);
  if(loading){input.disabled=true;list.append(el('p','불러오는 중…'));return;}
  const draw=()=>{list.replaceChildren();const matches=(choices[key]||[]).filter(v=>v.label.toLocaleLowerCase().includes(input.value.toLocaleLowerCase()));for(const v of matches){const row=el('label');const check=el('input');check.type='checkbox';check.checked=draft[key].includes(v.value);check.addEventListener('change',()=>{draft[key]=check.checked?[...draft[key],v.value]:draft[key].filter(x=>x!==v.value);updateSummary();if(key==='categories')loadOptions();});row.append(check,el('span',v.label));list.append(row);}if(!matches.length)list.append(el('p','해당 값이 없습니다.'));};input.addEventListener('input',draw);draw();
}
async function loadOptions(){
  request?.abort();request=new AbortController();const current=++serial;busy=true;submit.disabled=true;message.textContent='선택한 카테고리의 정보를 불러오는 중…';
  for(const key of ['publisher','publication_status','genre','tags','rating'])renderChoices(key,true);
  try{const q=new URLSearchParams({type:openedType,filters:JSON.stringify({categories:draft.categories})});const data=await json('/api/media/advanced-search/options?'+q,request.signal);if(current!==serial||openedType!==state.currentLibraryType)return;
    let removed=0;for(const key of ['publisher','publication_status','genre','tags','rating']){const values=data.options[key]||[];const prior=draft[key].length;draft[key]=draft[key].filter(x=>values.includes(x));removed+=prior-draft[key].length;choices[key]=values.map(value=>({value,label:label(key,value)}));renderChoices(key);}
    message.textContent=removed?`새 범위에 없는 선택값 ${removed}개를 해제했습니다.`:'카테고리를 선택하지 않으면 접근 가능한 전체 카테고리를 검색합니다.';busy=false;submit.disabled=false;
  }catch(e){if(e.name!=='AbortError'&&current===serial)message.textContent=e.message;}
}
async function apply(value){
  if(!['general','adult'].includes(state.currentLibraryType))return;
  state.advancedSearch=copy(value);state.groupMode='default';state.authorKeyFilter='';
  const search=document.getElementById('library-search');search.value=value.series;
  await window.selectCategory('all',false,{preserveSearch:true,searchNavigation:true,searchQuery:value.series,advancedSearch:copy(value)});
  if(panel&&!panel.hidden)close();renderActive();
}
async function resetSearch(){
  request?.abort();serial++;draft=empty();state.advancedSearch=null;
  state.filterGenres=[];state.filterTags=[];state.filterMode='and';state.searchQuery='';
  document.getElementById('library-search').value='';
  if(panel&&!panel.hidden)close();
  await window.selectCategory('all');renderActive();
}
function renderActive(){
  if(!button)return;const active=state.advancedSearch;const bar=document.getElementById('advanced-search-active');bar.replaceChildren();let count=0;
  if(active){for(const key of Object.keys(names)){const values=Array.isArray(active[key])?active[key]:active[key]?[active[key]]:[];for(const value of values){count++;const chip=el('button',`${names[key]}: ${label(key,value)} ×`);chip.type='button';chip.addEventListener('click',()=>{const next=copy(state.advancedSearch);next[key]=Array.isArray(next[key])?next[key].filter(v=>v!==value):'';apply(next);});bar.append(chip);}}
    const reset=el('button','전체 초기화');reset.type='button';reset.addEventListener('click',resetSearch);bar.append(reset);}
  bar.hidden=!active;button.replaceChildren();const icon=el('i',undefined,'fa-solid fa-sliders');icon.setAttribute('aria-hidden','true');button.append(icon,el('span','상세검색','advanced-trigger-label'));if(count)button.append(el('span',String(count),'advanced-trigger-count'));button.classList.toggle('has-filters',count>0);button.title=active?'상세검색 조건 변경':'상세검색';button.setAttribute('aria-label',count?`상세검색, ${count}개 조건 적용`:'상세검색');
  button.hidden=!['general','adult'].includes(state.currentLibraryType);
}
async function open(){
  if(!panel.hidden){close();return;}openedType=state.currentLibraryType;if(!['general','adult'].includes(openedType))return;busy=true;
  closeLibrarySearchPreview();draft={...empty(),...copy(state.advancedSearch||{}),series:state.advancedSearch?.series??document.getElementById('library-search').value};
  // Keep explicit advanced scopes (including "all"); otherwise inherit the
  // category currently being browsed, never virtual home/history/favorite IDs.
  if(!state.advancedSearch&&/^[1-9]\d*$/.test(String(state.currentLibraryId))){
    draft.categories=[String(state.currentLibraryId)];
  }
  choices={};
  form.replaceChildren();const textRow=el('div',undefined,'advanced-text-fields');for(const key of ['series','author','cover_artist']){const row=el('label',names[key]);const input=el('input');input.type='search';input.value=draft[key];input.maxLength=200;input.name=key;input.placeholder=key==='series'?'시리즈명으로 검색':names[key]+' 입력';input.addEventListener('input',()=>draft[key]=input.value);row.append(input);textRow.append(row);}form.append(textRow);
  const grid=el('div',undefined,'advanced-fields');for(const key of ['categories','publisher','publication_status','genre','tags','rating']){const field=el('details');field.dataset.field=key;grid.append(field);}form.append(grid);
  // An empty <details> displays the browser's default "Details" label.
  // Install stable summaries before revealing the panel, not after network I/O.
  for(const key of ['categories','publisher','publication_status','genre','tags','rating'])renderChoices(key,true);
  const modes=el('div',undefined,'advanced-modes');for(const key of ['genre','tags']){const row=el('label',names[key]+' 조건 ');const select=el('select');select.setAttribute('aria-label',names[key]+' 조건');for(const [value,text]of [['and','모두 포함 AND'],['or','하나 이상 OR']]){const opt=el('option',text);opt.value=value;select.append(opt);}select.value=draft[key+'_mode'];select.addEventListener('change',()=>draft[key+'_mode']=select.value);row.append(select);modes.append(row);}form.append(modes);
  message=el('p','','advanced-message');message.setAttribute('role','status');submit=el('button','검색','advanced-submit');submit.type='submit';submit.disabled=true;
  const actions=el('div',undefined,'advanced-actions');const reset=el('button','초기화','advanced-reset');reset.type='button';reset.addEventListener('click',resetSearch);actions.append(reset,submit);
  form.append(message,actions);panel.hidden=false;button.setAttribute('aria-expanded','true');position();
  const current=++serial;request?.abort();request=new AbortController();
  try{const data=await json('/api/media/libraries?type='+openedType,request.signal);if(current!==serial)return;choices.categories=(data.libraries||[]).map(l=>({value:String(l.id),label:l.name}));const allowed=new Set(choices.categories.map(v=>v.value));draft.categories=draft.categories.filter(v=>allowed.has(v));renderChoices('categories');await loadOptions();form.querySelector('input')?.focus();}catch(e){if(e.name!=='AbortError')message.textContent=e.message;}
}
export function initAdvancedSearch(){
  button=document.getElementById('btn-advanced-search');if(!button||button.dataset.bound)return;button.dataset.bound='1';
  panel=el('section',undefined,'advanced-search-panel');panel.id='advanced-search-panel';panel.hidden=true;panel.setAttribute('role','dialog');panel.setAttribute('aria-label','상세검색');
  const header=el('header');header.append(el('strong','상세검색'));const dismiss=el('button','닫기');dismiss.type='button';dismiss.addEventListener('click',close);header.append(dismiss);panel.append(header);
  form=el('form');form.addEventListener('submit',e=>{e.preventDefault();if(!busy&&openedType===state.currentLibraryType)apply(draft);});panel.append(form);document.body.append(panel);
  button.addEventListener('click',open);window.addEventListener('resize',position);
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!panel.hidden){e.preventDefault();e.stopPropagation();close();}},true);
  document.addEventListener('pointerdown',e=>{if(!panel.hidden&&!e.composedPath().includes(panel)&&!e.composedPath().includes(button))close();});
  window.addEventListener('bookoasis:advanced-search-changed',()=>{if(!panel.hidden&&openedType!==state.currentLibraryType)close();renderActive();});
  renderActive();
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',initAdvancedSearch);else initAdvancedSearch();
