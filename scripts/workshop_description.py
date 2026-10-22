#!/usr/bin/env python3
"""Import a UTF-8 description through Steam's normal editor, without SteamCMD."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import parse_qs, urlencode, urlparse


LANGUAGES = {
    'english': '0', 'german': '1', 'french': '2', 'italian': '3',
    'koreana': '4', 'spanish': '5', 'schinese': '6', 'tchinese': '7',
    'russian': '8', 'thai': '9', 'japanese': '10', 'portuguese': '11',
    'polish': '12', 'danish': '13', 'dutch': '14', 'finnish': '15',
    'norwegian': '16', 'swedish': '17', 'hungarian': '18', 'czech': '19',
    'romanian': '20', 'turkish': '21', 'brazilian': '22', 'bulgarian': '23',
    'greek': '24', 'ukrainian': '26', 'latam': '27', 'vietnamese': '28',
    'indonesian': '30', 'malay': '31',
}

BUNDLE_HEADINGS = {
    '英语（English）': 'english',
    '简体中文（Simplified Chinese）': 'schinese',
    '繁體中文（Traditional Chinese）': 'tchinese',
    '法语（Français）': 'french', '意大利语（Italiano）': 'italian',
    '韩语（한국어）': 'koreana', '日语（日本語）': 'japanese',
    '西班牙语（西班牙版本 · Español de España）': 'spanish',
    '西班牙语（拉丁美洲版本 · Español de Hispanoamérica）': 'latam',
    '德语（Deutsch）': 'german', '俄语（Русский）': 'russian',
}


def read_bundle(path):
    """Only fenced BBCode under recognized language headings is upload data."""
    text = read_description(path)
    sections = re.split(r'^##\s+\d+\.\s+(.+?)\s*$', text, flags=re.M)
    if len(sections) < 3:
        raise ValueError('未找到多语言合集章节')
    jobs = []
    seen = set()
    for heading, body in zip(sections[1::2], sections[2::2]):
        language = BUNDLE_HEADINGS.get(heading)
        if not language or language in seen:
            raise ValueError(f'未知或重复的合集语言章节：{heading}')
        blocks = re.findall(r'^```bbcode\s*\n(.*?)^```[ \t]*$', body, re.M | re.S)
        if len(blocks) != 1 or not blocks[0].strip():
            raise ValueError(f'章节必须包含一个非空 BBCode 块：{heading}')
        jobs.append((language, blocks[0]))
        seen.add(language)
    return jobs


def item_id(value):
    if not re.fullmatch(r'[1-9][0-9]*', value) or int(value) >= 2**64:
        raise argparse.ArgumentTypeError('工坊 ID 必须为有效的正整数')
    return value


def normalize(text):
    return text.replace('\r\n', '\n').replace('\r', '\n')


def read_description(path):
    with path.open('rb') as source:
        raw = source.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('简介文件超过 1 MiB')
    text = normalize(raw.decode('utf-8-sig'))
    if not text.strip() or '\0' in text:
        raise ValueError('简介不能为空或包含空字符')
    return text


def editor_url(identifier, language):
    return 'https://steamcommunity.com/sharedfiles/itemedittext/?' + urlencode(
        {'id': identifier, 'language': LANGUAGES[language]})


def assert_editor(page, identifier, language):
    url = urlparse(page.url)
    if (url.scheme != 'https' or url.netloc != 'steamcommunity.com'
            or url.path.rstrip('/') != '/sharedfiles/itemedittext'
            or parse_qs(url.query).get('id') != [identifier]):
        raise ValueError('未进入目标工坊编辑页；请检查登录状态及条目编辑权限')
    if page.locator('#language').input_value() != LANGUAGES[language]:
        raise ValueError('编辑页语言不匹配，已停止')


def backup_description(directory, identifier, language, title, text):
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A unique private directory also prevents replacing any earlier backup.
    target = Path(tempfile.mkdtemp(prefix=f'{identifier}-{language}-', dir=directory))
    (target / 'description.txt').write_text(text, encoding='utf-8')
    (target / 'metadata.json').write_text(json.dumps({
        'item_id': identifier, 'language': language, 'title': title,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'sha256': hashlib.sha256(text.encode('utf-8')).hexdigest(),
    }, ensure_ascii=False, indent=2), encoding='utf-8')
    return target


def upload(page, identifier, language, text, backup_dir):
    """Save once. Any failure after click is indeterminate; never auto retry."""
    assert_editor(page, identifier, language)
    description = page.locator('#description')
    title = page.locator('#title').input_value()
    original = normalize(description.input_value())
    if original == text:
        print('线上简介与文件一致，无需上传。')
        return
    maximum = description.get_attribute('maxlength')
    if maximum and int(maximum) >= 0 and len(text.encode('utf-16-le')) // 2 > int(maximum):
        raise ValueError('简介超过 Steam 编辑框长度限制')
    backup = backup_description(backup_dir, identifier, language, title, original)
    print(f'原简介已备份：{backup}')
    description.fill(text)
    assert_editor(page, identifier, language)
    if (page.locator('#title').input_value() != title
            or normalize(description.input_value()) != text):
        raise ValueError('提交前校验不一致，未点击保存')
    try:
        # Wait for Steam's normal save navigation, rather than assuming a click succeeded.
        with page.expect_navigation(wait_until='domcontentloaded', timeout=45000):
            page.locator('a[href="javascript:ValidateForm()"]').click()
        page.goto(editor_url(identifier, language), wait_until='domcontentloaded')
        assert_editor(page, identifier, language)
        if (normalize(page.locator('#description').input_value()) != text
                or page.locator('#title').input_value() != title):
            raise ValueError('重新读取的简介或标题不匹配')
    except Exception:
        raise RuntimeError('已尝试提交，但未能核验结果；请检查工坊页面和备份，不要直接重复上传') from None
    print(f'上传成功，已重新读取核验（{language}）；标题未变。')


def run_browser(args, jobs):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError('请先安装 scripts/requirements-workshop.txt 中的独立脚本依赖') from None
    with tempfile.TemporaryDirectory(prefix='workshop-description-') as temporary:
        profile = args.profile.expanduser().resolve() if args.profile else Path(temporary)
        if args.profile:
            profile.mkdir(parents=True, exist_ok=True, mode=0o700)
        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(profile), channel='chrome', headless=False)
            try:
                page = context.new_page()
                page.goto(editor_url(args.item_id, jobs[0][0]), wait_until='domcontentloaded')
                if not page.locator('#description').is_visible():
                    print('请在打开的 Chrome 窗口中登录 Steam 并完成 Steam Guard。不要在终端输入密码。')
                    input('完成登录后按回车继续：')
                for language, text in jobs:
                    print(f'处理语言：{language}')
                    page.goto(editor_url(args.item_id, language), wait_until='domcontentloaded')
                    upload(page, args.item_id, language, text, args.backup_dir.expanduser())
            finally:
                context.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description='从文件自动上传 Steam 工坊简介；默认只做离线预览')
    parser.add_argument('--item-id', required=True, type=item_id)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--language', choices=sorted(LANGUAGES))
    mode.add_argument('--bundle', action='store_true', help='按编号语言章节提取 Markdown 合集中的 BBCode，批量上传')
    parser.add_argument('--file', required=True, type=Path, help='UTF-8 文本或 BBCode 文件')
    parser.add_argument('--apply', action='store_true', help='启动浏览器并自动点击保存，实际修改线上简介')
    parser.add_argument('--profile', type=Path, help='可选：专用浏览器目录，显式指定即保留 Steam 登录态；不要使用日常 Chrome 配置目录')
    parser.add_argument('--backup-dir', type=Path, default=Path.home() / '.paradox-workshop' / 'backups')
    args = parser.parse_args(argv)
    try:
        jobs = read_bundle(args.file) if args.bundle else [(args.language, read_description(args.file))]
        print(f'工坊 ID：{args.item_id}；共 {len(jobs)} 个语言版本')
        for language, text in jobs:
            print(f'{language}: {len(text.encode("utf-8"))} 字节；SHA-256 {hashlib.sha256(text.encode("utf-8")).hexdigest()}')
        if not args.apply:
            print('预览模式，未打开浏览器或上传；添加 --apply 执行上传。\n')
            for language, text in jobs:
                print(f'\n--- {language} ---\n{text}')
            return 0
        run_browser(args, jobs)
        return 0
    except (Exception, KeyboardInterrupt) as error:
        # Do not dump browser internals, cookies, or complete request/response data.
        message = str(error) if isinstance(error, (ValueError, RuntimeError)) else type(error).__name__
        print(f'未确认成功：{message}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
