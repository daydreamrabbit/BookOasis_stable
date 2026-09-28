import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/viewer/control_capabilities.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { getViewerControlCapabilities, normalizeViewerOverlayTab } = await import(moduleUrl);

test('EPUB exposes text controls but hides comic-only controls', () => {
  const controls = getViewerControlCapabilities('epub', 'scroll');
  assert.equal(controls.styleTab, true);
  assert.equal(controls.marginTab, true);
  assert.equal(controls.splitSpread, false);
  assert.equal(controls.readingDirection, false);
  assert.equal(controls.centerGap, false);
  assert.equal(controls.tapZoneDirection, true);
  assert.equal(controls.widthRow, false);
  assert.equal(controls.pageStep, false);
  assert.equal(controls.spreadShift, false);
  assert.equal(controls.annotation, true);
});

test('page-only layout controls are available only while paging', () => {
  const paged = getViewerControlCapabilities('epub', 'page');
  assert.equal(paged.pageStep, true);
  assert.equal(paged.spreadShift, true);
  assert.equal(paged.centerGap, true);
  assert.equal(paged.tapZoneDirection, true);
  assert.equal(getViewerControlCapabilities('cbz', 'scroll').centerGap, false);
  assert.equal(getViewerControlCapabilities('pdf', 'scroll').tapZoneDirection, false);
});

test('image readers expose fit controls and PDF alone exposes manual scroll width', () => {
  assert.equal(getViewerControlCapabilities('cbz', 'page').widthRow, false);
  assert.equal(getViewerControlCapabilities('cbz', 'scroll').widthRow, false);
  assert.equal(getViewerControlCapabilities('pdf', 'scroll').widthRow, true);
  assert.equal(getViewerControlCapabilities('cbz', 'page').comicFit, true);
  assert.equal(getViewerControlCapabilities('zip', 'page').comicFit, true);
  assert.equal(getViewerControlCapabilities('imgdir', 'page').comicFit, true);
  assert.equal(getViewerControlCapabilities('pdf', 'page').comicFit, true);
  assert.equal(getViewerControlCapabilities('epub', 'page').comicFit, false);
  assert.equal(getViewerControlCapabilities('cbz', 'page').splitSpread, false);
  assert.equal(getViewerControlCapabilities('cbz', 'page').annotation, false);
  assert.equal(getViewerControlCapabilities('cbz', 'page').toc, false);
  assert.equal(getViewerControlCapabilities('cbz', 'page').readingNotes, true);
  assert.equal(getViewerControlCapabilities('cbz', 'page').search, false);
  assert.equal(getViewerControlCapabilities('cbz', 'page').bookmark, true);
});

test('hidden format-specific tabs fall back to navigation', () => {
  assert.equal(normalizeViewerOverlayTab('pdf', 'style'), 'nav');
  assert.equal(normalizeViewerOverlayTab('cbz', 'margin'), 'nav');
  assert.equal(normalizeViewerOverlayTab('epub', 'margin'), 'margin');
});
