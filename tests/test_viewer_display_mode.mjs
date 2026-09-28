import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/viewer/display_mode.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { ViewerDisplayMode, getViewerDisplayMode, saveViewerDisplayMode } = await import(moduleUrl);

function storage(initial = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, String(value)),
    values,
  };
}

test('legacy page preferences migrate to one unified mode', () => {
  assert.equal(getViewerDisplayMode(storage({ viewer_scroll_mode: 'scroll' })), ViewerDisplayMode.SCROLL);
  assert.equal(getViewerDisplayMode(storage({ viewer_scroll_mode: 'page', comic_page_step: '1' })), ViewerDisplayMode.ONE);
  assert.equal(getViewerDisplayMode(storage({ viewer_scroll_mode: 'page', comic_page_step: '2', comic_reading_direction: 'ltr' })), ViewerDisplayMode.ONE_TWO);
  assert.equal(getViewerDisplayMode(storage({ viewer_scroll_mode: 'page', comic_page_step: '2', comic_reading_direction: 'rtl' })), ViewerDisplayMode.TWO_ONE);
  assert.equal(getViewerDisplayMode(storage({ viewer_display_mode: 'two-three' })), ViewerDisplayMode.TWO_ONE);
});

test('spread modes update the legacy renderer preferences atomically', () => {
  const store = storage();
  saveViewerDisplayMode(ViewerDisplayMode.ONE_TWO, store);
  assert.equal(store.values.get('comic_page_step'), '2');
  assert.equal(store.values.get('viewer_spread_cover_alone'), '1');
  assert.equal(store.values.get('comic_reading_direction'), 'ltr');
  saveViewerDisplayMode(ViewerDisplayMode.TWO_ONE, store);
  assert.equal(store.values.get('comic_page_step'), '2');
  assert.equal(store.values.get('viewer_spread_cover_alone'), '1');
  assert.equal(store.values.get('comic_reading_direction'), 'rtl');
});
