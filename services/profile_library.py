"""Read-only, account-scoped profile lists and charts. No file access or scans."""
from collections import Counter, defaultdict
import hashlib
import json
import re

import database
from repositories.rated_series_page import _dir, _rating_expressions
from repositories.series_metadata_utils import select_series_cover_row, _ordered_volume_rows
from services.content_rating_service import ContentRatingService
from services.advanced_search_service import tokens, excluded_terms
from utils.cover_helper import get_cover_image_with_t
from utils.isbn import normalize_isbn


def _scope(row):
    return (row['library_id'], row.get('series_name') or row['title'],
            _dir(row.get('file_path'), row.get('file_format')))


def _rating(row, export):
    if export['identity'] == 'adult_series':
        raw = json.dumps([int(row['library_id']), str(row.get('series_name') or '')], ensure_ascii=False)
    else:
        title, author = (str(row.get(key) or '').strip() for key in ('series_name', 'author'))
        isbn = normalize_isbn(str(row.get('isbn') or '').strip())
        raw = 'isbn:' + isbn if isbn else ('ta:' + title + '|' + author if author else 't:' + title)
    value = export['ratings'].get(hashlib.sha256(raw.encode()).hexdigest())
    return float(value) if value is not None else None


def profile_library(user_id, include_adult=False, content_rating_max=18, include_ratings=True, include_history=False):
    """Group read/saved works by database, category AND directory, not title alone."""
    keywords = ContentRatingService.get_adult_keywords()
    works, activity = [], []
    rating_error = False
    for db_type in ['general'] + (['adult'] if include_adult else []):
        # Plugin exports may open their own connection; never hold a pool slot here.
        try:
            from services.plugin_rating_sort import ratings
            export = ratings(db_type) if include_ratings else {'identity': 'book_key', 'ratings': {}}
        except Exception:
            export = {'identity': 'book_key', 'ratings': {}}
            rating_error = True
        with database.connection(db_type) as conn:
            cursor = conn.cursor()
            excluded = excluded_terms(conn, db_type)
            level, directory, level_params = _rating_expressions(conn, keywords=keywords)
            # EXISTS avoids multiplication from duplicate favorites/collection/progress rows.
            saved = '''EXISTS(SELECT 1 FROM user_favorites f WHERE f.book_id=b.id AND f.user_id=?)'''
            bookmarked = '''EXISTS(SELECT 1 FROM epub_bookmarks bm WHERE bm.book_id=b.id AND bm.user_id=?)'''
            collected = '''EXISTS(SELECT 1 FROM collection_items ci JOIN collections c ON c.id=ci.collection_id
                WHERE c.user_id=? AND (ci.book_id=b.id OR
                (NULLIF(ci.series_name,'') IS NOT NULL AND ci.series_name=b.series_name)))'''
            cursor.execute(f'''SELECT b.id,b.library_id,b.title,b.series_name,b.file_path,b.file_format
                FROM books b WHERE COALESCE(b.is_deleted,0)=0
                AND EXISTS(SELECT 1 FROM user_category_permissions u WHERE u.user_id=? AND u.library_id=b.library_id AND u.has_access=1)
                AND (EXISTS(SELECT 1 FROM user_progress p WHERE p.book_id=b.id AND p.user_id=?
                    AND (COALESCE(p.pages_read,0)>0 OR COALESCE(p.last_epub_percent,0)>0 OR COALESCE(p.is_completed,0)=1))
                    OR {saved} OR {collected} OR {bookmarked})''', (user_id, user_id, user_id, user_id, user_id))
            seeds = {_scope(dict(row)): dict(row) for row in cursor.fetchall()}
            if include_ratings and export['ratings']:
                from services.plugin_rating_sort import identity_expression
                expression=identity_expression(conn,export['identity'],alias='b')
                keys=list(export['ratings'])
                for offset in range(0,len(keys),300):
                    batch=keys[offset:offset+300]
                    cursor.execute('''SELECT b.id,b.library_id,b.title,b.series_name,b.file_path,b.file_format
                        FROM books b WHERE COALESCE(b.is_deleted,0)=0
                        AND EXISTS(SELECT 1 FROM user_category_permissions u WHERE u.user_id=? AND u.library_id=b.library_id AND u.has_access=1)
                        AND ('''+expression+') IN ('+','.join('?' for _ in batch)+')',[user_id]+batch)
                    seeds.update((_scope(dict(row)),dict(row)) for row in cursor.fetchall())
            grouped = defaultdict(dict)
            candidates = list(seeds.items())
            for offset in range(0, len(candidates), 40):
                predicates, params = [], list(level_params) + [user_id, user_id, user_id, user_id]
                for (library, name, folder), row in candidates[offset:offset+40]:
                    series = 'b.series_name=?' if row['series_name'] else "(COALESCE(b.series_name,'')='' AND b.title=?)"
                    predicates.append(f'(b.library_id=? AND {series} AND ({directory})=?)')
                    params.extend((library, name, folder))
                cursor.execute(f'''SELECT b.id,b.library_id,b.title,b.series_name,b.series_alias,
                    b.author,b.cover_artist,b.publisher,b.genre,b.tags,b.file_path,b.file_format,
                    b.document_volume_index,b.document_number,b.cover_image,b.cover_updated_at,
                    b.release_date,b.total_pages,b.isbn,({level}) AS profile_age,
                    {saved} AS profile_favorite,{collected} AS profile_collected,{bookmarked} AS profile_bookmarked,
                    p.pages_read AS profile_pages,p.last_epub_percent AS profile_percent,
                    p.is_completed AS profile_complete,p.last_read_at AS profile_read_at
                    FROM books b LEFT JOIN user_progress p ON p.book_id=b.id AND p.user_id=?
                    WHERE COALESCE(b.is_deleted,0)=0 AND ({' OR '.join(predicates)})''', params)
                for result in cursor.fetchall():
                    row = dict(result)
                    bucket = grouped[_scope(row)]
                    old = bucket.get(row['id'])
                    if old is None or str(row.get('profile_read_at') or '') > str(old.get('profile_read_at') or ''):
                        bucket[row['id']] = row
            history = defaultdict(dict)
            if include_history:
                ids = []
                for volumes in grouped.values():
                    if max(int(value['profile_age'] or 0) for value in volumes.values()) <= int(content_rating_max):
                        ids.extend(volumes)
                for offset in range(0, len(ids), 400):
                    batch = ids[offset:offset+400]
                    cursor.execute('''SELECT book_id,SUBSTR(CAST(read_date AS CHAR),1,4) AS read_year,
                        SUM(CASE WHEN duration_seconds>0 THEN duration_seconds ELSE 0 END) AS seconds,
                        SUM(CASE WHEN pages_read_delta>0 THEN pages_read_delta ELSE 0 END) AS pages
                        FROM user_reading_log WHERE user_id=? AND book_id IN ('''+','.join('?' for _ in batch)+''')
                        GROUP BY book_id,SUBSTR(CAST(read_date AS CHAR),1,4)''', [user_id]+batch)
                    for entry in cursor.fetchall():
                        year = str(entry['read_year'] or '')
                        if re.fullmatch(r'(?:19|20)\d{2}', year):
                            history[entry['book_id']][year] = dict(seconds=int(entry['seconds'] or 0), pages=int(entry['pages'] or 0))
            for scope, volumes in grouped.items():
                rows = list(volumes.values())
                if max(int(row['profile_age'] or 0) for row in rows) > int(content_rating_max):
                    continue
                cover = select_series_cover_row(rows) or _ordered_volume_rows(rows)[0][2]
                completed = sum(bool(row.get('profile_complete')) for row in rows)
                started = [row for row in rows if row.get('profile_complete') or (row.get('profile_pages') or 0)>0 or (row.get('profile_percent') or 0)>0]
                stars = [_rating(row, export) for row in rows]
                dates = [str(row['profile_read_at']) for row in started if row.get('profile_read_at')]
                genres = sorted({name for row in rows for name in tokens(row.get('genre')) if name.casefold() not in excluded['genre']})
                tags = sorted({name for row in rows for name in tokens(row.get('tags')) if name.casefold() not in excluded['tags']})
                work = dict(id=cover['id'], db_type=db_type, library_id=scope[0], series_name=scope[1],
                    name=cover.get('series_alias') or scope[1],
                    author=next((row['author'] for row in rows if row.get('author')), ''),
                    cover_artist=next((row['cover_artist'] for row in rows if row.get('cover_artist')), ''),
                    publisher=next((row['publisher'] for row in rows if row.get('publisher')), ''), file_format=cover.get('file_format') or '',
                    cover_image=get_cover_image_with_t(cover.get('cover_image'),cover.get('cover_updated_at')),
                    total=len(rows), completed=completed, started=len(started),
                    status='completed' if completed==len(rows) else 'reading' if started else 'planning',
                    rating=max((v for v in stars if v is not None), default=None),
                    favorite=any(row['profile_favorite'] for row in rows),
                    collected=any(row['profile_collected'] for row in rows),
                    bookmarked=any(row['profile_bookmarked'] for row in rows),
                    genres=genres, tags=tags, last_read_at=max(dates, default=''),
                    release_year=next((m.group(0) for _,_,row in _ordered_volume_rows(rows) if (m:=re.search(r'\b(?:19|20)\d{2}\b', str(row.get('release_date') or '')))), ''))
                if include_history:
                    years = defaultdict(lambda: dict(seconds=0,pages=0))
                    for row in rows:
                        entries = history.get(row['id'], {})
                        if not entries and row in started and row.get('profile_read_at'):
                            year = str(row['profile_read_at'])[:4]
                            if re.fullmatch(r'(?:19|20)\d{2}',year):
                                entries = {year:dict(seconds=0,pages=0)}
                        for year, values in entries.items():
                            for key in ('seconds','pages'):
                                years[year][key] += values[key]
                    work['reading_years'] = dict(years)
                    work['duration_seconds'] = sum(value['seconds'] for value in years.values())
                    work['pages_read'] = sum(value['pages'] for value in years.values())
                works.append(work)
                for row in started:
                    if not row.get('profile_read_at'):
                        continue
                    activity.append(dict(id=row['id'], db_type=db_type, library_id=scope[0],series_name=scope[1],
                        name=row['title'], cover_image=get_cover_image_with_t(row.get('cover_image'), row.get('cover_updated_at')),
                        file_format=row.get('file_format') or '', last_read_at=str(row['profile_read_at']),
                        pages_read=row.get('profile_pages') or 0, total_pages=row.get('total_pages') or 0,
                        percent=row.get('profile_percent') or 0, completed=bool(row.get('profile_complete'))))
    return works, sorted(activity,key=lambda row:(row['last_read_at'],row['db_type'],row['id']), reverse=True), rating_error


