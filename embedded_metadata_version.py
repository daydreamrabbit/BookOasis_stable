# -*- coding: utf-8 -*-
"""Shared version marker for per-file embedded metadata extraction."""

CURRENT_EMBEDDED_METADATA_VERSION = 1
EMBEDDED_METADATA_FORMATS = ('zip', 'cbz', 'epub', 'pdf')
EMBEDDED_METADATA_EXTENSIONS = tuple(f'.{item}' for item in EMBEDDED_METADATA_FORMATS)
