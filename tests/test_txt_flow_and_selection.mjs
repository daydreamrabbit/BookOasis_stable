import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const root = new URL('../static/js/viewer/', import.meta.url);
const source = await fs.readFile(new URL('txt_render.js', root), 'utf8');
const {renderTxtChunkView} = await import('data:text/javascript;base64,' + Buffer.from(source).toString('base64'));
let writes=0, html='';
const contentArea={style:{},dataset:{},classList:{remove(){}},querySelector:selector=>selector==='.txt-flow-chunk'&&html.includes('txt-flow-chunk')?{}:null,
  get innerHTML(){return html;},set innerHTML(value){html=value;writes++;}};
const chunks=['first fragment','second fragment'];
const args={contentArea,txtChunks:chunks,currentChunkIdx:0,scrollMode:'page',isEpub:false,formatTxtToHtml:s=>`<p>${s}</p>`};
renderTxtChunkView(args);
assert(html.includes('data-idx="0"')&&html.includes('data-idx="1"'));
assert(!html.includes('height: 100%'));assert(html.includes('break-inside:auto'));
renderTxtChunkView({...args,currentChunkIdx:1});assert.equal(writes,1,'navigation must not recreate full text');
renderTxtChunkView({...args,scrollMode:'scroll',initMode:true});assert(!html.includes('3rem'));

const ui=await fs.readFile(new URL('annotation_ui.js',root),'utf8');
const fn=ui.slice(ui.indexOf('let selectionEndGeneration ='),ui.indexOf('async function createPendingAnnotation'));
let clears=0, timer=null;
const modal={};const area={contains:target=>target.inside};
const context=vm.createContext({document:{getElementById:id=>id==='media-viewer-modal'?modal:area},
 getComputedStyle:()=>({display:'flex'}),selectionGestureStartedOnText:false,
 window:{getSelection:()=>({removeAllRanges:()=>clears++})},hideButton(){},
 getViewerPlatformProfile:()=>({isMobileDevice:false}),setTimeout:cb=>{timer=cb;}});
vm.runInContext(fn,context);
context.handleSelectionEnd({target:{inside:false}});assert.equal(timer,null);
context.handleSelectionEnd({target:{inside:true,closest:()=>true}});assert.equal(timer,null);
context.handleSelectionEnd({target:{inside:true,closest:()=>false}});timer();assert.equal(clears,0);
console.log('PASS continuous chunk flow, DOM reuse, scroll gaps, external/control selection safety');
