import {state} from './state.js';
import {fetchUserSettings, invalidateUserSettingsCache} from './api.js';

export const welcomeDefaults = Object.freeze({
  eyebrow:'MY READING SPACE', title:'책이 있는 곳에\n언제나, 좋은 하루가.',
  subtitle:'BookOasis와 함께하는 나만의 독서 공간',
  images:['/static/images/home-reading-desk-v1.webp'],
  goal_minutes:60,quote:'조금씩이라도 계속 읽는 것이 중요합니다.'
});

export function normalizeWelcomeConfig(raw={}) {
  if(!raw || typeof raw!=='object' || Array.isArray(raw)) throw new Error('올바른 배너 설정이 아닙니다.');
  const config={};
  for(const [name,max] of [['eyebrow',80],['title',200],['subtitle',200]]){
    const value=raw[name] ?? welcomeDefaults[name];
    if(typeof value!=='string' || value.length>max) throw new Error(`문구 길이를 확인해 주세요. (최대 ${max}자)`);
    config[name]=value.trim();
  }
  const images=raw.images ?? welcomeDefaults.images;
  if(!Array.isArray(images) || images.length>6) throw new Error('배경 이미지는 최대 6개입니다.');
  config.images=[...new Set(images.map(image=>{
    if(typeof image!=='string' || image.length>480 || /[\\\s]/.test(image)) throw new Error('이미지 주소를 확인해 주세요. 공백은 %20으로 입력하세요.');
    const path=image.startsWith('/') && !image.startsWith('//');
    const url=new URL(image,'https://bookoasis.invalid');
    if((!path && !image.startsWith('https://')) || url.username || url.password) throw new Error('https:// 또는 /로 시작하는 이미지 주소만 사용할 수 있습니다.');
    return image;
  }))];
  if(!config.images.length) config.images=[...welcomeDefaults.images];
  config.goal_minutes=raw.goal_minutes??60;
  config.quote=raw.quote??welcomeDefaults.quote;
  if(!Number.isInteger(config.goal_minutes)||config.goal_minutes<1||config.goal_minutes>1440)throw new Error('독서 목표는 1~1440분으로 입력해 주세요.');
  if(typeof config.quote!=='string'||config.quote.length>160)throw new Error('독서 문구는 160자 이하로 입력해 주세요.');
  return config;
}

async function jsonResponse(response){
  if(!response.ok || !response.headers.get('content-type')?.includes('application/json')) throw new Error('서버 응답을 확인할 수 없습니다. 잠시 후 다시 시도하세요.');
  const result=await response.json();
  if(!result?.success) throw new Error(result?.error || '저장하지 못했습니다.');
  return result;
}

