import {getBookCoverSrc} from './cover_fallback.js';
import {state} from './state.js';

const profileStatuses={reading:'읽는 중',completed:'완독',planning:'읽을 예정'};
const libraryViews={reading:'profile-reading-content',favorites:'profile-favorites-content',statistics:'profile-charts'};
let libraryGeneration=0,libraryInitialized=false,currentLibraryTab='overview',librarySearchTimer;
const libraryRequests=new Map(),libraryResults=new Map(),libraryPages={};
const libraryFilters={format:'',genre:'',tag:'',year:''};
let libraryStatus='',libraryQuery='',librarySort='title',statisticsSection='overview';
const profileYearMetric={release:'titles',reading:'titles'};
let profileCategoryMetric='count';
const statisticsCovers=new Map();
const pe=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const profileCover=item=>getBookCoverSrc({coverImage:item.cover_image,title:item.name,format:item.file_format,seed:item.id});

export function resetProfileLibrary(){
  libraryGeneration++;
  clearTimeout(librarySearchTimer);
  for(const tab of Object.keys(libraryPages))libraryPages[tab]=1;
  for(const request of libraryRequests.values())request.abort();
  libraryRequests.clear();libraryResults.clear();
}

function libraryPagination(tab,data){
  const target=document.getElementById(`profile-${tab}-pages`);if(!target)return;
  const last=Math.max(1,Math.ceil(data.total/data.page_size));
  target.innerHTML=last>1?`<button type="button" data-profile-page="${tab}" data-page="${data.page-1}" ${data.page===1?'disabled':''}>이전</button><span>${data.page} / ${last} · ${data.total}작품</span><button type="button" data-profile-page="${tab}" data-page="${data.page+1}" ${data.page>=last?'disabled':''}>다음</button>`:'';
}

function libraryAction(item,index,content){
  return `<button type="button" data-profile-library-item="${index}" data-profile-library-mode="${currentLibraryTab}" aria-label="${pe(item.name)} 상세 보기" ${content}>`;
}

function renderReadingLibrary(data){
  for(const [filter,key]of Object.entries({format:'formats',genre:'genres',tag:'tags',year:'years'})){
    const select=document.querySelector(`[data-profile-list-filter="${filter}"]`);if(!select)continue;
    select.innerHTML='<option value="">전체</option>'+(data.options?.[key]||[]).map(value=>`<option value="${pe(value)}">${pe(value)}</option>`).join('');select.value=libraryFilters[filter];
  }
  const filters=document.getElementById('profile-reading-statuses');
  if(filters)filters.innerHTML=[['','전체',Object.values(data.counts).reduce((a,b)=>a+b,0)],...Object.entries(profileStatuses).map(([k,v])=>[k,v,data.counts[k]||0])].map(([key,label,n])=>`<button type="button" data-profile-status="${key}" aria-pressed="${libraryStatus===key}"><span>${label}</span><small>${n}</small></button>`).join('');
  const groups=Object.keys(profileStatuses).map(status=>{
    const rows=data.items.map((item,index)=>({item,index})).filter(({item})=>item.status===status);
    if(!rows.length)return '';
    return `<section class="profile-list-group"><h3>${profileStatuses[status]}</h3><div class="profile-reading-table"><div class="profile-reading-head"><span>작품</span><span>별점</span><span>완독 / 전체</span><span>형식</span></div>${rows.map(({item,index})=>`${libraryAction(item,index,`class="profile-reading-row" data-profile-tip="${pe(item.name)}" data-profile-tip-cover="${pe(profileCover(item))}" data-profile-tip-detail="${pe(item.author)}"`)}<span class="profile-reading-title"><img src="${pe(profileCover(item))}" alt="" loading="lazy"><span><strong>${pe(item.name)}</strong><small>${pe(item.author)}</small></span></span><span>${item.rating==null?'—':pe(item.rating)+' ★'}</span><span>${item.completed} / ${item.total}</span><span>${pe(item.file_format.toUpperCase())}</span></button>`).join('')}</div></section>`;
  }).join('');
  document.getElementById(libraryViews.reading).innerHTML=groups||'<p class="profile-library-empty">조건에 맞는 작품이 없습니다. 책을 읽거나 즐겨찾기·컬렉션에 저장해 보세요.</p>';
}

