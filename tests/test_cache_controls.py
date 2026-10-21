"""Cache selection must control both displayed states and actual AI reuse."""
import json
import unittest
from unittest.mock import patch

import test_entry_browser as browser_tests
from translation_cache import entries
import workshop_app as app


class CacheControlTests(unittest.TestCase):
    setUp = browser_tests.EntryBrowserTests.setUp
    scan = browser_tests.EntryBrowserTests.scan
    row = browser_tests.EntryBrowserTests.row

    def seed(self):
        parsed = entries(self.service.original_sources(self.item), 'hoi4', strict=False)
        by_key = {e['key'].split(':')[0]:e for e in parsed}
        with self.service.connect() as db:
            self.service.cache.put(db, self.identifier, by_key['cached'], '缓存中文', '缓存来源')
            self.service.cache.put(db, self.identifier, by_key['deployed'], '本机中文 $VALUE$', '本机来源')
        target = self.mod / app.target_path(by_key['deployed']['source_file'], 'hoi4')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('l_simp_chinese:\n deployed:0 "本机中文 $VALUE$"\n', encoding='utf-8')
        return target

    def simple_source(self):
        self.source.write_text('l_english:\n cached:0 "Beta"\n', encoding='utf-8')

    @staticmethod
    def translator(label, calls=None):
        def translate(texts, *args):
            if calls is not None:
                calls.extend(texts)
            return [{'text':label, 'success':True} for text in texts]
        return translate

    def test_default_latest_toggle_updates_index_and_preserves_deployed(self):
        self.seed()
        self.scan()
        self.assertTrue(self.service.cache.selection(self.identifier)['enabled'])
        self.assertEqual(self.row('cached')['auto_status'], 'cached')
        self.service.select_cache(self.identifier, False)
        self.assertEqual(self.row('cached')['auto_status'], 'untranslated')
        self.assertEqual(self.row('deployed')['auto_status'], 'translated')
        self.assertEqual(self.item['counts']['cached'], 0)
        restarted = app.WorkshopService(self.service.data_dir)
        self.assertFalse(restarted.cache.selection(self.identifier)['enabled'])
        self.service.select_cache(self.identifier, True)
        self.assertEqual(self.row('cached')['auto_status'], 'cached')

    def test_toggle_uses_only_mod_sql_and_never_scans_or_rewrites_workspace(self):
        self.seed()
        self.scan()
        with patch.object(self.service, 'analyze', side_effect=AssertionError('full scan')), \
             patch.object(self.service, 'original_sources', side_effect=AssertionError('read source')), \
             patch.object(self.service.cache, 'sync_workspace', side_effect=AssertionError('workspace rewrite')):
            self.service.select_cache(self.identifier, False)
            self.assertEqual(self.row('deployed')['auto_status'], 'translated')
            self.service.select_cache(self.identifier, True)
            self.assertEqual(self.row('cached')['auto_status'], 'cached')

    def test_unscanned_toggle_saves_preference_without_filesystem_scan(self):
        with patch.object(self.service, 'analyze', side_effect=AssertionError('full scan')):
            result = self.service.select_cache(self.identifier, False)
        self.assertTrue(result['needs_scan'])
        self.assertFalse(result['selection']['enabled'])

    def test_opt_out_retranslates_but_does_not_erase_saved_cache(self):
        self.simple_source()
        self.service.translate(self.identifier, self.translator('第一版中文'), deploy=False)
        self.service.select_cache(self.identifier, False)
        calls = []
        self.service.translate(self.identifier, self.translator('第二版中文', calls), deploy=False)
        self.assertEqual(calls, ['Beta'])
        self.assertEqual(self.row('cached')['auto_status'], 'untranslated')
        self.service.select_cache(self.identifier, True)
        self.assertEqual(self.row('cached')['chinese'], '第二版中文')

    def test_history_selection_uses_snapshot_and_rejects_changed_english(self):
        self.simple_source()
        first = self.service.translate(self.identifier, self.translator('第一版中文'), deploy=False)
        self.service.select_cache(self.identifier, False)
        self.service.translate(self.identifier, self.translator('第二版中文'), deploy=False)
        self.service.select_cache(self.identifier, True, first['version_id'])
        self.assertEqual(self.row('cached')['chinese'], '第一版中文')
        self.service.select_cache(self.identifier, True)
        self.assertEqual(self.row('cached')['chinese'], '第二版中文')
        self.source.write_text('l_english:\n cached:0 "Changed English"\n', encoding='utf-8')
        self.scan()  # External changes are detected by an explicit scan, not by a SQL-only toggle.
        self.service.select_cache(self.identifier, True, first['version_id'])
        self.assertEqual(self.row('cached')['auto_status'], 'needs_update')
        self.assertTrue(self.row('cached')['historical'])

    def test_delete_one_version_keeps_other_versions_and_refreshes_latest(self):
        self.simple_source()
        first = self.service.translate(self.identifier, self.translator('第一版中文'), deploy=False)
        self.service.select_cache(self.identifier, False)
        second = self.service.translate(self.identifier, self.translator('第二版中文'), deploy=False)
        self.service.select_cache(self.identifier, True, second['version_id'])
        self.service.delete_cache_version(self.identifier, second['version_id'])
        self.assertEqual([v['version_id'] for v in self.service.history()], [first['version_id']])
        self.assertIsNone(self.service.cache.selection(self.identifier)['version_id'])
        self.assertEqual(self.row('cached')['chinese'], '第一版中文')
        newest = self.service.translate(self.identifier, self.translator('不应调用'), deploy=False)
        self.assertGreater(newest['version_id'], second['version_id'])

    def test_delete_last_version_removes_exclusive_cache_without_touching_local(self):
        self.simple_source()
        version = self.service.translate(self.identifier, self.translator('缓存中文'), deploy=False)
        self.service.delete_cache_version(self.identifier, version['version_id'])
        self.assertEqual(self.service.history(), [])
        self.assertEqual(self.row('cached')['auto_status'], 'untranslated')
        self.scan()
        self.assertEqual(self.row('cached')['auto_status'], 'untranslated')
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM translation_entries WHERE mod_id=?', (self.identifier,)).fetchone()[0],0)

    def test_delete_shared_cache_preserves_surviving_version_and_deployed_files(self):
        self.simple_source()
        first = self.service.translate(self.identifier,self.translator('共享中文'))
        second = self.service.translate(self.identifier,self.translator('不应调用'))
        target = self.mod / app.target_path('localisation/english/test_l_english.yml','hoi4')
        before = target.read_bytes()
        self.service.delete_cache_version(self.identifier,first['version_id'])
        self.assertEqual(target.read_bytes(),before)
        self.assertEqual(self.row('cached')['auto_status'],'translated')
        self.assertEqual(self.service.history()[0]['version_id'],second['version_id'])

    def test_deleted_eu4_version_keeps_english_recovery_and_clear_translation(self):
        self.item['game']='eu4'
        self.item['appid']='236850'
        self.source.write_text('l_english:\n cached:0 "Beta"\n',encoding='utf-8')
        # Correct SQL identity for the test's EU4 fixture.
        with self.service.connect() as db:
            db.execute("UPDATE mods SET appid='236850' WHERE id=?",(self.identifier,))
        original=self.service.original_sources(self.item)
        version=self.service.translate(self.identifier,self.translator('欧陆中文'))
        self.service.delete_cache_version(self.identifier,version['version_id'])
        self.assertEqual(self.service.original_sources(self.item),original)
        result=self.service.clear_translations(self.identifier)
        self.assertEqual(result['cleared_files'],1)
        self.assertEqual(self.service.original_sources(self.item),original)

    def test_delete_version_checks_ownership_and_allows_uninstalled_mod(self):
        self.simple_source()
        version=self.service.translate(self.identifier,self.translator('中文'),deploy=False)
        with self.assertRaises(ValueError):
            self.service.delete_cache_version('other-mod',version['version_id'])
        self.service.inventory.pop(self.identifier)
        self.service.delete_cache_version(self.identifier,version['version_id'])
        self.assertEqual(self.service.history(),[])

    def test_invalid_or_foreign_selection_rejected(self):
        for enabled, version in [('true', None), (True, True), (True, 999), (True, '1')]:
            with self.subTest(enabled=enabled, version=version), self.assertRaises(ValueError):
                self.service.select_cache(self.identifier, enabled, version)

    def test_history_does_not_treat_failed_english_fallback_as_translated(self):
        self.simple_source()
        version = self.service.translate(self.identifier, lambda texts,*args:[{'text':t,'success':False} for t in texts], deploy=False)
        self.service.select_cache(self.identifier, True, version['version_id'])
        self.assertEqual(self.row('cached')['auto_status'], 'untranslated')
