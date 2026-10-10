"""Package source and development context using an explicit safe file list."""
import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def build_handoff(destination=None, release=None):
    release = Path(release or ROOT / 'dist/WorkshopTranslator-Windows.zip')
    # A handoff must carry a complete usable release, with no embedded API key.
    def check(value):
        if isinstance(value, dict):
            if value.get('api_key'):
                raise ValueError('发布包包含密钥，不能打包交接')
            for item in value.values():
                check(item)
        elif isinstance(value, list):
            for item in value:
                check(item)
    with zipfile.ZipFile(release) as program:
        for name in ('config.json', 'providers.json', 'completed.json'):
            check(json.loads(program.read('WorkshopTranslator/' + name)))
    files = ['workshop_app.py', 'paradox.py', 'request.py', 'translation_cache.py',
             'main.py', 'rules.json', 'workshop_ui.html', 'requirements.txt', '.gitignore',
             'README.md', '性能与改进建议.md', 'Windows使用说明.md', '试运行说明.md', '交接说明.md',
             '启动翻译程序.command', '演示程序.command', '.github/workflows/build-windows.yml']
    files += [path.relative_to(ROOT).as_posix() for folder in ('tests', 'assets', 'vendor', 'packaging')
              for path in (ROOT / folder).rglob('*') if path.is_file() and '__pycache__' not in path.parts]
    destination = Path(destination or ROOT / 'dist/WorkshopTranslator-Codex-Handoff.zip')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix('.zip.tmp')
    try:
        with zipfile.ZipFile(temporary, 'w', zipfile.ZIP_DEFLATED) as target:
            prefix = 'WorkshopTranslator-Handoff/'
            target.write(ROOT / '交接说明.md', prefix + '先读交接说明.md')
            for name in files:
                path = ROOT / name
                if path.is_symlink() or not path.resolve().is_relative_to(ROOT):
                    raise ValueError('交接源码路径不安全')
                target.write(path, prefix + 'source/' + name)
            target.write(release, prefix + 'Windows/WorkshopTranslator-Windows.zip')
            benchmark = ROOT / 'dist/startup-benchmark.json'
            if benchmark.is_file():
                target.write(benchmark, prefix + 'Windows/startup-benchmark.json')
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
    return destination


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='生成可交给另一 Codex 的源码与上下文压缩包')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    print(build_handoff(args.output))
