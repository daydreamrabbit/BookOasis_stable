import assert from 'node:assert/strict';

globalThis.localStorage = { getItem: () => null, setItem: () => {} };
globalThis.window = {};
const {
  isGeneralAdultRatingValue,
  isPornRatingValue,
  resolveContentRatingLabel,
} = await import('../static/js/detail/header_view.js');

assert.equal(resolveContentRatingLabel(19), '성인망가');
assert.equal(resolveContentRatingLabel(20), '포르노');
assert.equal(resolveContentRatingLabel(12), '등급 확인 필요');
assert.equal(isPornRatingValue('adult only'), false);
assert.equal(isGeneralAdultRatingValue('adult only'), true);
assert.equal(isPornRatingValue('adult only 18+'), true);
assert.equal(isGeneralAdultRatingValue('m'), false);

console.log('PASS general adult and explicit porn ratings stay distinct in the detail editor');
