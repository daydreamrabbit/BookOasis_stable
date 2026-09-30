const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('static/js/detail/index.js', 'utf8');
const start = source.indexOf('    const detailViewPluginId =');
const end = source.indexOf('    const data = await api.fetchMediaDetail', start);
const setup = source.slice(start, end);
(async () => {
  for (const id of [123, null]) {
    let resolveBundle;
    let calls = 0;
    const context = {
      state: {currentLibraryType: 'general', detailViewProviders: {general: 'rabbit_plugins'}},
      representativeBookId: id, requestSerial: 1, detailRequestSerial: 1,
      URLSearchParams, AbortSignal, console,
      api: {fetchPluginDetailUiBundle: () => new Promise(resolve => {resolveBundle = resolve;})},
      fetch: async () => {calls++; return {ok: true, json: async () => ({success: true})};},
    };
    vm.createContext(context);
    const task = vm.runInContext('(async () => {' + setup + '\nreturn preparedPromise;})()', context);
    resolveBundle({success: true, bundle: {initial_data_mode: 'files'}});
    const result = await task;
    assert.equal(calls, id ? 1 : 0);
    if (id) assert.equal(result.bookId, String(id));
  }
  console.log('PASS metadata starts before awaiting core detail; missing ID skips speculative request');
})().catch(error => {console.error(error); process.exitCode = 1;});
