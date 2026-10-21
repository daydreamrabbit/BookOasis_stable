// Only the same browser tab/account may resume a reader. Never auto-start TTS.
import { state } from '../state.js';
const KEY = 'bookoasis_open_viewer';
const FORMATS = new Set(['zip', 'cbz', 'imgdir', 'pdf', 'txt', 'epub']);
function account() { return String(window.currentUser?.id || window.currentUser?.username || state.currentUser?.id || state.currentUser?.username || ''); }
function write(entry) { try { sessionStorage.setItem(KEY, JSON.stringify(entry)); } catch {} }

export function readOpenViewerSession() {
  try {
    const entry = JSON.parse(sessionStorage.getItem(KEY) || 'null');
    if (!entry || !Number.isSafeInteger(Number(entry.bookId)) || Number(entry.bookId) <= 0
        || !FORMATS.has(entry.format) || !['general', 'adult'].includes(entry.type)
        || entry.account !== account()) return null;
    return entry;
  } catch { return null; }
}

export function rememberOpenViewer(bookId, format, title, pagesRead, totalPages) {
  const previous = readOpenViewerSession();
  const returnHistory = history.state?.view === 'viewer'
    ? previous?.returnHistory : history.state;
  write({ bookId, format, title: String(title || ''), type: state.currentLibraryType,
    libraryId: state.currentLibraryId || 'home', account: account(), returnHistory: returnHistory || null,
    pageIdx: Math.max(0, Number(pagesRead) || 0), totalPages: Math.max(0, Number(totalPages) || 0),
    savedAt: Date.now() });
}

export function updateOpenViewerProgress(data) {
  const entry = readOpenViewerSession();
  if (!entry || String(entry.bookId) !== String(data.book_id) || entry.type !== data.db_type) return;
  write({ ...entry, pageIdx: data.page_idx, totalPages: data.total_pages, savedAt: Date.now() });
}
export function forgetOpenViewer() { try { sessionStorage.removeItem(KEY); } catch {} }
