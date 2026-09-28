import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/book_context_read_state.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { shouldOfferMarkAsRead } = await import(moduleUrl);

test('unread detail cards offer mark-as-read', () => {
  assert.equal(shouldOfferMarkAsRead({
    hasProgress: false,
    isMultiSelection: false,
    isVideoLibrary: false,
  }), true);
});

test('missing detail progress is not treated as already read', () => {
  assert.equal(shouldOfferMarkAsRead({
    hasProgress: undefined,
    isMultiSelection: false,
    isVideoLibrary: false,
  }), true);
});

test('books with progress offer reset-to-unread', () => {
  assert.equal(shouldOfferMarkAsRead({
    hasProgress: true,
    isMultiSelection: false,
    isVideoLibrary: false,
  }), false);
});

test('multi-selection keeps the existing reset-to-unread action', () => {
  assert.equal(shouldOfferMarkAsRead({
    hasProgress: false,
    isMultiSelection: true,
    isVideoLibrary: false,
  }), false);
});
