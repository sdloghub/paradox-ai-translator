"""Language changes must not leak translations or damage English originals."""
import concurrent.futures
import http.client
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import localization
import request
import workshop_app as app
from server_sessions import contributions, public_database
from translation_cache import candidates


class LanguageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.base = app.WorkshopService(root / 'data')
        self.library = root / 'SteamLibrary'
        self.mod = self.library / 'steamapps/workshop/content/281990/123'
        self.source = self.mod / 'localisation/english/test_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('l_english:\n key:0 "New beginning $VALUE$"\n', encoding='utf-8')
        (self.mod / 'descriptor.mod').write_text('name="Original"\n')
        self.original = self.source.read_bytes()
        self.base.save_config({'steam_libraries': [str(self.library)]})
        self.base.scan(lambda ids: {})
        self.identifier = '281990:123'

    def translated(self, service, value):
        translator = Mock(return_value=[{'text': value, 'success': True}])
        result = service.translate(self.identifier, translator=translator)
        self.assertEqual(result['error_lines'], 0)
        translator.assert_called_once()
        return result

    def test_languages_are_isolated_and_exports_match_the_target(self):
        self.translated(self.base, '新的开始 $VALUE$')
        outputs = []
        for language, value, slot in [('zh-TW', '新的開始 $VALUE$', 'simp_chinese'),
                                      ('ru', 'Новое начало $VALUE$', 'russian')]:
            service = localization.workspace(self.base, language)
            self.assertEqual(service.config()['target_language'], language)
            self.assertNotEqual(service.database, self.base.database)
            counts = service.analyze(self.identifier)
            self.assertEqual(counts['untranslated'], 1)
            self.assertEqual(counts['translated'], 0)
            self.translated(service, value)
            self.assertEqual(service.get_mod(self.identifier)['counts']['deployed'], 1)
            files = app.unarchive(service.export_package(self.identifier))
            yml = next(data.decode('utf-8-sig') for name, data in files.items() if name.endswith('.yml'))
            self.assertTrue(any('/' + slot + '/' in name for name in files))
            self.assertIn('l_' + slot + ':', yml)
            self.assertIn(value, yml)
            payload = json.loads(next(data for name, data in files.items() if name.endswith('.cache.json')))
            self.assertEqual(payload['target_language'], language)
            result = service.generate_mod(self.identifier, introduction='Manual description')
            outputs.append(result['mod_path'])
            self.assertEqual(json.loads((Path(result['mod_path']) / 'source-manifest.json').read_text())['target_language'], language)
        self.assertNotEqual(*outputs)
        self.assertEqual(self.source.read_bytes(), self.original)
        self.assertEqual(localization.current_language(), 'zh-CN')

    def test_exported_cache_cannot_be_imported_into_a_different_language(self):
        self.translated(self.base, '新的开始 $VALUE$')
        package = Path(self.temp.name) / 'simplified.zip'
        package.write_bytes(self.base.export_package(self.identifier))
        traditional = localization.workspace(self.base, 'zh-TW')
        result = traditional.import_cache(self.identifier, str(package))
        self.assertEqual(result['imported'], 0)
        self.assertEqual(traditional.analyze(self.identifier)['translated'], 0)

    def test_parallel_language_context_and_token_validation(self):
        ru = localization.workspace(self.base, 'ru')
        tw = localization.workspace(self.base, 'zh-TW')
        def inspect(service):
            return service.config()['target_language'], service.source_label('test'), service.analyze(self.identifier)['total']
        with concurrent.futures.ThreadPoolExecutor(2) as pool:
            results = list(pool.map(inspect, (ru, tw)))
        self.assertEqual([row[0] for row in results], ['ru', 'zh-TW'])
        self.assertTrue(request.valid_translation('Hello $VALUE$', 'Привет $VALUE$', 'ru'))
        self.assertFalse(request.valid_translation('Hello $VALUE$', 'Привет', 'ru'))
        self.assertFalse(request.valid_translation('Hello', '你好', 'ru'))
        self.assertFalse(request.valid_translation('Hello', 'Привет', 'zh-CN'))
        self.assertEqual(localization.current_language(), 'zh-CN')

    def test_prompts_differ_and_keep_protection_and_game_guidance(self):
        for game in ('st', 'hoi4', 'eu4', 'ck3', 'vic3', 'para'):
            prompts = [request.findrule(game, code) for code in localization.LANGUAGES]
            self.assertEqual(len(set(prompts)), 3)
            for prompt in prompts:
                for token in ('---SEPARATOR---', '$VALUE', '[', '£', '§', '\\n'):
                    self.assertIn(token, prompt)
            self.assertIn('русский', request.findrule(game, 'ru'))
            self.assertIn('繁體中文', request.findrule(game, 'zh-TW'))
        with self.assertRaises(ValueError):
            request.findrule('st', 'en')

    def test_shared_records_are_partitioned_by_language(self):
        ru = localization.workspace(self.base, 'ru')
        ru.server_root = self.base
        with public_database(self.base) as db:
            db.execute('INSERT INTO contributions VALUES (1,?,?,?,?,?,?,?,?,?)',
                       (self.identifier, 'test', 'author', 'model', 0, 'now', 'test', 1, b'zip'))
        self.assertEqual(len(contributions(self.base)), 1)
        self.assertEqual(contributions(ru), [])

    def test_runtime_catalog_and_release_files_are_complete(self):
        root = Path(app.__file__).parent
        catalogs = json.loads((root / 'ui_languages.json').read_text())
        self.assertEqual(set(catalogs), set(localization.LANGUAGES))
        for language in ('ru', 'zh-TW'):
            self.assertTrue(all(catalogs[language].get(text) for text in
                ('开始 AI 翻译', '扫描此 Mod', '导入译文', '生成翻译 Mod', 'API 与 Steam 库设置', '下一页')))
        for filename in ('packaging/WorkshopTranslator.spec', 'packaging/WorkshopTranslator-macOS.spec',
                         'packaging/build_release.py', 'packaging/build_update.py'):
            content = (root / filename).read_text()
            for runtime in ('localization', 'localization_ui.js', 'ui_languages.json'):
                self.assertIn(runtime, content)

    def test_http_selects_target_language_without_saving_a_key(self):
        server = app.AppServer(('127.0.0.1', 0), self.base)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        for language, expected in [('ru', 200), ('zh-TW', 200), ('zh-CN', 200), ('en', 400)]:
            connection = http.client.HTTPConnection(*server.server_address)
            connection.request('GET', '/api/state', headers={
                'X-App-Token': server.token, 'X-Translation-Language': language})
            response = connection.getresponse()
            payload = json.loads(response.read())
            self.assertEqual(response.status, expected)
            if expected == 200:
                self.assertEqual(payload['target_language'], language)
                self.assertNotIn('api_key', payload['config'])
            connection.close()
