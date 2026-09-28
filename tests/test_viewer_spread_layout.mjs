import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/viewer/spread_layout.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { getSpreadPageIndices, getSpreadPageSlots, getAdjacentSpreadPage } = await import(moduleUrl);

test('regular two-page mode groups pages in stable pairs', () => {
  assert.deepEqual(getSpreadPageIndices({ page: 0, totalPages: 6, twoPage: true }), [0, 1]);
  assert.deepEqual(getSpreadPageIndices({ page: 1, totalPages: 6, twoPage: true }), [0, 1]);
  assert.deepEqual(getSpreadPageIndices({ page: 5, totalPages: 6, twoPage: true }), [4, 5]);
});

test('cover-alone mode keeps cover and then groups following pages', () => {
  assert.deepEqual(getSpreadPageIndices({ page: 0, totalPages: 6, twoPage: true, coverAlone: true }), [0]);
  assert.deepEqual(getSpreadPageIndices({ page: 1, totalPages: 6, twoPage: true, coverAlone: true }), [1, 2]);
  assert.deepEqual(getSpreadPageIndices({ page: 5, totalPages: 6, twoPage: true, coverAlone: true }), [5]);
});

test('cover-alone navigation never skips the cover or repeats the last spread', () => {
  assert.equal(getAdjacentSpreadPage({ page: 0, totalPages: 6, direction: 'next', coverAlone: true }), 1);
  assert.equal(getAdjacentSpreadPage({ page: 1, totalPages: 6, direction: 'prev', coverAlone: true }), 0);
  assert.equal(getAdjacentSpreadPage({ page: 5, totalPages: 6, direction: 'next', coverAlone: true }), null);
  assert.equal(getAdjacentSpreadPage({ page: 5, totalPages: 6, direction: 'prev', coverAlone: true }), 3);
});

test('rtl changes visual order without changing spread membership', () => {
  assert.deepEqual(getSpreadPageIndices({
    page: 1,
    totalPages: 6,
    twoPage: true,
    coverAlone: true,
    readingDirection: 'rtl',
  }), [2, 1]);
});

test('spread slots retain blank leaves for cover and odd endings', () => {
  assert.deepEqual(getSpreadPageSlots({ page: 0, totalPages: 6, twoPage: true, coverAlone: true }), [null, 0]);
  assert.deepEqual(getSpreadPageSlots({ page: 5, totalPages: 6, twoPage: true, coverAlone: true }), [5, null]);
  assert.deepEqual(getSpreadPageSlots({ page: 4, totalPages: 5, twoPage: true }), [4, null]);
});
