import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import vm from 'node:vm';
const source = await fs.readFile(new URL('../static/js/viewer/input_controller.js', import.meta.url), 'utf8');
const fn = source.slice(source.indexOf('function handleViewerKeydown('), source.indexOf('export function initKeyboardListener'));
test('user bindings override reserved arrows, space and fullscreen without consuming text input', () => {
  for (const key of ['ArrowLeft', ' ', 'f', 'Escape']) {
    const calls = [];
    const context = vm.createContext({
      document: {getElementById: id => id === 'media-viewer-modal' ? {style:{display:'flex'}} : null},
      localStorage: {getItem: name => name === 'custom_key_next' ? key : null},
      callDep: name => calls.push(name), window:{}, state:{currentViewerFormat:'epub'},
    });
    vm.runInContext(fn, context);
    context.handleViewerKeydown({key,code:key===' '?'Space':key,target:{tagName:'DIV'},preventDefault(){}});
    assert.deepEqual(calls, ['nextPage']);
    context.handleViewerKeydown({key,code:key,target:{tagName:'INPUT'},preventDefault(){}});
    assert.equal(calls.length,1);
  }
});

test('Rabbit resets just the targeted book immediately, including a numeric zero', async () => {
  const script = await fs.readFile(new URL('../plugins/metadata/rabbit_plugins/detail/script.js', import.meta.url), 'utf8');
  const start = script.indexOf('    const handleReadingReset =');
  const end = script.indexOf('    const handleViewerProgress =', start);
  const books = [{id:1,pages_read:42,is_completed:1},{id:2,pages_read:10,is_completed:0}];
  let renders=0;
  const context = vm.createContext({books,root:{isConnected:true},type:'general',renderHeader:()=>renders++});
  vm.runInContext(script.slice(start,end)+'\nglobalThis.reset = handleReadingReset;',context);
  context.reset({detail:{type:'general',id:1,scope:'book'}});
  assert.equal(books[0].pages_read,0);assert.equal(books[0].is_completed,0);
  assert.equal(books[1].pages_read,10);assert.equal(renders,1);
  context.reset({detail:{type:'adult',id:2,scope:'book'}});
  assert.equal(books[1].pages_read,10);assert.equal(renders,1);
});

test('visible EPUB text is captured even when its first-column container is offscreen', async () => {
  const code = await fs.readFile(new URL('../static/js/viewer/text_resume.js',import.meta.url),'utf8');
  const text = {length:20};
  const chunk = {dataset:{idx:'3'},getClientRects:()=>[{left:-800,right:-400,top:0,bottom:600}]};
  const rect = {left:20,right:200,top:20,bottom:40,height:20};
  const context = vm.createContext({NodeFilter:{SHOW_TEXT:4},document:{
    createTreeWalker:()=>{let done=false;return {nextNode(){if(done)return null;done=true;return text;}};},
    createRange:()=>({selectNodeContents(){},getClientRects:()=>[rect]}),
    caretRangeFromPoint:()=>({startContainer:text,startOffset:5}),
  }});
  vm.runInContext(code.replace(/export /g,''),context);
  const anchor=context.captureTextResume({getBoundingClientRect:()=>({left:0,right:400,top:0,bottom:600})},
    {querySelectorAll:()=>[chunk]},3);
  assert.equal(anchor.chunkIdx,3);assert.equal(anchor.offset,5);
});
