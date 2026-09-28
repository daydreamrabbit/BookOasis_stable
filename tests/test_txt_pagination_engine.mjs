import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
const source = await fs.readFile(new URL('../static/js/viewer/txt_pagination_engine.js', import.meta.url), 'utf8');
const { createTxtPaginationEngine } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
let live = 0, peak = 0, measured = 0, current = true, yields = 0;
const calculate = createTxtPaginationEngine({ batchSize: 2, maxEntries: 2, maxChars: 100,
  yieldControl: async () => { yields++; } });
const options = { key: 'book-A:font-16:single', chunks: ['abc','def','g','hi','j'],
  isCurrent: () => current,
  createProbe: text => { live++; peak = Math.max(peak, live); return {text, remove(){live--;}}; },
  readProbe: probe => { measured++; return probe.text.length; } };
assert.deepEqual(await calculate(options), [3,3,1,2,1]);
assert.equal(peak, 2);assert.equal(live, 0);assert.equal(yields, 2);
assert.deepEqual(await calculate({...options,chunks:options.chunks.slice()}), [3,3,1,2,1]);
assert.equal(measured, 5, 'same content and layout must reuse cache');
await calculate({...options,chunks:['changed']});assert.equal(measured,6);
await calculate({...options,key:'font-20'});assert.equal(measured,11);
await calculate(options);assert.equal(measured,16, 'LRU eviction');
const cancel = createTxtPaginationEngine({ batchSize: 2, yieldControl: async()=>{current=false;} });
assert.equal(await cancel(options),null);assert.equal(live,0);
current=true;
await assert.rejects(createTxtPaginationEngine()({...options,readProbe:()=>{throw Error('layout error');}}));
assert.equal(live,0,'cleanup on error');
console.log('PASS cache, file/layout invalidation, LRU, bounded DOM, cancellation, cleanup');
