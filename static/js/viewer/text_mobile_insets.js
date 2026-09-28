// Reserve the same reading area whether the overlay controls are shown or hidden.
// offsetHeight is unaffected by the toolbar's hide/show transform.
export function applyMobileTextInsets(wrapper, content, storage) {
  if (window.innerWidth > 768 || !wrapper || !content) return false;
  const modal = document.getElementById('media-viewer-modal');
  const header = modal?.querySelector('.ridi-viewer-toolbar-top');
  const footer = modal?.querySelector('.ridi-viewer-toolbar-bottom');
  const bottomInset = footer ? parseFloat(getComputedStyle(footer).bottom) || 0 : 0;
  const setting = (key, fallback) => Math.max(0, parseInt(storage.getItem(key) ?? fallback, 10) || 0);
  // Padding settings are minimum insets, not extra space on top of the bars.
  const top = Math.max(header?.offsetHeight || 48, setting('viewer_padding_top', 40));
  const bottom = Math.max((footer?.offsetHeight || 58) + bottomInset, setting('viewer_padding_bottom', 60));
  wrapper.style.marginTop = `${top}px`;
  wrapper.style.marginBottom = `${bottom}px`;
  // Use the containing viewer, not 100vh (which can include mobile browser UI).
  wrapper.style.height = `calc(100% - ${top + bottom}px)`;
  content.style.paddingTop = '0';
  content.style.paddingBottom = '0';
  return true;
}
