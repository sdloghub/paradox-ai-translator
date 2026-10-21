import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import paradox
import request
from translation_cache import entries


class BugBranchTests(unittest.TestCase):
    def test_duplicate_closing_quote_scans_and_translates_identically(self):
        raw = 'l_english:\n CIVILIAN_OUTPUT_MAT: "$TABBED_NEW_LINE$- $r_research$""\n'
        parsed = entries({'bugged_file_l_english.yml': raw.encode()}, 'st')
        self.assertEqual(len(parsed), 1)
        self.assertEqual(parsed[0]['text'], '$TABBED_NEW_LINE$- $r_research$')
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'localisation/st/bugged_file_l_english.yml'
            source.parent.mkdir(parents=True)
            source.write_text(raw, encoding='utf-8')
            def translator(texts, *args):
                return [{'text': text, 'success': True} for text in texts]
            self.assertEqual(paradox.translate_para('st/bugged_file_l_english.yml', 'st',
                             project_root=root, translator=translator), 0)
            output = (root / 'chn/st/bugged_file_l_simp_chinese.yml').read_text('utf-8')
            self.assertIn('l_simp_chinese:', output)
            self.assertNotIn('""', output)
            self.assertEqual(source.read_text('utf-8'), raw)

    def test_other_malformed_lines_fail_scan_with_file_and_line(self):
        with self.assertRaisesRegex(paradox.LocalisationError, 'bad.yml:2'):
            entries({'bad.yml': b'l_english:\n key:0 "unterminated\n'}, 'st')

    def test_tolerant_translation_preserves_bad_line_and_reports_number(self):
        raw = 'l_english:\n bad:0 "Unclosed\n good:0 "Hello"\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'localisation/st/test_l_english.yml'
            source.parent.mkdir(parents=True)
            source.write_text(raw, encoding='utf-8')
            issues = []
            paradox.translate_para('st/test_l_english.yml', 'st', project_root=root,
                issues=issues, translator=lambda texts, *args: [{'text': '你好', 'success': True} for text in texts])
            output = (root / 'chn/st/test_l_simp_chinese.yml').read_text('utf-8')
            self.assertIn(' bad:0 "Unclosed\n', output)
            self.assertIn(' good:0 "你好"', output)
            self.assertEqual([issue['line'] for issue in issues], [2])
            self.assertEqual(issues[0]['original_line'], ' bad:0 "Unclosed')
            self.assertEqual(source.read_text('utf-8'), raw)

    def test_common_prompt_keeps_distinct_game_guidance(self):
        rules = json.loads((Path(request.__file__).parent / 'rules.json').read_text('utf-8'))
        self.assertEqual(set(rules), {'common', 'games', 'languages'})
        with patch.object(request, '_RULES_CACHE', None):
            for game in ('st', 'hoi4', 'eu4', 'ck3', 'vic3', 'para'):
                prompt = request.findrule(game)
                self.assertIn(rules['common'], prompt)
                self.assertIn(rules['games'][game]['name'], prompt)
                self.assertIn(rules['games'][game]['guidance'], prompt)

    def test_repeated_key_failure_reports_each_original_line(self):
        raw = 'l_english:\n same:0 "First"\n same:0 "Second"\n'
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'localisation/st/test_l_english.yml'
            source.parent.mkdir(parents=True)
            source.write_text(raw, encoding='utf-8')
            issues = []
            paradox.translate_para('st/test_l_english.yml', 'st', project_root=root, issues=issues,
                translator=lambda texts, *args: [{'text': text, 'success': False} for text in texts])
            self.assertEqual([p['line'] for p in issues], [2, 3])
            self.assertEqual([p['original_line'] for p in issues], raw.splitlines()[1:])
            output = (root / 'chn/st/test_l_simp_chinese.yml').read_text('utf-8')
            self.assertEqual(output, raw.replace('l_english:', 'l_simp_chinese:'))


if __name__ == '__main__':
    unittest.main()
