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
        self.real_steam_libraries = app.steam_libraries
        libraries = patch.object(app, 'steam_libraries', side_effect=lambda extra=(): [Path(p) for p in extra])
        libraries.start()
        self.addCleanup(libraries.stop)
        self.service = app.WorkshopService(self.base / 'data')
        self.library = self.base / 'SteamLibrary'
        self.mod = self.library / 'steamapps/workshop/content/394360/123456'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n')
        (self.mod / 'descriptor.mod').write_text('name="Local title"\n')
        self.service.save_config({'steam_libraries': [str(self.library)]})

    def scan(self):
        items = self.service.scan(lambda ids: {'123456': {'title': 'Workshop title', 'consumer_app_id': 394360}})
        for item in items:
            self.service.analyze(item['id'])
        return items

    def test_matching_workspace_cache_does_not_rewrite_file(self):
        item = self.scan()[0]
        sources = app.english_files(self.mod)
        from translation_cache import ModCache
        cache = ModCache(self.service)
        workspace = cache.sync_workspace(item, sources)
        path = next((workspace / 'already').rglob('*.cache.json'))
        before = path.stat().st_mtime_ns
        cache.sync_workspace(item, sources)
        self.assertEqual(path.stat().st_mtime_ns, before)

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

    def test_scan_reuses_unchanged_inventory_after_restart(self):
        self.scan()
        restarted = app.WorkshopService(self.service.data_dir)
        self.assertEqual(restarted.inventory['394360:123456']['title'], 'Workshop title')
        self.assertEqual(restarted.inventory['394360:123456']['counts']['untranslated'], 1)
        with patch.object(restarted, 'analyze', side_effect=AssertionError('unchanged should not analyze')):
            result = restarted.scan(lambda ids: self.fail('unchanged should not fetch'))
        self.assertEqual(result[0]['title'], 'Workshop title')

    def test_directory_refresh_skips_deep_content_even_if_it_changed(self):
        self.scan()
        previous = self.source.stat()
        self.source.write_text(self.source.read_text().replace('Alpha', 'Gamma'))
        os.utime(self.source, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        calls = []
        def fetch(ids):
            calls.extend(ids)
            return {'123456': {'title': 'Updated title', 'consumer_app_id': 394360}}
        self.service.scan(fetch)
        self.assertEqual(calls, [])
        self.assertEqual(self.service.inventory['394360:123456']['title'], 'Workshop title')
        self.assertEqual(self.service.analyze('394360:123456')['untranslated'], 1)

    def test_scan_queries_only_new_and_changed_mods_and_removes_uninstalled(self):
        self.scan()
        new = self.mod.parent / '9999'
        new.mkdir()
        (new / 'descriptor.mod').write_text('name="Second Mod"')
        calls = []
        def fetch(ids):
            calls.append(ids)
            return {uid: {'title': uid, 'consumer_app_id': 394360} for uid in ids}
        self.service.scan(fetch)
        self.assertEqual(calls, [['9999']])
        (new / 'descriptor.mod').unlink()
        new.rmdir()
        self.service.scan(lambda ids: self.fail('removed should not fetch'))
        self.assertEqual(set(app.WorkshopService(self.service.data_dir).inventory), {'394360:123456'})

    def test_failed_metadata_query_retries_without_reanalyzing_unchanged_files(self):
        self.service.scan(lambda ids: {})
        calls = []
        with patch.object(self.service, 'analyze', side_effect=AssertionError('unchanged should not analyze')):
            self.service.scan(lambda ids: calls.extend(ids) or {'123456': {'title': 'Recovered', 'consumer_app_id': 394360}})
        self.assertEqual(calls, ['123456'])
        self.assertEqual(self.service.inventory['394360:123456']['title'], 'Recovered')

    def test_changed_chinese_refreshes_stats_and_manual_import_survives_restart(self):
        self.scan()
        chinese = self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml'
        chinese.parent.mkdir(parents=True)
        chinese.write_text('l_simp_chinese:\n key:0 "甲 $VALUE$"\n')
        self.scan()
        self.assertEqual(self.service.inventory['394360:123456']['counts']['translated'], 1)
        restarted = app.WorkshopService(self.service.data_dir)
        self.assertEqual(restarted.inventory['394360:123456']['counts']['translated'], 1)

    def test_initial_directory_refresh_does_not_read_mod_content(self):
        with patch.object(app, 'english_files', side_effect=AssertionError('content read forbidden')), patch.object(self.service, 'analyze', side_effect=AssertionError('analysis forbidden')):
            item = self.service.scan(lambda ids: {})[0]
        self.assertNotIn('counts', item)
        self.assertEqual(item['scan_state'], '未扫描')
        self.assertEqual(self.service.analyze(item['id'])['untranslated'], 1)
        self.assertEqual(item['scan_state'], '已扫描')

    def test_provider_profiles_persist_privately(self):
        self.service.save_config({'provider': '测试提供商', 'api_key': 'fake-secret'})
        registry = json.loads(self.service.providers_path.read_text())
        self.assertEqual(registry['profiles']['测试提供商']['api_key'], 'fake-secret')
        self.assertEqual(self.service.public_config()['provider'], '测试提供商')
        self.assertNotIn('api_key', self.service.public_config())

    def test_ai_and_imported_origins_are_preserved_separately(self):
        second = self.source.parent / 'second_l_english.yml'
        second.write_text('l_english:\n other:0 "Beta $VALUE$"\n')
        item = self.service.scan(lambda ids: {})[0]
        external = self.base / 'import.yml'
        external.write_text('l_simp_chinese:\n key:0 "甲 $VALUE$"\n')
        imported = self.service.import_cache(item['id'], external, '人工汉化组')
        self.assertEqual(imported['provider'], '人工汉化组')
        self.service.save_config({'provider': '模型供应商'})
        self.service.translate(item['id'], self.translator)
        self.assertEqual({origin['name'] for origin in item['counts']['origins']}, {'导入 · 人工汉化组', 'AI · 模型供应商'})
        self.assertEqual(self.service.history()[0]['provider'], '模型供应商')
        marker = json.loads(self.service.completed_path.read_text())
        self.assertEqual(len(marker['entries']), 2)

    def test_untranslated_and_changed_entries_are_distinguished(self):
        item = self.scan()[0]
        self.service.translate(item['id'], self.translator)
        self.source.write_text('l_english:\n key:0 "Beta $VALUE$"\n new:0 "Gamma"\n')
        result = self.service.analyze(item['id'])
        self.assertEqual(result['translated'], 0)
        self.assertEqual(result['untranslated'], 2)
        self.assertEqual(result['needs_update'], 1)

    def test_empty_provider_gets_date_and_persistent_revision(self):
        first = self.service.source_label('导入')
        restarted = app.WorkshopService(self.service.data_dir)
        second = restarted.source_label('AI')
        self.assertRegex(first, r'^翻译-\d{4}-\d{2}-\d{2}-1$')
        self.assertTrue(second.endswith('-2'))
        self.assertIn(second, json.loads(restarted.providers_path.read_text())['profiles'])

    def test_release_package_copies_settings_and_markers_but_redacts_keys(self):
        import importlib.util
        import zipfile
        spec = importlib.util.spec_from_file_location('release_builder', ROOT / 'packaging/build_release.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.scan()
        self.service.save_config({'provider': '供应商', 'api_key': 'fake-secret'})
        self.service.translate('394360:123456', self.translator)
        self.service.completed_path.unlink()  # Package can recover markers from an older local database.
        exe = self.base / 'test.exe'
        exe.write_bytes(b'MZtest')
        support = exe.parent / '_internal'
        support.mkdir()
        (support / 'runtime.dll').write_bytes(b'test-runtime')
        package = module.build_release(self.base / 'release.zip', self.service.data_dir, exe)
        with zipfile.ZipFile(package) as archive:
            config = json.loads(archive.read('WorkshopTranslator/config.json'))
            registry = json.loads(archive.read('WorkshopTranslator/providers.json'))
            completed = json.loads(archive.read('WorkshopTranslator/completed.json'))
            self.assertEqual(config['api_key'], '')
            self.assertEqual(registry['profiles']['供应商']['api_key'], '')
            self.assertEqual(len(completed['entries']), 1)
            self.assertIn('WorkshopTranslator/workshop_app.py', archive.namelist())
            self.assertEqual(archive.read('WorkshopTranslator/_internal/runtime.dll'), b'test-runtime')
        self.service.save_config({'model': 'updated-model'})
        module.build_release(package, self.service.data_dir, exe)
        with zipfile.ZipFile(package) as archive:
            self.assertEqual(json.loads(archive.read('WorkshopTranslator/config.json'))['model'], 'updated-model')

    def test_portable_completion_seed_merges_without_overwriting_local_settings(self):
        self.scan()
        self.service.translate('394360:123456', self.translator)
        bundle = self.base / 'bundle'
        bundle.mkdir()
        (bundle / 'completed.json').write_bytes(self.service.completed_path.read_bytes())
        (bundle / 'config.json').write_text(json.dumps({**app.DEFAULT_CONFIG, 'provider': '种子提供商'}))
        (bundle / 'providers.json').write_bytes(self.service.providers_path.read_bytes())
        with patch.object(app, 'ROOT', bundle):
            fresh = app.WorkshopService(self.base / 'seed-data')
            self.assertEqual(fresh.config()['provider'], '种子提供商')
            with fresh.connect() as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM translation_entries').fetchone()[0], 1)
            fresh.save_config({'provider': '本机提供商'})
            again = app.WorkshopService(fresh.data_dir)
            self.assertEqual(again.config()['provider'], '本机提供商')

    def test_handoff_contains_source_context_and_release_and_rejects_secrets(self):
        import importlib.util
        import zipfile
        spec = importlib.util.spec_from_file_location('handoff_builder', ROOT / 'packaging/build_handoff.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        release = self.base / 'program.zip'
        def write_release(key=''):
            with zipfile.ZipFile(release, 'w') as archive:
                for name in ('config.json', 'providers.json', 'completed.json'):
                    archive.writestr('WorkshopTranslator/' + name, json.dumps({'api_key': key}))
        write_release()
        destination = self.base / 'handoff.zip'
        module.build_handoff(destination, release)
        original = destination.read_bytes()
        with zipfile.ZipFile(destination) as archive:
            names = archive.namelist()
            self.assertIn('WorkshopTranslator-Handoff/source/tests/test_workshop.py', names)
            self.assertIn('WorkshopTranslator-Handoff/source/交接说明.md', names)
            self.assertEqual(archive.read('WorkshopTranslator-Handoff/Windows/WorkshopTranslator-Windows.zip'), release.read_bytes())
            self.assertFalse(any('/app_data' in name or '/.git/' in name or name.endswith('.sqlite3') for name in names))
        write_release('fake-secret')
        with self.assertRaises(ValueError):
            module.build_handoff(destination, release)
        self.assertEqual(destination.read_bytes(), original)

    def test_switch_saved_profiles_uses_matching_key_and_preserves_libraries(self):
        self.service.save_config({'config_name': '日常翻译', 'provider': '提供商', 'model': 'model-a', 'api_key': 'key-a'})
        self.service.save_config({'config_name': '精校模型', 'provider': '提供商', 'model': 'model-b', 'api_key': 'key-b'})
        libraries = [str(self.base / 'NewLibrary')]
        self.service.save_config({'steam_libraries': libraries})
        public = self.service.switch_profile('日常翻译')
        self.assertEqual(public['model'], 'model-a')
        self.assertEqual(self.service.config()['api_key'], 'key-a')
        self.assertEqual(public['steam_libraries'], libraries)
        self.assertNotIn('api_key', public)
        profiles = self.service.profiles()
        self.assertEqual({p['name'] for p in profiles}, {'日常翻译', '精校模型'})
        self.assertNotIn('key-a', json.dumps(profiles))
        restarted = app.WorkshopService(self.service.data_dir)
        restarted.switch_profile('精校模型')
        self.assertEqual(restarted.config()['api_key'], 'key-b')

    def test_switch_keyless_profile_does_not_inherit_other_profile_secret(self):
        self.service.save_config({'config_name': '无密钥模板', 'provider': '模板', 'api_key': ''})
        self.service.save_config({'config_name': '已配置接口', 'api_key': 'private-key'})
        selected = self.service.switch_profile('无密钥模板')
        self.assertFalse(selected['has_api_key'])
        self.assertEqual(self.service.config()['api_key'], '')

    def test_switch_unknown_or_running_profile_leaves_config_unchanged(self):
        previous = self.service.config()
        with self.assertRaises(ValueError):
            self.service.switch_profile('missing')
        self.service.job['running'] = True
        with self.assertRaisesRegex(ValueError, '等待任务'):
            self.service.switch_profile('missing')
        self.assertEqual(self.service.config(), previous)

    def test_unchanged_completion_seed_is_not_parsed_again_on_restart(self):
        self.scan()
        self.service.translate('394360:123456', self.translator)
        bundle = self.base / 'bundle'
        bundle.mkdir()
        seed = bundle / 'completed.json'
        seed.write_bytes(self.service.completed_path.read_bytes())
        with patch.object(app, 'ROOT', bundle):
            first = app.WorkshopService(self.base / 'seed-test')
            read_text = Path.read_text
            def guard(path, *args, **kwargs):
                if path == seed:
                    self.fail('unchanged completion seed was re-read')
                return read_text(path, *args, **kwargs)
            with patch.object(Path, 'read_text', guard):
                app.WorkshopService(first.data_dir)

    def test_startup_check_does_not_import_model_sdk(self):
        import subprocess
        result = subprocess.run([sys.executable, str(ROOT / 'workshop_app.py'), '--startup-check', '--data-dir', str(self.base / 'startup-check')], capture_output=True, text=True, check=True)
        self.assertFalse(json.loads(result.stdout)['sdk_loaded'])

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

    def test_failed_translation_preserves_english_and_backs_up_old_output(self):
        self.scan()
        output = self.mod / 'localisation/simp_chinese/test_l_simp_chinese.yml'
        output.parent.mkdir(parents=True)
        output.write_text('previous chinese')
        def failed(texts, *args):
            return [{'text': text, 'success': False} for text in texts]
        result = self.service.translate('394360:123456', failed)
        self.assertIn('Alpha $VALUE$', output.read_text('utf-8-sig'))
        self.assertEqual(result['error_lines'], 1)
        self.assertEqual(result['issues'][0]['line'], 2)
        self.assertEqual(len(self.service.history()), 1)
        self.service.translate('394360:123456', self.translator)
        self.assertIn('甲', output.read_text())

    def test_cached_entries_are_distinct_from_deployed_entries(self):
        item = self.scan()[0]
        self.service.translate(item['id'], self.translator, deploy=False)
        counts = self.service.analyze(item['id'])
        self.assertEqual((counts['deployed'], counts['cached']), (0, 1))
        self.service.translate(item['id'], self.translator)
        counts = self.service.analyze(item['id'])
        self.assertEqual((counts['deployed'], counts['cached']), (1, 0))

    def test_valueerror_from_provider_preserves_english_and_reports_line(self):
        self.scan()
        def broken(*args):
            raise ValueError('invalid provider result')
        result = self.service.translate('394360:123456', broken)
        self.assertEqual(result['error_lines'], 1)
        self.assertEqual(result['issues'][0]['line'], 2)
        counts = self.service.analyze('394360:123456')
        self.assertEqual(counts['translated'], 0)

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
        try:
            (self.mod / 'localisation/simp_chinese').symlink_to(outside, target_is_directory=True)
        except OSError as error:
            if getattr(error, 'winerror', None) == 1314:
                self.skipTest('Windows symlink privilege unavailable')
            raise
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
        self.assertIn(self.library, self.real_steam_libraries([str(installation)]))

    def write_manifest(self, installed=None, details=None):
        installed = installed if installed is not None else {'123456': {
            'size': '54223092', 'timeupdated': '1786173367', 'manifest': '7118271464932829424'}}
        details = details if details is not None else {'123456': {
            'manifest': '7118271464932829424', 'timeupdated': '1786173367',
            'timetouched': '1782720285', 'subscribedby': '1225308195',
            'latest_timeupdated': '1786173367', 'latest_manifest': '7118271464932829424'}}
        def dump(value):
            if isinstance(value, dict):
                return '{\n' + '\n'.join(json.dumps(k) + ' ' + dump(v) for k, v in value.items()) + '\n}'
            return json.dumps(value)
        manifest = self.library / 'steamapps/workshop/appworkshop_394360.acf'
        manifest.write_text('\ufeff// Steam metadata\n' + dump({'AppWorkshop': {
            'appid': '394360', 'WorkshopItemsInstalled': installed, 'WorkshopItemDetails': details}})[1:-1], encoding='utf-8')
        return manifest

    def test_acf_is_authoritative_and_read_once_without_directory_enumeration(self):
        manifest = self.write_manifest(details={'9999': {'latest_manifest': '2'}})
        extra = self.mod.parent / '9999'
        extra.mkdir()
        actual_read, actual_iter = Path.read_text, Path.iterdir
        reads = []
        def read(path, *args, **kwargs):
            if path == manifest:
                reads.append(path)
            return actual_read(path, *args, **kwargs)
        def iterate(path):
            if path == self.mod.parent:
                raise AssertionError('valid ACF must not enumerate game Mod directory')
            return actual_iter(path)
        with patch.object(Path, 'read_text', read), patch.object(Path, 'iterdir', iterate), patch.object(app, 'english_files', side_effect=AssertionError('no content scan')):
            result = self.service.scan(lambda ids: {})
        self.assertEqual([row['uid'] for row in result], ['123456'])
        self.assertEqual(reads, [manifest])
        self.assertEqual(result[0]['workshop']['manifest'], '7118271464932829424')
        self.assertEqual(result[0]['discovery_source'], 'Steam ACF')
        self.assertEqual(result[0]['scan_state'], '未扫描')

    def test_acf_touch_and_subscriber_and_local_write_do_not_invalidate_installed_version(self):
        self.write_manifest()
        self.scan()
        (self.mod / 'new-local-file.txt').write_text('local output')
        (self.mod / 'descriptor.mod').write_text('name="Updated descriptor"')
        self.write_manifest(details={'123456': {'timetouched': '9999999999', 'subscribedby': '42'}})
        restarted = app.WorkshopService(self.service.data_dir)
        result = restarted.scan(lambda ids: self.fail('unchanged installed version should not fetch'))
        self.assertEqual(result[0]['scan_state'], '已扫描')
        self.assertEqual(result[0]['counts']['total'], 1)

    def test_acf_installed_version_queries_only_changed_item_and_marks_counts_stale(self):
        first = {'size': '1', 'timeupdated': '1', 'manifest': '7118271464932829424'}
        second = {'size': '2', 'timeupdated': '2', 'manifest': '7118271464932829425'}
        (self.mod.parent / '9999').mkdir()
        self.write_manifest(installed={'123456': first, '9999': second}, details={})
        self.service.scan(lambda ids: {uid: {'title': uid, 'consumer_app_id': '394360'} for uid in ids})
        self.service.analyze('394360:123456')
        self.write_manifest(installed={'123456': {**first, 'manifest': '7118271464932829426'}, '9999': second}, details={})
        calls = []
        result = self.service.scan(lambda ids: calls.append(ids) or {uid: {'title': uid, 'consumer_app_id': '394360'} for uid in ids})
        self.assertEqual(calls, [['123456']])
        self.assertEqual(next(row for row in result if row['uid'] == '123456')['scan_state'], '待复查')

    def test_acf_latest_version_change_is_pending_without_relabeling_local_counts(self):
        self.write_manifest()
        self.scan()
        self.write_manifest(details={'123456': {'latest_manifest': '7118271464932829425', 'latest_timeupdated': '1786173368'}})
        row = self.service.scan(lambda ids: self.fail('remote-only change does not change installed version'))[0]
        self.assertTrue(row['steam_update_pending'])
        self.assertEqual(row['scan_state'], '已扫描')
        self.write_manifest()
        self.assertFalse(self.service.scan(lambda ids: self.fail('unchanged'))[0]['steam_update_pending'])

    def test_empty_acf_removes_inventory_even_if_old_directory_remains_and_preserves_backups(self):
        self.write_manifest()
        self.scan()
        self.service.translate('394360:123456', self.translator)
        self.write_manifest(installed={}, details={'123456': {'latest_manifest': '1'}})
        self.assertEqual(self.service.scan(lambda ids: self.fail('empty installed list')), [])
        self.assertEqual(app.WorkshopService(self.service.data_dir).inventory, {})
        self.assertEqual(len(self.service.history()), 1)

    def test_acf_unfinished_write_falls_back_instead_of_removing_mod(self):
        manifest = self.write_manifest()
        manifest.write_text('"AppWorkshop" { "WorkshopItemsInstalled" {')
        row = self.service.scan(lambda ids: {})[0]
        self.assertEqual(row['discovery_source'], '目录回退')
        self.assertTrue(any('ACF 暂不可读' in line for line in self.service.status()['messages']))

    def test_acf_path_missing_and_symlink_and_details_only_items_are_not_installed(self):
        record = {'size': '1', 'timeupdated': '1', 'manifest': '1'}
        outside = self.base / 'outside'
        outside.mkdir()
        linked = self.mod.parent / '9999'
        try:
            linked.symlink_to(outside, target_is_directory=True)
        except OSError:
            pass  # Windows runners may not grant symlink creation privileges.
        self.write_manifest(installed={'123456': record, '9999': record, '8888': record}, details={'7777': {'latest_manifest': '1'}})
        self.assertEqual([row['uid'] for row in self.service.scan(lambda ids: {})], ['123456'])

    def test_keyvalues_nested_escaped_strings_and_rejects_incomplete_or_duplicate_keys(self):
        parsed = app.parse_keyvalues('"AppWorkshop" { "note" "a \\"quote\\" and {brace}" "nested" { "id" "7118271464932829424" } }')
        self.assertEqual(parsed['AppWorkshop']['note'], 'a "quote" and {brace}')
        self.assertEqual(parsed['AppWorkshop']['nested']['id'], '7118271464932829424')
        for text in ('"AppWorkshop" {', '"a" "1" "a" "2"', '"a" }', '"a" "b" extra'):
            with self.assertRaises(ValueError):
                app.parse_keyvalues(text)

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