function renderLibraryFavorites(data){
  document.getElementById(libraryViews.favorites).innerHTML=data.items.map((item,index)=>`${libraryAction(item,index,`class="profile-favorite-poster" data-profile-tip="${pe(item.name)}" data-profile-tip-detail="${pe([item.release_year,item.file_format.toUpperCase(),item.favorite?'즐겨찾기':'',item.bookmarked?'뷰어 책갈피':'',item.collected?'컬렉션':''].filter(Boolean).join(' · '))}"`)}<img src="${pe(profileCover(item))}" alt="${pe(item.name)}" loading="lazy"><span class="profile-favorite-sources">${item.favorite?'<i class="fa-solid fa-star" aria-label="즐겨찾기"></i>':''}${item.bookmarked?'<i class="fa-solid fa-bookmark" aria-label="뷰어 책갈피"></i>':''}${item.collected?'<i class="fa-solid fa-layer-group" aria-label="컬렉션"></i>':''}</span></button>`).join('')||'<p class="profile-library-empty">아직 저장한 작품이 없습니다. 도서 메뉴의 즐겨찾기·컬렉션이나 뷰어의 책갈피를 추가해 주세요.</p>';
}

function chartBars(title,rows,chronological=false){
  rows=[...(rows||[])];if(chronological)rows.sort((a,b)=>Number(a.name)-Number(b.name));
  const max=Math.max(1,...rows.map(row=>row.count));
  const content=rows.length?`<div class="profile-bar-chart" role="img" aria-label="${pe(title)}: ${pe(rows.map(r=>r.name+' '+r.count+'작품').join(', '))}">${rows.map(row=>`<div class="profile-chart-column" data-profile-tip="${pe(row.name)}" data-profile-tip-detail="${row.count}작품" tabindex="0"><span>${row.count}</span><i style="height:${row.count>0?Math.max(2,row.count/max*120):0}px"></i><small>${pe(profileStatuses[row.name]||row.name)}</small></div>`).join('')}</div>`:'<p class="profile-library-empty">표시할 기록이 없습니다.</p>';
  return `<section class="profile-chart-section"><h3>${pe(title)}</h3><div class="profile-chart-card">${content}</div></section>`;
}

function chartRanks(title,rows=[]){
  statisticsCovers.clear();
  rows=[...rows].sort((a,b)=>(b[profileCategoryMetric]??-1)-(a[profileCategoryMetric]??-1)||b.count-a.count||a.name.localeCompare(b.name));
  const controls=`<div class="profile-chart-switch" aria-label="${pe(title)} 정렬">${[['count','작품 수'],['mean_score','평균 별점'],['volumes','읽은 권수']].map(([key,label])=>`<button type="button" data-profile-category-metric="${key}" aria-pressed="${profileCategoryMetric===key}">${label}</button>`).join('')}</div>`;
  return `<section class="profile-chart-section"><div class="profile-chart-heading"><h3>${pe(title)}</h3>${controls}</div><div class="profile-category-grid">${rows.map((row,index)=>`<article class="profile-category-card"><header><h4>${pe(row.name)}</h4><span class="profile-category-rank">${index+1}</span></header><dl>${[['작품 수',row.count],['평균 별점',row.mean_score==null?'—':row.mean_score+' ★'],['읽은 권수',row.volumes??0]].map(([label,value])=>`<div><dd>${pe(value)}</dd><dt>${label}</dt></div>`).join('')}</dl><div class="profile-category-covers">${(row.covers||[]).map((item,i)=>{const key=`${index}:${i}`;statisticsCovers.set(key,item);return `<button type="button" data-profile-stat-cover="${key}" data-profile-tip="${pe(item.name)}" data-profile-tip-detail="${pe([item.release_year,item.file_format?.toUpperCase()].filter(Boolean).join(' · '))}" aria-label="${pe(item.name)} 상세 보기"><img loading="lazy" src="${pe(profileCover(item))}" alt=""></button>`;}).join('')}</div></article>`).join('')||'<p class="profile-library-empty">표시할 기록이 없습니다.</p>'}</div></section>`;
}

