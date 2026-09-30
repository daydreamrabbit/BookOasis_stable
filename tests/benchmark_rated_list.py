"""Read-only comparison. Run in separate processes; optional argument 'legacy'."""
import hashlib
import json
import resource
import sys
import time
from services.series_service import SeriesService, rated_series_page

if len(sys.argv) > 1 and sys.argv[1] == 'legacy':
    rated_series_page.supported = lambda *a, **kw: False
started = time.perf_counter()
before = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
pages = []
for page in (1,2,3):
    entries = SeriesService.get_books_list('general',19,page,30,'',user_id=1,role='admin',content_rating_max=18)
    pages.append([(e['representative_book_id'],e['book_count'],e['series_key'],e['cover_image']) for e in entries])
totals=SeriesService.get_books_totals('general',19,user_id=1,role='admin',content_rating_max=18)
print(json.dumps({'mode':sys.argv[1:] or ['sql'], 'seconds':round(time.perf_counter()-started,3),
                  'peak_rss_mib':round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,1),
                  'peak_increase_mib':round((resource.getrusage(resource.RUSAGE_SELF).ru_maxrss-before)/1024,1),
                  'pages_digest':hashlib.sha256(json.dumps(pages,sort_keys=True).encode()).hexdigest(),
                  'totals':totals}, default=str))
