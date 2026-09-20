export const DASHBOARD_DATA_CACHE_TTL_MS = 60_000;

export function isDashboardDataReusable({
  forceRefresh = false,
  typeSwitched = false,
  historyReady = false,
  recentlyAddedReady = false,
  cached,
  context,
  now = Date.now(),
}) {
  return !forceRefresh
    && !typeSwitched
    && historyReady
    && recentlyAddedReady
    && !!cached
    && cached.context === context
    && now - cached.loadedAt < DASHBOARD_DATA_CACHE_TTL_MS;
}
