import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFile} from 'node:fs/promises';
const source=await readFile(new URL('../static/js/category/index.js',import.meta.url),'utf8');
const code=source.slice(source.indexOf('let sidebarLoadToken'),source.indexOf('function getLegacyCustomOrderStorageKey')).replace('export async function','async function');
test('count-only updates add/remove badges and discard stale category responses',async()=>{
 let badge=null, resolve;
 const container={prepend:b=>{badge=b}};
 const item={dataset:{categoryId:'2'},querySelector:s=>s==='.category-count-badge'?badge:{parentElement:container}};
 const state={currentLibraryType:'general'};
 const ctx=vm.createContext({state,window:{},Map,Number,String,Error,formatCompactCount:String,
  api:{fetchLibraries:()=>new Promise(r=>{resolve=r})},
  document:{querySelectorAll:()=>[item],createElement:()=>({remove(){badge=null}})}});
 vm.runInContext(code,ctx);
 let request=ctx.refreshLibraryCounts();resolve({success:true,libraries:[{id:2,book_count:17}]});await request;
 assert.equal(badge.textContent,'17');
 request=ctx.refreshLibraryCounts();state.currentLibraryType='adult';resolve({success:true,libraries:[{id:2,book_count:999}]});assert.equal(await request,false);
 assert.equal(badge.textContent,'17');
 request=ctx.refreshLibraryCounts();resolve({success:true,libraries:[{id:2,book_count:0}]});await request;assert.equal(badge,null);
});
