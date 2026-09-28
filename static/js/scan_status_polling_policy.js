export function evaluateScanPollingState({
  isActive,
  observedActive = false,
  consecutiveIdlePolls = 0,
  pollingStartedAt = 0,
  now = Date.now(),
  graceMs = 8000,
}) {
  if (isActive) {
    return {
      observedActive: true,
      consecutiveIdlePolls: 0,
      shouldStop: false,
    };
  }

  const nextIdlePolls = consecutiveIdlePolls + 1;
  const graceExpired = now - pollingStartedAt >= graceMs;
  return {
    observedActive,
    consecutiveIdlePolls: nextIdlePolls,
    shouldStop: observedActive || (graceExpired && nextIdlePolls >= 2),
  };
}
