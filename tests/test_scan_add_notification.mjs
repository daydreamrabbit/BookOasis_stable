import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
let source = await readFile(new URL('../static/js/api.js', import.meta.url), 'utf8');
source = source.replace("import { state } from './state.js';", "const state = { currentLibraryType: 'general' };");
globalThis.window = {};
const {addLibrary} = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('category auto-scan starts status updates, failures do not', async () => {
  for (const data of [{success:true,scan_queued:true}, {success:true,scan_queued:false}, {success:false}]) {
    const events=[];
    globalThis.window={dispatchEvent: e => events.push(e)};
    globalThis.CustomEvent=class {constructor(type, options){this.type=type;this.detail=options.detail;}};
    globalThis.fetch=async()=>({status:200,json:async()=>data});
    const form=new FormData(); form.set('type','adult');
    assert.deepEqual(await addLibrary(form),data);
    assert.equal(events.length,data.success && data.scan_queued ? 1:0);
    if(events.length) {assert.equal(events[0].type,'bookoasis:scan-queued');assert.equal(events[0].detail.type,'adult');}
  }
});
