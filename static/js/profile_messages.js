let messagesInitialized=false,messageGeneration=0,messageRequest=null,messagePage=1,messageSaving=false,messageRetryId=null,messageStatusVersion=0;
const messageEscape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

async function messageJSON(response){
  if(!response.headers.get('content-type')?.includes('application/json'))throw Error('서버 응답을 확인하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  const data=await response.json();if(!response.ok||!data.success)throw Error(data.error||'메시지 요청에 실패했습니다.');return data;
}

function messageStatus(text,error=false){
  messageStatusVersion++;
  const node=document.getElementById('profile-message-status');if(!node)return;
  node.hidden=!text;node.textContent=text;node.classList.toggle('is-error',error);
}

function renderMessages(data){
  const list=document.getElementById('profile-message-list');if(!list)return;
  const displayName=document.getElementById('profile-display-name')?.textContent||'나';
  list.innerHTML=data.items.map(item=>{
    const parsed=new Date(item.created_at),date=Number.isNaN(parsed.getTime())?'':new Intl.DateTimeFormat('ko-KR',{dateStyle:'medium',timeStyle:'short'}).format(parsed);
    return `<article class="profile-message-card"><header><strong>${messageEscape(displayName)}</strong><time datetime="${messageEscape(item.created_at)}">${messageEscape(date)}</time><button type="button" data-profile-message-delete="${messageEscape(item.id)}" aria-label="메시지 삭제"><i class="fa-solid fa-xmark" aria-hidden="true"></i></button></header><p>${messageEscape(item.body)}</p></article>`;
  }).join('');
  const last=Math.max(1,Math.ceil(data.total/data.page_size));
  document.getElementById('profile-message-pages').innerHTML=last>1?`<button type="button" data-message-page="${data.page-1}" ${data.page===1?'disabled':''}>이전</button><span>${data.page} / ${last}</span><button type="button" data-message-page="${data.page+1}" ${data.page>=last?'disabled':''}>다음</button>`:'';
}

export async function loadProfileMessages(page=1){
  const target=document.getElementById('profile-message-list');if(!target)return;
  const generation=++messageGeneration,statusVersion=messageStatusVersion;messageRequest?.abort();const controller=new AbortController();messageRequest=controller;
  try{
    const data=await messageJSON(await fetch('/api/account/profile/messages?page='+page,{cache:'no-store',signal:controller.signal}));
    if(generation!==messageGeneration)return;
    if(!Array.isArray(data.items)||!Number.isFinite(data.total)||!data.page_size)throw Error('메시지 목록 응답이 올바르지 않습니다.');
    if(page>1&&!data.items.length&&data.total>0){loadProfileMessages(Math.ceil(data.total/data.page_size));return;}
    messagePage=page;renderMessages(data);if(statusVersion===messageStatusVersion)messageStatus('');
  }catch(error){if(error.name!=='AbortError'&&generation===messageGeneration)messageStatus(error.message,true);}
}

export function initProfileMessages(){
  if(messagesInitialized)return;messagesInitialized=true;
  const form=document.getElementById('profile-message-form'),input=document.getElementById('profile-message-input');
  input?.addEventListener('input',()=>{messageRetryId=null;form?.classList.toggle('has-draft',!!input.value);});
  form?.addEventListener('submit',async event=>{
    event.preventDefault();if(messageSaving)return;
    const body=input.value.trim();if(!body||body.length>2000){messageStatus('메시지는 1~2000자로 입력해 주세요.',true);return;}
    messageSaving=true;const button=form.querySelector('[type=submit]');button.disabled=true;
    try{
      messageRetryId??=Array.from(crypto.getRandomValues(new Uint8Array(16)),v=>v.toString(16).padStart(2,'0')).join('');const id=messageRetryId;
      const data=await messageJSON(await fetch('/api/account/profile/messages',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id,body})}));
      if(!data.item||data.item.id!==id)throw Error('게시 결과를 확인하지 못했습니다. 다시 시도해 주세요.');
      if(input.value.trim()===body){input.value='';messageRetryId=null;form.classList.remove('has-draft');}
      await loadProfileMessages(1);
    }catch(error){messageStatus(error.message,true);}
    finally{messageSaving=false;button.disabled=false;}
  });
  document.addEventListener('click',async event=>{
    const page=event.target.closest('[data-message-page]');if(page){loadProfileMessages(Number(page.dataset.messagePage));return;}
    const remove=event.target.closest('[data-profile-message-delete]');if(!remove||remove.disabled)return;
    if(!window.confirm('이 메시지를 삭제할까요?'))return;
    remove.disabled=true;
    try{await messageJSON(await fetch('/api/account/profile/messages/'+encodeURIComponent(remove.dataset.profileMessageDelete),{method:'DELETE'}));await loadProfileMessages(messagePage);}
    catch(error){messageStatus(error.message,true);remove.disabled=false;}
  });
}
