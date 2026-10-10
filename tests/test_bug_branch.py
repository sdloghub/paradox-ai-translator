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

    def test_common_prompt_keeps_distinct_game_guidance(self):
        rules = json.loads((Path(request.__file__).parent / 'rules.json').read_text('utf-8'))
        self.assertEqual(set(rules), {'common', 'games'})
        with patch.object(request, '_RULES_CACHE', None):
            for game in ('st', 'hoi4', 'eu4', 'ck3', 'vic3', 'para'):
                prompt = request.findrule(game)
                self.assertIn(rules['common'], prompt)
                self.assertIn(rules['games'][game]['name'], prompt)
                self.assertIn(rules['games'][game]['guidance'], prompt)


if __name__ == '__main__':
    unittest.main()
