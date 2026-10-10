import json
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import workshop_app as app


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name).resolve()
        self.service = app.WorkshopService(self.base / 'data')
        self.library = self.base / 'SteamLibrary'
        self.mod = self.library / 'steamapps/workshop/content/394360/123456'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n')
        (self.mod / 'descriptor.mod').write_text('name="Local title"\n')
        self.service.save_config({'steam_libraries': [str(self.library)]})

    def scan(self):
        return self.service.scan(lambda ids: {'123456': {'title': 'Workshop title', 'consumer_app_id': 394360}})

    @staticmethod
    def translator(texts, game, already, total):
        return [{'text': text.replace('Alpha', '甲').replace('Beta', '乙'), 'success': True} for text in texts]

    def test_scan_matches_uid_title_link_and_path(self):
        items = self.scan()
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]['title'], 'Workshop title')
        self.assertEqual(items[0]['uid'], '123456')
        self.assertTrue(items[0]['url'].endswith('?id=123456'))
        self.assertEqual(Path(items[0]['path']), self.mod)

    def test_offline_scan_uses_descriptor(self):
        def unavailable(ids):
            raise OSError('offline')
        self.assertEqual(self.service.scan(unavailable)[0]['title'], 'Local title')

    def test_json_key_is_private_and_not_returned(self):
        public = self.service.save_config({'api_key': 'fake-key'})
        self.assertTrue(public['has_api_key'])
        self.assertNotIn('api_key', public)
        self.assertEqual(json.loads(self.service.config_path.read_text())['api_key'], 'fake-key')
        if os.name != 'nt':
            self.assertEqual(self.service.config_path.stat().st_mode & 0o777, 0o600)

    def test_translation_backup_restore_and_incremental_update(self):
        self.scan()
        original = self.source.read_bytes()
        calls = []
        def translate(texts, *args):
            calls.extend(texts)
            return self.translator(texts, *args)
        first = self.service.translate('394360:123456', translate)
        output = self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml'
        self.assertIn('甲 $VALUE$', output.read_text())
        self.assertEqual(self.source.read_bytes(), original)
        output.unlink()
        self.service.restore(first['version_id'], '394360:123456')
        self.assertIn('甲 $VALUE$', output.read_text())
        self.service.translate('394360:123456', translate)
        self.assertEqual(len(calls), 1)
        self.source.write_text('l_english:\n key:0 "Beta $VALUE$"\n')
        self.service.translate('394360:123456', translate)
        self.assertEqual(calls[-1], 'Beta $VALUE$')
        self.assertIn('乙 $VALUE$', output.read_text())
        self.assertEqual(len(self.service.history()), 3)
        with self.service.connect() as db:
            originals, chinese = db.execute('SELECT originals,chinese FROM versions WHERE id=?', (first['version_id'],)).fetchone()
        self.assertEqual(app.unarchive(originals)['localisation/english/test_l_english.yml'], original)
        self.assertIn('甲', app.unarchive(chinese)['localisation/simp_chinese/test_l_simp_chinese.yml'].decode())

    def test_failed_translation_does_not_touch_mod_or_create_version(self):
        self.scan()
        output = self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml'
        output.parent.mkdir(parents=True)
        output.write_text('previous chinese')
        def failed(texts, *args):
            return [{'text': text, 'success': False} for text in texts]
        with self.assertRaisesRegex(ValueError, '未修改 Workshop'):
            self.service.translate('394360:123456', failed)
        self.assertEqual(output.read_text(), 'previous chinese')
        self.assertEqual(self.service.history(), [])
        self.service.translate('394360:123456', self.translator)
        self.assertIn('甲', output.read_text())

    def test_repeated_eu4_uses_original_backup(self):
        eu = self.library / 'steamapps/workshop/content/236850/9999'
        source = eu / 'localisation/test_l_english.yml'
        source.parent.mkdir(parents=True)
        source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n')
        original = source.read_bytes()
        self.scan()
        calls = []
        def translate(texts, *args):
            calls.extend(texts)
            return self.translator(texts, *args)
        self.service.translate('236850:9999', translate)
        self.assertNotEqual(source.read_bytes(), original)
        self.service.translate('236850:9999', translate)
        self.assertEqual(calls, ['Alpha $VALUE$'])
        source.write_text('l_english:\n key:0 "Beta $VALUE$"\n')
        self.service.translate('236850:9999', translate)
        self.assertEqual(calls[-1], 'Beta $VALUE$')

    def test_restore_rejects_symlink_escape(self):
        self.scan()
        version = self.service.translate('394360:123456', self.translator, deploy=False)['version_id']
        outside = self.base / 'outside'
        outside.mkdir()
        (self.mod / 'localisation/simp_chinese').symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, '超出 Mod'):
            self.service.restore(version, '394360:123456')
        self.assertEqual(list(outside.iterdir()), [])

    def test_restore_rolls_back_when_second_write_fails(self):
        second = self.source.parent / 'second_l_english.yml'
        second.write_text('l_english:\n other:0 "Beta $VALUE$"\n')
        self.scan()
        version = self.service.translate('394360:123456', self.translator, deploy=False)['version_id']
        output = self.mod / 'localisation/simp_chinese'
        output.mkdir()
        first = output / 'second_l_simp_chinese.yml'
        first.write_text('old output')
        actual = app.atomic_bytes
        writes = []
        def fail(path, data, *args, **kwargs):
            writes.append(path)
            if len(writes) == 2:
                raise OSError('disk failure')
            return actual(path, data, *args, **kwargs)
        with patch.object(app, 'atomic_bytes', side_effect=fail), self.assertRaises(OSError):
            self.service.restore(version, '394360:123456')
        self.assertEqual(first.read_text(), 'old output')
        self.assertFalse((output / 'test_l_simp_chinese.yml').exists())

    def test_demo_runs_without_key_or_network(self):
        demo = app.WorkshopService(self.base / 'demo', demo=True)
        with patch.object(app.urllib.request, 'urlopen', side_effect=AssertionError('network')):
            item = demo.scan()[0]
            result = demo.translate(item['id'])
        self.assertEqual(result['files'], 1)
        self.assertTrue(demo.history())

    def test_vdf_library_paths(self):
        installation = self.base / 'Steam'
        config = installation / 'steamapps/libraryfolders.vdf'
        config.parent.mkdir(parents=True)
        config.write_text('"libraryfolders" { "1" { "path" "' + str(self.library) + '" } }')
        self.assertIn(self.library, app.steam_libraries([str(installation)]))

    def test_unsafe_archive_paths_rejected(self):
        with self.assertRaises(ValueError):
            app.unarchive(app.archive({'../escape': b'data'}))


    def test_frozen_windows_keeps_data_outside_unpack_directory(self):
        with patch.object(app.sys, 'frozen', True, create=True), patch.object(app, 'os', types.SimpleNamespace(name='nt', environ={'LOCALAPPDATA': str(self.base)})):
            self.assertEqual(app.default_data_dir(), self.base / 'WorkshopTranslator/app_data')
            self.assertEqual(app.default_data_dir(True), self.base / 'WorkshopTranslator/app_data_demo')

    def test_windows_open_folder_uses_native_shell(self):
        calls = []
        with patch.object(app, 'os', types.SimpleNamespace(name='nt', startfile=calls.append)):
            app.open_folder(self.mod)
        self.assertEqual(calls, [str(self.mod)])

    def test_config_reads_unicode_as_utf8(self):
        self.service.save_config({'steam_libraries': [str(self.base / '中文游戏库')]})
        self.assertIn('中文游戏库', self.service.config()['steam_libraries'][0])

    def chinese_file(self, text='甲 $VALUE$', name='test_l_simp_chinese.yml'):
        path = self.mod / 'localisation/simp_chinese' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('l_simp_chinese:\n key:0 "' + text + '"\n', encoding='utf-8')
        return path

    def test_scan_imports_native_chinese_and_counts(self):
        self.chinese_file()
        item = self.scan()[0]
        self.assertEqual(item['counts']['translated'], 1)
        self.assertEqual(item['counts']['untranslated'], 0)
        def unused(*args):
            raise AssertionError('already translated')
        self.service.translate(item['id'], unused)

    def test_changed_english_does_not_reuse_unchanged_native_chinese(self):
        self.chinese_file()
        item = self.scan()[0]
        self.source.write_text('l_english:\n key:0 "Beta $VALUE$"\n')
        counts = self.service.analyze(item['id'])
        self.assertEqual(counts['untranslated'], 1)
        self.assertEqual(counts['translated'], 0)
        self.service.translate(item['id'], self.translator)
        self.assertIn('乙', (self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml').read_text())
        self.assertEqual(self.service.cache.stats(item, self.service.original_sources(item))['translated'], 1)
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM translation_entries').fetchone()[0], 2)

    def test_manual_chinese_folder_matches_keys(self):
        item = self.scan()[0]
        folder = self.base / 'manual_chinese'
        folder.mkdir()
        (folder / 'external_l_simp_chinese.yml').write_text('l_simp_chinese:\n key:0 "甲 $VALUE$"\n', encoding='utf-8')
        result = self.service.import_cache(item['id'], folder)
        self.assertEqual(result['imported'], 1)
        self.assertEqual(result['untranslated'], 0)

    def test_export_import_roundtrip_and_stale_hash_rejection(self):
        self.chinese_file()
        item = self.scan()[0]
        payload = self.service.cache.export(item)
        path = self.base / 'export.cache.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        another = app.WorkshopService(self.base / 'fresh')
        another.save_config({'steam_libraries': [str(self.library)]})
        # Remove local Chinese to prove database import alone suffices.
        (self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml').unlink()
        another.scan(lambda ids: {})
        self.assertEqual(another.import_cache(item['id'], path)['imported'], 1)
        self.source.write_text('l_english:\n key:0 "Beta $VALUE$"\n')
        result = another.import_cache(item['id'], path)
        self.assertEqual(result['untranslated'], 1)
        self.assertGreater(result['rejected'], 0)

    def test_foreign_mod_cache_is_rejected(self):
        self.chinese_file()
        item = self.scan()[0]
        payload = self.service.cache.export(item)
        payload['mod_id'] = '394360:987654'
        path = self.base / 'foreign.cache.json'
        path.write_text(json.dumps(payload), encoding='utf-8')
        result = self.service.import_cache(item['id'], path)
        self.assertEqual(result['imported'], 0)
        self.assertGreater(result['rejected'], 0)

    def test_format_corruption_is_not_imported(self):
        self.chinese_file('甲 $WRONG$')
        item = self.scan()[0]
        self.assertEqual(item['counts']['translated'], 0)
        self.assertEqual(item['counts']['untranslated'], 1)

    def test_ambiguous_cross_file_key_is_not_imported(self):
        other = self.source.parent / 'other_l_english.yml'
        other.write_text('l_english:\n key:0 "Beta $VALUE$"\n')
        item = self.scan()[0]
        external = self.base / 'external.yml'
        external.write_text('l_simp_chinese:\n key:0 "甲 $VALUE$"\n', encoding='utf-8')
        result = self.service.import_cache(item['id'], external)
        self.assertEqual(result['imported'], 0)
        self.assertEqual(result['untranslated'], 2)

if __name__ == '__main__':
    unittest.main()
