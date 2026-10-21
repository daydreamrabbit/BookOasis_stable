import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
const source = fs.readFileSync(new URL('../static/js/book_context_menu.js', import.meta.url), 'utf8');
const start = source.indexOf('function finishMenuOpeningTouch(event)');
const end = source.indexOf("document.addEventListener('touchend', finishMenuOpeningTouch", start);
function setup() {
  const ctx = vm.createContext({Date, menuOpeningTouch:{identifier:7}, activeBookMenuTouch:{identifier:7}, menuOpenedByTouchUntil:0,
    suppressBookCardClickUntil:0, clearLongPressTimer() {}});
  vm.runInContext(source.slice(start, end), ctx);
  return ctx;
}
test('opening touch release stays protected even after the old timeout expired', () => {
  const ctx = setup(); let prevented=0, stopped=0;
  ctx.finishMenuOpeningTouch({changedTouches:[{identifier:7}],cancelable:true,
    preventDefault(){prevented++;},stopImmediatePropagation(){stopped++;}});
  assert.equal(ctx.menuOpeningTouch,null);
  assert.ok(ctx.menuOpenedByTouchUntil>Date.now());
  assert.ok(ctx.suppressBookCardClickUntil>Date.now());
  assert.equal(prevented,1);assert.equal(stopped,1);
});
test('other touches and subsequent menu taps are not swallowed', () => {
  const ctx=setup();const event={changedTouches:[{identifier:8}],cancelable:true,
    preventDefault(){assert.fail('menu tap swallowed');},stopImmediatePropagation(){assert.fail('menu tap stopped');}};
  ctx.finishMenuOpeningTouch(event);
  assert.equal(ctx.menuOpeningTouch.identifier,7);
  ctx.menuOpeningTouch=null;ctx.finishMenuOpeningTouch(event);
});
test('non-cancelable cancellation still clears the gesture', () => {
  const ctx=setup();
  ctx.finishMenuOpeningTouch({changedTouches:[{identifier:7}],cancelable:false,
    preventDefault(){assert.fail('not cancelable');},stopImmediatePropagation(){}});
  assert.equal(ctx.menuOpeningTouch,null);
});
