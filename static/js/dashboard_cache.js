export const DASHBOARD_DATA_CACHE_TTL_MS = 60_000;

export function shouldLoadDashboardLayout({
  targetType,
  renderedType,
  expectedMode,
  cachedMode,
}) {
  // #home-widget-stack is a single shared DOM tree. Knowing that a type's mode was
  // loaded earlier is not enough: another type may since have replaced its widgets.
  return renderedType !== targetType || cachedMode !== expectedMode;
}

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
