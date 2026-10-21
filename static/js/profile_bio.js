// Support AniList image notation and standard Markdown images; never execute HTML.
const bioImageURL=/^\/api\/account\/profile\/bio-images\/\d+\/[a-f0-9]{64}$/;
let bioEditorInitialized=false,bioEditorGeneration=0;
const bioUploads=new Set();
const bioRichPrefix='<!--bookoasis-bio-rich-->';
const bioRichTags=new Set(['B','STRONG','I','EM','U','S','STRIKE','H2','A','BR','P','DIV','SPAN','CENTER','BLOCKQUOTE','PRE','CODE','OL','UL','LI']);
const bioImageLoaders=new WeakMap();

function createBioImage(url,alt,width=null){
  const img=document.createElement('img');
  // Do not set src while constructing detached fragments: it starts a request immediately.
  img.dataset.bioSrc=url;img.alt=alt||'소개 이미지';img.loading='lazy';img.decoding='async';img.referrerPolicy='no-referrer';
  if(width!==null){img.style.width=width+'%';img.dataset.bioImageWidth=String(width);if(width<=25)img.className='profile-bio-badge-image';}
  return img;
}

function stopBioImages(target){
  const loader=bioImageLoaders.get(target);if(!loader)return;
  loader.observer?.disconnect();loader.stopped=true;loader.queue.clear();bioImageLoaders.delete(target);
}

function loadBioImages(target){
  if(!target?.isConnected)return;
  let loader=bioImageLoaders.get(target);
  if(!loader){
    loader={queue:new Set(),observed:new WeakSet(),active:0,stopped:false,observer:null};
    const pump=()=>{
      if(loader.stopped)return;
      for(const img of loader.queue){
        if(loader.active>=4)break;loader.queue.delete(img);
        if(!target.contains(img)||img.hasAttribute('src'))continue;
        loader.active++;
        const done=()=>{img.removeEventListener('load',done);img.removeEventListener('error',done);img.dataset.bioLoaded=img.naturalWidth>0?'true':'error';loader.active--;pump();};
        img.addEventListener('load',done);img.addEventListener('error',done);img.src=img.dataset.bioSrc;
      }
    };
    if(typeof IntersectionObserver!=='undefined'){
      const bounded=['auto','scroll'].includes(getComputedStyle(target).overflowY);
      loader.observer=new IntersectionObserver(entries=>{
        for(const entry of entries){if(entry.isIntersecting)loader.queue.add(entry.target);else loader.queue.delete(entry.target);}pump();
      },{root:bounded?target:null,rootMargin:'160px 0px'});
    }
    loader.pump=pump;bioImageLoaders.set(target,loader);
  }
  for(const img of target.querySelectorAll('img[data-bio-src]:not([src])')){
    if(loader.observed.has(img))continue;loader.observed.add(img);
    if(loader.observer)loader.observer.observe(img);else loader.queue.add(img);
  }
  loader.pump();
}

