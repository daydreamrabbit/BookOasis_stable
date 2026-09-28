// Device choices survive book changes and late account-default responses.
export function restoreViewerPreferences(settings, storage = localStorage) {
  const fields = {
    VIEWER_FONT_SIZE: ['viewer_font_size', v => (Number(v)/16).toFixed(2), v => String(Math.round(Number(v)*16))],
    VIEWER_FONT_FAMILY: ['viewer_font_family', v => v === 'sans-serif' ? 'pretendard' : v === 'serif' ? 'batang' : v],
    VIEWER_THEME: ['viewer_theme'],
    VIEWER_LINE_HEIGHT: ['viewer_line_height'],
    VIEWER_PARAGRAPH_SPACING: ['viewer_paragraph_spacing'],
  };
  const effective = {};
  for (const [key, [localKey, fromServer = String, toServer = String]] of Object.entries(fields)) {
    if (storage.getItem(localKey) === null && settings[key] != null && settings[key] !== '') {
      storage.setItem(localKey, fromServer(settings[key]));
    }
    const saved = storage.getItem(localKey);
    if (saved !== null) effective[key] = toServer(saved);
  }
  return effective;
}
