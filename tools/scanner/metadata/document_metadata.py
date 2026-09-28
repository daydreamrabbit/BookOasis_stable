# -*- coding: utf-8 -*-
"""Read book metadata embedded in EPUB OPF and PDF Info/XMP dictionaries."""
import os
import posixpath
import re
import threading
import zipfile
import xml.etree.ElementTree as ET

from . import clean_html_tags, normalize_metadata_list_field


_CONTAINER_NS = 'urn:oasis:names:tc:opendocument:xmlns:container'
_DC_NS = 'http://purl.org/dc/elements/1.1/'
_OPF_NS = 'http://www.idpf.org/2007/opf'
_RDF_NS = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#'
_CALIBRE_NS = 'http://calibre-ebook.com/xmp-namespace'
_CALIBRE_SERIES_INDEX_NS = 'http://calibre-ebook.com/xmp-namespace-series-index'
_REMOTE_TIMEOUT_SECONDS = 15
_MAX_XMP_BYTES = 8 * 1024 * 1024
_METADATA_FIELDS = (
    'title', 'author', 'cover_artist', 'isbn', 'publisher', 'summary',
    'release_date', 'genre', 'tags', 'link', 'localized_series',
    'publication_status',
    'document_series_name', 'document_volume_index', 'document_volume_count',
)
_SERIES_NAME_KEYS = ('calibre:series', 'series', 'comicinfo:series')
_SERIES_INDEX_KEYS = (
    'calibre:series_index', 'calibre:series-index', 'series_index',
    'series-index', 'volume', 'volume_number', 'volume-number',
    'comicinfo:volume', 'comic-info:volume',
)
_SERIES_COUNT_KEYS = (
    'calibre:series_count', 'calibre:series-count', 'calibre:series_total',
    'calibre:series-total', 'series_count', 'series-count', 'series_total',
    'series-total', 'collection_count', 'collection-count', 'comicinfo:count',
    'comic-info:count', 'comic-book-butler:count',
)


def _local_name(tag):
    return tag.rsplit('}', 1)[-1].lower()


def _text(element):
    if element is None:
        return ''
    return ''.join(element.itertext()).strip()


def _unique_names(values):
    result = []
    seen = set()
    for value in values:
        value = re.sub(r'\s+', ' ', str(value or '')).strip()
        key = value.casefold()
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return ', '.join(result)


def _normalize_date(value):
    match = re.match(r'^\s*(\d{4})(?:[-/.](\d{1,2})(?:[-/.](\d{1,2}))?)?', value or '')
    if not match:
        return ''
    year, month, day = match.groups()
    month = int(month or 1)
    day = int(day or 1)
    if month < 1 or month > 12 or day < 1 or day > 31:
        return ''
    return f'{year}-{month:02d}-{day:02d}'


def _valid_isbn(value):
    compact = re.sub(r'[^0-9X]', '', str(value or '').upper())
    if len(compact) == 10:
        return sum((10 - i) * (10 if char == 'X' else int(char))
                   for i, char in enumerate(compact)) % 11 == 0
    if len(compact) == 13 and compact.isdigit():
        check = sum(int(char) * (1 if i % 2 == 0 else 3)
                    for i, char in enumerate(compact[:12]))
        return (10 - check % 10) % 10 == int(compact[-1])
    return False


def _isbn_from_text(value, explicitly_isbn=False):
    value = str(value or '').strip()
    match = re.search(r'(?:urn:isbn:|isbn(?:-1[03])?\s*:?\s*)([0-9Xx -]+)', value, re.IGNORECASE)
    if match:
        candidate = match.group(1)
    elif re.fullmatch(r'[0-9Xx -]+', value):
        candidate = value
    elif explicitly_isbn:
        candidate = value
    else:
        return ''
    compact = re.sub(r'[^0-9X]', '', candidate.upper())
    return compact if _valid_isbn(compact) else ''


def _metadata_value(element):
    return str(element.get('content') or _text(element) or '').strip()


def _parse_volume_number(value):
    match = re.match(r'^\s*(\d+(?:\.\d+)?)', str(value or ''))
    if not match:
        return None
    try:
        number = float(match.group(1))
    except (TypeError, ValueError, OverflowError):
        return None
    return number if number > 0 and number < float('inf') else None


