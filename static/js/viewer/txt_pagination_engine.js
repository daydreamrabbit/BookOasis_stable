// Keep exact DOM measurements, but bound both temporary DOM and retained text.
export function createTxtPaginationEngine({ batchSize = 8, maxEntries = 6, maxChars = 6000000,
  yieldControl = () => new Promise(resolve => setTimeout(resolve, 0)) } = {}) {
  const cache = [];
  let retainedChars = 0;
  return async function calculate({ key, chunks, isCurrent, createProbe, readProbe }) {
    if (!isCurrent()) return null;
    const hit = cache.findIndex(entry => entry.key === key && entry.chunks.length === chunks.length
      && entry.chunks.every((text, index) => text === chunks[index]));
    if (hit >= 0) {
      const [entry] = cache.splice(hit, 1);
      cache.push(entry);
      return entry.counts.slice();
    }
    const counts = [];
    for (let start = 0; start < chunks.length; start += batchSize) {
      if (!isCurrent()) return null;
      const probes = [];
      try {
        for (const chunk of chunks.slice(start, start + batchSize)) probes.push(createProbe(chunk));
        // All reads precede removals: don't invalidate layout between probes.
        for (const probe of probes) counts.push(readProbe(probe));
      } finally {
        for (const probe of probes) probe?.remove();
      }
      if (start + batchSize < chunks.length) await yieldControl();
    }
    if (!isCurrent()) return null;
    const chars = chunks.reduce((sum, text) => sum + text.length, 0);
    if (chars <= maxChars) {
      while (cache.length && (cache.length >= maxEntries || retainedChars + chars > maxChars)) {
        retainedChars -= cache.shift().chars;
      }
      cache.push({ key, chunks: chunks.slice(), counts: counts.slice(), chars });
      retainedChars += chars;
    }
    return counts;
  };
}
