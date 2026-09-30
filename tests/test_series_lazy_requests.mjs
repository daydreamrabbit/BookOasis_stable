import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
const source = (await readFile(new URL('../static/js/api.js', import.meta.url), 'utf8'))
  .replace("import { state } from './state.js';", 'const state = {};');
globalThis.window = { dispatchEvent() {} };
const { triggerSeriesLazyScan } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
test('same series shares requests and successful cooldown, failures can retry', async t => {
  let calls = 0, signals = 0, release;
  t.mock.method(window, 'dispatchEvent', () => signals++);
  t.mock.method(globalThis, 'setTimeout', () => 0);
  t.mock.method(globalThis, 'fetch', () => {
    calls++;
    return new Promise(resolve => release = () => resolve(Response.json({success:true,scan_queued:false})));
  });
  const first = triggerSeriesLazyScan('general',2,'story');
  const second = triggerSeriesLazyScan('general',2,'story');
  assert.equal(calls,1);
  release(); await Promise.all([first,second]);
  await triggerSeriesLazyScan('general',2,'story');
  assert.equal(calls,1); assert.equal(signals,0);
  t.mock.method(globalThis, 'fetch', async () => { calls++; return Response.json({success:false}); });
  await triggerSeriesLazyScan('adult',2,'story');
  await triggerSeriesLazyScan('adult',2,'story');
  assert.equal(calls,3);
});
