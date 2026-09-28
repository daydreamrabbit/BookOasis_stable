import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('static/js/viewer/renderer.js','utf8');
const init=source.slice(source.indexOf('export async function initRenderer'),source.indexOf('// Accessors')).replace('export ','');
test('closing during progress fetch prevents late page initialization',async()=>{
 let respond;let pageRequests=0;
 const c=vm.createContext({state:{activeBookId:1,currentViewerFormat:'cbz'},console,
  fetch:()=>new Promise(resolve=>respond=resolve),showViewerLoading(){},clearBlobCache(){},
  document:{getElementById:()=>({style:{}})},FileLoader:{fetchTotalPagesIfNeeded(){pageRequests++;}},
 });
 vm.runInContext('let rendererSessionSeq=0,isInitializingProgress=false;function clearComicViewer(){rendererSessionSeq++;}\n'+init,c);
 const pending=vm.runInContext('initRenderer(1,0,0)',c);
 vm.runInContext('clearComicViewer()',c);respond({ok:true,json:async()=>({success:true,state:{pages_read:1}})});
 await pending;assert.equal(pageRequests,0);
 assert.match(source,/export function clearComicViewer\(\) \{\s*rendererSessionSeq \+= 1/);
});
test('automatic fullscreen does not consume Android Back before viewer routing',async()=>{
 const code=fs.readFileSync('static/js/viewer/platform_profile.js','utf8');
 const {shouldAutoFullscreenForFormat}=await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
 for(const format of ['cbz','zip','pdf','imgdir','epub','txt'])assert.equal(shouldAutoFullscreenForFormat(format,{isLikelyMobileContext:true}),false);
});
test('late page-count response cannot change state after close',async()=>{
 let respond;
 const c=vm.createContext({state:{activeBookId:1,currentViewerFormat:'cbz'},console,
  fetch:async()=>({ok:false}),showViewerLoading(){},clearBlobCache(){},
  document:{getElementById:()=>({style:{}})},FileLoader:{fetchTotalPagesIfNeeded:()=>new Promise(resolve=>respond=resolve)},
 });
 vm.runInContext('let rendererSessionSeq=0,isInitializingProgress=false,comicCurrentPage=0,comicTotalPages=0;function clearComicViewer(){rendererSessionSeq++;comicTotalPages=0;}\n'+init,c);
 const pending=vm.runInContext('initRenderer(1,0,1)',c);
 await new Promise(resolve=>setImmediate(resolve));
 vm.runInContext('clearComicViewer()',c);respond(25);await pending;
 assert.equal(vm.runInContext('comicTotalPages',c),0);
});
test('mobile navigation restores internal scroll without shifting the header',()=>{
 const code=fs.readFileSync('static/js/tab_media_library.js','utf8');
 const fn=code.slice(code.indexOf('function restoreNavigationScroll('),code.indexOf('function saveNavigationScrollState('));
 const main={},grid={},dashboard={},doc={},body={};const scrolls=[];
 const c=vm.createContext({state:{},rememberNavigationScroll(){},requestAnimationFrame:f=>f(),setTimeout:f=>f(),
  document:{querySelector:()=>main,getElementById:id=>id==='books-grid-view'?grid:dashboard,documentElement:doc,body},
  window:{matchMedia:()=>({matches:true}),scrollTo:(x,y)=>scrolls.push(y)}});
 vm.runInContext(fn+'restoreNavigationScroll(400,"home")',c);
 assert.equal(main.scrollTop,400);assert.equal(grid.scrollTop,0);assert.equal(dashboard.scrollTop,0);
 assert.deepEqual(scrolls,[0,0]);assert.equal(doc.scrollTop,0);
});
