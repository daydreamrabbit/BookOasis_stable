"""Read explicit comic page counts without opening the archive."""
import re


def filename_page_count(path, file_format=None):
    # Drive virtual paths append ?gid=...; # is a literal filename marker,
    # not a URL fragment. Do not parse/unquote away that marker.
    name = str(path or '').split('?gid=', 1)[0].replace('\\', '/').rsplit('/', 1)[-1]
    match = re.search(r'#([0-9]{1,7})\.(zip|cbz)$', name, re.IGNORECASE)
    if not match or (file_format and str(file_format).lower() not in ('zip', 'cbz')):
        return 0
    count = int(match.group(1))
    return count if 0 < count <= 1000000 else 0


def with_filename_page_counts(rows):
    """Scanner insert tuples: path at 6, format at 7, page count at 8."""
    result = []
    for row in rows:
        values = list(row)
        if not values[8] or values[8] == 1:
            values[8] = filename_page_count(values[6], values[7]) or values[8]
        result.append(tuple(values))
    return result