function chartLine(title,rows,unit='작품',controls=''){
  rows=[...(rows||[])].sort((a,b)=>Number(a.name)-Number(b.name));
  if(!rows.length)return `<section class="profile-chart-section"><div class="profile-chart-heading"><h3>${pe(title)}</h3>${controls}</div><div class="profile-chart-card"><p class="profile-library-empty">${unit==='점'?'평가된 작품이 없습니다.':'표시할 기록이 없습니다.'}</p></div></section>`;
  const max=Math.max(1,...rows.map(row=>row.count)),width=Math.max(320,rows.length*44);
  const points=rows.map((row,index)=>({row,x:rows.length===1?width/2:22+index*(width-44)/(rows.length-1),y:128-row.count/max*92}));
  let line=`M ${points[0].x} ${points[0].y}`;
  for(let i=1;i<points.length;i++){const a=points[i-1],b=points[i],mid=(a.x+b.x)/2;line+=` C ${mid} ${a.y} ${mid} ${b.y} ${b.x} ${b.y}`;}
  return `<section class="profile-chart-section"><div class="profile-chart-heading"><h3>${pe(title)}</h3>${controls}</div><div class="profile-chart-card profile-line-scroll"><div class="profile-line-plot" style="min-width:${width}px"><svg viewBox="0 0 ${width} 140" preserveAspectRatio="none" aria-hidden="true"><path d="${line} L ${points.at(-1).x} 140 L ${points[0].x} 140 Z" fill="var(--profile-accent)" opacity=".06"/><path d="${line}" fill="none" stroke="var(--profile-accent)" stroke-width="2.5" vector-effect="non-scaling-stroke"/></svg>${points.map(p=>`<button type="button" class="profile-line-point" data-profile-tip-layout="statistics" style="left:${p.x/width*100}%;top:${p.y}px" data-profile-tip="${pe(p.row.name)}년" data-profile-tip-detail="${pe(p.row.detail||p.row.count+unit)}" aria-label="${pe(p.row.name)}년 ${p.row.count}${pe(unit)}"><span>${p.row.count}</span><i></i></button><small class="profile-line-year" style="left:${p.x/width*100}%">${pe(p.row.name)}</small>`).join('')}</div></div></section>`;
}

function profileYearChart(kind,title,metrics,legacy){
  const selected=profileYearMetric[kind],units={titles:'작품',hours:'시간',mean_score:'점'};
  const controls=`<div class="profile-chart-switch" role="group" aria-label="${pe(title)} 지표">${[['titles','작품 수'],['hours','독서 시간'],['mean_score','평균 별점']].map(([key,label])=>`<button type="button" data-profile-year-chart="${kind}" data-profile-year-metric="${key}" aria-pressed="${selected===key}">${label}</button>`).join('')}</div>`;
  const rows=metrics?metrics.filter(row=>row[selected]!=null).map(row=>({name:row.name,count:row[selected],detail:`작품 수: ${row.titles}\n독서 시간: ${row.hours}시간\n평균 별점: ${row.mean_score==null?'—':row.mean_score+'점'}`})):selected==='titles'?legacy:[];
  return chartLine(title,rows,units[selected],controls);
}

function selectProfileStatistic(){
  document.querySelectorAll('[data-profile-stat]').forEach(el=>{
    const active=el.dataset.profileStat===statisticsSection;
    el.classList.toggle('active',active);el.setAttribute('aria-pressed',String(active));
    if(active)el.setAttribute('aria-current','page');else el.removeAttribute('aria-current');
  });
}

function chartDonut(title,rows){
  const total=rows.reduce((sum,row)=>sum+row.count,0),colors=['var(--profile-accent)','#3d526d','#ef6262','#f4b34d','#9d7de5','#4eab91'];
  let angle=-Math.PI/2;
  const tip=row=>`data-profile-tip-layout="statistics" data-profile-tip="${pe(title)}: ${pe(profileStatuses[row.name]||row.name)}" data-profile-tip-detail="${pe(`작품 수: ${row.count}\n독서 시간: ${row.hours??0}시간\n평균 별점: ${row.mean_score==null?'—':row.mean_score+'점'}`)}"`;
  const segments=rows.map((row,i)=>{const start=angle;angle+=row.count/total*Math.PI*2;const point=a=>`${50+48*Math.cos(a)} ${50+48*Math.sin(a)}`;return row.count===total?`<circle cx="50" cy="50" r="48" fill="${colors[i%colors.length]}" tabindex="0" ${tip(row)}/>`:`<path d="M 50 50 L ${point(start)} A 48 48 0 ${row.count/total>.5?1:0} 1 ${point(angle)} Z" fill="${colors[i%colors.length]}" tabindex="0" ${tip(row)}/>`;});
  return `<section class="profile-chart-section profile-distribution-section"><div class="profile-chart-card"><h3>${pe(title)}</h3><div class="profile-donut-card">${total?`<svg class="profile-pie-chart" viewBox="0 0 100 100" role="group" aria-label="${pe(title)}">${segments.join('')}</svg><div class="profile-donut-legend">${rows.map((row,i)=>`<div style="--chart-series-color:${colors[i%colors.length]}"><span>${pe(profileStatuses[row.name]||row.name)}</span><strong>${Math.round(row.count/total*100)}%</strong></div>`).join('')}</div>`:'<p class="profile-library-empty">표시할 기록이 없습니다.</p>'}</div></div></section>`;
}

