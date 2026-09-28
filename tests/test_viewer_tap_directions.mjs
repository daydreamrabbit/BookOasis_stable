import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs/promises';

const code = await fs.readFile(new URL('../static/js/viewer/tap_direction.js', import.meta.url), 'utf8');
const { getTapDirection, normalizeTapDirection } = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`);
for (const [direction, vertical, reverse] of [
  ['horizontal', false, false], ['horizontal-reverse', false, true],
  ['vertical', true, false], ['vertical-reverse', true, true],
]) {
  test(`tap direction ${direction} preserves axis and next-page side`, () => {
    const config = getTapDirection(direction);
    assert.equal(config.vertical, vertical);
    assert.equal(config.reverse, reverse);
    assert.equal(normalizeTapDirection(direction), direction);
  });
}
test('unset or invalid direction defaults to right-side next page', () => {
  for (const value of [null, undefined, '', 'rtl', 'invalid']) assert.equal(normalizeTapDirection(value), 'horizontal');
});
