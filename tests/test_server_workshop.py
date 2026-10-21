import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import workshop_app as app
from server_workshop import workshop_uid, lookup, copy_translation_files, download


class WorkshopImportTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.service = app.WorkshopService(self.root / 'data')
        self.service.server_mode = True
        self.link = 'https://steamcommunity.com/sharedfiles/filedetails/?id=123'
        self.item = {'appid': '281990', 'uid': '123', 'id': '281990:123', 'title': 'Test'}

    def test_link_validation_and_game_validation(self):
        self.assertEqual(workshop_uid(self.link), '123')
        for link in ['https://evil.test/?id=123', 'file:///etc/passwd',
                     self.link + '&id=456', self.link.replace('123', '../x'),
                     'https://steamcommunity.com/other?id=123']:
            with self.subTest(link=link), self.assertRaises(ValueError):
                workshop_uid(link)
        with patch.object(app, 'workshop_details', return_value={'123': {'consumer_app_id': 0}}):
            with self.assertRaises(ValueError): lookup(self.service, self.link)

    def test_keep_localisation_descriptor_cover_only_and_reject_symlinks(self):
        source = self.root / 'source'
        (source / 'localisation/english').mkdir(parents=True)
        (source / 'localisation/english/test.yml').write_text('l_english:\n key:0 "Hello"\n')
        (source / 'descriptor.mod').write_text('name="Test"\npicture="cover.png"')
        (source / 'cover.png').write_bytes(b'cover')
        (source / 'unnecessary.bin').write_bytes(b'large')
        copy_translation_files(source, self.root / 'kept')
        self.assertEqual(sorted(str(p.relative_to(self.root / 'kept')) for p in (self.root / 'kept').rglob('*') if p.is_file()),
                         ['cover.png', 'descriptor.mod', 'localisation/english/test.yml'])
        (source / 'localisation/evil.yml').symlink_to(source / 'cover.png')
        with self.assertRaises(ValueError): copy_translation_files(source, self.root / 'rejected')

    def fake_client(self, success):
        script = self.root / 'steamcmd'
        script.write_text('#!/usr/bin/env python3\nimport sys,pathlib\n'
                          'p=pathlib.Path(sys.argv[sys.argv.index("+force_install_dir")+1])/"steamapps/workshop/content/281990/123"\n'
                          '(p/"localisation/english").mkdir(parents=True)\n'
                          '(p/"localisation/english/test.yml").write_text(\'l_english:\\n key:0 "Hello"\\n\')\n'
                          '(p/"descriptor.mod").write_text(\'name="Test"\')\n'
                          '(p/"unnecessary.bin").write_bytes(b"unused")\n'
                          + ('print("Success. Downloaded item 123 to test")\n' if success else 'print("ERROR! Access Denied")\n'))
        script.chmod(0o755)
        return str(script)

    def test_download_import_cleanup_and_existing_mod_reuse(self):
        with patch.dict(os.environ, {'TRANSLATOR_STEAMCMD': self.fake_client(True)}):
            result = download(self.service, self.item)
        item = self.service.get_mod(result['id'])
        self.assertEqual(self.service.analyze(item['id'])['total'], 1)
        self.assertFalse((Path(item['path']) / 'unnecessary.bin').exists())
        self.assertFalse(list(self.service.data_dir.glob('workshop-download-*')))
        with patch.object(app, 'workshop_details', side_effect=AssertionError('must reuse')):
            self.assertTrue(lookup(self.service, self.link)['downloaded'])
        with patch('server_workshop.subprocess.Popen', side_effect=AssertionError('must not download')):
            download(self.service, self.item)

    def test_exit_zero_without_success_is_failure_and_cleans_temporary_files(self):
        with patch.dict(os.environ, {'TRANSLATOR_STEAMCMD': self.fake_client(False)}):
            with self.assertRaisesRegex(ValueError, 'Access Denied'):
                download(self.service, self.item)
        self.assertFalse(list(self.service.data_dir.glob('workshop-download-*')))
        self.assertFalse(self.service.inventory)