def profile_charts(works):
    read = [row for row in works if row['started']]
    rated = [row for row in works if row['rating'] is not None]
    relevant = [row for row in works if row['started'] or row['rating'] is not None]
    scores = [row['rating'] for row in rated]
    mean = sum(scores)/len(scores) if scores else None
    def counts(values):
        return [dict(name=str(name), count=count) for name,count in Counter(values).most_common()]
    def distribution(field, source, transform=lambda value:value):
        groups=defaultdict(list)
        for row in source:
            groups[transform(row[field])].append(row)
        result=[]
        for name,rows in groups.items():
            stars=[row['rating'] for row in rows if row['rating'] is not None]
            result.append(dict(name=name,count=len(rows),
                hours=round(sum(row.get('duration_seconds',0) for row in rows)/3600,2),
                mean_score=round(sum(stars)/len(stars),2) if stars else None))
        return sorted(result,key=lambda row:(-row['count'],row['name']))
    release, reading = defaultdict(list), defaultdict(list)
    for row in read:
        if row['release_year']:
            release[row['release_year']].append((row,row.get('duration_seconds',0)))
        years = row.get('reading_years')
        if years is None:
            years = {row['last_read_at'][:4]:dict(seconds=0)} if row['last_read_at'] else {}
        for year, values in years.items():
            reading[year].append((row,values['seconds']))
    def year_metrics(groups):
        result = []
        for year, values in sorted(groups.items()):
            stars = [row['rating'] for row,_ in values if row['rating'] is not None]
            result.append(dict(name=year,titles=len(values),hours=round(sum(seconds for _,seconds in values)/3600,2),
                               mean_score=round(sum(stars)/len(stars),2) if stars else None))
        return result
    def breakdown(field):
        groups=defaultdict(list)
        for row in relevant:
            names=row[field] if field in ('genres','tags') else set(tokens(row['author'])+tokens(row.get('cover_artist')))
            for name in names:
                if str(name).strip().casefold() not in ('','-','unknown','n/a','미상','알 수 없음'):
                    groups[name].append(row)
        result=[]
        for name,rows in groups.items():
            stars=[row['rating'] for row in rows if row['rating'] is not None]
            result.append(dict(name=name,count=len(rows),volumes=sum(row['started'] for row in rows),
                mean_score=round(sum(stars)/len(stars),2) if stars else None,
                covers=[{key:row.get(key,'') for key in ('id','db_type','library_id','series_name','name','cover_image','file_format','release_year')} for row in rows[:6]]))
        return sorted(result,key=lambda row:(-row['count'],row['name']))
    volume_bins=['1','2–6','7–16','17–28','29–55','56+']
    volume_values=Counter('1' if row['total']==1 else '2–6' if row['total']<=6 else '7–16' if row['total']<=16 else '17–28' if row['total']<=28 else '29–55' if row['total']<=55 else '56+' for row in relevant)
    return dict(total=len(works), read=len(read), completed=sum(row['status']=='completed' for row in works),
        rated=len(rated),
        volumes=sum(row['started'] for row in works),
        completed_volumes=sum(row['completed'] for row in works),
        pages_read=sum(row.get('pages_read',0) for row in works),
        duration_seconds=sum(row.get('duration_seconds',0) for row in works),
        average_rating=round(mean,2) if mean is not None else None,
        rating_deviation=round((sum((value-mean)**2 for value in scores)/len(scores))**0.5,2) if scores else None,
        scores=counts(row['rating'] for row in rated),
        volume_counts=[dict(name=name,count=volume_values[name]) for name in volume_bins],
        breakdowns={field:breakdown(field) for field in ('genres','tags','staff')},
        formats=distribution('file_format',read,str.upper),
        statuses=distribution('status',works),
        release_years=counts(row['release_year'] for row in read if row['release_year']),
        read_years=[dict(name=year,count=len(rows)) for year,rows in sorted(reading.items())],
        release_year_metrics=year_metrics(release),reading_year_metrics=year_metrics(reading),
        genres=counts(name for row in read for name in row['genres']),
        tags=counts(name for row in read for name in row['tags']),
        staff=counts(name for row in read for name in set(tokens(row['author'])+tokens(row.get('cover_artist')))),
        publishers=counts(name for row in read for name in tokens(row['publisher'])))
