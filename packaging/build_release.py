"""Create a portable program ZIP; update it using saved local settings and markers."""
import argparse
import hashlib
import json
import os
import sqlite3
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
    saved = ROOT / 'app_data'
    if os.name == 'nt' and not saved.is_dir():
        saved = Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData/Local'))) / 'WorkshopTranslator/app_data'
    data_dir = Path(data_dir or saved).resolve()
    destination = Path(destination or ROOT / 'dist/WorkshopTranslator-Windows.zip')
    preferred = ROOT / 'dist/WorkshopTranslator/WorkshopTranslator.exe'
    executable = Path(executable or (preferred if preferred.is_file() else ROOT / 'dist/WorkshopTranslator.exe'))
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
    database = data_dir / 'translations.sqlite3'
    if database.is_file():
        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
        try:
            connection.row_factory = sqlite3.Row
            if connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='translation_entries'").fetchone():
                completed['entries'] = [dict(row) for row in connection.execute('SELECT * FROM translation_entries')]
        finally:
            connection.close()
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
            support = executable.parent / '_internal'
            if support.is_dir():
                for dependency in support.rglob('*'):
                    if dependency.is_file():
                        archive.write(dependency, prefix + str(dependency.relative_to(executable.parent)).replace('\\', '/'))
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
