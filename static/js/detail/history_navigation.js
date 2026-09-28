// A browser popstate can require an asynchronous list restore before returning
// to a retained detail. Start that work, then reactivate detail synchronously
// so the intermediate list never gets painted as a separate screen.
export async function restoreBehindDetail(navigate, activateDetail) {
  const pendingNavigation = navigate();
  activateDetail();
  await pendingNavigation;
}

export function matchesRetainedDetailHistory(retained, target) {
  if (!retained?.hasContent || target?.view !== 'detail') return false;

  return String(retained.series || '') === String(target.series || '')
    && (!target.libraryId || String(retained.libraryId || '') === String(target.libraryId))
    && (!target.repBookId || String(retained.representativeBookId || '') === String(target.repBookId))
    && (!target.type || String(retained.libraryType || 'general') === String(target.type));
}
