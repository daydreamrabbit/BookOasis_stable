import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../static/js/genre_tag_filter.js', import.meta.url), 'utf8');
const start = source.indexOf('let filterDataRequestId = 0;');
const end = source.indexOf('// 탭 스위치', start);
const pending = [];
const ctx = vm.createContext({
  state: { currentLibraryType: 'general' }, libraryId: 1,
  genresData: ['old'], tagsData: ['old'], console,
  fetch: url => new Promise(resolve => pending.push({url, resolve})),
  renderChips() {}, renderSelectedChips() {}, normalizeMetadataToken: x => x,
});
vm.runInContext('function getCurrentLibraryIdForFilterOptions() { return libraryId; }', ctx);
vm.runInContext(source.slice(start, end).replace('export async function', 'async function'), ctx);
const first = ctx.loadGenresAndTagsData();
assert.equal(ctx.tagsData.length, 0, 'clear old tags while fetching');
ctx.libraryId = 2;
const second = ctx.loadGenresAndTagsData();
for (const request of pending.slice(2)) request.resolve({json: async()=>({success:true, genres:['new'], tags:['new']})});
await second;
for (const request of pending.slice(0,2)) request.resolve({json: async()=>({success:true, genres:['stale'], tags:['stale']})});
await first;
assert.equal(ctx.tagsData.join(), 'new');
assert.equal(ctx.genresData.join(), 'new');
console.log('PASS: pending refresh clears chips; older library response cannot overwrite current facets');

const scopeContext = vm.createContext({state: {currentLibraryId: 'favorite', detailLibraryId: 99, tagFilterSearchInAll: true}});
vm.runInContext(source.slice(source.indexOf('function getCurrentLibraryIdForFilterOptions()'), source.indexOf('export function refreshFilterCategory')), scopeContext);
for (const category of ['favorite', 'history', 'all', 17, 23]) {
  scopeContext.state.currentLibraryId = category;
  assert.equal(scopeContext.getCurrentLibraryIdForFilterOptions(), category);
}
console.log('PASS: category options ignore previous detail category and global quick-search preference');
