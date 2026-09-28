import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('embedded speed changes stop stale audio and request the current reader anchor', () => {
  const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  const fn=source.slice(source.indexOf('function changeVoice(patch)'),source.indexOf('function renderSettings()'));
  for (const paused of [false,true]) {
    const messages=[];
    const S={active:true,userPaused:paused,token:0,heardCurrentPiece:true,heardChapterSeconds:10};
    const context=vm.createContext({S,settings:{},embedMode:true,autoplayWanted:true,pendingReaderPositions:new Map(),
      $:()=>({}),renderStats:()=>{},wakeGenerator:()=>{},clearClips:()=>{},renderPlayBtn:()=>{},renderStatus:()=>{},
      player:{pause:()=>{}},location:{origin:'test'},window:{addEventListener:()=>{},parent:{postMessage:m=>messages.push(m)}}});
    vm.runInContext(fn+'changeVoice({speed:1.4});',context);
    assert.equal(S.active,false);assert.equal(S.userPaused,true);assert.equal(S.heardCurrentPiece,false);
    assert.equal(context.autoplayWanted,false);
    assert.equal(messages.length,paused?0:1);
    if (!paused) assert.equal(messages[0].type,'request-start');
  }
});

test('embedded progress mirrors the full reader, not chapter segment counts', () => {
  const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  const fn=source.slice(source.indexOf('function renderReaderProgress()'),source.indexOf('// 도서 메뉴'));
  const elements={seek:{style:{setProperty:(k,v)=>elements.fill=v}},pos:{},pct:{}};
  const c=vm.createContext({embedMode:true,readerProgress:{min:'1',max:'500',value:'7',label:'7 / 500',percent:1.2024,disabled:false},$:id=>elements[id]});
  vm.runInContext(fn+'renderReaderProgress();',c);
  assert.equal(elements.seek.value,'7'); assert.equal(elements.seek.max,'500');
  assert.equal(elements.pos.textContent,'7 / 500'); assert.equal(elements.pct.textContent,'1%');
  c.readerProgress={...c.readerProgress,value:'8',label:'8 / 500',percent:1.4};
  vm.runInContext('renderReaderProgress();',c);
  assert.equal(elements.seek.value,'8'); assert.equal(elements.pos.textContent,'8 / 500');
});

test('auto chapter transition resets the resume anchor and embedded TXT does not write chunk progress', () => {
  const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  assert.match(source,/S\.sync = \{ latest: 'read', read: \{ chapter_idx: book\.chapter \+ 1, char_offset: 0, anchor: '' \} \}/);
  assert.match(source,/const progress = !embedMode && canReportReaderProgress/);
  assert.match(source,/S\.heardCurrentPiece = false;\s*S\.heardChapterSeconds = 0;\s*player\.pause\(\)/);
});

test('embedded page navigation stays available before the voice engine is ready', () => {
  const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  const fn=source.slice(source.indexOf('function updateControls()'),source.indexOf('// ---- 읽기↔듣기'));
  const elements=Object.fromEntries(['playBtn','prevBtn','nextBtn','seek'].map(id=>[id,{}]));
  vm.runInNewContext(fn+'updateControls();', {embedMode:true,S:{tts:null,pieces:[]},$:id=>elements[id],
    renderReaderProgress:()=>{elements.seek.disabled=false;}});
  assert.equal(elements.playBtn.disabled,true);
  assert.equal(elements.seek.disabled,false);
});

test('skipping an image chapter starts the next text chapter at zero despite saved resume', async () => {
  const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  const fn=source.slice(source.indexOf('async function loadText()'),source.indexOf('function updateControls()'));
  const elements={chapterName:{},seek:{}};
  const S={syncApplied:false,sync:{latest:'read',read:{chapter_idx:0,char_offset:0}}};
  const c=vm.createContext({S,book:{format:'epub',chapter:0,chapters:['image','text']},
    dbType:'general',bookId:1,storage:null,MAX_PIECE_CHARS:120,MIN_ALONE_CHARS:10,
    fetchChapterText:async idx=>idx?'first sentence. second sentence.':'',
    segmentForTts:text=>text?[{start:0,text:'first sentence.'},{start:16,text:'second sentence.'}]:[],
    loadResume:()=>({piece:1,offset:5}),positionKey:()=>'',lastChapterKey:()=>'',
    log:()=>{},toast:()=>{},t:x=>x,$:id=>elements[id],renderText:()=>{},renderNow:()=>{},updateControls:()=>{},
    syncStartPiece:()=>S.syncApplied?null:{piece:0,offset:0}});
  await vm.runInContext(fn+'loadText();',c);
  assert.equal(c.book.chapter,1);
  assert.equal(S.sync.read.chapter_idx,1);
  assert.equal(S.sync.read.char_offset,0);
  assert.equal(S.cur,0);
  assert.equal(S.pendingOffset,0);
});
