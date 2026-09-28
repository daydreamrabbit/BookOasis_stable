import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source=fs.readFileSync('static/js/viewer_txt.js','utf8');
const method=source.slice(source.indexOf('  async seekToTtsPosition('),source.indexOf('  jumpTo(target)'));
for (const reason of ['reopen same book','open another book','cancel old TTS request']) {
  test(`late TTS chapter response cannot mutate viewer after ${reason}`,async()=>{
    let resolve;
    let current=true;
    const pending=new Promise(r=>{resolve=r;});
    const c=vm.createContext({cancelPendingTxtRestore:()=>{},txtSessionGeneration:1,state:{activeBookId:1,currentViewerFormat:'epub'},
      txtChunks:[null],currentChunkIdx:7,requestEpubChapterContent:(_idx,options)=>{
        assert.equal(options.updateDom,false);return pending;
      },position:{format:'epub',chapter_idx:0,isCurrent:()=>current}});
    const result=vm.runInContext(`({${method}}).seekToTtsPosition(position)`,c);
    if (reason==='reopen same book') c.txtSessionGeneration++;
    else if (reason==='open another book') c.state.activeBookId=2;
    else current=false;
    c.txtChunks=['new session text'];
    resolve('old chapter');
    assert.equal(await result,null);
    assert.equal(c.currentChunkIdx,7);
    assert.equal(c.txtChunks[0],'new session text');
  });
}
