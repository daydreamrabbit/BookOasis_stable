import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
const code = fs.readFileSync('static/js/tts/backend_policy.js', 'utf8');
const { backendOrder, qualitySteps, copyingInputs } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
test('iPhone and desktop-UA iPad force WASM, desktop keeps WebGPU', () => {
  assert.deepEqual(backendOrder('webgpu', true, {userAgent:'iPhone'}), ['wasm']);
  assert.deepEqual(backendOrder('auto', true, {platform:'MacIntel',maxTouchPoints:5}), ['wasm']);
  assert.deepEqual(backendOrder('auto', true, {platform:'MacIntel',maxTouchPoints:0}), ['webgpu','wasm']);
});
test('legacy Fast and invalid saved quality become Normal', () => {
  for (const value of [undefined, null, 2, '2', 0, 'invalid', 4]) assert.equal(qualitySteps(value), 4);
  assert.equal(qualitySteps(8), 8);
});
test('worker may detach copied inputs without corrupting reused tensors', async () => {
  class Tensor { constructor(type,data,dims) { Object.assign(this,{type,data,dims}); } }
  const original = new Tensor('float32', new Float32Array([1,2]), [2]);
  const session = copyingInputs({run: async feeds => {
    const copied = structuredClone(feeds, {transfer:[feeds.style.data.buffer]});
    return Array.from(copied.style.data);
  }}, Tensor);
  assert.deepEqual(await session.run({style:original}), [1,2]);
  assert.deepEqual(await session.run({style:original}), [1,2]);
  assert.equal(original.data.byteLength, 8);
});
