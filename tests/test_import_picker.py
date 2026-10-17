import subprocess
import unittest
from unittest.mock import patch

import workshop_app as app


class ImportPickerTests(unittest.TestCase):
    def test_macos_uses_native_panel_in_source_and_packaged_mode(self):
        for kind in ('file', 'folder'):
            for frozen in (False, True):
                with self.subTest(kind=kind, frozen=frozen), \
                     patch.object(app.sys, 'platform', 'darwin'), \
                     patch.object(app.sys, 'frozen', frozen, create=True), \
                     patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '/tmp/中文 缓存.json\n', '')) as run:
                    self.assertEqual(app.pick_import_path(kind), '/tmp/中文 缓存.json')
                    command = run.call_args.args[0]
                    self.assertEqual(command[0], '/usr/bin/osascript')
                    self.assertEqual(command[-1], kind)
                    self.assertIn('NSOpenPanel', command[-2])
                    self.assertNotIn(app.sys.executable, command)

    def test_cancel_preserves_empty_selection(self):
        with patch.object(app.sys, 'platform', 'darwin'), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '\n', '')):
            self.assertEqual(app.pick_import_path('file'), '')

    def test_native_path_keeps_trailing_spaces(self):
        with patch.object(app.sys, 'platform', 'darwin'), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, '/tmp/目录 \n', '')):
            self.assertEqual(app.pick_import_path('folder'), '/tmp/目录 ')

    def test_failures_offer_path_input_without_exposing_process_details(self):
        for failure in (OSError('private detail'), subprocess.TimeoutExpired('osascript', 180)):
            with self.subTest(failure=type(failure).__name__), \
                 patch.object(app.sys, 'platform', 'darwin'), \
                 patch('subprocess.run', side_effect=failure):
                with self.assertRaisesRegex(ValueError, '粘贴本机路径'):
                    app.pick_import_path('file')
        with patch('subprocess.run', return_value=subprocess.CompletedProcess([], 1, '', 'private detail')):
            with self.assertRaisesRegex(ValueError, '路径输入'):
                app.pick_import_path('file')

    def test_invalid_kind_starts_no_process(self):
        with patch('subprocess.run') as run:
            with self.assertRaises(ValueError):
                app.pick_import_path('invalid')
            run.assert_not_called()

    def test_other_platform_keeps_python_dialog_helper(self):
        with patch.object(app.sys, 'platform', 'win32'), \
             patch.object(app.sys, 'frozen', True, create=True), \
             patch('subprocess.run', return_value=subprocess.CompletedProcess([], 0, 'C:\\中文文件.yml\n', '')) as run:
            self.assertEqual(app.pick_import_path('file'), 'C:\\中文文件.yml')
            self.assertEqual(run.call_args.args[0], [app.sys.executable, '--choose-import', 'file'])


if __name__ == '__main__':
    unittest.main()
