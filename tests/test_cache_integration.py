"""Regressions for the cached entries and malformed markers seen in real Mods."""
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_entry_browser as fixtures
import paradox
import request
from translation_cache import entries, candidates
import workshop_app as app


class CacheIntegrationTests(unittest.TestCase):
    setUp = fixtures.EntryBrowserTests.setUp

    def test_history_requires_scan_again_after_restart(self):
        self.assertNotIn(self.identifier, self.service.analyzed_mod_ids)
        self.service.analyze(self.identifier)
        self.assertIn(self.identifier, self.service.analyzed_mod_ids)
        restarted = app.WorkshopService(self.service.data_dir)
        self.assertNotIn(self.identifier, restarted.analyzed_mod_ids)

    def test_import_can_replace_invalid_english_cache_and_normalizes_quotes(self):
        self.source.write_text('l_english:\n key:0 "Say \\"hello\\""\n', encoding='utf-8')
        sources = self.service.original_sources(self.item)
        source = entries(sources, 'hoi4')[0]
        with self.service.connect() as db:
            self.service.cache.put(db, self.identifier, source, source['text'], '旧错误缓存')
        result = self.service.cache.import_candidates(self.item, sources,
            [{**source, 'text':'说 "你好"'}], '导入修复')
        self.assertEqual(result['imported'], 1)
        self.service.translate(self.identifier, translator=Mock(side_effect=AssertionError('must reuse import')))
        self.assertEqual(self.item['counts']['deployed'], 1)
        self.assertEqual(self.item['counts']['cached'], 0)

    def test_token_only_cache_with_chinese_is_actually_deployed(self):
        self.source.write_text('l_english:\n councilor:0 "£logo£ $COUNCILOR$"\n', encoding='utf-8')
        source = entries(self.service.original_sources(self.item), 'hoi4')[0]
        chinese = '£logo£代理$COUNCILOR$'
        with self.service.connect() as db:
            self.service.cache.put(db, self.identifier, source, chinese, '手动导入')
        self.service.analyze(self.identifier)
        self.assertEqual(self.item['counts']['cached'], 1)
        no_api = Mock(side_effect=AssertionError('valid cache must not call AI'))
        self.service.translate(self.identifier, translator=no_api)
        self.assertEqual(self.item['counts']['cached'], 0)
        self.assertEqual(self.item['counts']['deployed'], 1)
        output = self.mod / app.target_path(source['source_file'], 'hoi4')
        self.assertIn(chinese, output.read_text('utf-8-sig'))
        self.service.select_cache(self.identifier, False)
        self.assertEqual(self.item['counts']['deployed'], 1)
        no_api.assert_not_called()

    def test_duplicates_are_errors_and_preserved_until_key_edit(self):
        self.source.write_text('l_english:\n same:0 "First"\n same:0 "Second"\n', encoding='utf-8')
        self.service.analyze(self.identifier)
        rows = self.service.cache.browser.list(self.identifier, 'format_error')['entries']
        self.assertEqual([r['line'] for r in rows], [2, 3])
        self.assertTrue(all('第 2 行' in r['reason'] and '第 3 行' in r['reason'] for r in rows))
        no_api = Mock(side_effect=AssertionError('duplicates must not reach AI'))
        result = self.service.translate(self.identifier, translator=no_api)
        no_api.assert_not_called()
        self.assertEqual(result['error_lines'], 2)
        target = self.mod / app.target_path(rows[0]['source_file'], 'hoi4')
        self.assertIn(' same:0 "First"', target.read_text('utf-8-sig'))
        self.service.analyze(self.identifier)
        row = self.service.cache.browser.list(self.identifier, 'format_error')['entries'][1]
        fixed = self.service.edit_key(self.identifier, row['entry_id'], 'unique_second')
        self.assertFalse(fixed['parse_error'])
        self.assertEqual(fixed['counts']['parse_errors'], 0)
        self.assertTrue(Path(fixed['backup_path']).is_file())
        result = self.service.translate(self.identifier, translator=lambda texts,*args:[
            {'text':{'First':'第一','Second':'第二'}[t], 'success':True} for t in texts])
        self.assertEqual(result['error_lines'], 0)
        self.assertEqual(self.item['counts']['deployed'], 2)

    def test_identical_duplicates_merge_and_translate_all_locations(self):
        self.source.write_text('l_english:\n same:0 "First"\n same:1 "First"\n', encoding='utf-8')
        other = self.source.with_name('other_l_english.yml')
        other.write_text('l_english:\n same:0 "First"\n', encoding='utf-8')
        counts = self.service.analyze(self.identifier)
        self.assertEqual(counts['parse_errors'], 0)
        self.assertEqual(counts['total'], 1)
        self.assertEqual(counts['untranslated'], 1)
        translator = Mock(side_effect=lambda texts, *args: [
            {'text': '第一', 'success': True} for text in texts])
        result = self.service.translate(self.identifier, translator=translator)
        self.assertEqual(result['error_lines'], 0)
        self.assertEqual(sum(len(call.args[0]) for call in translator.call_args_list), 1)
        self.assertEqual(self.item['counts']['total'], 1)
        self.assertEqual(self.item['counts']['deployed'], 1)
        outputs = [self.mod / app.target_path(str(path.relative_to(self.mod)), 'hoi4')
                   for path in (self.source, other)]
        self.assertEqual(sum(path.read_text('utf-8-sig').count('第一') for path in outputs), 3)

    def test_duplicates_across_files_and_versions_are_all_reported(self):
        self.source.write_text('l_english:\n same:0 "First"\n', encoding='utf-8')
        other = self.source.with_name('other_l_english.yml')
        other.write_text('l_english:\n same:1 "Second"\n', encoding='utf-8')
        result = self.service.analyze(self.identifier)
        self.assertEqual(result['parse_errors'], 2)
        self.assertEqual(result['total'], 2)
        self.assertTrue(all('other_l_english.yml' in r['reason'] and 'test_l_english.yml' in r['reason'] for r in result['issues']))



