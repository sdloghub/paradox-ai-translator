"""Create a portable program ZIP; update it using saved local settings and markers."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def sanitized(value):
    if isinstance(value, dict):
        return {key: '' if key == 'api_key' else sanitized(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitized(item) for item in value]
    return value


def build_release(destination=None, data_dir=None, executable=None):
    import workshop_app
    data_dir = Path(data_dir or ROOT / 'app_data')
    destination = Path(destination or ROOT / 'dist/WorkshopTranslator-Windows.zip')
    executable = Path(executable or ROOT / 'dist/WorkshopTranslator.exe')
    if not executable.is_file():
        raise FileNotFoundError('请先构建 Windows EXE')
    config = dict(workshop_app.DEFAULT_CONFIG)
    if (data_dir / 'config.json').is_file():
        config.update(json.loads((data_dir / 'config.json').read_text(encoding='utf-8')))
    profiles = {'format': 'workshop-providers-v1', 'profiles': {}}
    completed = {'format': 'workshop-completed-v1', 'entries': []}
    for name, target in [('providers.json', profiles), ('completed.json', completed)]:
        if (data_dir / name).is_file():
            target.update(json.loads((data_dir / name).read_text(encoding='utf-8')))
    files = ['workshop_app.py', 'paradox.py', 'request.py', 'translation_cache.py',
             'workshop_ui.html', 'rules.json', 'requirements.txt', 'Windows使用说明.md', 'README.md']
    files += [str(p.relative_to(ROOT)) for folder in ('vendor', 'assets', 'packaging')
              for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as archive:
            prefix = 'WorkshopTranslator/'
            archive.write(executable, prefix + 'WorkshopTranslator.exe')
            for name in files:
                archive.write(ROOT / name, prefix + name)
            for name, payload in [('config.json', config), ('providers.json', profiles), ('completed.json', completed)]:
                archive.writestr(prefix + name, json.dumps(sanitized(payload), ensure_ascii=False, indent=2))
            archive.writestr(prefix + 'SHA256SUMS.txt', hashlib.sha256(executable.read_bytes()).hexdigest() + '  WorkshopTranslator.exe\n')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成程序发布压缩包，并复制本地配置和完成记录')
    parser.add_argument('--data-dir', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(build_release(args.output, args.data_dir))