export function initWelcomeBanner(){
  const banner=document.querySelector('.home-welcome');
  if(!banner || banner.dataset.bound) return;
  banner.dataset.bound='true';
  const dialog=document.querySelector('.home-welcome-editor');
  const form=document.getElementById('home-welcome-editor-form');
  const error=document.getElementById('home-welcome-editor-error');
  let config=normalizeWelcomeConfig(),slide=0,loaded=false,saving=false,gesture=null,todayRequest=null,todaySeconds=0;
  function renderGoal(){
    document.getElementById('home-today-goal').textContent=String(config.goal_minutes);
    document.getElementById('home-today-quote').textContent=`“${config.quote}”`;
    const minutes=Math.floor(todaySeconds/60),ratio=Math.min(1,todaySeconds/(config.goal_minutes*60)),ring=banner.querySelector('.home-today-ring');
    ring.setAttribute('aria-valuemax',String(config.goal_minutes));ring.setAttribute('aria-valuenow',String(Math.min(config.goal_minutes,minutes)));
    ring.setAttribute('aria-valuetext',`${minutes}분 / ${config.goal_minutes}분`);
    const circle=document.getElementById('home-today-ring-progress');
    circle.style.strokeDasharray=String(2*Math.PI*44);circle.style.strokeDashoffset=String(2*Math.PI*44*(1-ratio));
  }
  function render(){
    document.getElementById('home-welcome-eyebrow').textContent=config.eyebrow;
    document.getElementById('home-welcome-title').textContent=config.title;
    document.getElementById('home-welcome-subtitle').textContent=config.subtitle;
    const background=banner.querySelector('.home-welcome-background');
    background.style.backgroundImage=`url(${JSON.stringify(config.images[slide])})`;
    const navigation=banner.querySelector('.home-welcome-navigation');
    navigation.hidden=config.images.length<2;
    const dots=banner.querySelector('.home-welcome-dots');
    dots.replaceChildren(...config.images.map((_,index)=>{
      const button=document.createElement('button');button.type='button';
      button.dataset.welcomeSlide=String(index);button.setAttribute('aria-label',`배경 ${index+1}`);
      button.setAttribute('aria-current',String(index===slide));return button;
    }));
    renderGoal();
  }
  function move(delta){slide=(slide+delta+config.images.length)%config.images.length;render();}
  function fill(value){for(const name of ['eyebrow','title','subtitle','goal_minutes','quote'])form.elements[name].value=value[name];form.elements.images.value=value.images.join('\n');}
  async function loadConfig(){
    try{
      const data=await fetchUserSettings();
      if(!data?.success) throw new Error(data?.error || '설정을 불러오지 못했습니다.');
      if(data.settings?.HOME_WELCOME_CONFIG) config=normalizeWelcomeConfig(JSON.parse(data.settings.HOME_WELCOME_CONFIG));
      render();loaded=true;
    }catch(e){console.warn('[Welcome] 설정 로드 실패:',e.message);}
  }
  async function loadToday(){
    todayRequest?.abort();
    const controller=new AbortController();todayRequest=controller;
    const minutes=document.getElementById('home-today-minutes');
    const summary=document.getElementById('home-today-summary');
    minutes.textContent='—';summary.textContent='독서 기록을 불러오는 중…';
    todaySeconds=0;renderGoal();
    try{
      const data=await jsonResponse(await fetch(`/api/dashboard/today?library_type=${encodeURIComponent(state.currentLibraryType||'general')}`,{signal:controller.signal}));
      if(todayRequest!==controller) return;
      todaySeconds=Math.max(0,Number(data.today.duration_seconds)||0);renderGoal();
      minutes.textContent=String(Math.floor(todaySeconds/60));
      summary.textContent=`${Number(data.today.books)||0}권 · ${Number(data.today.pages)||0}페이지`;
      minutes.parentElement.title='서버에 저장된 독서 기록 기준';
    }catch(e){if(e.name!=='AbortError' && todayRequest===controller) summary.textContent='독서 기록을 불러오지 못했습니다.';}
  }
  let ready=null;
  function ensureConfig(){
    if(!ready) ready=loadConfig().finally(()=>{if(!loaded) ready=null;});
    return ready;
  }
  render();
  window.addEventListener('bookoasis:view-changing',event=>{
    if(event.detail?.viewName==='dashboard'){ensureConfig();loadToday();}
    else {todayRequest?.abort();todayRequest=null;}
  });
  document.addEventListener('click',async event=>{
    const button=event.target.closest?.('[data-welcome-action], [data-welcome-slide]');
    if(!button) return;
    if(button.dataset.welcomeSlide!==undefined){slide=Number(button.dataset.welcomeSlide);render();return;}
    const action=button.dataset.welcomeAction;
    if(action==='next') move(1);
    if(action==='previous') move(-1);
    if(action==='edit'){
      await ensureConfig();
      if(!loaded){error.textContent='설정을 불러오지 못했습니다. 새로고침 후 다시 시도하세요.';fill(config);dialog.showModal();return;}
      fill(config);error.textContent='';dialog.showModal();
    }
    if(action==='cancel' && !saving) dialog.close();
    if(action==='reset' && !saving) fill(welcomeDefaults);
  });
  form.addEventListener('submit',async event=>{
    event.preventDefault();if(saving) return;
    if(!loaded){error.textContent='설정 조회에 실패하여 저장할 수 없습니다. 새로고침해 주세요.';return;}
    try{
      const raw=Object.fromEntries(['eyebrow','title','subtitle','images','quote'].map(name=>[name,name==='images'?form.elements[name].value.split('\n').map(v=>v.trim()).filter(Boolean):form.elements[name].value]));
      raw.goal_minutes=Number(form.elements.goal_minutes.value);
      const next=normalizeWelcomeConfig(raw);
      const value=JSON.stringify(next);
      if(value.length>4096) throw new Error('이미지 주소와 문구를 합쳐 4096자 이하로 입력해 주세요.');
      saving=true;form.querySelector('[type="submit"]').disabled=true;error.textContent='';
      const body=new FormData();body.append('key','HOME_WELCOME_CONFIG');body.append('value',value);
      await jsonResponse(await fetch('/api/media/settings/user',{method:'POST',body}));
      invalidateUserSettingsCache();
      config=next;slide=0;render();dialog.close();
    }catch(e){error.textContent=e.message;}
    finally{saving=false;form.querySelector('[type="submit"]').disabled=false;}
  });
  dialog.addEventListener('cancel',event=>{if(saving) event.preventDefault();});
  banner.addEventListener('keydown',event=>{
    if(event.target!==banner || !['ArrowLeft','ArrowRight'].includes(event.key)) return;
    event.preventDefault();move(event.key==='ArrowRight'?1:-1);
  });
  banner.addEventListener('pointerdown',event=>{
    if(event.button!==0 || event.target.closest('button') || config.images.length<2) return;
    gesture={id:event.pointerId,x:event.clientX,y:event.clientY};banner.setPointerCapture(event.pointerId);
  });
  banner.addEventListener('pointerup',event=>{
    if(!gesture || gesture.id!==event.pointerId) return;
    const {x,y}=gesture;gesture=null;
    if(banner.hasPointerCapture(event.pointerId)) banner.releasePointerCapture(event.pointerId);
    const dx=event.clientX-x,dy=event.clientY-y;
    if(Math.abs(dx)>40 && Math.abs(dx)>Math.abs(dy)*1.3) move(dx<0?1:-1);
  });
  banner.addEventListener('pointercancel',()=>gesture=null);
  banner.addEventListener('lostpointercapture',()=>gesture=null);
}

if(typeof document!=='undefined'){
  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',initWelcomeBanner,{once:true});
  else initWelcomeBanner();
}
