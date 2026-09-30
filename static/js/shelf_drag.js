// Mouse dragging supplements native touch scrolling. Binding survives row rerenders.
const bound = new WeakSet();
export function bindShelfDrag(row) {
  if (bound.has(row)) return;
  bound.add(row);
  let active = null;
  let suppressClick = false;
  row.addEventListener('dragstart', event => event.preventDefault());
  row.addEventListener('pointerdown', event => {
    if (event.pointerType !== 'mouse' || event.button !== 0) return;
    suppressClick = false;
    active = { id: event.pointerId, x: event.clientX, left: row.scrollLeft, dragging: false };
  });
  row.addEventListener('pointermove', event => {
    if (!active || active.id !== event.pointerId) return;
    if (!(event.buttons & 1)) { finish(); return; }
    const delta = event.clientX - active.x;
    if (!active.dragging && Math.abs(delta) < 6) return;
    if (!active.dragging) {
      active.dragging = true;
      row.setPointerCapture(event.pointerId);
      row.classList.add('is-mouse-dragging');
    }
    event.preventDefault();
    row.scrollLeft = active.left - delta;
  });
  function finish() {
    if (!active) return;
    suppressClick = active.dragging;
    const id = active.id;
    active = null;
    row.classList.remove('is-mouse-dragging');
    if (row.hasPointerCapture(id)) row.releasePointerCapture(id);
  }
  row.addEventListener('pointerup', finish);
  row.addEventListener('pointercancel', finish);
  row.addEventListener('lostpointercapture', finish);
  row.addEventListener('pointerleave', () => { if (active && !active.dragging) finish(); });
  row.addEventListener('click', event => {
    if (!suppressClick) return;
    suppressClick = false;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);
}
