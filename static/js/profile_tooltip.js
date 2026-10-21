// One floating tooltip for profile, reading activity and book-card titles.
export function initProfileTooltips(){
  if(document.getElementById('profile-hover-tooltip'))return;
  const tip=document.createElement('div');tip.id='profile-hover-tooltip';tip.className='profile-hover-tooltip';tip.setAttribute('role','tooltip');tip.setAttribute('aria-hidden','true');
  const title=document.createElement('strong'),detail=document.createElement('span'),preview=document.createElement('img');preview.alt='';tip.append(title,detail);document.body.append(tip);
  let active=null,hovered=null,showTimer=null,hideTimer=null,scrollTimer=null,frame=null;
  const roots=new WeakSet(),handledEvents=new WeakSet();
  const nativeSelector='.book-card[title],.book-card [title],.vol-grid-card[title],.vol-grid-card [title],.volume-card[title],.volume-card [title],.plugin-item-card[title],.plugin-item-card [title]';
  const selector=`#user-profile-view [data-profile-tip],.reading-activity-day[data-profile-tip],[data-app-tooltip],${nativeSelector}`;
  function resolveTarget(node){
    const target=node?.closest?.(selector);
    for(let titled=target;titled;titled=titled.parentElement?.closest(nativeSelector)){
      if(!titled.matches(nativeSelector))continue;
      const text=titled.getAttribute('title');
      if(text){
        titled.dataset.appTooltip=text;
        if(!titled.hasAttribute('aria-label')&&!titled.hasAttribute('aria-labelledby')&&!titled.textContent.trim())titled.setAttribute('aria-label',text);
        // Remove before the browser's native hover delay; keep the original
        // text on the node, without rebuilding cards or observing the whole DOM.
        titled.removeAttribute('title');
      }
    }
    return target&&(target.dataset.profileTip||target.dataset.appTooltip)?target:null;
  }
  function eventTarget(event){
    let target=null;
    for(const node of event.composedPath()){
      if(node.nodeType===11&&node.host)bindRoot(node);
      if(!target)target=resolveTarget(node);
    }
    return target;
  }
  function handled(event){
    if(handledEvents.has(event))return true;
    handledEvents.add(event);return false;
  }
  const clear=()=>{clearTimeout(showTimer);clearTimeout(hideTimer);clearTimeout(scrollTimer);cancelAnimationFrame(frame);};
  function detach(){
    if(!active)return;
    const ids=(active.getAttribute('aria-describedby')||'').split(' ').filter(v=>v&&v!==tip.id);
    if(ids.length)active.setAttribute('aria-describedby',ids.join(' '));else active.removeAttribute('aria-describedby');
  }
  function hide(){clear();detach();active=null;tip.classList.remove('is-visible');tip.setAttribute('aria-hidden','true');}
  function show(target){
    if(!target.isConnected)return;
    const visible=tip.classList.contains('is-visible');detach();active=target;
    title.textContent=target.dataset.profileTip||target.dataset.appTooltip||'';detail.textContent=target.dataset.profileTipDetail||'';
    tip.dataset.layout=target.dataset.profileTipLayout||'';
    const cover=target.dataset.profileTipCover;
    const safeCover=cover&&(/^(https?:|data:image\/)/i.test(cover)||cover.startsWith('/')&&!cover.startsWith('//'));
    if(safeCover){preview.src=cover;tip.prepend(preview);tip.dataset.preview='cover';}else{preview.remove();preview.removeAttribute('src');delete tip.dataset.preview;}
    tip.dataset.kind=target.classList.contains('reading-activity-day')?'activity':target.hasAttribute('data-app-tooltip')?'card':'profile';
    active.setAttribute('aria-describedby',[(active.getAttribute('aria-describedby')||''),tip.id].filter(Boolean).join(' '));
    if(!visible)tip.classList.add('is-positioning');
    const r=target.getBoundingClientRect(),width=tip.offsetWidth,height=tip.offsetHeight;
    const preferredX=safeCover?(r.left-width-16>=8?r.left-width-16:r.right+16):r.left+r.width/2-width/2;
    const x=Math.max(8,Math.min(innerWidth-width-8,preferredX));
    const below=r.top-height-10<8;
    const y=safeCover?Math.min(innerHeight-height-8,r.top):below?Math.min(innerHeight-height-8,r.bottom+10):r.top-height-10;
    tip.dataset.side=below?'below':'above';tip.style.setProperty('--profile-tip-arrow',`${Math.max(12,Math.min(width-12,r.left+r.width/2-x))}px`);
    tip.style.transform=`translate3d(${Math.round(x)}px,${Math.round(Math.max(8,y))}px,0)`;
    tip.setAttribute('aria-hidden','false');
    frame=requestAnimationFrame(()=>{tip.classList.remove('is-positioning');tip.classList.add('is-visible');});
  }
  function enter(target){clear();target=resolveTarget(target);if(!target)return;showTimer=setTimeout(()=>show(target),tip.classList.contains('is-visible')?0:80);}
  function onOver(event){
    if(handled(event)||event.pointerType==='touch')return;
    const target=eventTarget(event);hovered=target;
    if(target&&(!event.relatedTarget||!target.contains(event.relatedTarget)))enter(target);
  }
  function onOut(event){
    if(handled(event))return;
    const target=eventTarget(event);
    if(!target||target.contains(event.relatedTarget))return;
    if(hovered===target)hovered=null;
    clearTimeout(showTimer);hideTimer=setTimeout(hide,90);
  }
  function onFocusIn(event){if(!handled(event)){const target=eventTarget(event);if(target)enter(target);}}
  function onFocusOut(event){if(!handled(event)&&eventTarget(event))hide();}
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape')hide();
    const cell=event.target.closest?.('.reading-activity-day[data-date]');
    const delta={ArrowLeft:-7,ArrowRight:7,ArrowUp:-1,ArrowDown:1}[event.key];
    if(!cell||!delta)return;
    const cells=[...cell.parentElement.querySelectorAll('[data-date]')],index=cells.indexOf(cell);
    const next=cells[index+delta];
    event.preventDefault();
    if(next){cell.tabIndex=-1;next.tabIndex=0;next.focus();}
  });
  function onScroll(event){
    if(handled(event))return;
    hide();
    // Native scrollIntoView and late layout changes can scroll after pointerover.
    // Restore only once scrolling settles, and only for the still-hovered/focused cell.
    scrollTimer=setTimeout(()=>{
      let focused=document.activeElement;
      while(focused?.shadowRoot?.activeElement)focused=focused.shadowRoot.activeElement;
      const target=focused?.matches?.(selector)&&focused.matches(':focus-visible')?focused:hovered?.isConnected&&hovered.matches(':hover')?hovered:document.querySelector(`:is(${selector}):hover`);
      if(!target)return;
      const rect=target.getBoundingClientRect();
      if(rect.bottom>0&&rect.top<innerHeight&&rect.right>0&&rect.left<innerWidth)enter(target);
    },100);
  }
  function bindRoot(root){
    if(roots.has(root))return;
    roots.add(root);
    // Widget cards live in open Shadow DOM. Internal pointer/focus transitions
    // are retargeted at the host and do not always reach document listeners.
    root.addEventListener('pointerover',onOver);root.addEventListener('pointerout',onOut);
    root.addEventListener('focusin',onFocusIn);root.addEventListener('focusout',onFocusOut);
    root.addEventListener('scroll',onScroll,true);
  }
  bindRoot(document);
  window.addEventListener('resize',hide);window.addEventListener('bookoasis:view-changing',hide);
  window.addEventListener('bookoasis:profile-rendering',hide);
  window.addEventListener('bookoasis:activity-rendering',hide);
}
