const MAX_VOLUME_INDEX = 100000;
const MAX_DOCUMENT_NUMBER = 1000000;

function readNumber(value, upperBound) {
  if (value === null || value === undefined || String(value).trim() === '') return null;
  const number = Number(value);
  return Number.isFinite(number) && number >= 0 && number < upperBound ? number : null;
}

function sortNumber(entry) {
  const source = entry?.dataset || entry || {};
  const volumeIndex = readNumber(
    source.documentVolumeIndex ?? source.document_volume_index,
    MAX_VOLUME_INDEX
  );
  if (volumeIndex !== null) return volumeIndex;

  return readNumber(
    source.documentNumber ?? source.document_number,
    MAX_DOCUMENT_NUMBER
  );
}

function sortTitle(entry) {
  const source = entry?.dataset || entry || {};
  return String(source.title ?? entry?.title ?? '');
}

export function compareVolumeOrder(left, right, newestFirst = false) {
  const leftNumber = sortNumber(left);
  const rightNumber = sortNumber(right);
  let comparison = 0;

  if (leftNumber !== null && rightNumber !== null) {
    comparison = leftNumber - rightNumber;
  } else if (leftNumber !== null) {
    comparison = -1;
  } else if (rightNumber !== null) {
    comparison = 1;
  }

  if (comparison === 0) {
    comparison = sortTitle(left).localeCompare(sortTitle(right), 'ko', {
      numeric: true,
      sensitivity: 'base'
    });
  }

  return newestFirst ? -comparison : comparison;
}