def _parse_volume_count(value):
    match = re.match(r'^\s*(\d+)\s*$', str(value or ''))
    if not match:
        return None
    try:
        count = int(match.group(1))
    except (TypeError, ValueError, OverflowError):
        return None
    return count if count > 0 else None


def parse_epub_opf_metadata(opf):
    """Extract supported metadata from an already parsed EPUB package document."""
    metadata = {}
    package_metadata = next((e for e in opf.iter() if _local_name(e.tag) == 'metadata'), None)
    if package_metadata is None:
        return metadata

    def dc_values(name):
        return [_text(e) for e in package_metadata.iter()
                if e.tag == f'{{{_DC_NS}}}{name}' and _text(e)]

    titles = dc_values('title')
    if titles:
        metadata['title'] = titles[0]

    role_by_id = {}
    identifier_types = set()
    named_metadata = {}
    collection_types = {}
    collection_positions = {}
    collection_counts = {}
    for element in package_metadata.iter():
        if _local_name(element.tag) != 'meta':
            continue
        prop = element.get('property', '').lower()
        refines = element.get('refines', '').lstrip('#')
        value = _text(element).lower()
        name = element.get('name', '').strip().lower()
        if name:
            named_metadata[name] = _metadata_value(element)
        if prop == 'role' and refines:
            role_by_id[refines] = value
        elif prop == 'identifier-type' and refines:
            identifier_types.add(refines)
        elif prop == 'collection-type' and refines:
            collection_types[refines] = value
        elif prop == 'group-position' and refines:
            collection_positions[refines] = _metadata_value(element)
        elif prop in ('collection-count', 'group-count') and refines:
            collection_counts[refines] = _metadata_value(element)

    for key in _SERIES_NAME_KEYS:
        value = named_metadata.get(key)
        if value:
            metadata['document_series_name'] = re.sub(r'\s+', ' ', value).strip()
            break

    collection_elements = [
        element for element in package_metadata.iter()
        if _local_name(element.tag) == 'meta'
        and element.get('property', '').lower() == 'belongs-to-collection'
        and _metadata_value(element)
    ]
    if collection_elements:
        series_collection = next(
            (element for element in collection_elements
             if collection_types.get(element.get('id', ''), '') == 'series'),
            collection_elements[0],
        )
        collection_id = series_collection.get('id', '')
        metadata.setdefault('document_series_name', _metadata_value(series_collection))
        if collection_id:
            collection_index = collection_positions.get(collection_id)
            if collection_index:
                metadata.setdefault('document_volume_index', _parse_volume_number(collection_index))
            collection_count = collection_counts.get(collection_id)
            if collection_count:
                metadata.setdefault('document_volume_count', _parse_volume_count(collection_count))

    for key in _SERIES_INDEX_KEYS:
        value = named_metadata.get(key)
        if value:
            volume_index = _parse_volume_number(value)
            if volume_index is not None:
                metadata['document_volume_index'] = volume_index
                break

    for key in _SERIES_COUNT_KEYS:
        value = named_metadata.get(key)
        if value:
            volume_count = _parse_volume_count(value)
            if volume_count is not None:
                metadata['document_volume_count'] = volume_count
                break

    creators = [e for e in package_metadata.iter()
                if e.tag == f'{{{_DC_NS}}}creator' and _text(e)]
    authors, artists, unclassified = [], [], []
    has_creator_roles = False
    for creator in creators:
        creator_id = creator.get('id', '')
        role = (creator.get(f'{{{_OPF_NS}}}role')
                or creator.get('role')
                or role_by_id.get(creator_id, '')).lower()
        name = _text(creator)
        if role:
            has_creator_roles = True
        if role in ('aut', 'author', 'cre'):
            authors.append(name)
        elif role in ('art', 'ill', 'cov'):
            artists.append(name)
        elif not role:
            unclassified.append(name)

    if authors:
        metadata['author'] = _unique_names(authors)
    elif not has_creator_roles:
        metadata['author'] = _unique_names(unclassified or [_text(e) for e in creators])
    if artists:
        metadata['cover_artist'] = _unique_names(artists)

    for key, values in (
        ('publisher', dc_values('publisher')),
        ('summary', dc_values('description')),
    ):
        if values:
            value = _unique_names(values) if key == 'publisher' else '\n'.join(values)
            metadata[key] = clean_html_tags(value) if key == 'summary' else value

    subjects = dc_values('subject')
    if subjects:
        metadata['genre'] = normalize_metadata_list_field(', '.join(subjects))

    dates = dc_values('date')
    dates.extend(_text(e) for e in package_metadata.iter()
                 if _local_name(e.tag) == 'issued' and _text(e))
    dates.extend(_metadata_value(e) for e in package_metadata.iter()
                 if _local_name(e.tag) == 'meta'
                 and e.get('property', '').lower() == 'dcterms:issued'
                 and _metadata_value(e))
    for value in dates:
        release_date = _normalize_date(value)
        if release_date:
            metadata['release_date'] = release_date
            break

    for identifier in (e for e in package_metadata.iter()
                       if e.tag == f'{{{_DC_NS}}}identifier'):
        scheme = identifier.get(f'{{{_OPF_NS}}}scheme', '').lower()
        explicitly_isbn = 'isbn' in scheme or identifier.get('id', '') in identifier_types
        isbn = _isbn_from_text(_text(identifier), explicitly_isbn)
        if isbn:
            metadata['isbn'] = isbn
            break
    return metadata


