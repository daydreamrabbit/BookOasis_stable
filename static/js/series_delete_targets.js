// 시리즈 데이터 삭제 대상 정규화.
// 다중 선택에 잘못된 항목이 하나라도 섞이면 일부만 조용히 삭제하지 않고 전체 요청을 막는다.
export function resolveSeriesDeleteTargets(context) {
  if (!context || typeof context !== 'object') return [];
  const selectedBooks = Array.isArray(context.selectedBooks) ? context.selectedBooks : [];
  const candidates = selectedBooks.length > 1 ? selectedBooks : [context];
  const targets = [];
  const seen = new Set();

  for (const item of candidates) {
    const id = Number(item?.id);
    const libraryId = Number(item?.libraryId);
    const seriesName = String(item?.seriesName || '').trim();
    if (!Number.isInteger(id) || id <= 0
      || !Number.isInteger(libraryId) || libraryId <= 0
      || !seriesName) {
      return [];
    }

    const key = `${libraryId}\u0000${seriesName}`;
    if (seen.has(key)) continue;
    seen.add(key);
    targets.push({
      id,
      libraryId,
      seriesName,
      title: String(item?.title || '').trim(),
      isVolumeDetail: !!item?.isVolumeDetail,
    });
  }

  return targets;
}
