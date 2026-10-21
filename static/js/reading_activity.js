import {bindShelfDrag} from './shelf_drag.js';

let savedActivityColor='#39d353';
let colorSaveQueue=Promise.resolve();
let colorRevision=0;
export function applyActivityColor(value){
  const color=/^#[0-9a-f]{6}$/i.test(value||'')?value.toLowerCase():'#39d353';
  savedActivityColor=color;
  document.documentElement.style.setProperty('--reading-activity-color',color);
  document.querySelectorAll('[data-activity-color]').forEach(input=>{input.value=color;});
}
export function initActivityColors(){
  document.querySelectorAll('[data-activity-color]').forEach(input=>{
    if(input.dataset.bound)return;
    input.dataset.bound='1';input.value=savedActivityColor;
    input.addEventListener('input',()=>{
      document.documentElement.style.setProperty('--reading-activity-color',input.value);
    });
    input.addEventListener('change',()=>{
      const value=input.value,revision=++colorRevision;
      document.querySelectorAll('[data-activity-color]').forEach(el=>{el.value=value;});
      // Serialize saves: a slower old request must not overwrite a newer color.
      colorSaveQueue=colorSaveQueue.then(async()=>{
        try{
          const body=new FormData();body.append('key','READING_ACTIVITY_COLOR');body.append('value',value);
          const response=await fetch('/api/media/settings/user',{method:'POST',body});
          if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw new Error('색상을 저장하지 못했습니다.');
          const result=await response.json();if(!result.success)throw new Error(result.error||'색상 저장 실패');
          savedActivityColor=value;
          if(revision===colorRevision)applyActivityColor(value);
          window.dispatchEvent(new CustomEvent('bookoasis:activity-color-saved',{detail:{color:value}}));
        }catch(error){
          if(revision===colorRevision)applyActivityColor(savedActivityColor);
          if(window.showToast)window.showToast(error.message,'error');
          const message=document.querySelector('[data-activity-color-message]');
          if(message)message.textContent=error.message;
        }
      });
    });
  });
}

