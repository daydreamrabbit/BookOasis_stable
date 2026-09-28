import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('static/js/viewer_txt.js','utf8');
const fn=source.slice(source.indexOf('function saveProgress('),source.indexOf('function restoreServerTextPosition'));
for (const [chapter,start,local,expected] of [[7,8,1,7],[8,12,9,19]]) {
 test(`EPUB physical page ${expected+1} is saved independently of its chapter index`,()=>{
  let saved;
  const starts=[];starts[chapter]=start;
  const c=vm.createContext({textResumeReady:true,txtPageSnapInProgress:false,currentChunkIdx:chapter,
   state:{activeBookId:1,currentViewerFormat:'epub'},captureTextResume:()=>null,
   document:{getElementById:()=>({})},localStorage:{getItem:()=> 'page'},
   epubPagination:{bookId:1,starts,total:137},getTxtPhysicalPageInfo:()=>({first:local}),
   queueProgress:(...args)=>{saved=args;}});
  vm.runInContext(fn+`saveProgress(1,${chapter},24);`,c);
  assert.equal(saved[1],expected);assert.equal(saved[2],137);
  assert.equal(saved[3].epub_session.index,chapter);
  assert.equal(saved[3].epub_session.percent,expected/136*100);
  assert.equal(JSON.parse(saved[3].epub_session.cfi).chunkIdx,chapter);
 });
}
test('image-only EPUB read position is reported rather than retaining an old listen anchor',()=>{
 const text=fs.readFileSync('static/js/viewer/tts_sync.js','utf8');
 const fn=text.slice(text.indexOf('function readBody()'),text.indexOf('// 뷰어의 "듣기"'));
 const c=vm.createContext({positionProvider:()=>({chapter_idx:0,char_offset:0,text_len:0,anchor:''}),
  state:{activeBookId:1,currentViewerFormat:'epub',currentLibraryType:'general'},isTextViewer:()=>true});
 const result=JSON.parse(vm.runInContext(fn+'readBody()',c));
 assert.equal(result.kind,'read');assert.equal(result.chapter_idx,0);assert.equal(result.anchor,'');
});