class ProtectedTranslationTests(unittest.TestCase):
    def test_malformed_colour_closer_and_bare_marker_survive_retry(self):
        for original in ('produce £unity£ §YUnity§.', 'Eruption on §Y[From.GetName]§'):
            with self.subTest(original=original):
                client = Mock()
                def respond(**kwargs):
                    text = kwargs['messages'][-1]['content']
                    if '⟦WT' in text:
                        value = text.replace('produce', '生产').replace('Unity', '凝聚力').replace('Eruption on', '爆发于')
                    else:
                        value = original.replace('§.', '§!')
                        if value.endswith('§'):
                            value += '!'
                    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=value))])
                client.chat.completions.create.side_effect = respond
                with patch.object(request, 'load_sdk'), patch.object(request, 'OpenAI', return_value=client):
                    result = request.request_deepseek_batch([original], 'st', 0, 1,
                        pool_size=1, config={'api_key':'test-only'})[0]
                self.assertTrue(result['success'])
                self.assertTrue(request.valid_translation(original, result['text']))
                self.assertEqual(client.chat.completions.create.call_count, 3)
                self.assertNotEqual(result['text'], original)

    def test_escapes_are_protected_as_whole_sequences_and_not_silently_changed(self):
        original = r'Text \\n\n\"quote\"'
        masked, tokens = request.protect_tokens(original)
        self.assertIn(r'\\n', tokens.values())
        self.assertEqual(request.restore_tokens(masked, tokens), original)
        with self.assertRaises(request.ProtectedTokenError):
            request.restore_tokens(masked + next(iter(tokens)), tokens)
        self.assertFalse(request.valid_translation(original, original.replace(r'\\n', r'\\x')))

    def test_new_quote_escape_cannot_be_cached_then_differ_on_disk(self):
        self.assertFalse(request.valid_translation('English text', '中文 "引号"'))
        self.assertTrue(request.valid_translation(r'Say \"hello\"', '说 "你好"'))
        self.assertEqual(request.output_text('说 "你好"'), r'说 \"你好\"')

    def test_english_only_reply_is_not_a_finished_chinese_translation(self):
        self.assertFalse(request.valid_translation('Gain 0.25 $VALUE$', 'Gain 0.75 $VALUE$'))
        self.assertFalse(request.valid_translation('Hello', 'Hello'))
        self.assertTrue(request.valid_translation('$VALUE$', '$VALUE$'))


if __name__ == '__main__':
    unittest.main()
