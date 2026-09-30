import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = (await readFile(new URL('../static/js/api.js', import.meta.url), 'utf8'))
  .replace("import { state } from './state.js';", 'const state = {};');
globalThis.window = {location:{href:''}};
const { fetchLibrarySchedules } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('schedule API accepts JSON and requests an uncached JSON response', async t => {
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    assert.equal(url, '/api/media/libraries/schedules?type=general%26other');
    assert.equal(options.cache, 'no-store');
    assert.equal(options.headers.Accept, 'application/json');
    return Response.json({success:true,libraries:[{id:1}]});
  });
  assert.deepEqual(await fetchLibrarySchedules('general&other'), {success:true,libraries:[{id:1}]});
});

test('proxy HTML errors never reach the JSON parser and the next request recovers', async t => {
  let failed = true;
  let parses = 0;
  t.mock.method(globalThis, 'fetch', async () => failed ? {
    status:502,ok:false,headers:new Headers({'content-type':'text/html'}),
    json() { parses++; throw new SyntaxError('Unexpected token <'); },
  } : Response.json({success:true,libraries:[]}));
  const result = await fetchLibrarySchedules('general');
  assert.equal(result.success, false);
  assert.equal(result.http_status, 502);
  assert.equal(parses, 0);
  failed = false;
  assert.deepEqual(await fetchLibrarySchedules('general'), {success:true,libraries:[]});
});

test('HTML 200, malformed JSON, and invalid schemas return recoverable failures', async t => {
  for (const response of [
    new Response('<html>maintenance</html>', {headers:{'content-type':'text/html'}}),
    new Response('<html>maintenance</html>', {headers:{'content-type':'application/json'}}),
    Response.json(null), Response.json([]), Response.json({}),
    Response.json({success:true,libraries:null}),
  ]) {
    t.mock.method(globalThis, 'fetch', async () => response);
    assert.equal((await fetchLibrarySchedules('adult')).success, false);
    t.mock.restoreAll();
  }
});

test('non-OK JSON cannot report success, and preserves the server error', async t => {
  t.mock.method(globalThis, 'fetch', async () => Response.json({success:true,error:'denied'}, {status:403}));
  const result = await fetchLibrarySchedules('general');
  assert.equal(result.success, false);
  assert.equal(result.error, 'denied');
  assert.equal(result.http_status, 403);
});

test('network failure does not reject a periodic refresh', async t => {
  t.mock.method(globalThis, 'fetch', async () => { throw new TypeError('Failed to fetch'); });
  assert.equal((await fetchLibrarySchedules('general')).error_code, 'network_error');
});

test('expired session follows the existing login flow', async t => {
  const previous = globalThis.window;
  globalThis.window = {location:{href:''}};
  t.after(() => { globalThis.window = previous; });
  t.mock.method(console, 'warn', () => {});
  t.mock.method(globalThis, 'fetch', async () => Response.json({success:false}, {status:401}));
  assert.equal((await fetchLibrarySchedules('general')).error_code, 'unauthorized');
  assert.equal(window.location.href, '/login');
});
