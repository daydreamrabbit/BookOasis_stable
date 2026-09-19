// Category modules call back into the library entrypoint without importing it.
// Importing tab_media_library.js from its own dependency graph creates a second,
// query-less ES module instance when the entrypoint URL is cache-busted.
let selectCategoryHandler = null;

export function setSelectCategoryHandler(handler) {
  selectCategoryHandler = typeof handler === 'function' ? handler : null;
}

export function selectCategory(...args) {
  const handler = selectCategoryHandler
    || (typeof window !== 'undefined' ? window.selectCategory : null);
  if (typeof handler !== 'function') {
    console.error('[CategoryNavigation] selectCategory handler is not registered');
    return false;
  }
  return handler(...args);
}
