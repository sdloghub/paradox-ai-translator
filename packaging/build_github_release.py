"""Validate clean CI bundles and assemble versioned GitHub Release assets."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check_private_data(value):
    if isinstance(value, dict):
        for key in ('api_key', 'entries', 'profiles', 'sources', 'steam_roots', 'steam_libraries', 'developer_mode'):
            if value.get(key):
                raise ValueError('发行配置包含个人数据或开发者设置：' + key)
        for item in value.values():
            check_private_data(item)
    elif isinstance(value, list):
        for item in value:
            check_private_data(item)


def validate_bundle(path, platform):
    with zipfile.ZipFile(path) as archive:
        if archive.testzip() is not None:
            raise ValueError('发行包损坏')
        names = archive.namelist()
        for name in names:
            parts = PurePosixPath(name).parts
            if name.startswith('/') or '..' in parts or '\\' in name:
                raise ValueError('发行包包含不安全路径')
            if any(part.startswith('app_data') for part in parts) or name.endswith(('.sqlite3', '.db', 'config-storage.json')):
                raise ValueError('发行包包含本地数据库或保存模式')
        # Only external release templates; ignore Python/dependency JSON inside the app.
        templates = {}
        for name in names:
            if len(PurePosixPath(name).parts) == 2 and PurePosixPath(name).name in ('config.json', 'providers.json', 'completed.json'):
                templates[PurePosixPath(name).name] = json.loads(archive.read(name))
        if len(templates) != 3:
            raise ValueError('缺少空白发行配置模板')
        for value in templates.values():
            check_private_data(value)
        if platform == 'windows-x64':
            exe = archive.read('WorkshopTranslator/WorkshopTranslator.exe')
            if not exe.startswith(b'MZ'):
                raise ValueError('Windows 可执行文件无效')
            checksum = archive.read('WorkshopTranslator/SHA256SUMS.txt').decode().split()[0]
            if hashlib.sha256(exe).hexdigest() != checksum:
                raise ValueError('Windows 可执行文件校验失败')
        elif not any(name.endswith('.app/Contents/MacOS/WorkshopTranslator') for name in names):
            raise ValueError('缺少 Mac 可执行文件')


def build(version, commit, artifacts, destination):
    artifacts, destination = Path(artifacts), Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    bundles = list(artifacts.rglob('WorkshopTranslator-Windows.zip'))
    bundles += list(artifacts.rglob('WorkshopTranslator-macOS-*.zip'))
    if len(bundles) != 2:
        raise ValueError('必须包含恰好一个 Windows 和一个 macOS 发行包')
    assets = []
    for bundle in bundles:
        platform = 'windows-x64' if bundle.name == 'WorkshopTranslator-Windows.zip' else bundle.stem.removeprefix('WorkshopTranslator-').lower()
        validate_bundle(bundle, platform)
        target = destination / f'WorkshopTranslator-{version}-{platform}.zip'
        shutil.copy2(bundle, target)
        assets.append(target)
    source = destination / f'WorkshopTranslator-{version}-source.zip'
    subprocess.run(['git', 'archive', '--format=zip', '--prefix=WorkshopTranslator-source/', '-o', str(source.resolve()), commit], cwd=ROOT, check=True)
    with zipfile.ZipFile(source) as archive:
        if archive.testzip() is not None:
            raise ValueError('源码包损坏')
        if any(part in ('app_data', '.venv', 'dist') for name in archive.namelist() for part in PurePosixPath(name).parts):
            raise ValueError('源码包包含本地文件')
    assets.append(source)
    (destination / 'SHA256SUMS.txt').write_text(''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '  ' + path.name + '\n' for path in sorted(assets)), encoding='utf-8')
    return assets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--version', required=True)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--artifacts', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    for path in build(args.version, args.commit, args.artifacts, args.output):
        print(path)
