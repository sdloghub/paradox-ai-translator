import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch


SPEC = importlib.util.spec_from_file_location(
    'workshop_description_cli', Path(__file__).resolve().parents[1] / 'scripts' / 'workshop_description.py')
cli = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cli)


class DescriptionCLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_utf8_bom_bbcode_and_line_endings(self):
        path = self.root / 'description.txt'
        path.write_bytes('\ufeff[h1]中文[/h1]\r\n$VAR$\r尾行\n'.encode('utf-8'))
        self.assertEqual(cli.read_description(path), '[h1]中文[/h1]\n$VAR$\n尾行\n')

    def test_reject_invalid_files(self):
        path = self.root / 'description.txt'
        for raw in (b'\xff', b' \n', b'a\x00b', b'x' * (1024 * 1024 + 1)):
            with self.subTest(raw_length=len(raw)):
                path.write_bytes(raw)
                with self.assertRaises((ValueError, UnicodeError)):
                    cli.read_description(path)

    def test_bundle_extracts_only_bbcode(self):
        path = self.root / 'bundle.md'
        path.write_text('# 说明，不上传\n\n## 1. 英语（English）\n\n```bbcode\n[b]Hello[/b]\n```\n\n## 2. 简体中文（Simplified Chinese）\n```bbcode\n你好\n```\n', encoding='utf-8')
        self.assertEqual(cli.read_bundle(path), [('english', '[b]Hello[/b]\n'), ('schinese', '你好\n')])

    def test_bundle_rejects_unknown_duplicate_or_empty_sections(self):
        path = self.root / 'bundle.md'
        for content in ('## 1. 未知语言\n```bbcode\nhi\n```\n',
                        '## 1. 英语（English）\n```bbcode\n\n```\n',
                        '## 1. 英语（English）\n```bbcode\nhi\n```\n## 2. 英语（English）\n```bbcode\nagain\n```\n'):
            path.write_text(content, encoding='utf-8')
            with self.assertRaises(ValueError):
                cli.read_bundle(path)

    def test_preview_never_opens_browser(self):
        path = self.root / 'description.txt'
        path.write_text('[b]简介[/b]', encoding='utf-8')
        with patch.object(cli, 'run_browser') as browser:
            self.assertEqual(cli.main(['--item-id', '123', '--language', 'schinese', '--file', str(path)]), 0)
            browser.assert_not_called()

    def page(self):
        page = MagicMock()
        page.url = cli.editor_url('123', 'schinese')
        fields = {name: MagicMock() for name in ('#language', '#description', '#title', 'a[href="javascript:ValidateForm()"]')}
        page.locator.side_effect = fields.__getitem__
        fields['#language'].input_value.return_value = '6'
        fields['#description'].input_value.return_value = '旧简介'
        fields['#description'].get_attribute.return_value = None
        fields['#description'].fill.side_effect = lambda value: setattr(fields['#description'].input_value, 'return_value', value)
        fields['#title'].input_value.return_value = '原有标题'
        return page, fields

    def test_upload_backs_up_before_save_and_verifies(self):
        page, fields = self.page()
        save = fields['a[href="javascript:ValidateForm()"]']
        def check_backup():
            backups = list(self.root.glob('*/description.txt'))
            self.assertEqual(len(backups), 1)
            self.assertEqual(backups[0].read_text(), '旧简介')
        save.click.side_effect = check_backup
        cli.upload(page, '123', 'schinese', '[b]新简介[/b]', self.root)
        save.click.assert_called_once()
        page.goto.assert_called_once_with(cli.editor_url('123', 'schinese'), wait_until='domcontentloaded')
        fields['#title'].fill.assert_not_called()

    def test_same_content_no_save(self):
        page, fields = self.page()
        cli.upload(page, '123', 'schinese', '旧简介', self.root)
        fields['a[href="javascript:ValidateForm()"]'].click.assert_not_called()
        self.assertEqual(list(self.root.iterdir()), [])

    def test_wrong_target_or_language_never_saves(self):
        for url, lang in [('https://example.com/sharedfiles/itemedittext/?id=123', '6'),
                          (cli.editor_url('456', 'schinese'), '6'),
                          (cli.editor_url('123', 'english'), '0')]:
            page, fields = self.page()
            page.url = url
            fields['#language'].input_value.return_value = lang
            with self.assertRaises(ValueError):
                cli.upload(page, '123', 'schinese', '新简介', self.root)
            fields['a[href="javascript:ValidateForm()"]'].click.assert_not_called()

    def test_backup_failure_prevents_save(self):
        page, fields = self.page()
        with patch.object(cli, 'backup_description', side_effect=OSError('disk full')):
            with self.assertRaises(OSError):
                cli.upload(page, '123', 'schinese', '新简介', self.root)
        fields['a[href="javascript:ValidateForm()"]'].click.assert_not_called()

    def test_save_uncertain_is_not_retried(self):
        page, fields = self.page()
        save = fields['a[href="javascript:ValidateForm()"]']
        save.click.side_effect = TimeoutError()
        with self.assertRaisesRegex(RuntimeError, '未能核验'):
            cli.upload(page, '123', 'schinese', '新简介', self.root)
        save.click.assert_called_once()

    def test_readback_mismatch_fails(self):
        page, fields = self.page()
        page.goto.side_effect = lambda *a, **kw: setattr(fields['#description'].input_value, 'return_value', '旧简介')
        with self.assertRaisesRegex(RuntimeError, '未能核验'):
            cli.upload(page, '123', 'schinese', '新简介', self.root)


if __name__ == '__main__':
    unittest.main()
