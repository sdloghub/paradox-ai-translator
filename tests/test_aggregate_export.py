"""Developer auto-export now produces separate translation Mods, not a merged tree."""
import json
import re
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
import zipfile

import workshop_app as app
from aggregate_export import export
from mod_export import build, documents_mod_root, output_root, safe_id


class ModExportTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root=Path(temp.name)
        self.service=app.WorkshopService(self.root/'data')
        self.library=self.root/'SteamLibrary'
        self.mod=self.library/'steamapps/workshop/content/281990/123'
        self.source=self.mod/'localisation/english/shared_l_english.yml'
        self.source.parent.mkdir(parents=True)
        self.source.write_text('l_english:\n key:0 "Alpha $VALUE$"\n pending:0 "No translation"\n broken:0 "Bad" tail\n',encoding='utf-8')
        (self.mod/'descriptor.mod').write_text('name="Original"\nsupported_version="4.4.*"\nremote_file_id="123"\nreplace_path="common"\n')
        self.service.save_config({'steam_libraries':[str(self.library)]})
        with patch.object(app,'steam_libraries',return_value=[self.library]):
            self.item=self.service.scan(lambda ids:{})[0]
        from translation_cache import entries
        entry=entries(self.service.original_sources(self.item),'st',strict=False)[0]
        with self.service.connect() as db:
            self.service.cache.put(db,self.item['id'],entry,'中文 $VALUE$','人工来源')
        self.service.analyze(self.item['id'])

    def generate(self,**kwargs):
        return build(self.service,self.item,introduction='这是手写简介。',**kwargs)

    def test_manual_export_works_without_developer_or_api_and_excludes_untranslated(self):
        self.service.save_config({'api_key':'never-export-this-key'})
        source=self.source.read_bytes()
        result=self.generate(title='翻译 "标题"')
        root=Path(result['path']); name=safe_id(self.item)
        with zipfile.ZipFile(root/result['zip_name']) as package:
            data=package.read(name+'/localisation/simp_chinese/shared_l_simp_chinese.yml')
            self.assertTrue(data.startswith(b'\xef\xbb\xbf'))
            self.assertIn('中文 $VALUE$',data.decode('utf-8-sig'))
            self.assertNotIn(b'pending:',data); self.assertNotIn(b'broken:',data)
            descriptor=package.read(name+'/descriptor.mod').decode()
            self.assertIn('dependencies={ "Original" }',descriptor)
            self.assertIn('supported_version="4.4.*"',descriptor)
            self.assertNotIn('remote_file_id',descriptor); self.assertNotIn('replace_path',descriptor)
            self.assertIn('path="mod/'+name+'"',package.read(name+'.mod').decode())
            manifest=package.read('source-manifest.json').decode()
            self.assertNotIn('never-export-this-key',manifest)
            self.assertNotIn(str(self.mod),manifest)
        self.assertEqual(self.source.read_bytes(),source)
        self.assertEqual(result['entries'],1)
        self.assertTrue(result['warnings'])

    def test_original_picture_copied_to_installed_mod_and_zip(self):
        (self.mod/'images').mkdir()
        image = b'original-cover-image'
        (self.mod/'images/cover.jpg').write_bytes(image)
        descriptor = self.mod/'descriptor.mod'
        descriptor.write_text(descriptor.read_text() + 'picture="images/cover.jpg"\n')
        result = self.generate()
        root = Path(result['mod_path'])
        self.assertEqual((root/'thumbnail.jpg').read_bytes(), image)
        self.assertIn('picture="thumbnail.jpg"', (root/'descriptor.mod').read_text())
        launcher = root.with_suffix('.mod').read_text()
        self.assertIn('picture="thumbnail.jpg"', launcher)
        self.assertIn('path="mod/'+root.name+'"', launcher)
        self.assertNotIn('remote_file_id', launcher)
        self.assertFalse((root/safe_id(self.item)).exists())
        with zipfile.ZipFile(root/result['zip_name']) as package:
            self.assertEqual(package.read(root.name+'/thumbnail.jpg'), image)

    def test_picture_cannot_escape_source_mod(self):
        outside = self.root/'private.jpg'
        outside.write_bytes(b'private image')
        (self.mod/'descriptor.mod').write_text('picture="../../../../../private.jpg"\n')
        result = self.generate()
        self.assertFalse((Path(result['mod_path'])/'thumbnail.jpg').exists())

    def test_new_patch_leaves_workshop_id_for_steam(self):
        result = self.generate()
        root = Path(result['path'])
        self.assertEqual(result['folder_name'], safe_id(self.item))
        self.assertNotIn('generated_uid', result)
        manifest = json.loads((root/'source-manifest.json').read_text())
        self.assertNotIn('generated_uid', manifest)
        with zipfile.ZipFile(root/result['zip_name']) as package:
            for name in (root.name+'/descriptor.mod', root.name+'.mod'):
                self.assertNotIn('remote_file_id', package.read(name).decode())

    def test_regeneration_preserves_steam_assigned_id_of_published_patch(self):
        result = self.generate()
        root = Path(result['path'])
        for path in (root/'descriptor.mod', root.with_suffix('.mod')):
            path.write_text(path.read_text() + 'remote_file_id="3823400171"\n')
        result = self.generate()
        for path in (root/'descriptor.mod', root.with_suffix('.mod')):
            self.assertIn('remote_file_id="3823400171"', path.read_text())
        with zipfile.ZipFile(root/result['zip_name']) as package:
            for name in (root.name+'/descriptor.mod', root.name+'.mod'):
                self.assertIn('remote_file_id="3823400171"', package.read(name).decode())

    def test_regeneration_rejects_conflicting_or_original_workshop_ids(self):
        result = self.generate()
        root = Path(result['path'])
        descriptor = root/'descriptor.mod'
        launcher = root.with_suffix('.mod')
        descriptor.write_text(descriptor.read_text() + 'remote_file_id="3823400171"\n')
        launcher.write_text(launcher.read_text() + 'remote_file_id="999"\n')
        with self.assertRaisesRegex(ValueError, '不一致'):
            self.generate()
        for path in (descriptor, launcher):
            text = re.sub(r'remote_file_id="[0-9]+"', 'remote_file_id="123"', path.read_text())
            path.write_text(text)
        with self.assertRaisesRegex(ValueError, '误用了原 Mod'):
            self.generate()

    def test_local_default_enables_automatic_export(self):
        self.assertTrue(self.service.config()['developer_mode'])
        self.assertTrue(export(self.service,self.item,{},1)['enabled'])
        self.assertTrue(documents_mod_root(self.service).exists())

    def test_disabled_automatic_export_and_old_aggregate_stays_untouched(self):
        self.service.save_config({'developer_mode':False})
        self.assertFalse(export(self.service,self.item,{},1)['enabled'])
        self.assertFalse(documents_mod_root(self.service).exists())
        legacy=self.service.data_dir/'aggregate_mods/281990/old.yml'
        legacy.parent.mkdir(parents=True); legacy.write_text('existing')
        self.generate()
        self.assertEqual(legacy.read_text(),'existing')

    def test_developer_automatic_generates_per_mod_without_api_using_template(self):
        self.service.save_config({'developer_mode':True})
        result=export(self.service,self.item,{},1)
        self.assertTrue(result['enabled'])
        self.assertIn('/Documents/Paradox Interactive/Stellaris/mod/',result['path'].replace('\\','/'))
        self.assertNotEqual(Path(result['path']).name, self.item['uid'])
        self.assertEqual(Path(result['path']).name, safe_id(self.item))
        self.assertEqual(Path(result['mod_path']), Path(result['path']))
        self.assertTrue(Path(result['path']).with_suffix('.mod').is_file())
        self.assertIn('默认模板',result['description_source'])
        paragraphs = result['description'].split('\n\n')
        self.assertEqual(len(paragraphs), 3)
        self.assertIn(self.item['title'], paragraphs[0])
        self.assertIn('之后加载', paragraphs[0])
        self.assertIn('https://github.com/sdloghub/paradox-ai-translator', paragraphs[1])
        self.assertIn('Vibe coding', paragraphs[1])
        self.assertIn('API Key', paragraphs[1])
        self.assertIn('Star', paragraphs[2])
        self.assertIn('😭', paragraphs[2])
        self.service.save_config({'aggregate_export':False})
        self.assertFalse(export(self.service,self.item,{},1)['enabled'])

    def test_repeat_updates_backup_all_previous_content_and_reuses_intro(self):
        first=self.generate(); root=Path(first['path'])
        (root/'manual-notes.txt').write_text('manual work')
        self.service.save_config({'developer_mode':True})
        with patch('mod_export.description', wraps=__import__('mod_export').description):
            result=export(self.service,self.item,{},2)
        self.assertEqual(result['description'],'这是手写简介。')
        self.assertEqual((Path(result['backup_path'])/'manual-notes.txt').read_text(),'manual work')
        self.assertFalse((root/'manual-notes.txt').exists())

    def test_blank_intro_uses_default_api_and_never_sends_source_files(self):
        self.service.save_config({'api_key':'test-only','model':'chosen-model','provider':'我的提供商'})
        response=Mock(); response.choices=[Mock(message=Mock(content='模型生成的简介\n\n仍在汉化中'))]
        client=Mock(); client.chat.completions.create.return_value=response
        with patch('request.load_sdk'), patch('request.OpenAI',return_value=client) as factory:
            result=build(self.service,self.item)
        paragraphs = result['description'].split('\n\n')
        self.assertEqual(len(paragraphs), 3)
        self.assertEqual(paragraphs[0], '模型生成的简介 仍在汉化中')
        self.assertIn('https://github.com/sdloghub/paradox-ai-translator', paragraphs[1])
        self.assertIn('Star', paragraphs[2])
        args=client.chat.completions.create.call_args.kwargs
        self.assertEqual(args['model'],'chosen-model')
        self.assertNotIn('Alpha $VALUE$',json.dumps(args['messages']))
        self.assertIn('我的提供商',result['description_source'])
        self.assertEqual(factory.call_args.kwargs['api_key'],'test-only')

    def test_empty_intro_missing_api_or_failed_api_does_not_publish(self):
        with self.assertRaisesRegex(ValueError,'API Key'):
            build(self.service,self.item)
        self.service.save_config({'api_key':'test-only'})
        with patch('request.load_sdk'),patch('request.OpenAI',side_effect=RuntimeError('secret-body')):
            with self.assertRaisesRegex(ValueError,'可手动填写') as error:
                build(self.service,self.item)
            self.assertNotIn('secret-body',str(error.exception))
        self.assertFalse(output_root(self.service,self.item).exists())

    def test_symlink_and_unknown_directory_are_not_overwritten(self):
        outside=self.root/'outside';outside.mkdir()
        base=documents_mod_root(self.service);base.parent.mkdir(parents=True,exist_ok=True)
        base.symlink_to(outside,target_is_directory=True)
        with self.assertRaisesRegex(ValueError,'符号链接'):
            self.generate()
        self.assertEqual(list(outside.iterdir()),[])
        base.unlink()
        root=output_root(self.service,self.item);root.mkdir(parents=True);(root/'user.txt').write_text('keep')
        with self.assertRaisesRegex(ValueError,'已有其他文件'):
            self.generate()
        self.assertEqual((root/'user.txt').read_text(),'keep')

    def test_failed_write_preserves_existing_package(self):
        first=self.generate();root=Path(first['path']);before=(root/first['zip_name']).read_bytes()
        with patch.object(app,'atomic_bytes',side_effect=OSError('disk full')):
            with self.assertRaises(OSError):self.generate()
        self.assertEqual((root/first['zip_name']).read_bytes(),before)

    def test_failed_directory_publish_restores_previous_package(self):
        first=self.generate();root=Path(first['path']);before=(root/first['zip_name']).read_bytes()
        original=Path.rename
        def fail(path,target):
            if path.name=='package' and Path(target)==root:
                raise OSError('publish unavailable')
            return original(path,target)
        with patch.object(Path,'rename',fail):
            with self.assertRaises(OSError):self.generate()
        self.assertEqual((root/first['zip_name']).read_bytes(),before)

    def test_failed_sibling_descriptor_write_restores_previous_mod(self):
        first = self.generate()
        root = Path(first['path'])
        before = (root/first['zip_name']).read_bytes()
        launcher = root.with_suffix('.mod')
        previous_launcher = launcher.read_bytes()
        original = app.atomic_bytes
        def fail(path, data):
            if path == launcher:
                raise OSError('cannot write launcher descriptor')
            return original(path, data)
        with patch.object(app, 'atomic_bytes', side_effect=fail):
            with self.assertRaises(OSError):
                self.generate(title='different title')
        self.assertEqual((root/first['zip_name']).read_bytes(), before)
        self.assertEqual(launcher.read_bytes(), previous_launcher)

    def test_source_change_during_description_preserves_previous_package(self):
        first=self.generate();root=Path(first['path']);before=(root/first['zip_name']).read_bytes()
        def change(*args):
            self.source.write_bytes(self.source.read_bytes().replace(b'Alpha',b'Updated'))
            return '新简介','手动填写'
        with patch('mod_export.description',side_effect=change),self.assertRaisesRegex(ValueError,'英文文件发生变化'):
            self.generate()
        self.assertEqual((root/first['zip_name']).read_bytes(),before)

    def test_victoria_uses_metadata_id_not_workshop_uid_as_dependency(self):
        item={**self.item,'game':'vic3','appid':'529340','id':'529340:123'}
        metadata=self.mod/'.metadata/metadata.json';metadata.parent.mkdir()
        metadata.write_text(json.dumps({'id':'original.unique.id','supported_game_version':'1.12.*'}))
        with patch('mod_export.patch_files',return_value=({'localization/simp_chinese/file_l_simp_chinese.yml':b'content'},1,0)):
            result=build(self.service,item,introduction='手写简介')
        meta=json.loads((Path(result['mod_path'])/'.metadata/metadata.json').read_text())
        self.assertEqual(meta['game_id'],'victoria3')
        self.assertEqual(meta['relationships'][0]['id'],'original.unique.id')
        self.assertEqual(meta['id'],'local.workshoptranslator.patch.529340.123')
        self.assertFalse(list(Path(result['path']).glob('*.mod')))

    def test_developer_flag_is_bool_and_release_always_disables_it(self):
        with self.assertRaises(ValueError):self.service.save_config({'developer_mode':'true'})
        import importlib.util
        spec=importlib.util.spec_from_file_location('release_builder',Path(__file__).resolve().parents[1]/'packaging/build_release.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        self.assertFalse(module.sanitized({'developer_mode':True,'profiles':[{'developer_mode':True}]})['profiles'][0]['developer_mode'])
