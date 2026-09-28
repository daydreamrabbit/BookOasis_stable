import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const helperSource = await readFile(new URL('../static/js/dashboard_cache.js', import.meta.url), 'utf8');
const helperUrl = `data:text/javascript;base64,${Buffer.from(helperSource).toString('base64')}`;
const { isDashboardDataReusable, shouldLoadDashboardLayout } = await import(helperUrl);

const freshCache = { context: 'general:classic', loadedAt: 10_000 };

test('reuses the rendered dashboard during a quick return to Home', () => {
  assert.equal(isDashboardDataReusable({
    historyReady: true,
    recentlyAddedReady: true,
    cached: freshCache,
    context: 'general:classic',
    now: 20_000,
  }), true);
});

test('forces refresh after relevant changes or a library-type switch', () => {
  assert.equal(isDashboardDataReusable({
    forceRefresh: true,
    historyReady: true,
    recentlyAddedReady: true,
    cached: freshCache,
    context: 'general:classic',
    now: 20_000,
  }), false);
  assert.equal(isDashboardDataReusable({
    typeSwitched: true,
    historyReady: true,
    recentlyAddedReady: true,
    cached: freshCache,
    context: 'general:classic',
    now: 20_000,
  }), false);
});

test('does not reuse stale, incomplete, or differently configured dashboard data', () => {
  const args = {
    historyReady: true,
    recentlyAddedReady: true,
    cached: freshCache,
    context: 'general:classic',
    now: 70_001,
  };
  assert.equal(isDashboardDataReusable(args), false);
  assert.equal(isDashboardDataReusable({ ...args, now: 20_000, recentlyAddedReady: false }), false);
  assert.equal(isDashboardDataReusable({ ...args, now: 20_000, context: 'general:plugin-layout' }), false);
});

test('reloads the shared widget DOM when returning from another media type', () => {
  assert.equal(shouldLoadDashboardLayout({
    targetType: 'general',
    renderedType: 'video',
    expectedMode: 'plugin',
    cachedMode: 'plugin',
  }), true);
});

test('reuses a layout only while its media type and mode are still rendered', () => {
  assert.equal(shouldLoadDashboardLayout({
    targetType: 'adult',
    renderedType: 'adult',
    expectedMode: 'plugin',
    cachedMode: 'plugin',
  }), false);
  assert.equal(shouldLoadDashboardLayout({
    targetType: 'adult',
    renderedType: 'adult',
    expectedMode: 'classic',
    cachedMode: 'plugin',
  }), true);
});

test('restores the correct layout through book, audiobook, video, and back transitions', () => {
  let renderedType = 'general';
  for (const targetType of ['adult', 'audiobook', 'video', 'adult', 'general']) {
    assert.equal(shouldLoadDashboardLayout({
      targetType,
      renderedType,
      expectedMode: 'plugin',
      cachedMode: 'plugin',
    }), true, `${renderedType} -> ${targetType} must restore that type's layout`);
    renderedType = targetType;
  }
});
