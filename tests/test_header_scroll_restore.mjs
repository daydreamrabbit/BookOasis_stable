import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('restored scroll leaves header visible until actual user scrolling',()=>{
 const classes=new Set();const listeners={},windowListeners={};
 const header={classList:{add:x=>classes.add(x),remove:x=>classes.delete(x),toggle:(x,on)=>on?classes.add(x):classes.delete(x)}};
 const scroll={scrollTop:0,addEventListener:(type,fn)=>listeners[type]=fn};
 vm.runInNewContext(fs.readFileSync('static/js/header_scroll_behavior.js','utf8'),{
  document:{readyState:'complete',querySelector:selector=>selector==='.library-header'?header:scroll},
  window:{matchMedia:()=>({matches:true}),addEventListener:(type,fn)=>windowListeners[type]=fn},
  requestAnimationFrame:fn=>fn(),
 });
 scroll.scrollTop=350;listeners.scroll();assert.equal(classes.has('library-header--hidden'),false);
 listeners.touchmove();scroll.scrollTop=400;listeners.scroll();assert.equal(classes.has('library-header--hidden'),true);
 windowListeners['bookoasis:view-changing']();assert.equal(classes.has('library-header--hidden'),false);
 scroll.scrollTop=600;listeners.scroll();assert.equal(classes.has('library-header--hidden'),false);
 listeners.wheel();scroll.scrollTop=650;listeners.scroll();assert.equal(classes.has('library-header--hidden'),true);
 windowListeners.popstate();assert.equal(classes.has('library-header--hidden'),false);
});
