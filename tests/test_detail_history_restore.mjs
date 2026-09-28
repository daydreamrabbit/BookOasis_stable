import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/detail/history_navigation.js', import.meta.url), 'utf8');
const routeSource = await readFile(new URL('../static/js/tab_media_library.js', import.meta.url), 'utf8');
const { matchesRetainedDetailHistory, restoreBehindDetail } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
);

test('detail is reactivated synchronously while the prior category is restored asynchronously', async () => {
  const events = [];
  let finishNavigation;
  const navigation = restoreBehindDetail(
    () => {
      events.push('category-start');
      return new Promise((resolve) => { finishNavigation = resolve; });
    },
    () => events.push('detail-reactivated'),
  );

  assert.deepEqual(events, ['category-start', 'detail-reactivated']);
  finishNavigation();
  await navigation;
  assert.deepEqual(events, ['category-start', 'detail-reactivated']);
});

test('detail popstate hides the list before restoring the prior category', () => {
  const start = routeSource.indexOf("} else if (event.state && event.state.view === 'detail') {");
  const end = routeSource.indexOf("} else if ((!event.state || !event.state.view) && window.location.hash.startsWith('#detail'))", start);
  assert.notEqual(start, -1);
  assert.notEqual(end, -1);
  const branch = routeSource.slice(start, end);
  assert.match(branch, /detailViewForRestore\.style\.display = 'none'/);
  assert.match(branch, /restoreBehindDetail\(/);
  assert.match(branch, /const canReuseRetainedDetail = retainedDetailMatchesHistory\s*&&\s*matchesRetainedDetailHistory/);
  assert.match(branch, /switchActiveView\('detail'\);\s*if \(!canReuseRetainedDetail\) \{[\s\S]*?await openBookDetail/s);
  assert.doesNotMatch(branch, /await selectCategory\(/);
});

test('a matching retained detail can be reused without a second detail fetch', () => {
  const target = { view: 'detail', series: 'Series A', libraryId: '4', repBookId: '12', type: 'general' };
  const retained = {
    hasContent: true,
    series: 'Series A',
    libraryId: '4',
    representativeBookId: '12',
    libraryType: 'general',
  };

  assert.equal(matchesRetainedDetailHistory(retained, target), true);
  assert.equal(matchesRetainedDetailHistory({ ...retained, series: 'Series B' }, target), false);
  assert.equal(matchesRetainedDetailHistory({ ...retained, hasContent: false }, target), false);
  assert.equal(matchesRetainedDetailHistory(retained, { ...target, type: 'adult' }), false);
});
