import unittest
from unittest.mock import patch
import yaml
from tools.scanner.metadata.kavita_yaml import (
    parse_kavita_yaml, _normalize_misaligned_sequence_siblings,
)


class KavitaMultilineRecoveryTests(unittest.TestCase):
    def test_broken_search_preserves_cover_and_full_description(self):
        raw = """files:
    book.zip:
        cover: COVER
meta:
    Summary: 'First paragraph.

        Second paragraph.

        Last paragraph.'
search:
    - Day: '10'
    Month: '07'
    description: 'First paragraph.

        Second paragraph.

        Last paragraph.'
    title: Example
    score: 100
""".replace('COVER', 'A' * 104)
        with patch('tools.scanner.metadata.kavita_yaml.read_file_with_timeout', return_value=raw):
            result = parse_kavita_yaml('/fixture', files=['kavita.yaml'])
        self.assertIn('Last paragraph.', result['summary'])
        self.assertFalse(result['summary'].startswith("'"))
        self.assertEqual(result['cover_b64_map'], {'book.zip': 'A' * 104})
        self.assertEqual(result['score'], 100)
        self.assertEqual(result['parser_warnings'], [])

    def test_valid_nested_sequence_and_multiline_are_unchanged(self):
        raw = "search:\n    - title: Book\n      description: |\n        first\n\n        last\n      tags:\n        - tag\nmeta:\n    Summary: Good\n"
        repaired, changed = _normalize_misaligned_sequence_siblings(raw)
        self.assertFalse(changed)
        self.assertEqual(yaml.safe_load(repaired), yaml.safe_load(raw))

    def test_multiple_items_and_following_root_stay_separate(self):
        raw = "search:\n    - title: One\n    description: |\n        first\n\n        last\n    score: 1\n    - title: Two\n    score: 2\nmeta:\n    Summary: Kept\n"
        repaired, changed = _normalize_misaligned_sequence_siblings(raw)
        self.assertTrue(changed)
        result = yaml.safe_load(repaired)
        self.assertEqual(len(result['search']), 2)
        self.assertEqual(result['search'][1]['score'], 2)
        self.assertIn('last', result['search'][0]['description'])
        self.assertEqual(result['meta']['Summary'], 'Kept')
