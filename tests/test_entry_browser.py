import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workshop_app as app
from translation_cache import entries


class EntryBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.service = app.WorkshopService(self.root / 'data')
        self.library = self.root / 'SteamLibrary'
        self.mod = self.library / 'steamapps/workshop/content/394360/123'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('l_english:\n deployed:0 "Alpha $VALUE$"\n cached:0 "Beta"\n pending:0 "Gamma"\n stale:0 "New"\n malformed:0 "Bad" broken\n blank:0 ""\n repeated:0 "One"\n repeated:0 "Two"\n', encoding='utf-8')
        self.service.save_config({'steam_libraries': [str(self.library)]})
        with patch.object(app, 'steam_libraries', return_value=[self.library]):
            self.item = self.service.scan(lambda ids: {})[0]
        self.identifier = self.item['id']
        self.browser = self.service.cache.browser

    def scan(self):
        self.service.analyze(self.identifier)
        return self.browser.list(self.identifier)

    def row(self, key):
        return next(row for row in self.browser.list(self.identifier)['entries'] if row['entry_key'] == key)

    def test_auto_statuses_and_source_line_details(self):
        data = self.service.original_sources(self.item)
        parsed = {entry['key'].split(':')[0]: entry for entry in entries(data, 'hoi4', strict=False)}
        with self.service.connect() as db:
            self.service.cache.put(db, self.identifier, parsed['deployed'], '阿尔法 $VALUE$', '测试来源')
            self.service.cache.put(db, self.identifier, parsed['cached'], '贝塔', '测试来源')
            self.service.cache.put(db, self.identifier, {**parsed['stale'], 'text':'Old'}, '旧中文', '旧来源')
        target = self.mod / app.target_path(next(iter(data)), 'hoi4')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('l_simp_chinese:\n deployed:0 "阿尔法 $VALUE$"\n', encoding='utf-8')
        result = self.scan()
        self.assertEqual(result['counts'], {'translated':1, 'cached':1, 'untranslated':1, 'needs_update':1, 'format_error':3})
        self.assertEqual(self.row('deployed')['chinese'], '阿尔法 $VALUE$')
        self.assertEqual(self.row('cached')['origin'], '测试来源')
        self.assertEqual(self.row('stale')['historical'], 1)
        self.assertEqual(self.row('stale')['chinese'], '旧中文')
        bad = self.row('malformed')
        self.assertEqual(bad['line'], 6)
        self.assertEqual(bad['original_line'], ' malformed:0 "Bad" broken')
        self.assertEqual(self.item['counts']['skipped_blank'], 1)

    def test_mark_survives_restart_and_rescan_without_changing_cache(self):
        self.scan()
        entry = self.row('pending')
        self.browser.mark(self.identifier, entry['entry_id'], 'translated')
        restarted = app.WorkshopService(self.root / 'data')
        row = restarted.cache.browser.list(self.identifier, 'translated')['entries'][0]
        self.assertEqual(row['auto_status'], 'untranslated')
        self.assertEqual(row['manual_status'], 'translated')
        self.scan()
        self.assertEqual(self.row('pending')['manual_status'], 'translated')
        with self.service.connect() as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM translation_entries').fetchone()[0], 0)
        self.assertEqual(self.item['counts']['deployed'], 1)

    def test_changed_english_invalidates_mark_but_shifted_lines_do_not(self):
        self.scan()
        before = self.row('pending')
        self.browser.mark(self.identifier, before['entry_id'], 'cached')
        self.source.write_text('# inserted comment\n' + self.source.read_text(), encoding='utf-8')
        self.scan()
        self.assertEqual(self.row('pending')['manual_status'], 'cached')
        self.assertEqual(self.row('pending')['line'], before['line'] + 1)
        self.source.write_text(self.source.read_text().replace('"Gamma"', '"Changed"'), encoding='utf-8')
        self.scan()
        self.assertIsNone(self.row('pending')['manual_status'])
        with self.assertRaisesRegex(ValueError, '已变化'):
            self.browser.mark(self.identifier, before['entry_id'], 'translated')

    def test_duplicate_keys_have_distinct_marks_and_mods_are_isolated(self):
        self.scan()
        rows = self.browser.list(self.identifier, query='repeated')['entries']
        self.assertEqual(len(rows), 2)
        self.assertNotEqual(rows[0]['entry_id'], rows[1]['entry_id'])
        self.browser.mark(self.identifier, rows[0]['entry_id'], 'format_error')
        self.assertEqual(self.browser.list(self.identifier, 'format_error')['total'], 3)
        with self.assertRaises(ValueError):
            self.browser.mark('another-mod', rows[0]['entry_id'], 'cached')

    def test_pagination_search_clear_and_no_file_reads(self):
        self.scan()
        entry = self.row('pending')
        self.browser.mark(self.identifier, entry['entry_id'], 'translated')
        with patch.object(Path, 'read_bytes', side_effect=AssertionError('browser must use index')):
            result = self.browser.list(self.identifier, 'translated', 'gAmMa', page_size=1)
            self.assertEqual(result['total'], 1)
            self.assertEqual(result['entries'][0]['entry_key'], 'pending')
            self.assertEqual(self.browser.list(self.identifier, page=999, page_size=2)['page'], 4)
        self.browser.mark(self.identifier, entry['entry_id'], None)
        self.assertEqual(self.browser.list(self.identifier, 'translated')['total'], 0)
        self.assertEqual(self.browser.list(self.identifier, query='%')['total'], 0)
        self.assertEqual(self.browser.list(self.identifier, query='english/test')['total'], 7)

    def test_scan_required_and_bad_inputs_rejected(self):
        self.assertFalse(self.browser.list(self.identifier)['ready'])
        for kwargs in [{'page':0}, {'page':True}, {'page_size':500}, {'status':'invalid'}, {'query':[]}, {'query':'x'*257}]:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.browser.list(self.identifier, **kwargs)
        with self.assertRaises(ValueError):
            self.browser.mark(self.identifier, 'not-an-id', 'translated')

    def test_restore_refreshes_cached_entries_to_deployed(self):
        self.source.write_text(self.source.read_text().replace(' repeated:0 "One"\n repeated:0 "Two"\n', ''), encoding='utf-8')
        translator = lambda texts, *args: [{'text':'中文：' + text, 'success':True} for text in texts]
        result = self.service.translate(self.identifier, translator=translator, deploy=False)
        self.assertGreater(self.browser.list(self.identifier, 'cached')['total'], 0)
        self.service.restore(result['version_id'], self.identifier)
        self.assertEqual(self.browser.list(self.identifier, 'cached')['total'], 0)
        self.assertEqual(self.browser.list(self.identifier, 'translated')['total'], 4)
        cleared = self.service.clear_translations(self.identifier)
        self.assertEqual(cleared['cleared_files'], 1)
        self.assertEqual(self.item['counts']['deployed'], 0)
        self.assertEqual(self.item['counts']['cached'], 4)

    def test_edit_fixes_error_rescans_and_backs_up_full_original(self):
        self.scan()
        row = self.row('malformed')
        before = self.source.read_bytes()
        result = self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 "Fixed"')
        self.assertFalse(result['parse_error'])
        self.assertEqual(result['counts']['parse_errors'], 2)
        self.assertEqual(Path(result['backup_path']).read_bytes(), before)
        self.assertEqual(self.source.read_bytes(), before.replace(b' malformed:0 "Bad" broken', b' malformed:0 "Fixed"'))
        self.assertEqual(self.row('malformed')['english'], 'Fixed')
        self.assertEqual(self.row('malformed')['auto_status'], 'untranslated')

    def test_edit_still_malformed_without_quotes_is_reported(self):
        self.scan()
        row = self.row('malformed')
        result = self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 Missing quotes')
        self.assertTrue(result['parse_error'])
        self.assertEqual(result['counts']['parse_errors'], 3)
        self.assertEqual(self.row('malformed')['line'], 6)
        self.assertEqual(self.row('malformed')['original_line'], ' malformed:0 Missing quotes')

    def test_edit_preserves_bom_crlf_and_missing_final_newline(self):
        for ending in ('\r\n', ''):
            with self.subTest(ending=ending):
                original = b'\xef\xbb\xbf' + ('l_english:\r\n bad:0 "Broken" tail' + ending).encode()
                self.source.write_bytes(original)
                self.scan()
                row = self.row('bad')
                self.service.edit_entry(self.identifier, row['entry_id'], ' bad:0 "Fixed"')
                self.assertEqual(self.source.read_bytes(), original.replace(b'"Broken" tail', b'"Fixed"'))

    def test_edit_rejects_external_changes_and_multiline_input(self):
        self.scan()
        row = self.row('malformed')
        for text in ['a\nb', 'a\rb', 'a\x00b', 'a\u2028b', 'x'*16001, None]:
            with self.subTest(text=repr(text)[:30]), self.assertRaises(ValueError):
                self.service.edit_entry(self.identifier, row['entry_id'], text)
        changed = self.source.read_bytes().replace(b'"Bad" broken', b'"Changed elsewhere"')
        self.source.write_bytes(changed)
        with self.assertRaisesRegex(ValueError, '已在其他位置修改'):
            self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 "Fixed"')
        self.assertEqual(self.source.read_bytes(), changed)

    def test_edit_rejects_symlink_and_parent_traversal(self):
        self.scan()
        row = self.row('malformed')
        outside = self.root / 'outside.yml'
        original = self.source.read_bytes()
        outside.write_bytes(original)
        self.source.unlink()
        self.source.symlink_to(outside)
        with self.assertRaisesRegex(ValueError, '符号链接'):
            self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 "Fixed"')
        self.assertEqual(outside.read_bytes(), original)
        with self.service.connect() as db:
            db.execute('UPDATE browsable_entries SET source_file=? WHERE entry_id=?', ('../outside.yml', row['entry_id']))
        with self.assertRaisesRegex(ValueError, '路径无效'):
            self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 "Fixed"')

    def test_edit_refuses_to_overwrite_deployed_eu4_chinese(self):
        self.scan()
        row = self.row('malformed')
        self.item['game'] = 'eu4'
        original = self.source.read_bytes()
        with patch.object(self.service, 'original_sources', return_value={row['source_file']:b'other original'}):
            with self.assertRaisesRegex(ValueError, '回写后的中文'):
                self.service.edit_entry(self.identifier, row['entry_id'], ' malformed:0 "Fixed"')
        self.assertEqual(self.source.read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
