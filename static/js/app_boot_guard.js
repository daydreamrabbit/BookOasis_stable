// Entry URLs can differ (import maps, plugin imports). All share one boot promise.
export function initializeOnce(key, initialize) {
  if (window[key]) return window[key];
  window[key] = Promise.resolve().then(initialize);
  return window[key];
}
