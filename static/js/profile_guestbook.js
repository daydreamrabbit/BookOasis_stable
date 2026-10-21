// Public member identity and guestbooks are isolated from the private profile renderer.
import {renderProfileBio} from './profile_bio.js';
let communityInitialized=false,communitySettings=null,communitySettingsToken=0,communitySettingsSaving=false,communityRenderAvatar=null;
let communityGeneration=0,communityController=null,communityOwner=0,communityPage=1,communityQuery='',communitySearchTimer;
const communityDrafts=new Map(),communityPosting=new Set();
const ce=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const communityBase='/api/account/community';
const communityDialog=()=>document.getElementById('profile-community-dialog');
const communityBody=()=>document.getElementById('profile-community-body');

async function communityJSON(response){
  if(!response.headers.get('content-type')?.includes('application/json'))throw Error('서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  const data=await response.json();if(!response.ok||!data.success)throw Error(data.error||'프로필을 불러오지 못했습니다.');return data;
}

function communityStatus(text){const node=document.getElementById('profile-community-status');if(node)node.textContent=text;}
function communityStart(owner){
  communityOwner=owner;communityPage=1;communityGeneration++;communityController?.abort();communityController=new AbortController();
  clearTimeout(communitySearchTimer);
  document.querySelector('[data-community-back]').hidden=!owner;
  document.getElementById('profile-community-title').textContent=owner?'프로필 · 방명록':'회원 프로필';
  communityBody().innerHTML='<p class="profile-library-empty" role="status">불러오는 중…</p>';
  if(!communityDialog().open)communityDialog().showModal();
  return {generation:communityGeneration,signal:communityController.signal};
}

export async function loadProfileCommunitySettings(){
  const token=++communitySettingsToken;
  try{
    const data=await communityJSON(await fetch(communityBase+'/settings',{cache:'no-store'}));
    if(token!==communitySettingsToken||communitySettingsSaving)return;
    if(!Number.isInteger(data.user_id)||typeof data.enabled!=='boolean')throw Error('공개 설정 응답이 올바르지 않습니다.');
    communitySettings=data;document.getElementById('profile-community-enabled').checked=data.enabled;
    document.querySelectorAll('#profile-community-enabled,[data-community-members],[data-community-own]').forEach(el=>el.disabled=false);
    document.querySelector('[data-community-retry]').hidden=true;communityStatus('');
  }catch(error){if(token===communitySettingsToken){communityStatus(error.message);document.querySelector('[data-community-retry]').hidden=false;}}
}

function communityError(error,generation){
  if(error.name==='AbortError'||generation!==communityGeneration||!communityDialog().open)return;
  communityBody().innerHTML=`<p role="alert" class="profile-library-empty">${ce(error.message)}</p><button type="button" data-community-load-retry>다시 시도</button>`;
}

function communityPager(data,kind){
  const last=Math.max(1,Math.ceil(data.total/data.page_size));
  return last>1?`<div class="profile-pagination"><button type="button" data-community-page="${kind}" data-page="${data.page-1}" ${data.page===1?'disabled':''}>이전</button><span>${data.page} / ${last}</span><button type="button" data-community-page="${kind}" data-page="${data.page+1}" ${data.page>=last?'disabled':''}>다음</button></div>`:'';
}

async function communityMembers(page=1,searchOnly=false){
  let context;
  if(searchOnly){communityController?.abort();communityController=new AbortController();context={generation:++communityGeneration,signal:communityController.signal};}
  else{
    context=communityStart(0);
    communityBody().innerHTML=`<label class="community-member-search">회원 검색<input type="search" data-community-search maxlength="80" value="${ce(communityQuery)}" placeholder="표시 이름으로 검색"></label><p class="community-privacy-note">공개를 허용한 회원만 표시됩니다.</p><div id="community-member-results" aria-live="polite"></div>`;
  }
  try{
    const params=new URLSearchParams({q:communityQuery,page});
    const data=await communityJSON(await fetch(communityBase+'/members?'+params,{cache:'no-store',signal:context.signal}));
    if(context.generation!==communityGeneration)return;
    if(!Array.isArray(data.items)||!Number.isFinite(data.total)||!data.page_size)throw Error('회원 목록 응답이 올바르지 않습니다.');
    document.getElementById('community-member-results').innerHTML=`<div class="community-member-grid">${data.items.map(item=>`<button type="button" data-community-visit="${ce(item.id)}"><i class="fa-solid fa-user" aria-hidden="true"></i><strong>${ce(item.display_name)}</strong><span>프로필 · 방명록 <i class="fa-solid fa-angle-right" aria-hidden="true"></i></span></button>`).join('')||'<p class="profile-library-empty">공개된 회원 프로필이 없습니다.</p>'}</div>${communityPager(data,'members')}`;
  }catch(error){communityError(error,context.generation);}
}

function renderCommunityProfile(profile,data){
  const draft=communityDrafts.get(profile.id)||{body:'',id:null};communityDrafts.set(profile.id,draft);
  const appearance=profile.appearance||{};
  communityBody().innerHTML=`<section class="community-public-hero"><div class="community-public-identity"><span class="community-public-avatar">${profile.avatar_url?`<img src="${ce(profile.avatar_url)}" alt="">`:'<i class="fa-solid fa-user" aria-hidden="true"></i>'}</span><h2>${ce(profile.display_name)}</h2></div></section><p class="community-public-bio">${ce(appearance.bio||'아직 소개가 없습니다.')}</p>
    <section class="community-guestbook"><h3>방명록</h3><p class="community-privacy-note">로그인한 회원에게 공개되는 글입니다. 작성자와 프로필 주인이 삭제할 수 있습니다.</p>
    <form data-community-form class="${draft.body?'has-draft':''}"><label for="community-guestbook-input">메시지 남기기</label><textarea id="community-guestbook-input" maxlength="2000" rows="1" required ${data.can_post?'':'disabled'} placeholder="${data.can_post?'메시지를 남겨 보세요…':'프로필 공개 설정을 켜면 방명록을 이용할 수 있습니다.'}">${ce(draft.body)}</textarea><button type="submit" ${!data.can_post||communityPosting.has(profile.id)?'disabled':''}>남기기</button></form><p class="community-post-status" role="status"></p>
    <div class="community-guestbook-entries">${data.items.map(item=>{
      const parsed=new Date(item.created_at),date=Number.isNaN(parsed.getTime())?'':new Intl.DateTimeFormat('ko-KR',{dateStyle:'medium',timeStyle:'short'}).format(parsed);
      return `<article class="profile-message-card"><header><strong>${ce(item.author_name)}</strong><time datetime="${ce(item.created_at)}">${ce(date)}</time>${item.can_delete?`<button type="button" data-community-delete="${ce(item.id)}" aria-label="방명록 글 삭제"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button>`:''}</header><p>${ce(item.body)}</p></article>`;
    }).join('')||'<p class="profile-library-empty">아직 방명록 글이 없습니다.</p>'}</div>${communityPager(data,'entries')}</section>`;
  renderProfileBio(communityBody().querySelector('.community-public-bio'),appearance.bio,'아직 소개가 없습니다.');
  const hero=communityBody().querySelector('.community-public-hero');
  if(communityRenderAvatar)communityRenderAvatar(communityBody().querySelector('.community-public-avatar'),profile.avatar,profile.avatar_url);
  if(appearance.banner_url){
    try{const url=new URL(appearance.banner_url,location.origin);if((url.protocol==='https:'||url.origin===location.origin)&&!url.username&&!url.password)hero.style.backgroundImage=`linear-gradient(180deg,#0002,#0b1324b8),url(${JSON.stringify(url.href)})`;}catch{}
  }
}

async function communityVisit(owner,page=1){
  if(!Number.isInteger(owner)||owner<1)return;
  const context=communityStart(owner);
  try{
    const [publicData,entries]=await Promise.all([
      fetch(`${communityBase}/profiles/${owner}`,{cache:'no-store',signal:context.signal}).then(communityJSON),
      fetch(`${communityBase}/profiles/${owner}/guestbook?page=${page}`,{cache:'no-store',signal:context.signal}).then(communityJSON),
    ]);
    if(context.generation!==communityGeneration)return;
    if(publicData.profile?.id!==owner||!Array.isArray(entries.items)||!Number.isFinite(entries.total)||!entries.page_size)throw Error('프로필 응답이 올바르지 않습니다.');
    if(page>1&&!entries.items.length&&entries.total>0){await communityVisit(owner,Math.ceil(entries.total/entries.page_size));return;}
    communityPage=page;renderCommunityProfile(publicData.profile,entries);
  }catch(error){communityError(error,context.generation);}
}

function communityClose(){
  communityGeneration++;communityController?.abort();clearTimeout(communitySearchTimer);
  if(communityDialog()?.open)communityDialog().close();
}

export function initProfileCommunity(renderAvatar=null){
  if(typeof renderAvatar==='function')communityRenderAvatar=renderAvatar;
  if(communityInitialized)return;communityInitialized=true;
  const dialog=communityDialog();if(!dialog)return;
  dialog.addEventListener('close',()=>{communityGeneration++;communityController?.abort();clearTimeout(communitySearchTimer);});
  window.addEventListener('bookoasis:view-changing',communityClose);
  document.getElementById('profile-community-enabled')?.addEventListener('change',async event=>{
    if(communitySettingsSaving||!communitySettings)return;
    const enabled=event.target.checked;communitySettingsSaving=true;communitySettingsToken++;event.target.disabled=true;
    try{
      const data=await communityJSON(await fetch(communityBase+'/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})}));
      if(data.enabled!==enabled||data.user_id!==communitySettings.user_id)throw Error('공개 설정 저장 결과를 확인하지 못했습니다.');
      communitySettings=data;communityStatus(enabled?'프로필과 방명록을 회원에게 공개했습니다.':'프로필과 방명록을 비공개로 변경했습니다.');
    }catch(error){event.target.checked=communitySettings.enabled;communityStatus(error.message);}
    finally{communitySettingsSaving=false;event.target.disabled=false;}
  });
  document.addEventListener('click',async event=>{
    if(event.target.closest('[data-community-close]')){communityClose();return;}
    if(event.target.closest('[data-community-retry]')){loadProfileCommunitySettings();return;}
    if(event.target.closest('[data-community-members],[data-community-back]')){communityMembers();return;}
    if(event.target.closest('[data-community-own]')){if(communitySettings)communityVisit(communitySettings.user_id);return;}
    const visit=event.target.closest('[data-community-visit]');if(visit){communityVisit(Number(visit.dataset.communityVisit));return;}
    const retry=event.target.closest('[data-community-load-retry]');if(retry){communityOwner?communityVisit(communityOwner):communityMembers();return;}
    const pager=event.target.closest('[data-community-page]');if(pager){pager.dataset.communityPage==='members'?communityMembers(Number(pager.dataset.page),true):communityVisit(communityOwner,Number(pager.dataset.page));return;}
    const remove=event.target.closest('[data-community-delete]');if(!remove||remove.disabled)return;
    if(!confirm('이 방명록 글을 삭제할까요?'))return;
    const owner=communityOwner,generation=communityGeneration;remove.disabled=true;
    try{
      await communityJSON(await fetch(`${communityBase}/profiles/${owner}/guestbook/${encodeURIComponent(remove.dataset.communityDelete)}`,{method:'DELETE'}));
      if(generation===communityGeneration)communityVisit(owner,communityPage);
    }catch(error){if(generation===communityGeneration){dialog.querySelector('.community-post-status').textContent=error.message;remove.disabled=false;}}
  });
  dialog.addEventListener('input',event=>{
    if(event.target.matches('[data-community-search]')){communityQuery=event.target.value.trim();clearTimeout(communitySearchTimer);communitySearchTimer=setTimeout(()=>communityMembers(1,true),250);}
    if(event.target.id==='community-guestbook-input'){communityDrafts.set(communityOwner,{body:event.target.value,id:null});event.target.closest('form').classList.toggle('has-draft',!!event.target.value);}
  });
  dialog.addEventListener('submit',async event=>{
    if(!event.target.matches('[data-community-form]'))return;event.preventDefault();
    const owner=communityOwner,generation=communityGeneration,input=event.target.querySelector('textarea'),body=input.value.trim();
    if(!body||body.length>2000||communityPosting.has(owner))return;
    const draft=communityDrafts.get(owner)||{body:input.value,id:null};
    draft.id??=Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');communityDrafts.set(owner,draft);
    communityPosting.add(owner);const button=event.target.querySelector('[type=submit]');button.disabled=true;
    try{
      const data=await communityJSON(await fetch(`${communityBase}/profiles/${owner}/guestbook`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:draft.id,body})}));
      if(data.item?.id!==draft.id)throw Error('게시 결과를 확인하지 못했습니다. 다시 시도해 주세요.');
      if(communityDrafts.get(owner)?.body.trim()===body)communityDrafts.delete(owner);
      if(generation===communityGeneration)await communityVisit(owner);
    }catch(error){if(generation===communityGeneration)dialog.querySelector('.community-post-status').textContent=error.message;}
    finally{communityPosting.delete(owner);if(generation===communityGeneration)button.disabled=false;else if(communityOwner===owner){const current=dialog.querySelector('[data-community-form] [type=submit]');if(current&& !dialog.querySelector('textarea')?.disabled)current.disabled=false;}}
  });
}
