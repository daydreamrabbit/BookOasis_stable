// Preserve the public viewer API without loading the reader engines on the home screen.
import { lazyModule } from './utils/lazy_module.js';
export const loadViewer = lazyModule(async () => {
  const [viewer] = await Promise.all([import('./viewer.js?rev=20260927-tts-session-v8'), import('./viewer/viewer_padding.js')]);
  viewer.initKeyboardListener();
  return viewer;
});
const invoke = (name, args) => {
  const viewer = loadViewer.peek();
  return viewer ? viewer[name](...args) : loadViewer().then(module => module[name](...args));
};
let openingGeneration = 0;
export const openReader = (...args) => {
  const generation = ++openingGeneration;
  const viewer = loadViewer.peek();
  if (viewer) return viewer.openReader(...args);
  return loadViewer().then(module => {
    if (generation === openingGeneration) return module.openReader(...args);
  });
};
export const toggleFullscreenViewer = (...args) => invoke('toggleFullscreenViewer', args);
export const setComicFitMode = (...args) => invoke('setComicFitMode', args);
export const changeFontSize = (...args) => invoke('changeFontSize', args);
export const toggleReaderTheme = (...args) => invoke('toggleReaderTheme', args);
export const nextComicPage = (...args) => invoke('nextComicPage', args);
export const nextPage = (...args) => invoke('nextPage', args);
export const prevComicPage = (...args) => invoke('prevComicPage', args);
export const nextPdfPage = (...args) => invoke('nextPdfPage', args);
export const prevPdfPage = (...args) => invoke('prevPdfPage', args);
export const epubPrevPage = (...args) => invoke('epubPrevPage', args);
export const epubNextPage = (...args) => invoke('epubNextPage', args);
export const prevTxtPage = (...args) => invoke('prevTxtPage', args);
export const nextTxtPage = (...args) => invoke('nextTxtPage', args);
export const initKeyboardListener = () => loadViewer.peek()?.initKeyboardListener();
export const closeMediaViewer = (...args) => {
  ++openingGeneration;
  return loadViewer.peek()?.closeMediaViewer(...args);
};
export function flushProgress(...args) {
  if (!loadViewer.peek()) return Promise.resolve(null);
  return import('./viewer_progress.js?rev=20260927-tts-session-v8').then(module => module.flushProgress(...args));
}
