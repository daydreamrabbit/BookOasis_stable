import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync('static/js/viewer.js','utf8');
const start=source.indexOf('function initMediaViewerDelegation()');
const end=source.indexOf('window.__mediaViewerDelegationBound = true;',start);
const setup=source.slice(start,end)+'window.__mediaViewerDelegationBound = true;\n}';
test('a center hotspot click opens chrome once without the body closing it again',()=>{
 let hidden=true,stopped=false,handler;
 const toggle=()=>{hidden=!hidden;};
 const context=vm.createContext({window:{},document:{addEventListener:(type,fn)=>{if(type==='click')handler=fn;}},
  isViewerTextPoint:()=>false,getTapZoneDirection:()=> 'horizontal',toggleViewerChrome:toggle,
  dismissViewerChromeOnContentTap:()=>{if(hidden)return false;toggle();return true;}});
 vm.runInContext(setup+'initMediaViewerDelegation();',context);
 const target={closest:s=>s==='[data-role="viewer-action"]'||s==='#common-viewer-hotspot'?target:null,
  getAttribute:k=>k==='data-action'?'toggle-viewer-controls':null};
 for(let i=0;i<6;i++){
  stopped=false;handler({target,clientX:500,clientY:400,preventDefault(){},stopPropagation(){stopped=true;}});
  // Mimic the later body listener which dismisses newly visible chrome.
  if(!stopped)context.dismissViewerChromeOnContentTap();
  assert.equal(hidden,i%2!==0);assert.equal(stopped,true);
 }
});
