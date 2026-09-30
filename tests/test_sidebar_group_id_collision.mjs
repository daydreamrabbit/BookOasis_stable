import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/category_indicator.js', import.meta.url), 'utf8');
const { updateCurrentCategoryIndicator } = await import(
  `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`
);

function makeItem({ id, categoryId, name, type }) {
  const classes = new Set();
  const attributes = {};
  if (id != null) attributes['data-id'] = String(id);
  if (categoryId != null) attributes['data-category-id'] = String(categoryId);
  if (name) attributes['data-name'] = name;
  return {
    dataset: { id: String(id ?? ''), categoryId: String(categoryId ?? ''), name, type },
    textContent: name || '',
    getAttribute(key) { return attributes[key] ?? null; },
    classList: {
      toggle(key, enabled) { if (enabled) classes.add(key); else classes.delete(key); },
      contains(key) { return classes.has(key); },
    },
  };
}

test('a matching library ID does not activate a group header with the same numeric ID', () => {
  const webtoonGroup = makeItem({ id: 2, name: '웹툰', type: 'group' });
  const mangaLibrary = makeItem({ id: 2, categoryId: 2, name: '[만화] 연재', type: 'custom' });
  const items = [webtoonGroup, mangaLibrary];
  const indicator = { textContent: '', title: '' };
  globalThis.document = {
    getElementById: (id) => id === 'current-category-indicator' ? indicator : null,
    querySelectorAll: (selector) => selector === '#sidebar-categories .menu-item' ? items : [],
  };

  updateCurrentCategoryIndicator(2);

  assert.equal(webtoonGroup.classList.contains('active'), false);
  assert.equal(mangaLibrary.classList.contains('active'), true);
  assert.equal(indicator.textContent, '[만화] 연재');
});