def _parse_epub(file_path):
    with zipfile.ZipFile(file_path, 'r') as epub:
        container = ET.fromstring(epub.read('META-INF/container.xml'))
        rootfile = container.find(f'.//{{{_CONTAINER_NS}}}rootfile')
        if rootfile is None:
            rootfile = next((e for e in container.iter() if _local_name(e.tag) == 'rootfile'), None)
        opf_path = (rootfile.get('full-path') if rootfile is not None else '')
        opf_path = posixpath.normpath(opf_path.lstrip('/'))
        if not opf_path or opf_path == '..' or opf_path.startswith('../'):
            return {}
        return parse_epub_opf_metadata(ET.fromstring(epub.read(opf_path)))


def _namespace(tag):
    if isinstance(tag, str) and tag.startswith('{') and '}' in tag:
        return tag[1:].split('}', 1)[0]
    return ''


def _xmp_property_values(root, local_names, namespace=None):
    """Read scalar or rdf container values for matching XMP properties."""
    names = {str(name).casefold() for name in local_names}
    values = []
    for element in root.iter():
        if _local_name(element.tag).casefold() not in names:
            continue
        if namespace is not None and _namespace(element.tag) != namespace:
            continue
        items = [
            _text(child) for child in element.iter()
            if child is not element
            and _namespace(child.tag) == _RDF_NS
            and _local_name(child.tag) == 'li'
            and _text(child)
        ]
        if items:
            values.extend(items)
        else:
            value = _text(element)
            if value:
                values.append(value)
    return values


def _xmp_explicit_values(root, local_names):
    """Read explicitly named custom XMP elements or attributes."""
    names = {str(name).casefold() for name in local_names}
    values = _xmp_property_values(root, names)
    for element in root.iter():
        for attribute, raw_value in element.attrib.items():
            if _local_name(attribute).casefold() in names and str(raw_value or '').strip():
                values.append(str(raw_value).strip())
    return values


def _first_xmp_value(root, local_names, namespace=None):
    values = _xmp_property_values(root, local_names, namespace=namespace)
    return values[0] if values else ''


def _xmp_attribute(root, namespace, local_name):
    key = f'{{{namespace}}}{local_name}'
    for element in root.iter():
        value = str(element.get(key) or '').strip()
        if value:
            return value
    return ''


