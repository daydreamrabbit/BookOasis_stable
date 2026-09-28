import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source=fs.readFileSync('static/js/tts/tts_player.js','utf8');
const helper=source.slice(source.indexOf('let playAttempt ='),source.indexOf('async function playCurrent()'));
for(const ready of [true,false]) test(`reader readiness ${ready} is awaited before playback`,async()=>{
 const messages=[];
 const c=vm.createContext({embedMode:true,S:{cur:0,segments:[{start:0,text:'첫 문장'}]},book:{format:'epub',chapter:4},
  document:{hidden:false},setTimeout:()=>1,clearTimeout:()=>{},location:{origin:'test'},window:{parent:{postMessage:m=>messages.push(m)}}});
 const pending=vm.runInContext(helper+'prepareReaderPosition()',c);
 let settled=false;pending.then(()=>{settled=true;});
 await Promise.resolve();assert.equal(settled,false);
 assert.equal(messages[0].type,'prepare-position');assert.equal(messages[0].chapter_idx,4);
 vm.runInContext(`pendingReaderPositions.get(1)(${ready})`,c);
 assert.equal(await pending,ready);
});
test('hidden reader does not block playback on a DOM acknowledgement', async()=>{
 const messages=[];
 const c=vm.createContext({embedMode:true,S:{cur:0,segments:[{start:15,text:'문장'}]},book:{format:'epub',chapter:4},
  document:{hidden:true},location:{origin:'test'},window:{parent:{postMessage:m=>messages.push(m)}}});
 assert.equal(await vm.runInContext(helper+'prepareReaderPosition()',c),true);
 assert.equal(messages[0].char_offset,15);
 assert.equal(vm.runInContext('pendingReaderPositions.size',c),0);
});
