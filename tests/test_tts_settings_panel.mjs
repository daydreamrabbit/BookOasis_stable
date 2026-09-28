import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

test('embedded settings close leaves playback host alive and sends close to child', () => {
  const source = fs.readFileSync('static/js/viewer/inline_tts.js', 'utf8');
  const fn = source.slice(source.indexOf('function closeInlineTtsSettings()'), source.indexOf("document.addEventListener('pointerdown'"));
  const removed = [], messages = [];
  const context = vm.createContext({settingsRequested:true,
    showSettingsPanel:open=>assert.equal(open,false),
    host:{classList:{remove:c=>removed.push(c)}},
    document:{getElementById:()=>({classList:{remove:c=>removed.push(c)}})},
    postToPlayer:m=>messages.push(m)});
  vm.runInContext(fn+'\ncloseInlineTtsSettings();',context);
  assert.equal(context.settingsRequested,false);
  assert.deepEqual(removed,['settings-open','viewer-tts-settings-open']);
  assert.equal(messages[0].type,'close-settings');
  assert.ok(context.host);
});

test('settings has explicit close control and mobile panel height limit', () => {
  const html=fs.readFileSync('templates/tts_player.html','utf8');
  const css=fs.readFileSync('static/css/tab_media_library_viewer.css','utf8');
  const player=fs.readFileSync('static/js/tts/tts_player.js','utf8');
  assert.match(html,/id="closeSettingsBtn"/);
  assert.match(player,/\$\('closeSettingsBtn'\)\.onclick = closeSheets/);
  assert.match(css,/max-height: min\(48dvh, calc\(100dvh - 280px\)\)/);
  assert.match(css,/#viewer-tts-settings-panel/);
  assert.doesNotMatch(css,/\.viewer-tts-host\.settings-open\s*\{\s*height: 100dvh/);
});
