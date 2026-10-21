// Natural image dimensions, not the fitted on-screen height, determine spreads.
const imageSizes = new Map();
const MAX_IMAGE_SIZES = 512;

export function rememberEpubImageSize(image, src = image?.getAttribute?.('src')) {
  const width = Number(image?.naturalWidth), height = Number(image?.naturalHeight);
  if (!src || !(width > 0 && height > 0)) return;
  const previous = imageSizes.get(src);
  if (previous?.width === width && previous?.height === height) return;
  imageSizes.delete(src);
  imageSizes.set(src, { width, height });
  if (imageSizes.size > MAX_IMAGE_SIZES) imageSizes.delete(imageSizes.keys().next().value);
  document.dispatchEvent(new CustomEvent('epub-image-dimensions-ready'));
}

export function getEpubImages(html) {
  if (typeof html !== 'string' || !html.includes('<img')) return [];
  const probe = document.createElement('div');
  probe.innerHTML = html;
  const images = Array.from(probe.querySelectorAll('img'));
  return probe.textContent.trim() ? [] : images;
}

function imageKind(image) {
  const size = imageSizes.get(image.getAttribute('src'));
  const width = size?.width || Number(image.getAttribute('width'));
  const height = size?.height || Number(image.getAttribute('height'));
  if (!(width > 0 && height > 0)) return 'unknown';
  return width > height ? 'wide' : 'portrait';
}

export function getEpubImageLayout(html) {
  const images = getEpubImages(html);
  if (!images.length) return 'text';
  return images.length > 1 ? 'sequence' : imageKind(images[0]);
}

// Preserve canonical spine indices; several illustrations can belong to one
// chapter. Sheets paginate those images without inventing server chapter IDs.
export function getEpubImageSheets(html, pageStep = 2) {
  const images = getEpubImages(html), sheets = [];
  for (let index = 0; index < images.length;) {
    const first = index, kind = imageKind(images[index]);
    index++;
    if (pageStep === 2 && kind === 'portrait' && images[index] && imageKind(images[index]) === 'portrait') index++;
    sheets.push({ first: first + 1, last: index, images: images.slice(first, index), wide: kind !== 'portrait' });
  }
  return sheets;
}

export function epubImageSheetSignature(sheets) {
  return sheets.map(sheet => `${sheet.first}-${sheet.last}:${sheet.wide ? 'w' : 'p'}`).join(',');
}

export function resolveEpubImageSpread(chunks, index, { coverAlone = false, pairAnchor = null, kindOf = getEpubImageLayout } = {}) {
  const kind = kindOf(chunks[index]);
  if (kind !== 'portrait') return { start: index, span: 1, wide: kind === 'wide' || kind === 'unknown' };
  // A wide illustration or a text chapter ends the preceding portrait run.
  // Restart pairing after it; global even/odd chapter arithmetic skips/repeats leaves.
  let runStart = index;
  while (runStart > 0 && kindOf(chunks[runStart - 1]) === 'portrait') runStart--;
  let origin = runStart;
  if (pairAnchor !== null && pairAnchor >= runStart) {
    let end = index;
    while (kindOf(chunks[end + 1]) === 'portrait') end++;
    if (pairAnchor <= end) origin += (pairAnchor - runStart) % 2;
  } else if (coverAlone && runStart === 0) origin = 1;
  if (index < origin) return { start: index, span: 1, wide: false };
  const start = origin + Math.floor((index - origin) / 2) * 2;
  return { start, span: kindOf(chunks[start + 1]) === 'portrait' ? 2 : 1, wide: false };
}
