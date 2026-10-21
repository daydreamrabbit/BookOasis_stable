import json
from flask import Blueprint, jsonify, request, session
from api.auth import login_required, check_adult_permission
from services import advanced_search_service as search

advanced_search_bp = Blueprint('advanced_search', __name__)


@advanced_search_bp.route('/api/media/advanced-search/<action>')
@login_required
def advanced_search(action):
    db_type = request.args.get('type', 'general')
    if db_type not in ('general', 'adult') or not check_adult_permission(db_type):
        return jsonify(success=False, error='접근할 수 없는 도서 유형입니다.'), 403
    try:
        raw = request.args.get('filters')
        if raw is None:
            raw = json.dumps({'series': request.args.get('search', ''),
                'genre': [v.strip() for v in request.args.get('genres','').split(',') if v.strip()],
                'tags': [v.strip() for v in request.args.get('tags','').split(',') if v.strip()],
                'genre_mode': request.args.get('filter_mode','and'), 'tags_mode': request.args.get('filter_mode','and')})
        if len(raw) > 16000:
            raise ValueError('검색 조건이 너무 깁니다.')
        filters = search.normalize(json.loads(raw))
        if 'read_filter' in request.args:
            filters['read_filter'] = request.args.get('read_filter') if request.args.get('read_filter') in ('only_read', 'exclude_read') else ''
        user = session['user_id']
        rating = session.get('content_rating_max', 18)
        if action == 'options':
            return jsonify(success=True, options=search.options(db_type, user, rating, filters['categories']))
        limit = max(1, min(200, int(request.args.get('limit', 30))))
        page = max(1, int(request.args.get('page', 1)))
        sort = request.args.get('sort', 'asc')
        include_metadata = request.args.get('include_has_metadata','').lower() in ('1','true','yes')
        if sort not in ('asc', 'desc', 'date_asc', 'date_desc', 'score_desc', 'rating_desc', 'rating_asc'):
            raise ValueError('지원하지 않는 정렬입니다.')
        kw = dict(library_id=request.args.get('library_id', 'all'), limit=limit, sort=sort)
        if action == 'totals':
            return jsonify(success=True, **search.search(db_type, user, rating, filters, totals=True, **kw))
        if action in ('jump', 'selection-range'):
            from services.series_service import _get_initial, _strip_leading_bracket_tags
            rows = search.search(db_type, user, rating, filters, index=True, **kw)
            if action == 'selection-range':
                positions = []
                for side in ('start', 'end'):
                    wanted = (int(request.args[side+'_id']), int(request.args[side+'_library_id']))
                    pos = next((i for i,r in enumerate(rows) if (r['id'],r['library_id']) == wanted), None)
                    if pos is None:
                        raise ValueError('선택한 작품이 검색 결과에 없습니다.')
                    positions.append(pos)
                a,b = sorted(positions)
                return jsonify(success=True, targets=[dict(id=r['id'], libraryId=r['library_id'], title=r['title_alias'] or r['title'], seriesName=r['series_name'], fileFormat=r['file_format'], markUnreadScope='series', isVolumeDetail=False) for r in rows[a:b+1]])
            found = next((i for i,r in enumerate(rows) if _get_initial(_strip_leading_bracket_tags(r['series_name'])) == request.args.get('char')), -1)
            if found < 0:
                return jsonify(success=True, found=False, total=len(rows))
            page = found // limit + 1
            result = search.search(db_type, user, rating, filters, page=page, **kw)
            return jsonify(success=True, found=True, total=len(rows), index=found, page=page, offset_in_page=found % limit, series=search.entries(db_type,result[:limit]), has_more=len(result)>limit)
        if action != 'list':
            return jsonify(success=False, error='Unknown action'), 404
        rows = search.search(db_type, user, rating, filters, page=page, **kw)
        from services.series_service import SeriesService
        return jsonify(success=True, series=SeriesService.annotate_recent_additions(db_type,search.entries(db_type, rows[:limit], include_metadata)), has_more=len(rows)>limit)
    except (ValueError, TypeError, KeyError) as error:
        return jsonify(success=False, error=str(error)), 400
    except Exception:
        from flask import current_app
        current_app.logger.exception('Advanced search failed')
        return jsonify(success=False, error='검색 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.'), 500
