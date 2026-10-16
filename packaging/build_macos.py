"""Build the Apple Silicon app and a ZIP preserving bundle symlinks/signatures."""
import hashlib
import argparse
from datetime import datetime
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description='构建 Mac 应用与发布包/覆盖更新包')
    parser.add_argument('--update', action='store_true', help='只打包应用与说明，不包含用户配置')
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('请在 Apple Silicon Mac 上运行此脚本')
    from PIL import Image
    sys.path.insert(0, str(ROOT))
    from packaging_build_helpers import release_settings

    (ROOT / 'build').mkdir(exist_ok=True)
    with Image.open(ROOT / 'assets/app-icon.png') as icon:
        icon.convert('RGBA').resize((1024, 1024), Image.Resampling.LANCZOS).save(
            ROOT / 'build/macos-icon.icns', format='ICNS')
    subprocess.run([sys.executable, '-m', 'PyInstaller', '--noconfirm',
                    '--workpath', str(ROOT / 'build/macos'),
                    str(ROOT / 'packaging/WorkshopTranslator-macOS.spec')], cwd=ROOT, check=True)
    destination = ROOT / 'dist/WorkshopTranslator-macOS-arm64'
    destination.mkdir(parents=True, exist_ok=True)
    app = destination / 'WorkshopTranslator.app'
    if app.exists():
        shutil.rmtree(app)
    subprocess.run(['/usr/bin/ditto', str(ROOT / 'dist/WorkshopTranslator.app'), str(app)], check=True)
    shutil.copy2(ROOT / 'Mac使用说明.md', destination / 'Mac使用说明.md')
    # Refresh bundled templates without overwriting any existing portable settings.
    for name, payload in release_settings().items():
        target = destination / name
        if not target.exists():
            target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    name = ('WorkshopTranslator-macOS-arm64-Update-' + datetime.now().strftime('%Y%m%d')
            if args.update else 'WorkshopTranslator-macOS-arm64')
    archive = ROOT / 'dist' / (name + '.zip')
    archive.unlink(missing_ok=True)
    with tempfile.TemporaryDirectory(prefix='mac-release-') as temporary:
        payload = destination
        if args.update:
            payload = Path(temporary) / 'WorkshopTranslator-macOS-arm64'
            payload.mkdir()
            subprocess.run(['/usr/bin/ditto', str(app), str(payload / app.name)], check=True)
            shutil.copy2(ROOT / 'Mac使用说明.md', payload / 'Mac使用说明.md')
            (payload / '更新说明.txt').write_text(
                '请先退出旧版 WorkshopTranslator 进程。\n'
                '解压后，将 WorkshopTranslator.app 拖入原程序文件夹，选择替换整个应用。\n'
                '只替换 .app，保留原文件夹中的 config.json、providers.json、completed.json 等文件。\n'
                '用户目录中的配置、SQLite 缓存和备份继续保留，首次启动会自动升级数据库。\n'
                '新增：翻译条目浏览、状态筛选、搜索分页、原文件行定位和人工状态标注。\n', encoding='utf-8')
        subprocess.run(['/usr/bin/ditto', '-c', '-k', '--sequesterRsrc', '--keepParent',
                        str(payload), str(archive)], check=True)
    checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
    (ROOT / 'dist' / (name + '.sha256')).write_text(
        f'{checksum}  {archive.name}\n', encoding='utf-8')
    print(archive)


if __name__ == '__main__':
    main()
