import ast
import os
from pathlib import Path
import unittest
from unittest.mock import Mock, patch

from utils.process_helper import should_enable_embedded_scanner_worker


class ScannerWorkerModeTests(unittest.TestCase):
    def test_defaults_and_explicit_overrides(self):
        for docker in (True, False):
            for raw, expected in (('', not docker), ('invalid', not docker),
                                  ('true', True), ('1', True), (' YES ', True),
                                  ('on', True), ('false', False), ('0', False),
                                  (' No ', False), ('off', False)):
                with self.subTest(docker=docker, raw=raw), patch.dict(
                        os.environ, {'BOOKOASIS_ENABLE_EMBEDDED_WORKER': raw}), patch(
                        'utils.process_helper.os.path.exists', return_value=docker):
                    self.assertEqual(should_enable_embedded_scanner_worker(), expected)

    def worker_function(self, enabled, running=False, process=None):
        # Extract only the real function: importing core would start app services.
        tree = ast.parse((Path(__file__).resolve().parents[1] / 'core.py').read_text())
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                        and n.name == 'ensure_scanner_worker_running')
        namespace = {'should_enable_embedded_scanner_worker': Mock(return_value=enabled),
                     '_worker_process': process,
                     'is_scanner_worker_running_os': Mock(return_value=running),
                     'start_scanner_worker_process': Mock()}
        exec(compile(ast.Module(body=[function], type_ignores=[]), '<worker-test>', 'exec'), namespace)
        namespace['ensure_scanner_worker_running']()
        return namespace

    def test_disabled_does_not_probe_or_spawn(self):
        process = Mock()
        result = self.worker_function(False, process=process)
        process.poll.assert_not_called()
        result['is_scanner_worker_running_os'].assert_not_called()
        result['start_scanner_worker_process'].assert_not_called()

    def test_enabled_recovers_missing_worker(self):
        result = self.worker_function(True)
        result['start_scanner_worker_process'].assert_called_once_with()

    def test_existing_os_worker_is_not_duplicated(self):
        result = self.worker_function(True, running=True)
        result['start_scanner_worker_process'].assert_not_called()

    def test_existing_child_is_not_duplicated(self):
        process = Mock()
        process.poll.return_value = None
        result = self.worker_function(True, process=process)
        result['is_scanner_worker_running_os'].assert_not_called()
        result['start_scanner_worker_process'].assert_not_called()

    def test_startup_uses_shared_policy(self):
        source = (Path(__file__).resolve().parents[1] / 'core.py').read_text()
        self.assertIn('if should_enable_embedded_scanner_worker() and not is_reloader_parent:', source)
        self.assertNotIn('embedded_worker_raw =', source)