function renderLibraryStatistics(data){
  window.dispatchEvent(new Event('bookoasis:profile-rendering'));
  const c=data.charts;
  const readingSeconds=Number(c.duration_seconds||0);
  const readingTime=readingSeconds>=3600?`${Math.round(readingSeconds/360)/10}시간`:`${Math.round(readingSeconds/60)}분`;
  selectProfileStatistic();
  const titles={genres:'장르',tags:'태그',staff:'작가',publishers:'출판사'};
  document.getElementById(libraryViews.statistics).innerHTML=statisticsSection!=='overview'?chartRanks(titles[statisticsSection],c.breakdowns?.[statisticsSection]||c[statisticsSection]):`
    <div class="profile-chart-metrics">${[['fa-book-open','읽은 작품',c.read],['fa-bookmark','읽기 시작한 권',c.volumes],['fa-clock','독서 시간',readingTime],['fa-file-lines','읽은 페이지',Number(c.pages_read||0).toLocaleString('ko-KR')],['fa-star','평균 별점',c.average_rating??'—'],['fa-divide','표준편차',c.rating_deviation??'—']].map(([icon,label,value])=>`<article><i class="fa-solid ${icon}" aria-hidden="true"></i><div><strong>${pe(value)}</strong><span>${label}</span></div></article>`).join('')}</div>
    <p class="profile-chart-basis">전체 기간 · 시간은 실제 저장된 독서 로그 기준 · 미평가 작품은 평균에서 제외됩니다. 독서 연도는 여러 해에 걸친 기록을 각각 반영합니다.</p>
    ${data.rating_error?'<p role="status">플러그인 별점을 불러오지 못했습니다. 다른 통계는 정상 표시됩니다.</p>':''}
    ${chartBars('별점 분포',c.scores,true)}${chartBars('시리즈 권수 분포',c.volume_counts)}
    <div class="profile-chart-distributions">${chartDonut('파일 형식',c.formats)}${chartDonut('독서 상태',c.statuses)}</div>
    ${profileYearChart('release','출간 연도',c.release_year_metrics,c.release_years)}${profileYearChart('reading','독서 연도',c.reading_year_metrics,c.read_years)}`;
}

