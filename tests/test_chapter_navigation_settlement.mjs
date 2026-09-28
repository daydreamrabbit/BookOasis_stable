import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const code=(await fs.readFile(new URL('../static/js/viewer/txt_navigation.js',import.meta.url),'utf8'))
  .replace(/^import .*;$/m,'').replace(/export /g,'');
for (const direction of ['prev','next']) test(`${direction} chapter commits its final position once and unlocks immediately`,()=>{
  let locked=false,idx=2,settle;const updates=[],timers=[];
  const wrapper={scrollLeft:direction==='prev'?0:200,scrollWidth:300,clientWidth:100,style:{},scrollTop:0};
  const runtime=vm.createContext({getTxtPageScrollLeft:w=>w.scrollLeft,setTxtPageScrollLeft:(w,x)=>w.scrollLeft=x,
    setTimeout:cb=>timers.push(cb)});
  vm.runInContext(code,runtime);
  const ctx={getScrollWrapper:()=>wrapper,cancelPendingRestore(){},getScrollMode:()=> 'page',
    getTxtPageSnapInProgress:()=>locked,setTxtPageSnapInProgress:v=>locked=v,snapTxtPageScrollLeft(){},
    getCurrentChunkIdx:()=>idx,setCurrentChunkIdx:v=>idx=v,getChunkCount:()=>5,getTxtPageAdvanceWidth:()=>100,
    renderCurrentChunk:(init,cb)=>{settle=cb;wrapper.scrollLeft=direction==='prev'?0:200;},
    saveDetailPosition(){},updatePageInfo:()=>updates.push({left:wrapper.scrollLeft,locked}),logActiveViewportText(){}};
  runtime[`${direction}TxtPageAction`](ctx);
  assert.equal(locked,true);assert.equal(updates.length,0);assert.equal(timers.length,0);
  settle();
  assert.equal(locked,false);assert.equal(wrapper.style.visibility,'');
  assert.equal(updates.length,1);assert.equal(updates[0].left,direction==='prev'?200:0);
  assert.equal(updates[0].locked,false);
  settle();assert.equal(updates.length,1);
});
