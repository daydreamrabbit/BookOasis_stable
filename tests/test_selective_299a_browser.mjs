import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright-core');
test('category deletion reports HTTP proxy errors and does not treat failed JSON as success',async()=>{
 const source=await fs.readFile('static/js/api.js','utf8');
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try{
  const page=await browser.newPage();let reply;
  await page.route('http://audit.test/**',route=>{
   const path=new URL(route.request().url()).pathname;
   if(path==='/api.js')return route.fulfill({contentType:'application/javascript',body:source});
   if(path==='/state.js')return route.fulfill({contentType:'application/javascript',body:'export const state={};'});
   if(path==='/search_filters.js')return route.fulfill({contentType:'application/javascript',body:'export const filteredSearchUrl=()=>null;'});
   if(path==='/api/media/libraries/delete')return route.fulfill(reply);
   return route.fulfill({contentType:'text/html',body:'<script type="module">import{deleteLibrary}from"/api.js";window.remove=()=>deleteLibrary(new FormData());window.ready=true;</script>'});
  });
  await page.goto('http://audit.test/');await page.waitForFunction(()=>window.ready);
  reply={status:504,contentType:'text/html',body:'<h1>Gateway Timeout</h1>'};
  assert.deepEqual(await page.evaluate(()=>window.remove()),{success:false,error:'HTTP 504 Gateway Timeout'});
  reply={status:500,json:{success:false,error:'DB busy'}};
  assert.deepEqual(await page.evaluate(()=>window.remove()),{success:false,error:'DB busy'});
  reply={status:500,json:{success:true}};
  assert.deepEqual(await page.evaluate(()=>window.remove()),{success:false,error:'HTTP 500 Internal Server Error'});
  reply={status:200,json:{success:true,message:'ok'}};
  assert.deepEqual(await page.evaluate(()=>window.remove()),{success:true,message:'ok'});
 }finally{await browser.close();}
});
