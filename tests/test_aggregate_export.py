"""Developer auto-export now produces separate translation Mods, not a merged tree."""
import json
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

    def test_default_hides_automatic_export_and_old_aggregate_stays_untouched(self):
        self.assertFalse(self.service.config()['developer_mode'])
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
        self.assertIn('/Documents/Stellaris/mod/',result['path'].replace('\\','/'))
        self.assertNotEqual(Path(result['path']).name, self.item['uid'])
        self.assertRegex(Path(result['path']).name, r'^[0-9]{10}$')
        self.assertIn('默认模板',result['description_source'])
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
        response=Mock(); response.choices=[Mock(message=Mock(content='模型生成的简介'))]
        client=Mock(); client.chat.completions.create.return_value=response
        with patch('request.load_sdk'), patch('request.OpenAI',return_value=client) as factory:
            result=build(self.service,self.item)
        self.assertEqual(result['description'],'模型生成的简介')
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
