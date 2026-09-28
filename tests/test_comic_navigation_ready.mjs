import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/viewer/navigation.js', 'utf8');
function navigation(total) {
  let page = 0;
  const notices = [];
  const ctx = vm.createContext({
    Renderer: { getComicTotalPages: () => total, getComicCurrentPage: () => page,
      setComicCurrentPage: value => { page = value; }, loadComicPage() {} },
    Settings: { getComicPageStep: () => 1 },
    localStorage: { getItem: () => 'page' },
    getSpreadPageIndices: ({ page }) => [page],
    showViewerBoundaryNotice: value => notices.push(value),
  });
  const start = source.indexOf('export function nextComicPage()');
  const end = source.indexOf('\nexport ', source.indexOf('export function moveComicPageByOne'));
  vm.runInContext(source.slice(start, end < 0 ? undefined : end).replaceAll('export function', 'function'), ctx);
  return { call: expression => vm.runInContext(expression, ctx), page: () => page, notices };
}

test('loading or closed comics do not show boundaries or open the next volume', () => {
  const nav = navigation(0);
  for (const action of ['nextComicPage()', 'prevComicPage()', "moveComicPageByOne('next')", "moveComicPageByOne('prev')"]) nav.call(action);
  assert.equal(nav.page(), 0);
  assert.deepEqual(nav.notices, []);
});

test('170-page comic advances from first page with both input paths', () => {
  const nav = navigation(170);
  nav.call('nextComicPage()');
  assert.equal(nav.page(), 1);
  nav.call("moveComicPageByOne('next')");
  assert.equal(nav.page(), 2);
  nav.call('prevComicPage()');
  assert.equal(nav.page(), 1);
  assert.deepEqual(nav.notices, []);
});

test('seek rejects unknown counts and clamps targets to the actual page count', () => {
  let total = 0, page = 0, renders = 0;
  const ctx = vm.createContext({ Renderer: {
    getComicTotalPages: () => total, hideSeekbarTooltip() {},
    setComicCurrentPage: value => { page = value; }, loadComicPage: () => { renders++; },
  }});
  const fn = source.slice(source.indexOf('export function comicSliderChange'), source.indexOf('export function switchViewerOverlayTab')).replace('export ', '');
  vm.runInContext(fn, ctx);
  vm.runInContext('comicSliderChange(null,27)', ctx);
  assert.equal(renders, 0);
  total = 170;
  vm.runInContext('comicSliderChange(null,27)', ctx);
  assert.equal(page, 26);
  vm.runInContext('comicSliderChange(null,999)', ctx);
  assert.equal(page, 169);
  vm.runInContext('comicSliderChange(null,NaN)', ctx);
  assert.equal(renders, 2);
});