const escape=value=>String(value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function activityTip(date,entry,future,today){
  const books=Math.max(0,Math.floor(Number(entry.book_count)||0));
  const pages=Math.max(0,Number(entry.pages_read)||0);
  const seconds=Math.max(0,Math.floor(Number(entry.duration_seconds)||0));
  const duration=seconds>0&&seconds<60?`${seconds}초`:`${Math.floor(seconds/60)}분`;
  const detail=future?'아직 오지 않은 날짜입니다.':books||pages||seconds?`${books}권 · ${pages}페이지 · ${duration}`:'독서 기록이 없습니다.';
  const title=date.replace(/^(\d{4})-(\d{2})-(\d{2})$/,'$1년 $2월 $3일');
  return `data-profile-tip="${escape(title)}" data-profile-tip-detail="${escape(detail)}" tabindex="${date===today?'0':'-1'}"`;
}
export function activityCalendar(year,daily=[],today=new Date().toISOString().slice(0,10)){
  year=Number(year);
  if(!Number.isInteger(year)||year<2000||year>2100) throw new Error('올바르지 않은 연도입니다.');
  const first=Date.UTC(year,0,1),last=Date.UTC(year+1,0,1),leading=new Date(first).getUTCDay();
  const days=Math.round((last-first)/86400000),weeks=Math.ceil((leading+days)/7);
  const byDate=new Map(daily.filter(v=>v&&typeof v.date==='string').map(v=>[v.date,v]));
  const cells=[];let active=0;
  for(let i=0;i<leading;i++) cells.push('<span class="reading-activity-day is-empty" aria-hidden="true"></span>');
  for(let i=0;i<days;i++){
    const date=new Date(first+i*86400000).toISOString().slice(0,10),entry=byDate.get(date)||{};
    const pages=Math.max(0,Number(entry.pages_read)||0),minutes=Math.max(0,Math.floor((Number(entry.duration_seconds)||0)/60));
    const score=Math.max(pages,minutes,Number(entry.book_count)||0),future=date>today;
    const level=future||score<=0?0:score<10?1:score<30?2:score<80?3:4;
    if(level)active++;
    const label=`${date} · ${pages}페이지 · ${minutes}분${future?' · 아직 오지 않은 날짜':''}`;
    cells.push(`<span class="reading-activity-day${future?' is-future':''}" data-date="${date}" data-level="${level}" ${activityTip(date,entry,future,today)} aria-label="${escape(label)}"></span>`);
  }
  const months=Array.from({length:12},(_,month)=>{
    const column=Math.floor((leading+(Date.UTC(year,month,1)-first)/86400000)/7)+1;
    return `<span style="grid-column:${column}">${month+1}월</span>`;
  }).join('');
  return {year,days,weeks,active,html:`<div class="reading-activity-annual"><div class="reading-activity-scroll" tabindex="0" aria-label="${year}년 독서 활동, 좌우로 이동"><div class="reading-activity-chart" style="--activity-weeks:${weeks}"><div class="reading-activity-months">${months}</div><div class="reading-activity-weekdays" aria-hidden="true"><span>일</span><span></span><span>화</span><span></span><span>목</span><span></span><span>토</span></div><div class="reading-activity-days" role="img" aria-label="${year}년 일별 독서 활동">${cells.join('')}</div></div></div><div class="reading-activity-footer"><span>${year}년 · ${active}일 독서</span><div class="reading-activity-legend"><span>적음</span>${[0,1,2,3,4].map(level=>`<i data-level="${level}"></i>`).join('')}<span>많음</span></div></div></div>`};
}

const annualResizeObservers=new WeakMap();
export function renderActivityCalendar(target,year,daily,today){
  if(!target)return;
  annualResizeObservers.get(target)?.disconnect();
  window.dispatchEvent(new CustomEvent('bookoasis:activity-rendering'));
  const result=activityCalendar(year,daily,today);target.innerHTML=result.html;
  const scroll=target.querySelector('.reading-activity-scroll');bindShelfDrag(scroll);
  // On narrow screens show the current month rather than only January.
  const current=target.querySelector(`[data-date="${today||new Date().toISOString().slice(0,10)}"]`);
  let lastWidth=0;
  const revealCurrent=()=>{
    const width=scroll.clientWidth;
    if(!width||width===lastWidth)return;
    lastWidth=width;
    if(current)scroll.scrollLeft=Math.max(0,current.offsetLeft-width+50);
  };
  revealCurrent();
  if(typeof ResizeObserver!=='undefined'){
    const observer=new ResizeObserver(revealCurrent);observer.observe(scroll);
    annualResizeObservers.set(target,observer);
  }
}

// Dashboard history runs from January 1 through today. A narrow card scrolls;
// resizing must never silently change which past dates are included.
export function activityHistory(daily=[],today=new Date().toISOString().slice(0,10)){
  const date=new Date(today+'T00:00:00Z');
  if(!Number.isFinite(date.getTime()))throw new Error('올바르지 않은 날짜입니다.');
  const year=date.getUTCFullYear(),start=Date.UTC(year,0,1),leading=new Date(start).getUTCDay();
  const days=Math.round((date.getTime()-start)/86400000)+1,weeks=Math.ceil((leading+days)/7);
  const byDate=new Map(daily.map(entry=>[entry.date,entry]));
  const cells=Array.from({length:days},(_,i)=>{
    const key=new Date(start+i*86400000).toISOString().slice(0,10),entry=byDate.get(key)||{};
    const pages=Math.max(0,Number(entry.pages_read)||0),minutes=Math.max(0,Math.floor((Number(entry.duration_seconds)||0)/60));
    const score=Math.max(pages,minutes,Number(entry.book_count)||0),future=key>today;
    const level=future||score<=0?0:score<10?1:score<30?2:score<80?3:4;
    const title=`${key} · ${pages}페이지 · ${minutes}분`;
    return `<span class="reading-activity-day${future?' is-future':''}" data-date="${key}" data-level="${level}" ${activityTip(key,entry,future,today)} aria-label="${escape(title)}"></span>`;
  });
  const padding='<span class="reading-activity-day is-empty" aria-hidden="true"></span>'.repeat(leading);
  return {year,days,weeks,start:new Date(start).toISOString().slice(0,10),html:`<div class="reading-activity-mini-scroll" tabindex="0" aria-label="${year}년 1월 1일부터 ${today}까지 독서 활동, 좌우로 이동"><div class="reading-activity-mini-grid" style="--activity-mini-weeks:${weeks}" role="img" aria-label="${year}년 일별 독서 활동">${padding}${cells.join('')}</div></div><div class="reading-activity-mini-legend"><span>${year}년</span><div class="reading-activity-legend"><span>적음</span>${[0,1,2,3,4].map(level=>`<i data-level="${level}"></i>`).join('')}<span>많음</span></div></div>`};
}

let activityRequest=null;
let historyResizeObserver=null;
export function renderActivityHistory(target,daily,today){
  if(!target)return;
  historyResizeObserver?.disconnect();
  window.dispatchEvent(new CustomEvent('bookoasis:activity-rendering'));
  target.innerHTML=activityHistory(daily,today).html;
  const scroll=target.querySelector('.reading-activity-mini-scroll');
  bindShelfDrag(scroll);
  let lastWidth=0;
  const revealToday=()=>{
    const width=scroll.clientWidth;
    if(!width||width===lastWidth)return;
    lastWidth=width;
    scroll.scrollLeft=Math.max(0,scroll.scrollWidth-width);
  };
  revealToday();
  if(typeof ResizeObserver!=='undefined'){
    historyResizeObserver=new ResizeObserver(revealToday);
    historyResizeObserver.observe(scroll);
  }
}
export async function loadDashboardActivity(libraryType='general'){
  initActivityColors();
  const target=document.getElementById('dashboard-activity-calendar');if(!target)return;
  activityRequest?.abort();const controller=new AbortController();activityRequest=controller;
  try{
    const response=await fetch(`/api/dashboard/activity?library_type=${encodeURIComponent(libraryType)}`,{signal:controller.signal});
    if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw new Error('활동 기록 조회 실패');
    const data=await response.json();if(!data.success)throw new Error('활동 기록 조회 실패');
    if(activityRequest!==controller)return;
    renderActivityHistory(target,data.activity.daily,data.activity.today);
  }catch(e){if(e.name!=='AbortError'&&activityRequest===controller)target.textContent='활동 기록을 불러오지 못했습니다. 홈을 다시 열어 주세요.';}
}

if(typeof window!=='undefined')window.addEventListener('bookoasis:view-changing',event=>{
  if(event.detail?.viewName!=='dashboard'){activityRequest?.abort();activityRequest=null;historyResizeObserver?.disconnect();}
});
