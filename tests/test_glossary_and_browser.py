"""Tests for glossary workflow modes, word-cloud scanning, import extraction, server memory caps, and browser engine."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import glossary
import workshop_app as app


class GlossaryAndBrowserTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.service = app.WorkshopService(self.root / 'data', demo=True)
        self.library = self.root / 'SteamLibrary'
        self.service.demo_library = self.library
        self.mod = self.library / 'steamapps/workshop/content/281990/555'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text(
            'l_english:\n'
            ' k1:0 "Galactic Empire"\n'
            ' k2:0 "Galactic Empire"\n'
            ' k3:0 "Supreme Council"\n'
            ' k4:0 "The Supreme Council rules the Galactic Empire with $VALUE$ Fleet Power and Fleet Power."\n'
            ' k5:0 "Long description with Imperial Armada and Imperial Armada appearing twice in text."\n',
            encoding='utf-8'
        )
        (self.mod / 'descriptor.mod').write_text('name="Glossary Test Mod"\n', encoding='utf-8')
        self.service.scan(lambda ids: {})
        self.identifier = '281990:555'

    def test_short_keys_vs_long_extract_and_ai_approve(self):
        # 1. Short keys (<5 words) priority scan
        short_res = self.service.scan_glossary(self.identifier, extract_mode='short_keys', approval_mode='manual', min_count=2)
        short_terms = {t['term']: t for t in short_res['terms']}
        self.assertIn('Galactic Empire', short_terms)
        self.assertIn('Supreme Council', short_terms)
        self.assertNotIn('Imperial Armada', short_terms)
        self.assertEqual(short_res['settings']['workflow_mode'], 'glossary')
        self.assertEqual(short_res['settings']['extract_mode'], 'short_keys')

        # 2. Long key extraction includes proper phrases / repeated words from >=5 word entries
        long_res = self.service.scan_glossary(self.identifier, extract_mode='long_extract', approval_mode='manual', min_count=2)
        long_terms = {t['term']: t for t in long_res['terms']}
        self.assertIn('Galactic Empire', long_terms)
        self.assertIn('Imperial Armada', long_terms)
        self.assertIn('Fleet Power', long_terms)

        # 3. AI auto-approval fills translations and marks approved
        ai_res = self.service.scan_glossary(self.identifier, extract_mode='ai_extract', approval_mode='ai_approve', min_count=2)
        ai_terms = {t['term']: t for t in ai_res['terms']}
        self.assertTrue(ai_terms['Galactic Empire']['approved'])
        self.assertEqual(ai_terms['Galactic Empire']['translation'], '银河帝国')

    def test_exported_package_direct_glossary_extraction(self):
        # Translate and save glossary on source service, then export package
        self.service.save_glossary(
            self.identifier,
            terms=[{'term': 'Galactic Empire', 'translation': '银河帝国', 'count': 3, 'enabled': True, 'approved': True}],
            workflow_mode='glossary',
        )
        self.service.translate(self.identifier, workflow_mode='glossary', extract_mode='short_keys', approval_mode='ai_approve')
        pkg_bytes = self.service.export_package(self.identifier)
        pkg_path = self.root / 'exported_package.zip'
        pkg_path.write_bytes(pkg_bytes)

        # Import into a fresh service and verify glossary is directly extracted without AI
        other = app.WorkshopService(self.root / 'other_data', demo=False)
        other.save_config({'steam_libraries': [str(self.library)]})
        other.scan(lambda ids: {})
        res = other.import_cache(self.identifier, str(pkg_path), provider='导出包测试', extract_glossary_ai=False)
        self.assertGreater(res['glossary_extracted'], 0)
        terms = {t['term']: t['translation'] for t in other.glossary.list_terms(self.identifier)}
        self.assertEqual(terms.get('Galactic Empire'), '银河帝国')

    def test_pure_yml_import_ai_extraction_switch(self):
        yml_path = self.root / 'pure_chinese.yml'
        yml_path.write_text(
            'l_simp_chinese:\n'
            ' k1:0 "银河帝国"\n'
            ' k2:0 "银河帝国"\n'
            ' k3:0 "最高议会"\n'
            ' k4:0 "最高议会统治着银河帝国并拥有 $VALUE$ 舰队实力。"\n'
            ' k5:0 "帝国无敌舰队与帝国无敌舰队在长句中重复出现。"\n',
            encoding='utf-8'
        )
        # With extract_glossary_ai=False on pure YML, glossary is not extracted
        other1 = app.WorkshopService(self.root / 'yml_no_ai', demo=True)
        other1.demo_library = self.library
        other1.scan(lambda ids: {})
        res_off = other1.import_cache(self.identifier, str(yml_path), extract_glossary_ai=False)
        self.assertEqual(res_off['glossary_extracted'], 0)

        # With extract_glossary_ai=True on pure YML, repeated Chinese terms are extracted into glossary
        other2 = app.WorkshopService(self.root / 'yml_with_ai', demo=True)
        other2.demo_library = self.library
        other2.scan(lambda ids: {})
        res_on = other2.import_cache(self.identifier, str(yml_path), extract_glossary_ai=True)
        self.assertGreater(res_on['glossary_extracted'], 0)
        terms = other2.glossary.list_terms(self.identifier)
        translations = {t['translation'] for t in terms}
        self.assertIn('银河帝国', translations)

    def test_server_mode_memory_caps_vs_local_unlimited(self):
        # Local mode has no limit even when SERVER_MAX_SCAN_ENTRIES is patched to 2
        with patch.object(glossary, 'SERVER_MAX_SCAN_ENTRIES', 2):
            counts = self.service.analyze(self.identifier)
            self.assertEqual(counts['total'], 5)

        # Web server_mode enforces memory & entry caps on both analyze and glossary scan
        self.service.server_mode = True
        try:
            with patch.object(glossary, 'SERVER_MAX_SCAN_ENTRIES', 2):
                with self.assertRaisesRegex(ValueError, '网页版内存保护'):
                    self.service.analyze(self.identifier)
                with self.assertRaisesRegex(ValueError, '网页版内存保护'):
                    self.service.scan_glossary(self.identifier, extract_mode='short_keys')
            with patch.object(glossary, 'SERVER_MAX_SCAN_BYTES', 10):
                with self.assertRaisesRegex(ValueError, '网页版内存保护'):
                    self.service.analyze(self.identifier)
        finally:
            self.service.server_mode = False

    def test_glossary_prompt_injected_into_request_batch(self):
        prompt = glossary.format_glossary_prompt_for_batch(
            ['The Supreme Council rules the Galactic Empire.'],
            {'Galactic Empire': '银河帝国', 'Supreme Council': '最高议会', 'Unused Term': '未使用'},
            'zh-CN'
        )
        self.assertIn('Galactic Empire = 银河帝国', prompt)
        self.assertIn('Supreme Council = 最高议会', prompt)
        self.assertNotIn('Unused Term', prompt)

    def test_browser_js_and_ts_files_exist_and_expose_functions(self):
        root = Path(app.__file__).parent
        js_file = root / 'browser_translator.js'
        ts_file = root / 'browser_translator.ts'
        self.assertTrue(js_file.is_file())
        self.assertTrue(ts_file.is_file())
        js_text = js_file.read_text(encoding='utf-8')
        ts_text = ts_file.read_text(encoding='utf-8')
        for fn in ('extractGlossaryCandidates', 'extractGlossaryFromPackagePairs',
                   'extractChineseRepeatsLocal', 'formatGlossaryPromptForBatch', 'parseYmlEntries'):
            self.assertIn(fn, js_text)
            self.assertIn(fn, ts_text)


if __name__ == '__main__':
    unittest.main()
