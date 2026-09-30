# -*- coding: utf-8 -*-
"""Shared version markers for per-file embedded metadata extraction."""

# Version 2 covers the existing embedded metadata fields. Version 3 adds a
# one-time ComicInfo rating correction. Version 4 imports ComicInfo Translator.
LEGACY_EMBEDDED_METADATA_VERSION = 2
COMICINFO_RATING_METADATA_VERSION = 3
COMICINFO_TRANSLATOR_METADATA_VERSION = 4
CURRENT_EMBEDDED_METADATA_VERSION = COMICINFO_TRANSLATOR_METADATA_VERSION
EMBEDDED_METADATA_FORMATS = ('zip', 'cbz', 'epub', 'pdf')
EMBEDDED_METADATA_EXTENSIONS = tuple(f'.{item}' for item in EMBEDDED_METADATA_FORMATS)


def needs_comicinfo_rating_refresh(books_lv):
    """Return whether an old CBZ rating needs checking against its own ComicInfo."""
    value = str(books_lv or '').strip().casefold()
    return value in {
        '', 'adult only', 'adultonly', 'adults only', 'adultsonly',
        'adult only 18+', 'adultsonly18+', 'adults only 18+',
        'adultsonly18+', 'porn', 'pornography', '포르노',
    }


def is_embedded_metadata_outdated(file_path, metadata_version, books_lv='', translator=''):
    """Check old extraction rows and one-time ComicInfo rating/translator repairs."""
    path = str(file_path or '').lower()
    if not path.endswith(EMBEDDED_METADATA_EXTENSIONS):
        return False
    try:
        version = int(metadata_version or 0)
    except (TypeError, ValueError):
        version = 0
    if version < LEGACY_EMBEDDED_METADATA_VERSION:
        return True
    is_comicinfo = path.endswith(('.cbz', '.zip'))
    return (
        is_comicinfo
        and version < COMICINFO_RATING_METADATA_VERSION
        and needs_comicinfo_rating_refresh(books_lv)
    ) or (
        is_comicinfo
        and version < COMICINFO_TRANSLATOR_METADATA_VERSION
        and not str(translator or '').strip()
    )
