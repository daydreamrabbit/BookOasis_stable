"""Account-scoped reading rankings, without scanning files or the whole library."""
from collections import defaultdict
import re
import database
from repositories.rated_series_page import _dir, _rating_expressions
from repositories.series_metadata_utils import series_cover_id_sql
from services.advanced_search_service import tokens, excluded_terms
from utils.cover_helper import get_cover_image_with_t
from services.content_rating_service import ContentRatingService


def _names(value):
    names = {}
    for name in tokens(value):
        if name.casefold() not in ('-', 'unknown', 'n/a', '미상', '알 수 없음'):
            names.setdefault(name.casefold(), name)
    return list(names.values())


def _rank(counter, limit):
    return sorted(counter.values(), key=lambda item: (-item['count'], item['name'].casefold()))[:limit]


def get_profile_reading_overview(user_id, include_adult=False, content_rating_max=18):
    staff, publishers, genres, works = {}, {}, {}, {}
    # Read shared settings before holding a book connection (also works with pool size 1).
    keywords = ContentRatingService.get_adult_keywords()
    for db_type in ['general'] + (['adult'] if include_adult else []):
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            cursor.execute('''SELECT b.id,b.library_id,b.title,b.series_name,b.series_alias,b.author,
                b.cover_artist,b.publisher,b.genre,b.file_path,b.file_format
                FROM books b JOIN user_progress p ON p.book_id=b.id
                WHERE p.user_id=? AND COALESCE(b.is_deleted,0)=0
                AND (COALESCE(p.pages_read,0)>0 OR COALESCE(p.last_epub_percent,0)>0 OR COALESCE(p.is_completed,0)=1)
                AND EXISTS(SELECT 1 FROM user_category_permissions u WHERE u.user_id=p.user_id
                    AND u.library_id=b.library_id AND u.has_access=1)''', (user_id,))
            # DISTINCT prevents legacy duplicate progress rows counting a volume twice.
            rows = list({row['id']: dict(row) for row in cursor.fetchall()}.values())
            if not rows:
                continue
            scopes = {}
            for row in rows:
                key = (row['library_id'], row['series_name'] or row['title'], _dir(row['file_path'], row['file_format']))
                row['_scope'] = key
                scopes[key] = row
            level, directory, level_params = _rating_expressions(conn, keywords=keywords)
            cover_id = series_cover_id_sql('b', mariadb=database.is_mariadb_mode())
            summaries = {}
            candidates = list(scopes.items())
            # Bound each query to read series only, including their highest-rated volume.
            for offset in range(0, len(candidates), 80):
                predicates, params = [], list(level_params)
                for (library, name, folder), row in candidates[offset:offset+80]:
                    series = 'b.series_name=?' if row['series_name'] else "(COALESCE(b.series_name,'')='' AND b.title=?)"
                    predicates.append(f'(b.library_id=? AND {series} AND ({directory})=?)')
                    params.extend((library, name, folder))
                cursor.execute(f'''SELECT b.library_id,COALESCE(NULLIF(b.series_name,''),b.title) AS series_key,
                    {directory} AS folder,MAX({level}) AS rating,{cover_id} AS cover_id
                    FROM books b WHERE COALESCE(b.is_deleted,0)=0 AND ({' OR '.join(predicates)})
                    GROUP BY b.library_id,COALESCE(NULLIF(b.series_name,''),b.title),{directory}''', params)
                for item in cursor.fetchall():
                    summaries[(item['library_id'], item['series_key'], item['folder'])] = dict(item)
            excluded = excluded_terms(conn, db_type)['genre']
            seen = set()
            for row in rows:
                if row['id'] in seen:
                    continue
                seen.add(row['id'])
                scope = row['_scope']
                summary = summaries.get(scope)
                if not summary or int(summary['rating'] or 0) > int(content_rating_max):
                    continue
                key = (db_type, *scope)
                work = works.setdefault(key, {'name': row['series_alias'] or scope[1], 'series_name': scope[1],
                    'library_id': row['library_id'], 'db_type': db_type, 'id': summary['cover_id'], 'count': 0})
                work['count'] += 1
                writers, artists = _names(row['author']), _names(row['cover_artist'])
                people = {}
                for role, names in [('글', writers), ('그림', artists)]:
                    for name in names:
                        person = people.setdefault(name.casefold(), {'name': name, 'roles': set()})
                        person['roles'].add(role)
                for key_name, person in people.items():
                    item = staff.setdefault(key_name, {'name': person['name'], 'count': 0, 'roles': set(), 'db_type': db_type})
                    item['count'] += 1
                    item['roles'].update(person['roles'])
                for name in _names(row['publisher']):
                    item = publishers.setdefault(name.casefold(), {'name': name, 'count': 0, 'db_type': db_type})
                    item['count'] += 1
                for name in _names(row['genre']):
                    if name.casefold() in excluded:
                        continue
                    item = genres.setdefault(name.casefold(), {'name': name, 'count': 0, 'db_type': db_type})
                    item['count'] += 1
    top_works = _rank(works, 12)
    by_type = defaultdict(list)
    for work in top_works:
        by_type[work['db_type']].append(work)
    for db_type, items in by_type.items():
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            cursor.execute('SELECT id,cover_image,cover_updated_at,file_format,release_date FROM books WHERE id IN (' + ','.join('?' for _ in items) + ')', [item['id'] for item in items])
            covers = {row['id']: dict(row) for row in cursor.fetchall()}
        for item in items:
            cover = covers.get(item['id'], {})
            item['cover_image'] = get_cover_image_with_t(cover.get('cover_image'), cover.get('cover_updated_at'))
            item['file_format'] = cover.get('file_format') or ''
            match = re.search(r'\b(?:19|20)\d{2}\b', str(cover.get('release_date') or ''))
            item['publication_year'] = match.group(0) if match else ''
    total = sum(item['count'] for item in genres.values())
    genre_rows = _rank(genres, 6)
    remainder = total - sum(item['count'] for item in genre_rows)
    if remainder:
        genre_rows.append({'name': '기타', 'count': remainder, 'is_other': True})
    for item in genre_rows:
        item['percent'] = round(item['count'] * 100 / total, 1) if total else 0
    staff_rows = _rank(staff, 12)
    for item in staff_rows:
        item['roles'] = [role for role in ('글', '그림') if role in item['roles']]
    return {'books': top_works, 'staff': staff_rows, 'publishers': _rank(publishers, 12), 'genres': genre_rows,
            'basis': '읽기 시작한 고유 도서 수 · 전체 기간'}
