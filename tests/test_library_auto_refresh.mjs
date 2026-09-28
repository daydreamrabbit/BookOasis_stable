import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const trackerSource = await readFile(new URL('../static/js/library_revision_tracker.js', import.meta.url), 'utf8');
const refreshSource = await readFile(new URL('../static/js/library_auto_refresh.js', import.meta.url), 'utf8');

test('background revision changes refresh once, defer reader/input, and survive category changes', async () => {
  let revisions = { general: '1', adult: '1' }, lists = 0, details = 0;
  let viewer = false, typing = false;
  const state = { currentLibraryType: 'general', currentLibraryId: '2', detailSeriesName: 'test' };
  const elements = { 'media-viewer-modal': {}, 'book-detail-view': {} };
  const document = { hidden: false, activeElement: { matches: () => typing },
    getElementById: id => elements[id], querySelector: () => null, addEventListener() {} };
  const context = vm.createContext({ state, document, console,
    window: { invalidateBookListAfterScan: () => lists++, invalidateDashboardData() {},
      refreshLibraryCounts: async () => true,
      openBookDetail: async () => details++, getSelection: () => '', addEventListener() {} },
    getComputedStyle: e => ({ display: e === elements['media-viewer-modal'] && !viewer ? 'none' : 'block' }),
    fetch: async () => { throw new Error('periodic revision requests are forbidden'); },
    EventSource: class { addEventListener() {} close() {} },
    setTimeout() {}, clearTimeout() {},
  });
  vm.runInContext(trackerSource.replace('export function', 'function') + '\n' +
    refreshSource.replace(/^import .*;\n/gm, '').replace('export async function', 'async function')
      .replace(/checkLibraryChanges\(\);\s*$/, ''), context);
  const check = () => { context.revisions = revisions; vm.runInContext('tracker.observe(revisions)', context); return context.checkLibraryChanges(); };
  await check(); assert.equal(lists, 0); // baseline is not a change
  revisions = { general: '2', adult: '2' }; viewer = true;
  await check(); assert.equal(lists, 0);
  viewer = false; typing = true;
  await check(); assert.equal(lists, 1); assert.equal(details, 1); // idle focus must not block
  typing = false;
  await check(); assert.equal(lists, 1);
  state.currentLibraryType = 'adult'; await check(); assert.equal(lists, 2);
  document.hidden = true; await check(); assert.equal(lists, 2);
  document.hidden = false; revisions = { general: '3', adult: '3' };
  await Promise.all([check(), check(), check()]); assert.equal(lists, 3);
});
