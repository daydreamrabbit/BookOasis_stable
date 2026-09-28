import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

test('every text viewer consumer shares a single stateful module URL', async () => {
  const urls = new Set();
  for (const file of ['viewer.js', 'viewer/lifecycle_controller.js', 'viewer/seekbar_controller.js',
    'viewer/ridi_panels.js', 'viewer/viewer_padding.js']) {
    const url = new URL(`../static/js/${file}`, import.meta.url);
    const code = await fs.readFile(url, 'utf8');
    for (const match of code.matchAll(/['"](\.\.?\/viewer_txt\.js[^'"]*)['"]/g)) {
      urls.add(new URL(match[1], url).href);
    }
  }
  assert.equal(urls.size, 1, [...urls].join('\n'));
});
