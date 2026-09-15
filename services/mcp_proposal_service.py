# -*- coding: utf-8 -*-
"""
mcp_proposal_service.py – MCP Tier B(대량/파괴적 작업) "제안 → 관리자 승인" 큐.

Tier A(services/mcp_admin_tools_service.py)는 개별/소규모(≤500건) 쓰기를 즉시 실행하지만,
대량 작업은 여기서 mcp_pending_changes 테이블에 제안 레코드만 남기고, 관리자가 설정 화면의
"MCP 승인 대기" 탭에서 검토 후 승인해야 실제로 DB에 반영된다.

중요: approve()/reject()는 관리자가 이미 인증된 웹 세션에서 호출하는 것이므로
MCP_WRITE_ENABLED 게이트와 무관하게 항상 동작한다 - 그 설정은 "MCP 클라이언트가 제안을
만들 수 있는가"만 통제하며, 일단 제안이 만들어진 뒤의 승인/거부는 순수한 관리자 웹 UI
액션이다.
"""
import json

from repositories import McpPendingChangesRepository
from services.mcp_admin_tools_service import McpAdminToolsService, _validate_db_type


class McpProposalService:
    @staticmethod
    def propose_bulk_book_metadata_update(db_type, series_names, library_id, fields):
        """여러 시리즈에 대한 메타데이터 일괄 수정을 제안한다. 즉시 실행하지 않고
        미리보기(diff)를 계산해 mcp_pending_changes에 저장한다."""
        McpAdminToolsService._require_write_enabled()
        db_type = _validate_db_type(db_type)
        if not isinstance(series_names, list) or not series_names:
            raise ValueError('series_names는 비어있지 않은 리스트여야 합니다.')

        McpAdminToolsService._validate_metadata_fields(fields)

        from services.book_detail_service import BookDetailService
        allowed_fields = McpAdminToolsService.METADATA_ALLOWED_FIELDS
        preview = {}
        not_found = []
        for series_name in series_names:
            series_name = str(series_name or '').strip()
            if not series_name:
                continue
            current_meta, current_books = BookDetailService.get_media_detail(db_type, series_name, library_id=library_id)
            if not current_books:
                not_found.append(series_name)
                continue
            before = {k: current_meta.get(k, '') for k in allowed_fields}
            after = dict(before)
            after.update({k: v for k, v in fields.items() if v is not None})
            changed = {k: {'before': before[k], 'after': after[k]} for k in allowed_fields if before[k] != after[k]}
            if changed:
                preview[series_name] = changed

        if not preview:
            raise ValueError('변경될 내용이 없거나(이미 동일한 값) 모든 시리즈를 찾을 수 없습니다: ' + ', '.join(not_found or series_names))

        payload = {'series_names': list(preview.keys()), 'library_id': library_id, 'fields': fields}
        target = f"{len(preview)}개 시리즈"
        change_id = McpPendingChangesRepository.create(
            'bulk_update_book_metadata', db_type, target,
            json.dumps(payload, ensure_ascii=False), json.dumps(preview, ensure_ascii=False),
        )
        McpAdminToolsService._write_audit_log('bulk_update_book_metadata_proposed', db_type, target, {'change_id': change_id, 'preview': preview, 'not_found': not_found})

        return {'success': True, 'change_id': change_id, 'target': target, 'preview': preview, 'not_found': not_found,
                'message': f'제안이 생성되었습니다(변경 ID {change_id}). 관리자가 설정 > MCP 승인 대기에서 검토 후 승인해야 실제로 반영됩니다.'}

    @staticmethod
    def propose_bulk_set_favorite(db_type, book_ids, is_favorite, user_id):
        """대량(500건 초과) 즐겨찾기 일괄 등록/해제를 제안한다."""
        McpAdminToolsService._require_write_enabled()
        db_type = _validate_db_type(db_type)
        if not isinstance(book_ids, list) or not book_ids:
            raise ValueError('book_ids는 비어있지 않은 리스트여야 합니다.')
        book_ids = [int(b) for b in book_ids]

        payload = {'book_ids': book_ids, 'is_favorite': bool(is_favorite), 'user_id': int(user_id or 1)}
        preview = {'book_count': len(book_ids), 'is_favorite': bool(is_favorite)}
        target = f"{len(book_ids)}권"
        change_id = McpPendingChangesRepository.create(
            'bulk_set_favorite', db_type, target,
            json.dumps(payload, ensure_ascii=False), json.dumps(preview, ensure_ascii=False),
        )
        McpAdminToolsService._write_audit_log('bulk_set_favorite_proposed', db_type, target, {'change_id': change_id, 'preview': preview})

        return {'success': True, 'change_id': change_id, 'target': target, 'preview': preview,
                'message': f'제안이 생성되었습니다(변경 ID {change_id}). 관리자가 설정 > MCP 승인 대기에서 검토 후 승인해야 실제로 반영됩니다.'}

    @staticmethod
    def list_pending(status=None):
        rows = McpPendingChangesRepository.list(status=status)
        for row in rows:
            row['payload'] = json.loads(row['payload']) if row.get('payload') else {}
            row['preview'] = json.loads(row['preview']) if row.get('preview') else {}
        return rows

    @staticmethod
    def approve(change_id, admin_user_id):
        row = McpPendingChangesRepository.get(change_id)
        if not row:
            raise ValueError(f'변경 ID {change_id}를 찾을 수 없습니다.')
        if row['status'] != 'pending':
            raise ValueError(f"이미 처리된 제안입니다 (status={row['status']}).")

        payload = json.loads(row['payload'])
        tool_name = row['tool_name']
        db_type = row['db_type']
        results = {}

        if tool_name == 'bulk_update_book_metadata':
            fields = payload['fields']
            # 승인 시점에도 검증을 다시 돌린다 - 제안이 오래 대기하는 동안 정책이 바뀌었을 수 있고,
            # 이 큐에 다른 경로로 잘못된 행이 들어왔을 가능성에 대한 방어심층화이기도 하다.
            McpAdminToolsService._validate_metadata_fields(fields)
            for series_name in payload['series_names']:
                try:
                    changed, success, message = McpAdminToolsService._apply_book_metadata(
                        db_type, series_name, payload.get('library_id', 'all'), fields
                    )
                    results[series_name] = {'success': bool(success), 'changed': changed}
                except Exception as e:
                    results[series_name] = {'success': False, 'error': str(e)}
        elif tool_name == 'bulk_set_favorite':
            from repositories.book_repository import BookRepository
            try:
                BookRepository.update_favorites_bulk(db_type, payload['book_ids'], payload['is_favorite'], payload['user_id'])
                results['book_ids'] = {'success': True, 'count': len(payload['book_ids'])}
            except Exception as e:
                results['book_ids'] = {'success': False, 'error': str(e)}
        else:
            raise ValueError(f"알 수 없는 tool_name입니다: {tool_name}")

        McpPendingChangesRepository.update_status(change_id, 'approved', admin_user_id, None)
        McpAdminToolsService._write_audit_log(f'{tool_name}_approved', db_type, row['target'], {'change_id': change_id, 'results': results, 'decided_by': admin_user_id})

        return {'success': True, 'change_id': change_id, 'results': results}

    @staticmethod
    def reject(change_id, admin_user_id, note=None):
        row = McpPendingChangesRepository.get(change_id)
        if not row:
            raise ValueError(f'변경 ID {change_id}를 찾을 수 없습니다.')
        if row['status'] != 'pending':
            raise ValueError(f"이미 처리된 제안입니다 (status={row['status']}).")

        McpPendingChangesRepository.update_status(change_id, 'rejected', admin_user_id, note)
        McpAdminToolsService._write_audit_log(f"{row['tool_name']}_rejected", row['db_type'], row['target'], {'change_id': change_id, 'decided_by': admin_user_id, 'note': note})

        return {'success': True, 'change_id': change_id}
