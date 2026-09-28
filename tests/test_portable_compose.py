import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class PortableComposeTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('docker'), 'Docker CLI is required')
    def test_public_defaults_without_operator_env_or_override(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copyfile(ROOT / 'docker-compose.yml', root / 'docker-compose.yml')
            shutil.copyfile(ROOT / '.env.example', root / '.env')
            result = subprocess.run(
                ['docker', 'compose', 'config', '--format', 'json'],
                cwd=root, env={'PATH': os.environ['PATH'], 'HOME': os.environ.get('HOME', '')},
                check=True, capture_output=True, text=True, timeout=30,
            )
            services = json.loads(result.stdout)['services']
            self.assertEqual(set(services), {'bookoasis', 'bookoasis-volume-check', 'redis'})
            app = services['bookoasis']
            self.assertEqual(app['environment']['DB_ENGINE'], 'sqlite')
            self.assertEqual(app['environment']['PGID'], '1000')
            self.assertFalse(app.get('devices'))
            self.assertEqual(app['volumes'], services['bookoasis-volume-check']['volumes'])
            for volume in app['volumes']:
                self.assertTrue(Path(volume['source']).is_relative_to(root))
                self.assertFalse(volume['bind']['create_host_path'])

    def test_operator_files_are_excluded_from_git_and_build(self):
        gitignore = (ROOT / '.gitignore').read_text().splitlines()
        dockerignore = (ROOT / '.dockerignore').read_text().splitlines()
        for path in ['.env', 'docker-compose.override.yml', 'rclone/', 'books/', 'comics/']:
            self.assertIn(path, gitignore)
            self.assertIn(path, dockerignore)


if __name__ == '__main__':
    unittest.main()
