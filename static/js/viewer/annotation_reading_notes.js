// annotation_reading_notes.js — 독서노트 목록에서 형광펜/메모를 삭제하는 공통 동작.
// 본문 형광펜 모드의 삭제와 같은 사용자 소유권 API를 사용하며, 책갈피는 다루지 않는다.
import { state } from '../state.js';
import { removeAnnotationLocal } from './annotation_state.js';

function removeRenderedAnnotationMarks(annotationId) {
  const safeId = String(annotationId).replace(/["\\]/g, '\\$&');
  document.querySelectorAll(`mark.annotation-highlight[data-annotation-id="${safeId}"]`).forEach((mark) => {
    const parent = mark.parentNode;
    if (!parent) return;
    while (mark.firstChild) parent.insertBefore(mark.firstChild, mark);
    parent.removeChild(mark);
    parent.normalize();
  });
}

export async function deleteReadingNoteAnnotation(annotation, { confirm = true } = {}) {
  const annotationId = Number(annotation?.id);
  if (!Number.isInteger(annotationId) || annotationId <= 0) return false;

  if (confirm) {
    const note = String(annotation?.note || '').trim();
    const message = note
      ? `이 형광펜과 메모를 삭제할까요?\n메모: ${note}`
      : '이 형광펜을 삭제할까요?';
    if (!window.confirm(message)) return false;
  }

  const dbType = encodeURIComponent(state.currentLibraryType || 'general');
  try {
    const response = await fetch(`/api/v1/annotations/${annotationId}?db_type=${dbType}`, { method: 'DELETE' });
    const data = await response.json().catch(() => null);
    if (!response.ok || !data?.success) {
      window.showToast?.(data?.error || '형광펜 메모 삭제에 실패했습니다.', 'error');
      return false;
    }

    removeAnnotationLocal(annotationId);
    removeRenderedAnnotationMarks(annotationId);
    return true;
  } catch (error) {
    console.error('[Annotation] reading note delete failed', error);
    window.showToast?.('형광펜 메모 삭제 중 오류가 발생했습니다.', 'error');
    return false;
  }
}
