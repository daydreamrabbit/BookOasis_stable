import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source = await fs.readFile(new URL('../static/js/viewer/text_resume.js', import.meta.url), 'utf8');
const { readTextResume, restoreTextResume } = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
const anchor = { type: 'bookoasis-text-v1', chunkIdx: 3, offset: 7 };
assert.deepEqual(readTextResume({ cfi: JSON.stringify(anchor) }), anchor);
for (const cfi of ['epubcfi(/6/2)', '{}', 'null', '{', JSON.stringify({...anchor, offset:-1})]) {
  assert.equal(readTextResume({cfi}), null);
}
globalThis.NodeFilter = { SHOW_TEXT: 4 };
const node = { length: 50 };
let left = 640, top = 180;
globalThis.document = {
  createTreeWalker: () => { let done=false; return {nextNode(){if(done)return null;done=true;return node;}}; },
  createRange: () => ({setStart(n,o){assert.equal(o,7);},setEnd(){},getBoundingClientRect:()=>({left,right:left+10,top})}),
};
const content = {querySelector:s=>s==='[data-idx="3"]'?{}:null};
const wrapper = {scrollLeft:0,scrollTop:20,getBoundingClientRect:()=>({left:0,right:600,top:30})};
assert(restoreTextResume(anchor,wrapper,content,{scroll:false,rtl:false,advance:600}));
assert.equal(wrapper.scrollLeft,600);
left=-50;wrapper.scrollLeft=0;
assert(restoreTextResume(anchor,wrapper,content,{scroll:false,rtl:true,advance:600}));
assert.equal(wrapper.scrollLeft,-600);
assert(restoreTextResume(anchor,wrapper,content,{scroll:true,advance:600}));
assert.equal(wrapper.scrollTop,170);

// The exit snapshot must run synchronously before sendBeacon, without importing
// another lifecycle module instance (query-string URLs have separate state).
const progress = (await fs.readFile(new URL('../static/js/viewer_progress.js',import.meta.url),'utf8'))
  .replace(/^import .*;$/gm,'').replace(/export /g,'');
const handlers={}, sent=[];
const context=vm.createContext({state:{currentLibraryType:'books'},console:{log(){},warn(){},error(){}},
  flushReadReport(){},noteReadActivity(){},
  setTimeout:()=>1,clearTimeout(){},Blob:class {constructor(parts){this.parts=parts;}},
  navigator:{sendBeacon:(url,body)=>{sent.push(JSON.parse(body.parts[0]));return true;}},
  window:{addEventListener:(name,fn)=>handlers[name]=fn},
  document:{visibilityState:'hidden',addEventListener:(name,fn)=>handlers[name]=fn}});
vm.runInContext(progress,context);
context.setProgressSnapshotProvider(()=>context.saveProgress(1,3,100,{epub_session:{cfi:JSON.stringify(anchor)}}));
handlers.pagehide();handlers.visibilitychange();
assert.equal(sent.length,2);assert.deepEqual(JSON.parse(sent[0].epub_session.cfi),anchor);
console.log('PASS text anchor validation, LTR/RTL/scroll restoration, synchronous exit snapshots');
