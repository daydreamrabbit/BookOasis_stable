export const TAP_DIRECTIONS = ['horizontal', 'horizontal-reverse', 'vertical', 'vertical-reverse'];

export function normalizeTapDirection(value) {
  return TAP_DIRECTIONS.includes(value) ? value : 'horizontal';
}

export function getTapDirection(value = localStorage.getItem('viewer_tap_zone_direction')) {
  const direction = normalizeTapDirection(value);
  return {
    direction,
    vertical: direction.startsWith('vertical'),
    reverse: direction.endsWith('-reverse'),
    label: { horizontal: '좌→우', 'horizontal-reverse': '우→좌', vertical: '상→하', 'vertical-reverse': '하→상' }[direction],
  };
}
