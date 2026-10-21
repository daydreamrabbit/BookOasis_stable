import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const {chromium}=await import(process.env.PLAYWRIGHT_MODULE||'playwright-core');
test('EPUB refresh previews selected fields, escapes source and requires renewed approval after edits',async()=>{
 const source=await fs.readFile('static/js/embedded_metadata_refresh.js','utf8'),css=await fs.readFile('static/css/problem_cards.css','utf8');
 const browser=await chromium.launch({executablePath:'/usr/bin/google-chrome',args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}}),calls=[];
  await page.route('http://refresh.test/**',route=>{
   if(route.request().url().includes('/api/')){
    const payload=route.request().postDataJSON();calls.push(payload);
    return route.fulfill({json:payload.action==='preview'?{success:true,entries:[{id:1,title:'<script>bad</script>',changes:{genre:{before:'해외라이트노벨',after:'라이트노벨, 해외라이트노벨',source:'라이트노벨, 해외라이트노벨'}}},{id:2,title:'locked',changes:{},error:'메타데이터 잠금'}]}:{success:true,updated:1,results:[{id:1,status:'updated'}]}});
   }
   if(route.request().url().endsWith('.js'))return route.fulfill({contentType:'application/javascript',body:source});
   return route.fulfill({contentType:'text/html',body:`<style>:root{--app-panel-rgb:39,41,46;--app-border:#444;--app-input-bg:#1c1d20;--app-accent:#4f8ef0;--app-accent-soft:#4f8ef022;--app-text-primary:#eee;--app-text-secondary:#aaa;--app-accent-contrast:#fff}*{box-sizing:border-box}${css}</style><script type="module">import{openEmbeddedMetadataRefresh}from'/refresh.js';window.open=()=>openEmbeddedMetadataRefresh('general',[1],'series',()=>window.updated=(window.updated||0)+1);window.ready=true;</script>`});
  });
  await page.goto('http://refresh.test/');await page.waitForFunction(()=>window.ready);await page.evaluate(()=>window.open());
  const apply=page.locator('[data-refresh="apply"]');assert.equal(await apply.isDisabled(),true);
  for(const width of [320,390,1440]){
   await page.setViewportSize({width,height:844});
   const layout=await page.locator('#embedded-refresh-modal').evaluate(n=>({overflow:n.scrollWidth>n.clientWidth,fields:[...n.querySelectorAll('.embedded-refresh-field span')].map(e=>e.getBoundingClientRect().height),fieldset:getComputedStyle(n.querySelector('fieldset')).borderStyle,button:getComputedStyle(n.querySelector('[data-refresh="preview"]')).height}));
   assert.equal(layout.overflow,false);assert.ok(layout.fields.every(h=>h>=40));assert.equal(layout.fieldset,'none');assert.ok(parseFloat(layout.button)>=40);
  }
  await page.setViewportSize({width:390,height:844});
  await page.locator('[data-refresh="preview"]').click();await page.waitForFunction(()=>!document.querySelector('[data-refresh="apply"]').disabled);
  assert.deepEqual(calls[0].fields,['genre']);assert.equal(calls[0].scope,'series');assert.equal(await page.locator('#embedded-refresh-modal script').count(),0);
  assert.match(await page.locator('[data-refresh-results]').innerText(),/해외라이트노벨 → 라이트노벨, 해외라이트노벨/);
  await page.locator('.embedded-refresh-mode').filter({has:page.locator('[value="merge"]')}).click();assert.equal(await apply.isDisabled(),true);
  await page.locator('[data-refresh="preview"]').click();await apply.click();await page.waitForFunction(()=>window.updated===1);
  assert.equal(calls.at(-1).approved.length,1);assert.equal(calls.at(-1).mode,'merge');assert.equal(await apply.isDisabled(),true);
  await page.keyboard.press('Escape');assert.equal(await page.locator('#embedded-refresh-modal').count(),0);
  await page.evaluate(()=>window.open());await page.keyboard.press('Escape');assert.equal(await page.locator('#embedded-refresh-modal').count(),0);
 }finally{await browser.close();}
});
