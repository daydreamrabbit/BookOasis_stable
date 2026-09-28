import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync('static/js/viewer.js', 'utf8');
const start = source.indexOf("if (action === 'open-reading-notes')");
const end = source.indexOf("if (action === 'open-viewer-search')", start);
const handler = source.slice(start, end);

for (const format of ['cbz', 'zip', 'imgdir', 'CBZ', 'epub', 'txt']) {
  test(`reading notes click routes ${format} without relying on direction-handler variables`, () => {
    const calls = [];
    const context = vm.createContext({
      state: { currentViewerFormat: format },
      openImageReadingNotesPanel: () => calls.push('image'),
      openEpubTocPanel: tab => calls.push(tab),
    });
    vm.runInContext(`(function(action) { ${handler} })('open-reading-notes')`, context);
    assert.deepEqual(calls, [ ['epub', 'txt'].includes(format) ? 'notes' : 'image' ]);
  });
}
