"""Exercise the browser's folder archive with the real server importer."""
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
import zipfile

import workshop_app as app
from server_upload import upload_mod


@unittest.skipUnless(shutil.which('node'), 'Node.js is needed for browser archive tests')
class FolderImportTests(unittest.TestCase):
    def archive(self, files):
        source = (app.ROOT / 'server_ui.js').read_text()
        start = source.index('  async function folderImportArchive(')
        end = source.index('  // 网页版浏览器文件导入对话框', start)
        script = source[start:end] + '''
const fs = require('fs');
const files = JSON.parse(fs.readFileSync(0, 'utf8')).map(item => ({
  name: item.path.split('/').at(-1), webkitRelativePath: item.path,
  size: item.size ?? Buffer.byteLength(item.text),
  arrayBuffer: async () => new TextEncoder().encode(item.text).buffer
}));
folderImportArchive(files).then(async result => {
  process.stdout.write(Buffer.from(await result.blob.arrayBuffer()));
}).catch(error => { process.stderr.write(error.message); process.exitCode = 1; });
'''
        return subprocess.run(['node', '-e', script], input=json.dumps(files).encode(), capture_output=True)

    def test_nested_unicode_folder_import_and_excluded_files(self):
        result = self.archive([
            {'path': '译文/localisation/simp_chinese/test_l_simp_chinese.yaml',
             'text': 'l_simp_chinese:\n first:0 "你好"\n'},
            {'path': '译文/localisation/second_l_simp_chinese.yml',
             'text': 'l_simp_chinese:\n second:0 "世界"\n'},
            {'path': '译文/.env', 'text': 'private-do-not-upload'},
            {'path': '译文/cover.png', 'text': 'not-an-image'},
        ])
        self.assertEqual(result.returncode, 0, result.stderr)
        with zipfile.ZipFile(io.BytesIO(result.stdout)) as archive:
            self.assertIsNone(archive.testzip())
            self.assertEqual(len(archive.namelist()), 2)
            self.assertTrue(all(name.startswith('译文/localisation/') for name in archive.namelist()))
        with tempfile.TemporaryDirectory() as directory:
            service = app.WorkshopService(Path(directory) / 'data')
            service.server_mode = True
            source = io.BytesIO()
            with zipfile.ZipFile(source, 'w') as archive:
                archive.writestr('Original/descriptor.mod', 'name="Folder test"')
                archive.writestr('Original/localisation/english/test_l_english.yml', 'l_english:\n first:0 "Hello"\n')
                archive.writestr('Original/localisation/english/second_l_english.yml', 'l_english:\n second:0 "World"\n')
            upload_mod(service, source.getvalue(), '281990', '123')
            path = Path(directory) / 'folder.zip'
            path.write_bytes(result.stdout)
            imported = service.import_cache('281990:123', path)
            self.assertEqual(imported['imported'], 2)
            self.assertEqual(imported['translated'], 2)

    def test_empty_oversized_and_unsafe_folders_are_rejected(self):
        for files, message in [
            ([{'path': 'folder/readme.md', 'text': 'not a translation'}], '没有可导入'),
            ([{'path': 'folder/test.yml', 'text': '', 'size': 33 * 1024 * 1024}], '总大小'),
            ([{'path': '../test.yml', 'text': 'bad'}], '无效路径'),
        ]:
            with self.subTest(message=message):
                result = self.archive(files)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr.decode())
