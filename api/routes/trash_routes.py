from flask import Blueprint, request, jsonify
from services.trash_service import TrashService
from api.auth import admin_required

trash_bp = Blueprint('admin_trash', __name__)

@trash_bp.route('/api/admin/trash', methods=['GET'])
@admin_required
def get_trash_books():
    """휴지통 목록 조회 (일반/성인 통합 또는 분리 조회 가능)"""
    try:
        db_type = request.args.get('db_type')
        if db_type:
            if db_type not in ('general','adult','audiobook','video'):
                return jsonify(success=False,error='지원하지 않는 도서 유형입니다.'),400
            raw_id = request.args.get('library_id')
            library_id = int(raw_id) if raw_id is not None else None
            if library_id is not None and library_id <= 0:
                return jsonify(success=False,error='올바른 카테고리가 필요합니다.'),400
            response = jsonify(success=True, **{db_type:TrashService.get_deleted_books(db_type,library_id)})
            response.headers['Cache-Control'] = 'no-store'
            return response
        general_books = TrashService.get_deleted_books('general')
        adult_books = TrashService.get_deleted_books('adult')
        audiobook_books = TrashService.get_deleted_books('audiobook')
        video_books = TrashService.get_deleted_books('video')
        return jsonify({
            'success': True,
            'general': general_books,
            'adult': adult_books,
            'audiobook': audiobook_books,
            'video': video_books
        })
    except ValueError:
        return jsonify(success=False,error='올바른 카테고리가 필요합니다.'),400
    except Exception as e:
        print(f"[API ERROR] Failed to fetch trash books: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trash_bp.route('/api/admin/trash/restore', methods=['POST'])
def restore_trash_books():
    """휴지통 내부 선택 도서 복구"""
    data = request.get_json() or {}
    db_type = data.get('db_type', 'general')
    book_ids = data.get('book_ids', [])
    
    if not book_ids:
        return jsonify({'success': False, 'error': '복구할 도서가 선택되지 않았습니다.'}), 400
        
    try:
        success = TrashService.restore_books(db_type, book_ids)
        if success:
            return jsonify({'success': True, 'message': f'{len(book_ids)}권의 도서가 성공적으로 복구되었습니다.'})
        else:
            return jsonify({'success': False, 'error': '도서 복구 처리에 실패했습니다.'}), 500
    except Exception as e:
        print(f"[API ERROR] Failed to restore books: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@trash_bp.route('/api/admin/trash/empty', methods=['POST'])
def empty_trash_books():
    """휴지통 비우기 (일괄 또는 선택 영구 삭제)"""
    data = request.get_json() or {}
    db_type = data.get('db_type', 'general')
    library_id = data.get('library_id')
    book_ids = data.get('book_ids') # 선택 삭제용
    
    try:
        success = TrashService.empty_trash(db_type, library_id=library_id, book_ids=book_ids)
        if success:
            cnt = len(book_ids) if book_ids else '선택한 모든'
            return jsonify({'success': True, 'message': f'휴지통에서 {cnt} 도서가 영구 삭제되었습니다.'})
        else:
            return jsonify({'success': False, 'error': '휴지통 비우기 처리에 실패했습니다.'}), 500
    except Exception as e:
        print(f"[API ERROR] Failed to empty trash: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500
