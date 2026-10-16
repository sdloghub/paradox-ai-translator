import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workshop_app as app
from aggregate_export import export


class AggregateExportTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = app.WorkshopService(self.root / 'data')
        self.library = self.root / 'SteamLibrary'
        self.mod, self.source = self.make_mod('281990', '123', 'First Mod')
        self.service.save_config({'steam_libraries':[str(self.library)]})
        self.scan()
        self.identifier = '281990:123'

    def make_mod(self, appid, uid, title):
        mod = self.library / 'steamapps/workshop/content' / appid / uid
        source = mod / 'localisation/english/shared_l_english.yml'
        source.parent.mkdir(parents=True)
        source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n', encoding='utf-8')
        (mod / 'descriptor.mod').write_text('name="' + title + '"', encoding='utf-8')
        return mod, source

    def scan(self):
        with patch.object(app, 'steam_libraries', return_value=[self.library]):
            self.service.scan(lambda ids: {})

    @staticmethod
    def translator(texts, *args):
        return [{'text':'中文：' + text, 'success':True} for text in texts]

    def translate(self, identifier=None, **kwargs):
        return self.service.translate(identifier or self.identifier, translator=self.translator, **kwargs)

    def test_default_on_copies_after_deployment_and_tracks_public_sources(self):
        self.assertTrue(self.service.config()['aggregate_export'])
        self.service.save_config({'api_key':'private-key-do-not-export'})
        result = self.translate()
        folder = Path(result['aggregate']['path'])
        target = self.mod / 'localisation/simp_chinese/shared_l_simp_chinese.yml'
        exported = folder / 'localisation/simp_chinese/123_shared_l_simp_chinese.yml'
        self.assertEqual(exported.read_bytes(), target.read_bytes())
        manifest_text = (folder / 'translation-manifest.json').read_text()
        record = json.loads(manifest_text)['mods']['123']
        self.assertEqual(record['name'], 'First Mod')
        self.assertEqual(record['workshop_url'], 'https://steamcommunity.com/sharedfiles/filedetails/?id=123')
        self.assertEqual(record['version_id'], result['version_id'])
        self.assertNotIn('private-key-do-not-export', manifest_text)
        self.assertNotIn(str(self.mod), manifest_text)
        self.assertEqual(len(list(folder.rglob('*.yml'))), 1)

    def test_off_persists_and_keeps_primary_deployment(self):
        self.service.save_config({'aggregate_export':False})
        restarted = app.WorkshopService(self.root / 'data')
        self.assertFalse(restarted.config()['aggregate_export'])
        result = self.translate()
        self.assertFalse(result['aggregate']['enabled'])
        self.assertTrue((self.mod / 'localisation/simp_chinese/shared_l_simp_chinese.yml').is_file())
        self.assertFalse((self.root / 'data/aggregate_mods').exists())

    def test_two_mods_do_not_collide_and_retranslation_updates_own_files(self):
        first = self.translate()
        self.make_mod('281990', '456', 'Second Mod')
        self.scan()
        self.translate('281990:456')
        folder = Path(first['aggregate']['path'])
        second = folder / 'localisation/simp_chinese/456_shared_l_simp_chinese.yml'
        before = second.read_bytes()
        self.source.write_text('l_english:\n key:0 "Changed $VALUE$"\n', encoding='utf-8')
        updated = self.translate()
        self.assertEqual(second.read_bytes(), before)
        self.assertIn('Changed', (folder / 'localisation/simp_chinese/123_shared_l_simp_chinese.yml').read_text())
        self.assertEqual(len(list(folder.rglob('*.yml'))), 2)
        self.assertEqual(set(json.loads((folder / 'translation-manifest.json').read_text())['mods']), {'123','456'})
        self.assertTrue(updated['aggregate']['enabled'])
        self.assertTrue(list((self.root / 'data/aggregate_backups').rglob('123_shared_l_simp_chinese.yml')))

    def test_games_are_separate(self):
        first = self.translate()
        self.make_mod('394360', '123', 'Another game')
        self.scan()
        second = self.translate('394360:123')
        self.assertNotEqual(first['aggregate']['path'], second['aggregate']['path'])
        for result, appid in [(first,'281990'),(second,'394360')]:
            manifest = json.loads((Path(result['aggregate']['path']) / 'translation-manifest.json').read_text())
            self.assertEqual(manifest['appid'], appid)

    def test_backup_only_waits_for_restore_and_switch_keeps_existing_files(self):
        result = self.translate(deploy=False)
        self.assertFalse((self.root / 'data/aggregate_mods').exists())
        restored = self.service.restore(result['version_id'], self.identifier)
        folder = Path(restored['aggregate']['path'])
        contents = {str(path.relative_to(folder)):path.read_bytes() for path in folder.rglob('*') if path.is_file()}
        self.service.save_config({'aggregate_export':False})
        self.service.restore(result['version_id'], self.identifier)
        self.assertEqual({str(path.relative_to(folder)):path.read_bytes() for path in folder.rglob('*') if path.is_file()}, contents)

    def test_export_failure_does_not_undo_mod_deployment(self):
        outside = self.root / 'outside'
        outside.mkdir()
        base = self.root / 'data/aggregate_mods'
        base.mkdir()
        (base / '281990').symlink_to(outside, target_is_directory=True)
        result = self.translate()
        self.assertIn('error', result['aggregate'])
        self.assertTrue((self.mod / 'localisation/simp_chinese/shared_l_simp_chinese.yml').is_file())
        self.assertEqual(list(outside.iterdir()), [])

    def test_managed_stale_files_removed_but_manual_edits_retained(self):
        item = self.service.get_mod(self.identifier)
        one = {'localisation/simp_chinese/a_l_simp_chinese.yml':b'old-a', 'localisation/simp_chinese/b_l_simp_chinese.yml':b'old-b'}
        result = export(self.service, item, one, 1)
        folder = Path(result['path'])
        b = folder / 'localisation/simp_chinese/123_b_l_simp_chinese.yml'
        b.write_bytes(b'manual-edit')
        result = export(self.service, item, {'localisation/simp_chinese/c_l_simp_chinese.yml':b'new-c'}, 2)
        self.assertFalse((folder / 'localisation/simp_chinese/123_a_l_simp_chinese.yml').exists())
        self.assertEqual(b.read_bytes(), b'manual-edit')
        self.assertEqual(len(result['warnings']), 1)

    def test_export_rolls_back_on_copy_failure(self):
        item = self.service.get_mod(self.identifier)
        files = {'localisation/simp_chinese/a_l_simp_chinese.yml':b'old-a', 'localisation/simp_chinese/b_l_simp_chinese.yml':b'old-b'}
        result = export(self.service, item, files, 1)
        folder = Path(result['path'])
        old_manifest = (folder / 'translation-manifest.json').read_bytes()
        original = app.atomic_bytes
        def fail(path, data, **kwargs):
            if data == b'new-b' and 'aggregate_mods' in Path(path).parts:
                raise OSError('simulated disk failure')
            return original(path, data, **kwargs)
        with patch.object(app, 'atomic_bytes', side_effect=fail), self.assertRaises(OSError):
            export(self.service, item, {key:value.replace(b'old',b'new') for key,value in files.items()}, 2)
        self.assertEqual((folder / 'translation-manifest.json').read_bytes(), old_manifest)
        self.assertEqual((folder / 'localisation/simp_chinese/123_a_l_simp_chinese.yml').read_bytes(), b'old-a')

    def test_legacy_configuration_defaults_on_and_api_profiles_keep_switch(self):
        self.service.config_path.write_text(json.dumps({'model':'test-model'}))
        self.assertTrue(self.service.config()['aggregate_export'])
        self.service.save_config({'config_name':'Main', 'aggregate_export':True})
        self.service.save_config({'aggregate_export':False})
        self.service.switch_profile('Main')
        self.assertFalse(self.service.config()['aggregate_export'])
        with self.assertRaises(ValueError):
            self.service.save_config({'aggregate_export':'true'})


if __name__ == '__main__':
    unittest.main()
