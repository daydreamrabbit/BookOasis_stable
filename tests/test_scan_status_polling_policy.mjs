import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const source = await readFile(new URL('../static/js/scan_status_polling_policy.js', import.meta.url), 'utf8');
const moduleUrl = `data:text/javascript;base64,${Buffer.from(source).toString('base64')}`;
const { evaluateScanPollingState } = await import(moduleUrl);

test('queued scans keep polling during the worker visibility grace period', () => {
  const state = evaluateScanPollingState({
    isActive: false,
    pollingStartedAt: 1000,
    now: 5000,
    consecutiveIdlePolls: 1,
    graceMs: 8000,
  });
  assert.equal(state.shouldStop, false);
  assert.equal(state.consecutiveIdlePolls, 2);
});

test('polling continues while a scan is active', () => {
  const state = evaluateScanPollingState({
    isActive: true,
    pollingStartedAt: 1000,
    now: 12000,
    consecutiveIdlePolls: 4,
  });
  assert.deepEqual(state, {
    observedActive: true,
    consecutiveIdlePolls: 0,
    shouldStop: false,
  });
});

test('polling stops as soon as an observed scan finishes', () => {
  const state = evaluateScanPollingState({
    isActive: false,
    observedActive: true,
    pollingStartedAt: 1000,
    now: 5000,
  });
  assert.equal(state.shouldStop, true);
});

test('a queue request that never becomes visible stops after grace and two idle polls', () => {
  const state = evaluateScanPollingState({
    isActive: false,
    pollingStartedAt: 1000,
    now: 10000,
    consecutiveIdlePolls: 1,
    graceMs: 8000,
  });
  assert.equal(state.shouldStop, true);
});