// Only our explicit rich-document marker enables formatting. Legacy HTML stays literal.
function safeBioRich(source){
  const template=document.createElement('template');template.innerHTML=source;
  const clean=node=>{
    if(node.nodeType===Node.TEXT_NODE){const part=document.createElement('span');renderProfileBio(part,node.data);return Array.from(part.childNodes);}
    if(node.nodeType!==Node.ELEMENT_NODE)return [];
    if(node.tagName==='IMG'){
      const url=safeBioImageURL(node.getAttribute('src')||'');if(!url)return [];
      const width=parseFloat(node.style.width);return [createBioImage(url,node.getAttribute('alt'),node.style.width.endsWith('%')&&width>0&&width<=100?width:null)];
    }
    if(node.tagName==='IFRAME'){
      const src=node.getAttribute('src')||'';if(!/^https:\/\/www\.youtube-nocookie\.com\/embed\/[\w-]{11}$/.test(src))return [];
      const frame=document.createElement('iframe');frame.src=src;frame.title='YouTube 동영상';frame.loading='lazy';frame.referrerPolicy='no-referrer';frame.allowFullscreen=true;frame.setAttribute('sandbox','allow-scripts allow-same-origin allow-presentation');return [frame];
    }
    if(node.tagName==='VIDEO'){
      const src=safeBioImageURL(node.getAttribute('src')||'');if(!src||!new URL(src,location.origin).pathname.endsWith('.webm'))return [];
      const video=document.createElement('video');video.src=src;video.controls=true;video.preload='none';return [video];
    }
    if(!bioRichTags.has(node.tagName))return [];
    const el=document.createElement(node.tagName.toLowerCase());
    if(node.tagName==='A'){
      const href=safeBioImageURL(node.getAttribute('href')||'');if(href){el.href=href;el.target='_blank';el.rel='noopener noreferrer';}
    }
    if(node.classList.contains('profile-bio-badge-row'))el.className='profile-bio-badge-row';
    if(node.classList.contains('profile-bio-spoiler')){el.className='profile-bio-spoiler';el.tabIndex=0;}
    if(node.style.textAlign==='center')el.style.textAlign='center';
    for(const child of node.childNodes)el.append(...clean(child));
    if(el.classList.contains('profile-bio-badge-row'))for(const nested of el.querySelectorAll('.profile-bio-badge-row'))nested.replaceWith(...nested.childNodes);
    return [el];
  };
  const fragment=document.createDocumentFragment();for(const node of template.content.childNodes)fragment.append(...clean(node));return fragment;
}

function serializeBioEditor(editor){
  // Never clone image elements on each keystroke; serialize pending images as well as loaded ones.
  const copy=node=>{
    if(node.nodeType===Node.ELEMENT_NODE&&node.tagName==='IMG'){
      const width=node.dataset.bioImageWidth,url=node.dataset.bioSrc||node.getAttribute('src');
      return document.createTextNode(width?`img${width}%(${url})`:`![소개 이미지](${url})`);
    }
    const clone=node.cloneNode(false);for(const child of node.childNodes)clone.append(copy(child));return clone;
  };
  const clone=copy(editor);
  if(editor.style.textAlign==='center'){
    const aligned=document.createElement('div');aligned.style.textAlign='center';aligned.append(...clone.childNodes);clone.append(aligned);
  }
  return clone.textContent===''&&!clone.querySelector('img,iframe,video,br')?'':bioRichPrefix+clone.innerHTML;
}

function safeBioImageURL(value){
  if(bioImageURL.test(value))return value;
  if(!value.startsWith('https://')||/[\u0000-\u0020\\]/.test(value))return null;
  try{const url=new URL(value);return url.protocol==='https:'&&url.hostname&&!url.username&&!url.password?url.href:null;}catch{return null;}
}

export function renderProfileBio(target,bio,fallback=''){
  if(!target)return;
  const fragment=document.createDocumentFragment(),text=String(bio||fallback);
  stopBioImages(target);
  if(text.startsWith(bioRichPrefix)){target.replaceChildren(safeBioRich(text.slice(bioRichPrefix.length)));target.classList.add('profile-bio-rich');loadBioImages(target);return;}
  const pattern=/(!?)\[([^\]\n]*)\]\(([^)\s]+)\)|\bimg(\d+(?:\.\d+)?)%\(([^)\s]+)\)/gi;
  const lines=text.split('\n');
  for(const [index,line]of lines.entries()){
    const content=document.createDocumentFragment();let position=0,remaining='',scaled=0,ordinary=0;
    for(const match of line.matchAll(pattern)){
      if(!match[4]&&!match[1]&&match[2].toLowerCase()!=='image')continue;
      const width=match[4]?Number(match[4]):!match[1]?18:null;
      if(width!==null&&(!Number.isFinite(width)||width<=0||width>100))continue;
      const url=safeBioImageURL(match[5]||match[3]);if(!url)continue;
      const before=line.slice(position,match.index);remaining+=before;content.append(document.createTextNode(before));
      const img=createBioImage(url,match[2],width);
      if(width!==null)scaled++;else ordinary++;
      content.append(img);position=match.index+match[0].length;
    }
    const rest=line.slice(position);remaining+=rest;content.append(document.createTextNode(rest));
    if(scaled&&!ordinary&&!remaining.trim()){
      const row=document.createElement('span');row.className='profile-bio-badge-row';row.append(content);fragment.append(row);
    }else fragment.append(content);
    if(index<lines.length-1)fragment.append(document.createTextNode('\n'));
  }
  target.replaceChildren(fragment);target.classList.add('profile-bio-rich');loadBioImages(target);
}

