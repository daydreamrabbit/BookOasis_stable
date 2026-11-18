import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import {chromium} from 'playwright-core';
const script=await fs.readFile(new URL('../static/js/advanced_search.js',import.meta.url),'utf8');
const css=await fs.readFile(new URL('../static/css/advanced_search.css',import.meta.url),'utf8');
for(const width of [390,1280])test(`advanced search selections, category options and safe labels at ${width}px`,async t=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 const page=await browser.newPage({viewport:{width,height:800}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 page.setDefaultTimeout(5000);
 await page.route('**/*',async route=>{const url=new URL(route.request().url());let body='',contentType='text/javascript';
 if(url.pathname.endsWith('advanced_search.js'))body=script;
 else if(url.pathname.endsWith('state.js'))body='export const state=window.__state;';
 else if(url.pathname.endsWith('library_search_preview.js'))body='export function closeLibrarySearchPreview(){}';
 else if(url.pathname==='/api/media/libraries'){contentType='application/json';body=JSON.stringify({success:true,libraries:[{id:1,name:'첫 카테고리'},{id:2,name:'두번째 카테고리'}]});}
 else if(url.pathname.endsWith('/options')){const f=JSON.parse(url.searchParams.get('filters'));contentType='application/json';body=JSON.stringify({success:true,options:{publisher:f.categories.includes('2')?['Two']:['One','<img onerror=alert(1)>'],publication_status:['0','1','2'],genre:['SF','판타지'],tags:['A'],rating:['0','15']}});}
 else{contentType='text/html';body=`<style>${css}</style><div class="library-search-box" style="position:relative;height:42px"><input id="library-search"><button id="btn-advanced-search">상세검색</button></div><div id="advanced-search-active" hidden></div>`;}
 await route.fulfill({contentType,body});});
 await page.goto('http://search.test/');await page.evaluate(()=>{window.__state={currentLibraryType:'general',advancedSearch:null};window.calls=[];window.selectCategory=async(id,back,options)=>{window.calls.push({id,options});if(!options)window.__state.advancedSearch=null;};});
 await page.addScriptTag({type:'module',url:'http://search.test/static/js/advanced_search.js'});
 await page.waitForFunction(()=>document.querySelector('#btn-advanced-search').dataset.bound==='1');
 await page.locator('#btn-advanced-search').click();await page.locator('.advanced-submit').waitFor();await page.waitForFunction(()=>!document.querySelector('.advanced-submit').disabled);
 await page.locator('[data-field=publisher] summary').click();await page.getByText('<img onerror=alert(1)>',{exact:true}).click();assert.equal(await page.locator('.advanced-search-panel img').count(),0);
 await page.locator('[data-field=categories] summary').click();await page.getByText('두번째 카테고리',{exact:true}).click();await page.waitForFunction(()=>document.querySelector('[data-field=publisher]').textContent.includes('Two'));
 assert.match(await page.locator('.advanced-message').textContent(),/해제/);
 if(await page.locator('[data-field=publisher]').getAttribute('open')===null)await page.locator('[data-field=publisher] summary').click();await page.getByText('Two',{exact:true}).click();
 await page.locator('input[name=author]').fill('작가');await page.locator('input[name=series]').fill('시리즈');
 const bounds=await page.locator('.advanced-search-panel').boundingBox();assert.ok(bounds.x>=0&&bounds.x+bounds.width<=width+1);
 await page.locator('.advanced-submit').click();assert.equal(await page.locator('.advanced-search-panel').isVisible(),false);
 const call=await page.evaluate(()=>calls.at(-1));assert.equal(call.id,'all');assert.deepEqual(call.options.advancedSearch.categories,['2']);assert.equal(call.options.advancedSearch.author,'작가');assert.deepEqual(call.options.advancedSearch.publisher,['Two']);
 assert.match(await page.locator('#advanced-search-active').textContent(),/출판사: Two/);
 await page.getByText('전체 초기화',{exact:true}).click();assert.equal(await page.locator('#advanced-search-active').isVisible(),false);
 await page.locator('#btn-advanced-search').click();await page.waitForFunction(()=>!document.querySelector('.advanced-submit').disabled);
 await page.locator('input[name=series]').fill('임시 조건');
 await page.locator('.advanced-reset').click();
 assert.equal(await page.locator('.advanced-search-panel').isVisible(),false);
 assert.equal(await page.locator('#library-search').inputValue(),'');
 assert.equal(await page.evaluate(()=>__state.advancedSearch),null);
 await page.locator('#btn-advanced-search').click();await page.waitForFunction(()=>!document.querySelector('.advanced-submit').disabled);
 assert.equal(await page.locator('input[name=series]').inputValue(),'');
 assert.deepEqual(errors,[]);
});

test('stable labels before network and inherited category scope',async t=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 const page=await browser.newPage();page.setDefaultTimeout(5000);
 let release;const scopes=[];
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());let body='',contentType='text/javascript';
  if(url.pathname.endsWith('advanced_search.js'))body=script;
  else if(url.pathname.endsWith('state.js'))body='export const state=window.__state;';
  else if(url.pathname.endsWith('library_search_preview.js'))body='export function closeLibrarySearchPreview(){}';
  else if(url.pathname==='/api/media/libraries'){
   await new Promise(resolve=>release=resolve);contentType='application/json';body=JSON.stringify({success:true,libraries:[{id:1,name:'One'},{id:2,name:'Two'}]});
  }else if(url.pathname.endsWith('/options')){
   const scope=JSON.parse(url.searchParams.get('filters')).categories;scopes.push(scope);
   contentType='application/json';body=JSON.stringify({success:true,options:{publisher:scope.includes('2')?['TwoPublisher']:['AllPublisher']}});
  }else{contentType='text/html';body=`<style>${css}</style><div class="library-search-box"><input id="library-search"><button id="btn-advanced-search">상세검색</button></div><div id="advanced-search-active" hidden></div>`;}
  await route.fulfill({contentType,body});
 });
 await page.goto('http://search.test/');await page.evaluate(()=>{window.__state={currentLibraryType:'general',currentLibraryId:'2',advancedSearch:null};window.selectCategory=async()=>{};});
 await page.addScriptTag({type:'module',url:'http://search.test/static/js/advanced_search.js'});
 await page.waitForFunction(()=>document.querySelector('#btn-advanced-search').dataset.bound==='1');
 for(const [id,active,expected] of [['2',null,['2']],['home',null,[]],['2',{categories:[]},[]],['2',{categories:['1']},['1']]]){
  await page.evaluate(({id,active})=>{__state.currentLibraryId=id;__state.advancedSearch=active;},{id,active});
  const requested=page.waitForRequest('**/api/media/libraries?*');await page.locator('#btn-advanced-search').click();await requested;
  assert.deepEqual(await page.locator('.advanced-fields summary').allTextContents(),[
   `카테고리 · ${expected.length?'1개 선택':'전체'}`,'출판사 · 전체','연재상태 · 전체','장르 · 전체','태그 · 전체','연령등급 · 전체']);
  assert.equal(await page.locator('.advanced-submit').isDisabled(),true);
  release();await page.waitForFunction(()=>!document.querySelector('.advanced-submit').disabled);
  assert.deepEqual(scopes.at(-1),expected);
  assert.equal(await page.locator('[data-field=categories] input:checked').count(),expected.length);
  if(expected.includes('2'))assert.match(await page.locator('[data-field=publisher]').textContent(),/TwoPublisher/);
  await page.locator('.advanced-search-panel header button').click();
 }
});

