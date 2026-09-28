import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

globalThis.window = {
  dispatchEvent() {},
  location: { href: '' },
};

const apiSource = (await readFile(new URL('../static/js/api.js', import.meta.url), 'utf8'))
  .replace("import { state } from './state.js';", 'const state = {};');
const apiUrl = `data:text/javascript;base64,${Buffer.from(apiSource).toString('base64')}`;
const { fetchBooksList } = await import(apiUrl);

async function requestedUrl(includeHasMetadata) {
  let capturedUrl = '';
  globalThis.fetch = async (url) => {
    capturedUrl = String(url);
    return { status: 200, json: async () => ({ success: true, series: [] }) };
  };
  await fetchBooksList({
    type: 'general',
    libraryId: 1,
    page: 1,
    limit: 60,
    includeHasMetadata,
  });
  return capturedUrl;
}

test('metadata presence is not requested by default', async () => {
  const url = await requestedUrl(false);
  assert.equal(url.includes('include_has_metadata='), false);
});

test('metadata presence is requested only when the user enables the setting', async () => {
  const url = await requestedUrl(true);
  assert.equal(new URL(url, 'https://bookoasis.test').searchParams.get('include_has_metadata'), '1');
});
