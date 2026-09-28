function clampPage(page, totalPages) {
  const total = Math.max(0, Number(totalPages) || 0);
  if (total === 0) return 0;
  return Math.max(0, Math.min(Math.trunc(Number(page) || 0), total - 1));
}

export function getSpreadAnchor(page, totalPages, coverAlone = false) {
  const safePage = clampPage(page, totalPages);
  if (!coverAlone) return Math.floor(safePage / 2) * 2;
  if (safePage === 0) return 0;
  return 1 + Math.floor((safePage - 1) / 2) * 2;
}

export function getSpreadPageIndices({
  page,
  totalPages,
  twoPage = false,
  coverAlone = false,
  readingDirection = 'ltr',
} = {}) {
  return getSpreadPageSlots({ page, totalPages, twoPage, coverAlone, readingDirection })
    .filter(index => index !== null);
}

export function getSpreadPageSlots({
  page,
  totalPages,
  twoPage = false,
  coverAlone = false,
  readingDirection = 'ltr',
} = {}) {
  const total = Math.max(0, Number(totalPages) || 0);
  if (total === 0) return [];
  if (!twoPage) return [clampPage(page, total)];

  const anchor = getSpreadAnchor(page, total, coverAlone);
  const slots = coverAlone && anchor === 0
    ? [null, 0]
    : [anchor, anchor + 1 < total ? anchor + 1 : null];
  return readingDirection === 'rtl' ? slots.reverse() : slots;
}

export function getAdjacentSpreadPage({
  page,
  totalPages,
  direction,
  coverAlone = false,
} = {}) {
  const total = Math.max(0, Number(totalPages) || 0);
  if (total === 0) return null;

  const anchor = getSpreadAnchor(page, total, coverAlone);
  if (direction === 'next') {
    const next = coverAlone && anchor === 0 ? 1 : anchor + 2;
    return next < total ? next : null;
  }

  if (anchor === 0) return null;
  if (coverAlone && anchor === 1) return 0;
  return Math.max(0, anchor - 2);
}
