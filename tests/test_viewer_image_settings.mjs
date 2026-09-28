import test from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';

const template = await readFile(new URL('../templates/components/media_viewer.html', import.meta.url), 'utf8');
const settings = await readFile(new URL('../static/js/viewer/reader_settings.js', import.meta.url), 'utf8');
const renderer = await readFile(new URL('../static/js/viewer/renderer.js', import.meta.url), 'utf8');
const css = await readFile(new URL('../static/css/tab_media_library_viewer.css', import.meta.url), 'utf8');
const navigation = await readFile(new URL('../static/js/viewer/navigation.js', import.meta.url), 'utf8');

test('image viewer settings expose only width and height fit modes without mixing text controls', () => {
  for (const mode of ['width', 'height']) {
    assert.match(template, new RegExp(`data-comic-fit-mode="${mode}"`));
  }
  assert.doesNotMatch(template, /data-comic-fit-mode="(?:original|contain)"/);
  assert.match(settings, /VALID_FIT_MODES = new Set\(\['width', 'height'\]\)/);
  assert.match(template, /ridi-text-setting/);
  assert.match(template, /id="ridi-image-settings" hidden/);
  assert.match(css, /fit-width \.comic-page-pair\.single-page img[\s\S]*max-height: none !important;[\s\S]*height: auto !important;/);
  assert.match(css, /align-items: safe center/);
  assert.match(css, /data-display-mode="one-two"[\s\S]*#ridi-image-settings/);
});

test('horizontal and vertical tap choices show a temporary zone preview', () => {
  assert.match(template, /id="ridi-page-direction-settings" hidden/);
  assert.match(template, /data-tap-zone-direction="horizontal"/);
  assert.match(template, /data-tap-zone-direction="vertical"/);
  assert.match(navigation, /pageDirectionSettings\.hidden = !capabilities\.tapZoneDirection/);
  assert.match(settings, /classList\.add\('tap-zone-preview'\)/);
  assert.match(settings, /1200/);
  assert.match(css, /\.comic-hotspot-layer\.tap-zone-preview/);
});
