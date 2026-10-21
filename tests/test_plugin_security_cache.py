import os
import tempfile
import unittest
from unittest.mock import patch

from services import metadata_factory as factory


class PluginSecurityCacheTests(unittest.TestCase):
    def setUp(self):
        factory._cached_forbidden_calls.cache_clear()
        self.addCleanup(factory._cached_forbidden_calls.cache_clear)

    def test_identical_content_reuses_analysis(self):
        with patch.object(factory, '_find_forbidden_calls_in_source', return_value=[]) as scan:
            factory._cached_forbidden_calls('plugin.py', 'x = 1')
            factory._cached_forbidden_calls('plugin.py', 'x = 1')
            self.assertEqual(scan.call_count, 1)

    def test_changed_content_is_rechecked_and_policy_not_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'plugin.py')
            with open(path, 'w') as stream:
                stream.write('x = 1\n')
            factory._scan_plugin_for_forbidden_subprocess_usage(directory)
            with open(path, 'w') as stream:
                stream.write('import subprocess\n')
            with patch.dict(os.environ, {'ALLOW_PLUGIN_SUBPROCESS': 'true'}), patch.object(factory, '_log_plugin_subprocess_allowed'):
                factory._scan_plugin_for_forbidden_subprocess_usage(directory)
            with patch.dict(os.environ, {'ALLOW_PLUGIN_SUBPROCESS': 'false'}):
                with self.assertRaises(factory.SecurityError):
                    factory._scan_plugin_for_forbidden_subprocess_usage(directory)

    def test_cache_is_bounded(self):
        self.assertEqual(factory._cached_forbidden_calls.cache_info().maxsize, 512)
