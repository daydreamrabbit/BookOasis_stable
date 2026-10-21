import { getViewerDisplayMode } from './display_mode.js';
import { getTapDirection } from './tap_direction.js';

export function resolveSeekbarDirection(mode, tapDirection = 'horizontal') {
  if (mode === 'two-one') return 'rtl';
  if (mode === 'one' && tapDirection === 'horizontal-reverse') return 'rtl';
  return 'ltr';
}

export function getSeekbarDirection() {
  // The open reader owns its layout. localStorage is shared by other tabs and
  // may already describe the next/default reader rather than the visible one.
  const modal = document.getElementById('media-viewer-modal');
  const mode = modal?.dataset.displayMode || getViewerDisplayMode();
  const selectedTap = modal?.querySelector('[data-tap-zone-direction][aria-pressed="true"]');
  const tapDirection = selectedTap?.dataset.tapZoneDirection || getTapDirection().direction;
  return resolveSeekbarDirection(mode, tapDirection);
}

export function seekbarVisualRatio(ratio, direction = getSeekbarDirection()) {
  const clamped = Math.max(0, Math.min(1, ratio));
  return direction === 'rtl' ? 1 - clamped : clamped;
}

export function syncSeekbarDirection() {
  const direction = getSeekbarDirection();
  const slider = document.getElementById('viewer-page-slider');
  const footer = slider?.closest('.overlay-footer');
  if (footer) footer.dataset.seekDirection = direction;
  if (slider) slider.dir = direction;
  return direction;
}