export function resetProfileBioEditor(){
  bioEditorGeneration++;for(const controller of bioUploads)controller.abort();bioUploads.clear();
  const editor=document.getElementById('profile-bio-editor');stopBioImages(editor);editor?.replaceChildren();
}
export function profileBioIsUploading(){return bioUploads.size>0;}
export function previewProfileBio(){
  const input=document.getElementById('profile-bio-input'),editor=document.getElementById('profile-bio-editor');
  if(editor){editor.style.removeProperty('text-align');renderProfileBio(editor,input?.value);editor.dispatchEvent(new Event('biohydrate'));}
  renderProfileBio(document.getElementById('profile-bio-preview'),input?.value,'소개 미리보기');
}

export function initProfileBioEditor(){
  if(bioEditorInitialized)return;bioEditorInitialized=true;
  const input=document.getElementById('profile-bio-input'),editor=document.getElementById('profile-bio-editor');if(!input||!editor)return;
  const status=text=>{const node=document.getElementById('profile-bio-status');if(node){node.textContent=text;node.hidden=!text;}};
  let lastHTML='',savedRange=null;
  editor.addEventListener('biohydrate',()=>{lastHTML=editor.innerHTML;savedRange=null;});
  const changed=()=>{
    const source=serializeBioEditor(editor);
    if(source.length>20000||new TextEncoder().encode(source).length>60000){stopBioImages(editor);editor.innerHTML=lastHTML;loadBioImages(editor);status('소개는 서식을 포함해 20,000자까지 입력할 수 있습니다.');return false;}
    input.value=source;lastHTML=editor.innerHTML;loadBioImages(editor);input.dispatchEvent(new Event('input',{bubbles:true}));return true;
  };
  const remember=()=>{
    const sel=getSelection();if(!sel?.rangeCount||!editor.contains(sel.anchorNode)||!editor.contains(sel.focusNode))return;
    savedRange=sel.getRangeAt(0).cloneRange();
    for(const command of ['bold','italic','underline','strikeThrough','insertOrderedList','insertUnorderedList','center'])document.querySelector(`[data-bio-command="${command}"]`)?.setAttribute('aria-pressed',String(document.queryCommandState(command==='center'?'justifyCenter':command)));
  };
  document.addEventListener('selectionchange',remember);
  const restore=()=>{editor.focus();const sel=getSelection();if(savedRange&&editor.contains(savedRange.commonAncestorContainer)){sel.removeAllRanges();sel.addRange(savedRange);}else{const range=document.createRange();range.selectNodeContents(editor);range.collapse(false);sel.removeAllRanges();sel.addRange(range);}};
  const insertNode=node=>{
    restore();const sel=getSelection(),range=sel.getRangeAt(0),last=node.nodeType===Node.DOCUMENT_FRAGMENT_NODE?node.lastChild:node;if(!last)return;
    const before=document.createRange(),after=document.createRange();before.selectNodeContents(editor);before.setEnd(range.startContainer,range.startOffset);after.selectNodeContents(editor);after.setStart(range.endContainer,range.endOffset);
    const media=[...editor.querySelectorAll('img,iframe,video')];
    const empty=!editor.textContent&&!media.length;
    const replacesAll=!range.collapsed&&!before.toString()&&!after.toString()&&media.every(img=>range.intersectsNode(img));
    // Pasting over an entire bio must not nest new badge rows inside the old first row.
    if(empty||replacesAll){editor.replaceChildren(node);editor.style.removeProperty('text-align');}else{range.deleteContents();range.insertNode(node);}
    range.setStartAfter(last);range.collapse(true);sel.removeAllRanges();sel.addRange(range);remember();changed();
  };
  const insertText=text=>{
    const holder=document.createElement('div');renderProfileBio(holder,text);
    // A bare image URL is equivalent to an AniList image badge.
    const walker=document.createTreeWalker(holder,NodeFilter.SHOW_TEXT),nodes=[];while(walker.nextNode())nodes.push(walker.currentNode);
    for(const node of nodes){
      const re=/https:\/\/[^\s<>"']+\.(?:png|jpe?g|gif|webp|avif|svg)(?:\?[^\s<>"']*)?/gi;
      const fragment=document.createDocumentFragment();let position=0;
      for(const match of node.data.matchAll(re)){const url=safeBioImageURL(match[0]);if(!url)continue;fragment.append(document.createTextNode(node.data.slice(position,match.index)));const part=document.createElement('span');renderProfileBio(part,`[image](${url})`);fragment.append(...part.childNodes);position=match.index+match[0].length;}
      if(position){fragment.append(document.createTextNode(node.data.slice(position)));node.replaceWith(fragment);}
    }
    const fragment=document.createDocumentFragment();fragment.append(...holder.childNodes);if(fragment.childNodes.length)insertNode(fragment);
  };
  async function insert(file){
    if(!file?.type.startsWith('image/')||file.size>5*1024*1024){status('이미지는 파일당 5MB 이하로 선택해 주세요.');return;}
    if(input.value.length+150>(input.maxLength>0?input.maxLength:20000)){status('소개에 이미지를 넣을 공간이 부족합니다. 소개 내용을 줄여 주세요.');return;}
    const generation=bioEditorGeneration,controller=new AbortController();bioUploads.add(controller);
    const marker=document.createElement('span');marker.textContent='[이미지 업로드 중…]';marker.dataset.bioUpload=crypto.randomUUID();insertNode(marker);status('소개 이미지를 업로드하는 중…');
    try{
      const form=new FormData();form.append('image',file);
      const response=await fetch('/api/account/profile/bio-images',{method:'POST',body:form,signal:controller.signal});
      if(!response.headers.get('content-type')?.includes('application/json'))throw Error('이미지 업로드 응답을 확인하지 못했습니다. 다시 붙여넣어 주세요.');
      const data=await response.json();if(!response.ok||!data.success)throw Error(data.error||'이미지를 업로드하지 못했습니다.');
      if(!bioImageURL.test(data.url))throw Error('이미지 주소가 올바르지 않습니다.');
      if(generation!==bioEditorGeneration)return;
      if(!editor.contains(marker))return;
      const part=document.createElement('span');renderProfileBio(part,`![소개 이미지](${data.url})`);marker.replaceWith(...part.childNodes);
      changed();status('이미지가 삽입되었습니다. 저장을 누르면 소개에 반영됩니다.');
    }catch(error){
      if(generation===bioEditorGeneration){marker.remove();changed();if(error.name!=='AbortError')status(error.message);}
    }finally{bioUploads.delete(controller);}
  }
  editor.addEventListener('paste',event=>{
    const files=Array.from(event.clipboardData?.items||[]).filter(item=>item.kind==='file'&&item.type.startsWith('image/')).map(item=>item.getAsFile()).filter(Boolean);
    event.preventDefault();remember();if(files.length){for(const file of files)insert(file);}else insertText(event.clipboardData?.getData('text/plain')||'');
  });
  editor.addEventListener('drop',event=>{event.preventDefault();remember();const files=[...event.dataTransfer.files];if(files.length){for(const file of files)insert(file);}else insertText(event.dataTransfer.getData('text/plain'));});
  editor.addEventListener('input',()=>{changed();remember();});
  editor.addEventListener('keydown',event=>{
    if((event.key===' '||event.key==='Enter')&&!event.isComposing){
      const sel=getSelection(),node=sel?.anchorNode;
      if(node?.nodeType===Node.TEXT_NODE&&sel.isCollapsed){const before=node.data.slice(0,sel.anchorOffset),match=before.match(/https:\/\/[^\s]+\.(?:png|jpe?g|gif|webp|avif|svg)(?:\?[^\s]*)?$/i);if(match&&safeBioImageURL(match[0])){const range=document.createRange();range.setStart(node,before.length-match[0].length);range.setEnd(node,sel.anchorOffset);sel.removeAllRanges();sel.addRange(range);remember();insertText(match[0]);}}
    }
  });
  input.addEventListener('input',()=>{lastHTML=editor.innerHTML;});
  const toolbar=document.getElementById('profile-bio-toolbar');
  toolbar?.addEventListener('mousedown',event=>event.preventDefault());
  toolbar?.addEventListener('click',event=>{
    const button=event.target.closest('[data-bio-command]');if(!button)return;restore();const command=button.dataset.bioCommand;
    if(['bold','italic','underline','strikeThrough','insertOrderedList','insertUnorderedList'].includes(command))document.execCommand(command);
    else if(['heading','quote','code'].includes(command)){const tag={heading:'h2',quote:'blockquote',code:'pre'}[command];document.execCommand('formatBlock',false,String(document.queryCommandValue('formatBlock')).toLowerCase()===tag?'div':tag);}
    else if(command==='center')document.execCommand(document.queryCommandState('justifyCenter')?'justifyLeft':'justifyCenter');
    else if(command==='spoiler'){
      const selection=getSelection(),range=selection.getRangeAt(0),span=document.createElement('span');span.className='profile-bio-spoiler';span.tabIndex=0;span.append(range.extractContents());if(!span.textContent)span.textContent='스포일러';insertNode(span);
    }else{
      const value=prompt(command==='image'?'이미지 URL (https://)':command==='youtube'?'YouTube URL':command==='video'?'WebM URL (https://)':'링크 URL (https://)');if(!value)return;
      const url=safeBioImageURL(value.trim());if(!url){status('올바른 HTTPS 주소를 입력해 주세요.');return;}restore();
      if(command==='image')insertText(`[image](${url})`);
      if(command==='link'){if(getSelection().isCollapsed){const a=document.createElement('a');a.href=url;a.textContent=url;a.target='_blank';a.rel='noopener noreferrer';insertNode(a);}else document.execCommand('createLink',false,url);}
      if(command==='youtube'){
        const parsed=new URL(url),id=parsed.hostname==='youtu.be'?parsed.pathname.slice(1):['youtube.com','www.youtube.com'].includes(parsed.hostname)?parsed.searchParams.get('v'):null;
        if(!/^[\w-]{11}$/.test(id||'')){status('올바른 YouTube 영상 주소를 입력해 주세요.');return;}
        insertNode(safeBioRich(`<iframe src="https://www.youtube-nocookie.com/embed/${id}"></iframe>`));
      }
      if(command==='video'){if(!new URL(url).pathname.endsWith('.webm')){status('WebM 파일 주소를 입력해 주세요.');return;}const video=document.createElement('video');video.src=url;video.controls=true;video.preload='none';insertNode(video);}
    }
    changed();remember();
  });
  const picker=document.getElementById('profile-bio-file');
  document.getElementById('profile-bio-image-button')?.addEventListener('click',()=>picker?.click());
  picker?.addEventListener('change',()=>{for(const file of picker.files||[])insert(file);picker.value='';});
}
