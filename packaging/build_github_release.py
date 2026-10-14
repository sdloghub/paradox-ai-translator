"""Prepare verified upload-ready GitHub Release assets without local user data."""
import hashlib
import json
from pathlib import Path
import shutil
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.1.0-preview.20261014'
COMMIT = 'ba70536ff30130351d0928325131c081fadfd0d6'


def check_private_data(value):
    if isinstance(value, dict):
        if value.get('api_key'):
            raise ValueError('发布文件包含 API Key')
        if value.get('entries'):
            raise ValueError('发布文件包含个人翻译记录')
        if value.get('profiles') or value.get('sources'):
            raise ValueError('发布文件包含个人接口或来源记录')
        for item in value.values():
            check_private_data(item)
    elif isinstance(value, list):
        for item in value:
            check_private_data(item)


def build():
    release = ROOT / 'dist/WorkshopTranslator-Windows.zip'
    update = ROOT / 'dist/WorkshopTranslator-Update-20261014.zip'
    with zipfile.ZipFile(release) as program:
        if program.testzip() is not None:
            raise ValueError('完整程序包损坏')
        for name in ('config.json', 'providers.json', 'completed.json'):
            check_private_data(json.loads(program.read('WorkshopTranslator/' + name)))
        for name in program.namelist():
            if 'app_data' in Path(name).parts or name.endswith(('.sqlite3', '.db')) or name.endswith('config-storage.json'):
                raise ValueError('完整程序包包含本地数据')
        exe = program.read('WorkshopTranslator/WorkshopTranslator.exe')
        checksum = program.read('WorkshopTranslator/SHA256SUMS.txt').decode().split()[0]
        if hashlib.sha256(exe).hexdigest() != checksum:
            raise ValueError('EXE 校验值不一致')
    with zipfile.ZipFile(update) as patch:
        if patch.testzip() is not None:
            raise ValueError('更新包损坏')
        protected = {'config.json', 'providers.json', 'completed.json', 'config-storage.json', 'app_data', 'translations.sqlite3'}
        if any(set(Path(name).parts) & protected for name in patch.namelist()):
            raise ValueError('更新包会覆盖个人数据')
        if patch.read('WorkshopTranslator.exe') != exe:
            raise ValueError('完整包和更新包 EXE 版本不一致')

    destination = ROOT / 'dist' / ('GitHub-Release-v' + VERSION)
    destination.mkdir(parents=True, exist_ok=True)
    assets = [
        (release, 'WorkshopTranslator-' + VERSION + '-windows-x64.zip'),
        (update, 'WorkshopTranslator-' + VERSION + '-windows-x64-update.zip'),
    ]
    for source, name in assets:
        if source == release:
            with zipfile.ZipFile(source) as original, zipfile.ZipFile(destination / name, 'w', zipfile.ZIP_DEFLATED) as public:
                for item in original.infolist():
                    if item.filename == 'WorkshopTranslator/交接说明.md':
                        continue
                    public.writestr(item, original.read(item))
        else:
            shutil.copy2(source, destination / name)
    notes = '''# Workshop Translator v0.1.0-preview.20261014

用于 Paradox 游戏创意工坊 Mod 本地翻译的预览版，支持扫描、AI 翻译、缓存复用、中文备份与恢复。

## 下载与使用

- 首次使用 Windows：下载 windows-x64.zip，完整解压后运行 WorkshopTranslator.exe，保留 _internal 文件夹。无需另行安装 Python。
- 已安装用户：下载 windows-x64-update.zip，关闭程序后直接解压到原 EXE 所在文件夹，覆盖同名文件。累计包含此前修复，适用于 2026-10-10 最后完整发布版及其后已交付的更新版。
- 本次没有 macOS 可执行文件。Mac 可使用源码方式运行；macOS 独立应用需另行构建和验证。

## 功能与修复

- 配置可保存在程序所在文件夹或用户文件夹，切换时复制设置、合并接口列表，重启后保留模式。
- 按游戏分类，优先通过 Steam Workshop ACF 清单发现本机 Mod，进入具体 Mod 后扫描文本。
- 区分已翻译、已缓存、未翻译、需更新，复用英文哈希匹配的译文。
- 空白条目保留原样，不发送给模型；格式错误和翻译失败保留原文并记录文件、行号与整行原文。
- 支持已有中文/缓存导入导出、SQLite 备份与一键复制；Steam 投稿入口目前未启用。

## 验证范围

76 项自动测试及 Windows 打包后的离线自检通过。真实 Steam API 与付费模型翻译未在本次发布准备中验证。

完整包使用空白默认配置，不包含个人密钥、翻译缓存或数据库；更新包不覆盖个人配置、保存模式标记、缓存与备份。AI 请求可能产生提供商费用。

源码提交：ba70536ff30130351d0928325131c081fadfd0d6
构建记录：https://github.com/sdloghub/paradox-ai-translator/actions/runs/38418215086
'''
    (destination / 'RELEASE_NOTES.md').write_text(notes, encoding='utf-8')
    instructions = '''GitHub Release 发布文件集

建议标题：Workshop Translator v0.1.0-preview.20261014
建议标签：v0.1.0-preview.20261014
标签目标提交：ba70536ff30130351d0928325131c081fadfd0d6
仓库：sdloghub/paradox-ai-translator

进入仓库 Releases → Draft a new release，将标签指向上述提交（对应已验证构建）。
复制 RELEASE_NOTES.md 作为发布说明，勾选预发布版本。
将两个 Windows ZIP 和 SHA256SUMS.txt 作为独立附件上传。
本文件集的外层 ZIP 仅供整理、传递，用户下载应直接选择其中的程序 ZIP 或更新 ZIP。
GitHub 会为标签自动提供 Source code 下载，不需要上传完整聊天包或开发交接包。
当前仅整理了本地文件，尚未在线创建或发布 GitHub Release。
'''
    (destination / '发布步骤.txt').write_text(instructions, encoding='utf-8')
    hashes = []
    for name in [name for _, name in assets] + ['RELEASE_NOTES.md']:
        hashes.append(hashlib.sha256((destination / name).read_bytes()).hexdigest() + '  ' + name)
    (destination / 'SHA256SUMS.txt').write_text('\n'.join(hashes) + '\n', encoding='utf-8')
    output = Path(str(destination) + '.zip')
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_STORED) as archive:
        for path in sorted(destination.iterdir()):
            archive.write(path, destination.name + '/' + path.name)
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise ValueError('发布文件集压缩包校验失败')
    return output


if __name__ == '__main__':
    print(build())
