import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('github_release_builder', Path(__file__).resolve().parents[1] / 'packaging/build_github_release.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class ReleaseAssetsTests(unittest.TestCase):
    def make_bundle(self, directory, extras=None, config=None):
        path = Path(directory) / 'windows.zip'
        exe = b'MZtest-executable'
        files = {'WorkshopTranslator/WorkshopTranslator.exe': exe,
                 'WorkshopTranslator/SHA256SUMS.txt': hashlib.sha256(exe).hexdigest(),
                 'WorkshopTranslator/config.json': json.dumps(config or {'api_key': '', 'developer_mode': False}),
                 'WorkshopTranslator/providers.json': '{"profiles": {}}',
                 'WorkshopTranslator/completed.json': '{"entries": []}'}
        files.update(extras or {})
        with zipfile.ZipFile(path, 'w') as archive:
            for name, content in files.items():
                archive.writestr(name, content)
        return path

    def test_clean_bundle_and_private_data_rejection(self):
        with tempfile.TemporaryDirectory() as directory:
            builder.validate_bundle(self.make_bundle(directory), 'windows-x64')
            for config in ({'api_key': 'private'}, {'developer_mode': True}, {'steam_libraries': ['/Users/private/Steam']}):
                with self.assertRaises(ValueError):
                    builder.validate_bundle(self.make_bundle(directory, config=config), 'windows-x64')
            for name in ('WorkshopTranslator/app_data/config.json', '../config.json', 'WorkshopTranslator/translations.sqlite3'):
                with self.assertRaises(ValueError):
                    builder.validate_bundle(self.make_bundle(directory, {name: '{}'}), 'windows-x64')

    def test_modified_executable_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                builder.validate_bundle(self.make_bundle(directory, {'WorkshopTranslator/WorkshopTranslator.exe': b'MZchanged'}), 'windows-x64')
