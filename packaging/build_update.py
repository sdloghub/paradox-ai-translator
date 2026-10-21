"""Create a differential ZIP applied inside the existing program directory."""
import argparse
import hashlib
from pathlib import Path, PurePosixPath
import zipfile

PROGRAM_FILES = {'WorkshopTranslator.exe', 'workshop_app.py', 'paradox.py',
                 'request.py', 'translation_cache.py', 'workshop_ui.html', 'entry_browser.py', 'entry_browser_ui.js', 'aggregate_export.py', 'mod_export.py',
                 'server_sessions.py', 'server_workshop.py', 'server_upload.py', 'server_ui.js', 'tutorial_ui.js', 'rules.json', 'requirements.txt', 'SHA256SUMS.txt',
                 'README.md', 'Windows使用说明.md'}


def program_files(archive):
    result = {}
    with zipfile.ZipFile(archive) as source:
        for info in source.infolist():
            if info.is_dir() or not info.filename.startswith('WorkshopTranslator/'):
                continue
            name = info.filename[len('WorkshopTranslator/'):]
            path = PurePosixPath(name)
            if path.is_absolute() or '..' in path.parts or '\\' in name:
                raise ValueError('发布包包含不安全路径')
            if name in PROGRAM_FILES or path.parts[0] in ('_internal', 'vendor', 'assets'):
                result[name] = source.read(info)
    if 'WorkshopTranslator.exe' not in result:
        raise ValueError('发布包缺少 Windows 程序')
    return result


def build_update(base, release, destination):
    old, new = program_files(base), program_files(release)
    changes = {name: data for name, data in new.items() if old.get(name) != data}
    # Use an allowlist: config, providers, completed markers, DBs and workspaces
    # must never enter an overwrite update, even if present in the source ZIP.
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.tmp')
    base_hash = hashlib.sha256(old['WorkshopTranslator.exe']).hexdigest()
    lines = ['覆盖更新说明', '', '请先关闭程序。',
             '将本包直接解压到原 WorkshopTranslator.exe 所在文件夹，覆盖同名文件。',
             '不要额外新建子文件夹，不要删除原 _internal 文件夹。',
             '本包不包含 API 配置、完成记录、数据库或 Mod 文件，不会覆盖这些数据。',
             '空字符串、纯空格与制表符条目保留原样，不发送给模型，不计入待翻译。',
             '', '差异比较基准 EXE SHA256：' + base_hash,
             '变化文件校验值：']
    lines += [hashlib.sha256(data).hexdigest() + '  ' + name for name, data in sorted(changes.items())]
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
            for name, data in changes.items():
                target.writestr(name, data)
            target.writestr('更新说明.txt', '\n'.join(lines) + '\n')
        with zipfile.ZipFile(temporary) as target:
            if target.testzip() is not None:
                raise ValueError('更新包校验失败')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成可直接覆盖原程序文件夹的差异更新包')
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build_update(args.base, args.release, args.output))