def parse_pdf_xmp_metadata(xmp_data):
    """Extract BookOasis fields from a decoded PDF XMP metadata stream.

    Explicit Genre and Tags properties are independent. ``dc:subject`` is a
    backwards-compatible Genre fallback only, so subject values are no longer
    silently converted into Tags when a producer starts writing both fields.
    """
    if not xmp_data:
        return {}
    if isinstance(xmp_data, str):
        xmp_data = xmp_data.encode('utf-8')
    if not isinstance(xmp_data, (bytes, bytearray)) or len(xmp_data) > _MAX_XMP_BYTES:
        return {}
    try:
        root = ET.fromstring(bytes(xmp_data))
    except (ET.ParseError, ValueError, TypeError):
        return {}

    metadata = {}
    title = _first_xmp_value(root, ('title',), namespace=_DC_NS)
    if title:
        metadata['title'] = title

    creators = _xmp_property_values(root, ('creator',), namespace=_DC_NS)
    if creators:
        metadata['author'] = _unique_names(creators)

    descriptions = _xmp_property_values(root, ('description',), namespace=_DC_NS)
    if descriptions:
        metadata['summary'] = clean_html_tags('\n'.join(descriptions))

    publishers = _xmp_property_values(root, ('publisher',), namespace=_DC_NS)
    if publishers:
        metadata['publisher'] = _unique_names(publishers)

    explicit_genres = _xmp_explicit_values(root, ('genre', 'genres'))
    explicit_tags = _xmp_explicit_values(root, ('tag', 'tags'))
    subjects = _xmp_property_values(root, ('subject',), namespace=_DC_NS)
    if explicit_genres:
        metadata['genre'] = normalize_metadata_list_field(', '.join(explicit_genres))
    elif subjects:
        metadata['genre'] = normalize_metadata_list_field(', '.join(subjects))
    if explicit_tags:
        metadata['tags'] = normalize_metadata_list_field(', '.join(explicit_tags))

    dates = _xmp_property_values(root, ('date',), namespace=_DC_NS)
    dates.extend(_xmp_explicit_values(root, ('publicationdate', 'releasedate', 'issued')))
    for value in dates:
        release_date = _normalize_date(value)
        if release_date:
            metadata['release_date'] = release_date
            break

    identifiers = _xmp_property_values(root, ('identifier',), namespace=_DC_NS)
    identifiers.extend(_xmp_explicit_values(root, ('isbn', 'isbn10', 'isbn13')))
    for value in identifiers:
        isbn = _isbn_from_text(value, explicitly_isbn=True)
        if isbn:
            metadata['isbn'] = isbn
            break

    series_name = _xmp_attribute(root, _CALIBRE_NS, 'series')
    if not series_name:
        series_elements = [
            element for element in root.iter()
            if _namespace(element.tag) == _CALIBRE_NS
            and _local_name(element.tag) == 'series'
        ]
        for element in series_elements:
            value_element = next(
                (child for child in element.iter()
                 if _namespace(child.tag) == _RDF_NS and _local_name(child.tag) == 'value'),
                None,
            )
            series_name = _text(value_element) or _text(element)
            if series_name:
                break
    if not series_name:
        values = _xmp_explicit_values(root, ('seriesname', 'documentseriesname'))
        series_name = values[0] if values else ''
    if series_name:
        metadata['document_series_name'] = re.sub(r'\s+', ' ', series_name).strip()

    volume_index = _xmp_attribute(root, _CALIBRE_SERIES_INDEX_NS, 'series_index')
    if not volume_index:
        values = _xmp_explicit_values(root, ('series_index', 'seriesindex', 'volume', 'volumeindex'))
        volume_index = values[0] if values else ''
    parsed_volume_index = _parse_volume_number(volume_index)
    if parsed_volume_index is not None:
        metadata['document_volume_index'] = parsed_volume_index

    count_values = _xmp_explicit_values(root, ('count', 'seriescount', 'series_count', 'volumecount'))
    for value in count_values:
        volume_count = _parse_volume_count(value)
        if volume_count is not None:
            metadata['document_volume_count'] = volume_count
            break

    localized_values = _xmp_explicit_values(root, ('localizedseries', 'localized_series'))
    if localized_values:
        metadata['localized_series'] = re.sub(r'\s+', ' ', localized_values[0]).strip()

    artist_values = _xmp_explicit_values(root, ('coverartist', 'cover_artist', 'penciller', 'artist'))
    if artist_values:
        metadata['cover_artist'] = _unique_names(artist_values)

    status_values = _xmp_explicit_values(root, ('publicationstatus', 'publication_status'))
    if status_values:
        metadata['publication_status'] = status_values[0].strip()

    link_values = _xmp_explicit_values(root, ('weburls', 'weburl', 'links', 'link'))
    if link_values:
        metadata['link'] = '\n'.join(dict.fromkeys(value.strip() for value in link_values if value.strip()))
    return metadata