test('level-19 facets distinguish adult light novels and retain legacy selections',async t=>{
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',headless:true,args:['--no-sandbox']});t.after(()=>browser.close());
 const page=await browser.newPage();page.setDefaultTimeout(5000);
 await page.route('**/*',async route=>{
  const url=new URL(route.request().url());let body='',contentType='text/javascript';
  if(url.pathname.endsWith('advanced_search.js'))body=script;
  else if(url.pathname.endsWith('state.js'))body='export const state=window.__state;';
  else if(url.pathname.endsWith('library_search_preview.js'))body='export function closeLibrarySearchPreview(){}';
  else if(url.pathname==='/api/media/libraries'){
   contentType='application/json';body=JSON.stringify({success:true,libraries:[{id:1,name:'일반'}]});
  }else if(url.pathname.endsWith('/options')){
   contentType='application/json';body=JSON.stringify({success:true,options:{publisher:[],publication_status:[],genre:[],tags:[],rating:['19-light-novel','19-manga']}});
  }else{
   contentType='text/html';body='<div class="library-search-box"><input id="library-search"><button id="btn-advanced-search">상세검색</button></div><div id="advanced-search-active" hidden></div>';
  }
  await route.fulfill({contentType,body});
 });
 await page.goto('http://search.test/');
 await page.evaluate(()=>{
  window.__state={currentLibraryType:'general',currentLibraryId:'all',advancedSearch:{rating:['19']}};
  window.selectCategory=async(id,back,options)=>window.__calls.push({id,options});
  window.__calls=[];
 });
 await page.addScriptTag({type:'module',url:'http://search.test/static/js/advanced_search.js'});
 await page.waitForFunction(()=>document.querySelector('#btn-advanced-search').dataset.bound==='1');
 await page.locator('#btn-advanced-search').click();
 await page.waitForFunction(()=>!document.querySelector('.advanced-submit').disabled);
 await page.locator('[data-field=rating] summary').click();
 const labels=await page.locator('[data-field=rating] .advanced-choice-list label').allTextContents();
 assert.deepEqual(labels,['성인라노벨','성인망가']);
 assert.equal(await page.locator('[data-field=rating] input:checked').count(),2);
 await page.locator('[data-field=rating] label').filter({hasText:'성인망가'}).locator('input').uncheck();
 await page.locator('.advanced-submit').click();
 const call=await page.evaluate(()=>__calls.at(-1));
 assert.deepEqual(call.options.advancedSearch.rating,['19-light-novel']);
 assert.match(await page.locator('#advanced-search-active').textContent(),/연령등급: 성인라노벨/);
});
