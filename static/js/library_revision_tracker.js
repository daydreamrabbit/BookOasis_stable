// Remember changes even while another category, a hidden tab or the reader is open.
export function createRevisionTracker() {
  const seen = new Map();
  const pending = new Set();
  return {
    observe(revisions) {
      for (const [type, revision] of Object.entries(revisions)) {
        if (seen.has(type) && seen.get(type) !== revision) pending.add(type);
        seen.set(type, revision);
      }
    },
    has(type) { return pending.has(type); },
    revision(type) { return seen.get(type); },
    acknowledge(type, revision = seen.get(type)) {
      if (seen.get(type) === revision) pending.delete(type);
    },
  };
}