def _parse_pdf_xmp_file(file_path):
    """Decode the catalog Metadata stream with pypdf, including Flate streams."""
    try:
        from pypdf import PdfReader

        reader = PdfReader(file_path, strict=False)
        catalog = reader.trailer.get('/Root')
        if hasattr(catalog, 'get_object'):
            catalog = catalog.get_object()
        metadata_stream = catalog.get('/Metadata') if catalog else None
        if hasattr(metadata_stream, 'get_object'):
            metadata_stream = metadata_stream.get_object()
        if metadata_stream is None or not hasattr(metadata_stream, 'get_data'):
            return {}
        return parse_pdf_xmp_metadata(metadata_stream.get_data())
    except Exception as error:
        print(f'[Scanner-Document] PDF XMP read failed ({os.path.basename(file_path)}): {error}')
        return {}


def parse_pdf_document_metadata(pdf, xmp_metadata=None):
    """Extract embedded fields from PDF Info and decoded XMP metadata."""
    info = pdf.get_metadata_dict() or {}
    metadata = {}
    title = str(info.get('Title') or '').strip()
    if title:
        metadata['title'] = title
    for key, field in (('Author', 'author'), ('Subject', 'summary')):
        value = str(info.get(key) or '').strip()
        if value:
            metadata[field] = clean_html_tags(value)

    keywords = str(info.get('Keywords') or '').strip()
    if keywords:
        metadata['tags'] = normalize_metadata_list_field(keywords)
        isbn = _isbn_from_text(keywords)
        if isbn:
            metadata['isbn'] = isbn
    for field, value in (xmp_metadata or {}).items():
        if value not in (None, ''):
            metadata[field] = value
    return metadata


def _parse_pdf(file_path):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(file_path)
    try:
        return parse_pdf_document_metadata(pdf, _parse_pdf_xmp_file(file_path))
    finally:
        pdf.close()


def _parse_local(file_path, file_format):
    if file_format == 'epub':
        return _parse_epub(file_path)
    if file_format == 'pdf':
        return _parse_pdf(file_path)
    return {}


def parse_embedded_metadata(file_path, file_format, is_remote=False, status_out=None):
    """Extract supported embedded fields, bounding reads from mounted remote files."""
    file_format = str(file_format or '').lower()
    if isinstance(status_out, dict):
        status_out['parsed'] = False
    if not file_path or file_format not in ('epub', 'pdf'):
        return {}

    if not is_remote:
        try:
            parsed = _parse_local(file_path, file_format)
            if isinstance(status_out, dict):
                status_out['parsed'] = True
            return parsed
        except Exception as error:
            print(f'[Scanner-Document] {file_format.upper()} metadata read failed ({os.path.basename(file_path)}): {error}')
            return {}

    result = []

    def parse_remote():
        try:
            result.append(_parse_local(file_path, file_format))
        except Exception as error:
            result.append(error)

    worker = threading.Thread(target=parse_remote, daemon=True)
    worker.start()
    worker.join(_REMOTE_TIMEOUT_SECONDS)
    if worker.is_alive():
        print(f'[Scanner-Document] {file_format.upper()} metadata read timed out ({_REMOTE_TIMEOUT_SECONDS}s): {os.path.basename(file_path)}')
        return {}
    if not result:
        return {}
    if isinstance(result[0], Exception):
        print(f'[Scanner-Document] {file_format.upper()} metadata read failed ({os.path.basename(file_path)}): {result[0]}')
        return {}
    if isinstance(status_out, dict):
        status_out['parsed'] = True
    return result[0]


def merge_embedded_metadata(target, embedded):
    """Fill blank folder metadata fields from the current EPUB/PDF document."""
    if not isinstance(target, dict) or not isinstance(embedded, dict):
        return target
    for field in _METADATA_FIELDS:
        value = embedded.get(field)
        if field in ('genre', 'tags'):
            value = normalize_metadata_list_field(value)
        if value and not target.get(field):
            target[field] = value
    return target
