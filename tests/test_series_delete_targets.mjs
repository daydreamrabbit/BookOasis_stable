import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/series_delete_targets.js', import.meta.url), 'utf8');
const { resolveSeriesDeleteTargets } = await import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);

test('single series context resolves to one deletion target', () => {
  assert.deepEqual(resolveSeriesDeleteTargets({
    id: 10, libraryId: 2, seriesName: 'Series A', title: 'Series A', isVolumeDetail: false,
  }), [{ id: 10, libraryId: 2, seriesName: 'Series A', title: 'Series A', isVolumeDetail: false }]);
});

test('multi selection resolves distinct series and removes duplicate series targets', () => {
  const targets = resolveSeriesDeleteTargets({
    selectedBooks: [
      { id: 10, libraryId: 2, seriesName: 'Series A', title: 'A' },
      { id: 11, libraryId: 2, seriesName: 'Series A', title: 'A second anchor' },
      { id: 20, libraryId: 2, seriesName: 'Series B', title: 'B' },
      { id: 30, libraryId: 3, seriesName: 'Series A', title: 'Same name, other library' },
    ],
  });

  assert.deepEqual(targets.map(({ id, libraryId, seriesName }) => ({ id, libraryId, seriesName })), [
    { id: 10, libraryId: 2, seriesName: 'Series A' },
    { id: 20, libraryId: 2, seriesName: 'Series B' },
    { id: 30, libraryId: 3, seriesName: 'Series A' },
  ]);
});

test('an invalid selected item blocks the whole multi-delete request', () => {
  assert.deepEqual(resolveSeriesDeleteTargets({
    selectedBooks: [
      { id: 10, libraryId: 2, seriesName: 'Series A' },
      { id: 20, libraryId: null, seriesName: 'Series B' },
    ],
  }), []);
});
