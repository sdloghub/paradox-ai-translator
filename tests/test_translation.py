import importlib.util
import os
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
# These tests work without the SDK and never make network requests.
sdk = types.ModuleType('openai')
sdk.OpenAI = Mock()
sdk.APIConnectionError = type('APIConnectionError', (Exception,), {})
sdk.APITimeoutError = type('APITimeoutError', (Exception,), {})

def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

with patch.dict(sys.modules, {'openai': sdk}):
    request = load('translation_request_test', 'request.py')
    request.load_sdk()
with patch.dict(sys.modules, {'request': request}):
    paradox = load('translation_paradox_test', 'paradox.py')
with patch.dict(sys.modules, {'paradox': paradox}):
    main = load('translation_main_test', 'main.py')

def reply(text):
    return types.SimpleNamespace(choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=text))])

class TranslationTests(unittest.TestCase):
    def call(self, texts, responses):
        client = Mock()
        client.chat.completions.create.side_effect = responses
        with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'test-only'}), patch.object(request, 'OpenAI', return_value=client), patch.object(request, 'findrule', return_value='rule'), patch.object(request.time, 'sleep'):
            result = request.request_deepseek_batch(texts, 'hoi4', 0, len(texts), pool_size=1)
        return result, client

    def test_batch_success(self):
        result, _ = self.call(['a', 'b'], [reply('甲\n---SEPARATOR---\n乙')])
        self.assertEqual([r['text'] for r in result], ['甲', '乙'])
        self.assertTrue(all(r['success'] for r in result))

    def test_bad_separator_retries_individually(self):
        result, _ = self.call(['a', 'b'], [reply('错误合并'), reply('甲'), ValueError('failure')])
        self.assertEqual(result[0]['text'], '甲')
        self.assertFalse(result[1]['success'])
        self.assertEqual(result[1]['text'], 'b')

    def test_connection_retry_limit(self):
        result, client = self.call(['a'], [sdk.APIConnectionError()] * 4)
        self.assertEqual(client.chat.completions.create.call_count, 4)
        self.assertFalse(result[0]['success'])

    def test_failure_is_retried_on_next_run(self):
        with tempfile.TemporaryDirectory() as directory:
            previous = os.getcwd()
            try:
                os.chdir(directory)
                old_root = paradox.ROOT
                paradox.ROOT = Path(directory)
                source = Path('localisation/hoi4/test.yml')
                source.parent.mkdir(parents=True)
                source.write_text('l_english:\n a:0 "Alpha"\n b:0 "Beta"\n', encoding='utf-8')
                first = [{'text': '阿尔法', 'success': True, 'error': None}, {'text': 'Beta', 'success': False, 'error': 'failure'}]
                with patch.object(request, 'request_deepseek_batch', return_value=first):
                    paradox.translate_para('hoi4/test.yml', 'hoi4')
                cache = Path('already/hoi4/test.yml.cache.json').read_text()
                self.assertIn('a:0', cache)
                self.assertNotIn('b:0', cache)
                self.assertIn('Beta', Path('chn/hoi4/test.yml').read_text())
                with patch.object(request, 'request_deepseek_batch', return_value=[{'text': '贝塔', 'success': True, 'error': None}]) as batch:
                    paradox.translate_para('hoi4/test.yml', 'hoi4')
                self.assertEqual(batch.call_args.args[0], ['Beta'])
                self.assertIn('贝塔', Path('already/hoi4/test.yml.cache.json').read_text())
            finally:
                paradox.ROOT = old_root
                os.chdir(previous)

    def test_source_change_invalidates_cache(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(paradox, 'ROOT', Path(directory)):
            source = Path(directory) / 'localisation/hoi4/test.yml'
            source.parent.mkdir(parents=True)
            source.write_text('l_english:\n a:0 "Alpha"\n')
            with patch.object(request, 'request_deepseek_batch', return_value=[{'text': '甲', 'success': True}]) as batch:
                paradox.translate_para('hoi4/test.yml', 'hoi4')
                paradox.translate_para('hoi4/test.yml', 'hoi4')
                self.assertEqual(batch.call_count, 1)
                source.write_text('l_english:\n a:0 "Changed"\n')
                paradox.translate_para('hoi4/test.yml', 'hoi4')
                self.assertEqual(batch.call_args.args[0], ['Changed'])

    def test_parser_preserves_comments_bom_and_escaped_quotes(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(paradox, 'ROOT', Path(directory)):
            source = Path(directory) / 'localisation/hoi4/test_l_english.yml'
            source.parent.mkdir(parents=True)
            text = '\ufeffl_english:\r\n  key:0 "Say \\"Hello\\"" # comment'
            source.write_bytes(text.encode('utf-8'))
            entries = paradox.extract(source, 'hoi4')
            self.assertEqual(entries, [('key:0 ', 'Say \\"Hello\\"')])
            paradox.outputs('hoi4/test_l_english.yml', {'key:0 ': paradox.Paradox_data('key:0 ', '说 \\"你好\\"', 1)}, 'hoi4')
            result = (Path(directory) / 'chn/hoi4/test_l_simp_chinese.yml').read_bytes().decode('utf-8')
            self.assertEqual(result, '\ufeffl_simp_chinese:\r\n  key:0 "说 \\"你好\\"" # comment')
            self.assertEqual(source.read_bytes().decode('utf-8'), text)

    def test_variable_corruption_is_not_successful(self):
        result, client = self.call(['Gain $VALUE$'], [reply('获得数值')] * 4)
        self.assertFalse(result[0]['success'])
        self.assertEqual(client.chat.completions.create.call_count, 4)
        self.assertTrue(request.valid_translation('Gain $VALUE$ §Ggold§!', '获得 $VALUE$ §G金币§!'))

    def test_failed_game_keeps_output_and_successful_game_replaces(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(paradox, 'ROOT', Path(directory)), patch.object(main, 'ROOT', Path(directory)):
            base = Path(directory)
            source = base / 'localisation/hoi4/test_l_english.yml'
            source.parent.mkdir(parents=True)
            source.write_text('l_english:\n a:0 "Alpha"\n')
            old = base / 'chn/hoi4/old.yml'
            old.parent.mkdir(parents=True)
            old.write_text('old output')
            with patch.object(request, 'request_deepseek_batch', return_value=[{'text': 'Alpha', 'success': False}]):
                self.assertFalse(main.translate_game('hoi4'))
            self.assertEqual(old.read_text(), 'old output')
            with patch.object(request, 'request_deepseek_batch', return_value=[{'text': '甲', 'success': True}]):
                self.assertTrue(main.translate_game('hoi4'))
            self.assertFalse(old.exists())
            self.assertIn('甲', (base / 'chn/hoi4/test_l_simp_chinese.yml').read_text())
            self.assertTrue(source.exists())

    def test_unparseable_entry_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'bad.yml'
            source.write_text(' key:0 "unclosed text\n')
            with self.assertRaisesRegex(ValueError, '无法解析'):
                paradox.extract(source, 'hoi4')

    def test_legacy_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(paradox, 'ROOT', Path(directory)):
            base = Path(directory)
            source = base / 'localisation/hoi4/test.yml'
            source.parent.mkdir(parents=True)
            source.write_text('l_english:\n a:0 "Alpha"\n')
            legacy = base / 'already/hoi4/test.yml'
            legacy.parent.mkdir(parents=True)
            legacy.write_text(' a:0 "旧译文"\n')
            with patch.object(request, 'request_deepseek_batch', return_value=[{'text': '新译文', 'success': True}]) as batch:
                paradox.translate_para('hoi4/test.yml', 'hoi4')
            self.assertEqual(batch.call_args.args[0], ['Alpha'])
            self.assertIn('旧译文', legacy.read_text())

if __name__ == '__main__':
    unittest.main()
