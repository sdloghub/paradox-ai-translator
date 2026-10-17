from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workshop_app as app
from translation_cache import entries


class TranslationEditorTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = app.WorkshopService(self.root / 'data')
        self.library = self.root / 'SteamLibrary'
        self.mod = self.library / 'steamapps/workshop/content/394360/123'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_bytes(b'\xef\xbb\xbfl_english:\r\n key:0 "Alpha $VALUE$" # note\r\n other:0 "Beta"\r\n')
        self.service.save_config({'steam_libraries':[str(self.library)]})
        with patch.object(app, 'steam_libraries', return_value=[self.library]):
            self.item = self.service.scan(lambda ids: {})[0]
        self.id = self.item['id']
        parsed = entries(self.service.original_sources(self.item), 'hoi4')
        with self.service.connect() as db:
            self.service.cache.put(db, self.id, parsed[0], '旧中文 $VALUE$', '原汉化组')
            self.service.cache.put(db, self.id, parsed[1], '另一中文', '原汉化组')
        self.target = self.mod / app.target_path(parsed[0]['source_file'], 'hoi4')

    def scan(self):
        self.service.analyze(self.id)
        return next(row for row in self.service.cache.browser.list(self.id)['entries'] if row['entry_key'] == 'key')

    def deploy(self):
        self.target.parent.mkdir(parents=True, exist_ok=True)
        self.target.write_bytes('\ufeffl_simp_chinese:\r\n key:0 "旧中文 $VALUE$" # note\r\n other:0 "另一中文"\r\n'.encode())

    def edit(self, row, text='修订中文 $VALUE$'):
        return self.service.edit_translation(self.id, row['entry_id'], text, row['chinese'])

    def test_cached_edit_persists_and_reuses_without_ai_or_deployment(self):
        row = self.scan()
        self.assertEqual(row['auto_status'], 'cached')
        result = self.edit(row)
        self.assertFalse(result['deployed'])
        self.assertFalse(self.target.exists())
        restarted = app.WorkshopService(self.service.data_dir)
        current = restarted.cache.browser.get(self.id, row['entry_id'])
        self.assertEqual(current['chinese'], '修订中文 $VALUE$')
        self.assertIn('手动修订', current['origin'])
        with self.service.connect() as db:
            old = db.execute('SELECT old_chinese,new_chinese,old_origin FROM translation_edits').fetchone()
        self.assertEqual(old, ('旧中文 $VALUE$', '修订中文 $VALUE$', '原汉化组'))
        result = self.service.translate(self.id, translator=lambda *args: self.fail('should reuse corrected cache'))
        self.assertIn('修订中文 $VALUE$', self.target.read_text(encoding='utf-8-sig'))

    def test_deployed_edit_keeps_format_backs_up_and_updates_aggregate(self):
        self.deploy()
        before = self.target.read_bytes()
        english = self.source.read_bytes()
        result = self.edit(self.scan())
        self.assertTrue(result['deployed'])
        self.assertEqual(self.target.read_bytes(), before.replace('旧中文'.encode(), '修订中文'.encode()))
        self.assertEqual(self.source.read_bytes(), english)
        with self.service.connect() as db:
            backup = db.execute('SELECT previous_files FROM deployments WHERE version_id=?', (result['version_id'],)).fetchone()
        self.assertIn(before, app.unarchive(backup[0]).values())
        aggregate = Path(result['aggregate']['path']) / 'localisation/simp_chinese/123_test_l_simp_chinese.yml'
        self.assertEqual(aggregate.read_bytes(), self.target.read_bytes())
        self.assertEqual(self.scan()['auto_status'], 'translated')

    def test_conflicts_and_stale_english_are_rejected(self):
        row = self.scan()
        with self.assertRaisesRegex(ValueError, '中文已变化'):
            self.service.edit_translation(self.id, row['entry_id'], '新 $VALUE$', 'outdated')
        self.source.write_bytes(self.source.read_bytes().replace(b'Alpha', b'Changed'))
        with self.assertRaisesRegex(ValueError, '英文原文件已变化'):
            self.edit(row)

    def test_invalid_variables_empty_or_multiline_change_nothing(self):
        self.deploy()
        before = self.target.read_bytes()
        row = self.scan()
        for text in ('删除变量', '', '一\n二 $VALUE$', '\ufeff中文 $VALUE$'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.edit(row, text)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.scan()['chinese'], '旧中文 $VALUE$')

    def test_external_chinese_changes_are_not_overwritten(self):
        self.deploy()
        row = self.scan()
        self.target.write_text('l_simp_chinese:\n key:0 "外部修订 $VALUE$"\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '本机中文文件已变化'):
            self.edit(row)
        self.assertIn('外部修订', self.target.read_text())

    def test_write_failure_keeps_original_cache_and_disk(self):
        self.deploy()
        row = self.scan()
        before = self.target.read_bytes()
        real = app.atomic_bytes
        def fail(path, data, **kwargs):
            if Path(path).resolve() == self.target.resolve():
                raise OSError('disk unavailable')
            return real(path, data, **kwargs)
        with patch.object(app, 'atomic_bytes', side_effect=fail), self.assertRaises(OSError):
            self.edit(row)
        self.assertEqual(self.target.read_bytes(), before)
        self.assertEqual(self.scan()['chinese'], '旧中文 $VALUE$')

    def test_noop_and_manual_status_do_not_enable_invalid_edit(self):
        row = self.scan()
        self.assertFalse(self.edit(row, row['chinese'])['saved'])
        self.source.write_text('l_english:\n new:0 "Fresh"\n', encoding='utf-8')
        self.service.analyze(self.id)
        row = self.service.cache.browser.list(self.id)['entries'][0]
        self.service.cache.browser.mark(self.id, row['entry_id'], 'translated')
        with self.assertRaisesRegex(ValueError, '仅可修改'):
            self.edit(row, '新中文')

    def test_eu4_revision_keeps_original_english_for_future_hash_checks(self):
        mod = self.library / 'steamapps/workshop/content/236850/456'
        source = mod / 'localisation/test_l_english.yml'
        source.parent.mkdir(parents=True)
        source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n other:0 "Beta"\n', encoding='utf-8-sig')
        original = source.read_bytes()
        with patch.object(app, 'steam_libraries', return_value=[self.library]):
            self.service.scan(lambda ids: {})
        identifier = '236850:456'
        self.service.translate(identifier, translator=lambda texts,*args: [{'text':'旧中文 $VALUE$' if '$VALUE$' in text else '其他中文','success':True} for text in texts])
        row = next(row for row in self.service.cache.browser.list(identifier)['entries'] if row['entry_key']=='key')
        self.assertEqual(row['auto_status'], 'translated')
        self.service.edit_translation(identifier, row['entry_id'], '修订中文 $VALUE$', row['chinese'])
        item = self.service.get_mod(identifier)
        self.assertEqual(self.service.original_sources(item)['localisation/test_l_english.yml'], original)
        row = self.service.cache.browser.get(identifier, row['entry_id'])
        self.assertEqual(row['auto_status'], 'translated')
        self.assertEqual(row['chinese'], '修订中文 $VALUE$')
