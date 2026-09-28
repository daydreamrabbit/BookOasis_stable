import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const load=async path=>import(`data:text/javascript;base64,${Buffer.from(fs.readFileSync(path,'utf8')).toString('base64')}`);
const {restoreViewerPreferences}=await load('static/js/viewer/preference_restore.js');
const {pdfTextRects}=await load('static/js/viewer/pdf_text_hit.js');
test('late defaults do not overwrite saved reader preferences',()=>{
 const values=new Map([['viewer_font_size','1.50'],['viewer_theme','sepia'],['viewer_line_height','2.0'],['viewer_font_family','batang'],['viewer_paragraph_spacing','2']]);
 const storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v))};
 const before=[...values];
 const effective=restoreViewerPreferences({VIEWER_FONT_SIZE:'18',VIEWER_THEME:'dark',VIEWER_LINE_HEIGHT:'1.8',VIEWER_FONT_FAMILY:'sans-serif',VIEWER_PARAGRAPH_SPACING:'1'},storage);
 assert.deepEqual([...values],before);assert.equal(effective.VIEWER_FONT_SIZE,'24');
});
test('new device initializes missing preferences from account defaults',()=>{
 const values=new Map();const storage={getItem:k=>values.get(k)??null,setItem:(k,v)=>values.set(k,String(v))};
 restoreViewerPreferences({VIEWER_FONT_SIZE:'24',VIEWER_FONT_FAMILY:'serif'},storage);
 assert.equal(values.get('viewer_font_size'),'1.50');assert.equal(values.get('viewer_font_family'),'batang');
});
test('PDF text hit map excludes empty/image-only pages and maps scaled text',()=>{
 const viewport={transform:[2,0,0,-2,0,400],scale:2};
 assert.deepEqual(pdfTextRects({items:[]},viewport),[]);
 const [rect]=pdfTextRects({items:[{str:'hello',transform:[10,0,0,10,20,100],width:40}]},viewport);
 assert.equal(rect.left,40);assert.equal(rect.right,120);assert.ok(rect.top<200&&rect.bottom>200);
});
const src=fs.readFileSync('static/js/viewer/input_controller.js','utf8');
const handler=src.slice(src.indexOf('export function dismissViewerChromeOnContentTap'),src.indexOf('// 높이맞춤 +')).replace('export ','');
for(const text of [false,true])test(`visible toolbar content tap text=${text}`,()=>{
 let calls=0;const context=vm.createContext({document:{getElementById:()=>({style:{display:'flex'},classList:{contains:()=>false}})},
  isViewerTextPoint:()=>text,window:{getSelection:()=>null},callDep:()=>calls++});
 vm.runInContext(handler,context);
 const target={closest:selector=>selector==='#viewer-body-container'?{}:null};
 assert.equal(context.dismissViewerChromeOnContentTap(target,20,20),!text);
 assert.equal(calls,text?0:1);
});
