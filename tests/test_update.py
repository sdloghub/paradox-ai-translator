import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

spec = importlib.util.spec_from_file_location('build_update', Path(__file__).resolve().parents[1] / 'packaging/build_update.py')
update = importlib.util.module_from_spec(spec)
spec.loader.exec_module(update)


class UpdateTests(unittest.TestCase):
    def test_overlay_updates_runtime_and_preserves_local_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old = {'WorkshopTranslator.exe': b'old', '_internal/library.dll': b'old-library',
                   '_internal/unchanged.dll': b'same', 'config.json': b'private-config',
                   'providers.json': b'private-providers', 'completed.json': b'local-markers',
                   'app_data/translations.sqlite3': b'local-db'}
            new = {**old, 'WorkshopTranslator.exe': b'new', '_internal/library.dll': b'new-library',
                   'config.json': b'blank-default', 'completed.json': b'empty-default',
                   '_internal/new.dll': b'new-dependency'}
            for name, files in [('old.zip', old), ('new.zip', new)]:
                with zipfile.ZipFile(root / name, 'w') as z:
                    for path, data in files.items():
                        z.writestr('WorkshopTranslator/' + path, data)
            result = update.build_update(root / 'old.zip', root / 'new.zip', root / 'update.zip')
            target = root / 'installed'
            with zipfile.ZipFile(root / 'old.zip') as z:
                z.extractall(target)
            with zipfile.ZipFile(result) as z:
                self.assertNotIn('_internal/unchanged.dll', z.namelist())
                self.assertNotIn('config.json', z.namelist())
                z.extractall(target / 'WorkshopTranslator')
            for path, data in old.items():
                expected = new[path] if path.endswith('.exe') or path == '_internal/library.dll' else data
                self.assertEqual((target / 'WorkshopTranslator' / path).read_bytes(), expected)
            self.assertEqual((target / 'WorkshopTranslator/_internal/new.dll').read_bytes(), b'new-dependency')