export async function showProfileLibraryTab(tab,force=false,background=false){
  if(!background)currentLibraryTab=tab;
  if(tab==='overview'){showProfileLibraryTab('statistics',false,true);return;}
  if(!libraryViews[tab])return;
  if(!force&&libraryResults.has(tab))return;
  libraryRequests.get(tab)?.abort();
  const controller=new AbortController(),generation=libraryGeneration;
  libraryRequests.set(tab,controller);
  const target=document.getElementById(libraryViews[tab]);if(!target)return;
  if(!libraryResults.has(tab))target.innerHTML='<p class="profile-library-empty" role="status">불러오는 중…</p>';
  const params=new URLSearchParams({mode:tab,page:libraryPages[tab]||1});
  if(tab==='reading'){params.set('status',libraryStatus);params.set('q',libraryQuery);params.set('sort',librarySort);for(const [key,value]of Object.entries(libraryFilters))if(value)params.set(key,value);}
  try{
    const response=await fetch('/api/account/profile/library?'+params,{cache:'no-store',signal:controller.signal});
    if(!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('목록을 불러오지 못했습니다.');
    const data=await response.json();
    if(!data.success||!(tab==='statistics'?data.charts:Array.isArray(data.items)))throw Error(data.error||'목록 응답이 올바르지 않습니다.');
    if(generation!==libraryGeneration||controller.signal.aborted)return;
    libraryResults.set(tab,data);
    if(tab==='statistics')window.dispatchEvent(new CustomEvent('bookoasis:profile-charts-loaded',{detail:data.charts}));
    // Render with the originating tab, even if another tab became active meanwhile.
    const activeTab=currentLibraryTab;currentLibraryTab=tab;
    try{({reading:renderReadingLibrary,favorites:renderLibraryFavorites,statistics:renderLibraryStatistics})[tab](data);libraryPagination(tab,data);}
    finally{currentLibraryTab=activeTab;}
  }catch(error){
    if(error.name==='AbortError'||generation!==libraryGeneration)return;
    // Keep a previously usable page rather than replacing it with a blank panel.
    const message=document.createElement('p');message.className='profile-library-error';message.setAttribute('role','alert');message.textContent=error.message+' ';
    const retry=document.createElement('button');retry.type='button';retry.dataset.profileRetry=tab;retry.textContent='다시 시도';message.append(retry);
    target.querySelector('.profile-library-error')?.remove();
    if(!libraryResults.has(tab))target.replaceChildren(message);else target.prepend(message);
  }finally{if(libraryRequests.get(tab)===controller)libraryRequests.delete(tab);}
}

export function initProfileLibrary(){
  if(libraryInitialized)return;libraryInitialized=true;
  selectProfileStatistic();
  document.addEventListener('click',async event=>{
    const cover=event.target.closest('[data-profile-stat-cover]');
    if(cover){const item=statisticsCovers.get(cover.dataset.profileStatCover);if(item){if(item.db_type!==state.currentLibraryType)await window.switchLibraryType(item.db_type,{skipRefresh:true});window.openBookDetail(event,item.series_name,item.library_id,item.id,item.name);}return;}
    const categoryMetric=event.target.closest('[data-profile-category-metric]');
    if(categoryMetric){profileCategoryMetric=categoryMetric.dataset.profileCategoryMetric;const data=libraryResults.get('statistics');if(data)renderLibraryStatistics(data);document.querySelector(`[data-profile-category-metric="${profileCategoryMetric}"]`)?.focus({preventScroll:true});return;}
    const row=event.target.closest('[data-profile-library-item]');
    if(row){
      const item=libraryResults.get(row.dataset.profileLibraryMode)?.items[Number(row.dataset.profileLibraryItem)];if(!item)return;
      try{if(item.db_type!==state.currentLibraryType)await window.switchLibraryType(item.db_type,{skipRefresh:true});
        window.openBookDetail(event,item.series_name,item.library_id,item.id,item.name);
      }catch(error){console.error('[ProfileLibrary] 상세 이동 실패',error);}return;
    }
    const status=event.target.closest('[data-profile-status]');
    if(status){libraryStatus=status.dataset.profileStatus;libraryPages.reading=1;showProfileLibraryTab('reading',true);return;}
    const pager=event.target.closest('[data-profile-page]');
    if(pager){libraryPages[pager.dataset.profilePage]=Number(pager.dataset.page);showProfileLibraryTab(pager.dataset.profilePage,true);return;}
    const retry=event.target.closest('[data-profile-retry]');if(retry){showProfileLibraryTab(retry.dataset.profileRetry,true);return;}
    const metric=event.target.closest('[data-profile-year-metric]');if(metric){
      profileYearMetric[metric.dataset.profileYearChart]=metric.dataset.profileYearMetric;
      const data=libraryResults.get('statistics');if(data){renderLibraryStatistics(data);document.querySelector(`[data-profile-year-chart="${metric.dataset.profileYearChart}"][data-profile-year-metric="${metric.dataset.profileYearMetric}"]`)?.focus({preventScroll:true});}return;
    }
    const stat=event.target.closest('[data-profile-stat]');if(stat){statisticsSection=stat.dataset.profileStat;selectProfileStatistic();const data=libraryResults.get('statistics');if(data)renderLibraryStatistics(data);}
  });
  document.getElementById('profile-list-search')?.addEventListener('input',event=>{
    libraryQuery=event.target.value.trim();clearTimeout(librarySearchTimer);
    librarySearchTimer=setTimeout(()=>{libraryPages.reading=1;showProfileLibraryTab('reading',true);},250);
  });
  document.getElementById('profile-list-sort')?.addEventListener('change',event=>{librarySort=event.target.value;libraryPages.reading=1;showProfileLibraryTab('reading',true);});
  document.querySelectorAll('[data-profile-list-filter]').forEach(select=>select.addEventListener('change',()=>{libraryFilters[select.dataset.profileListFilter]=select.value;libraryPages.reading=1;showProfileLibraryTab('reading',true);}));
}
