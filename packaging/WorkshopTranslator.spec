# Default to a folder bundle to avoid extracting dependencies on each launch.
from pathlib import Path
import os
root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'workshop_app.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'workshop_ui.html'), '.'), (str(root / 'rules.json'), '.'),
           (str(root / 'vendor'), 'vendor'), (str(root / 'assets'), 'assets')],
    hiddenimports=['paradox', 'request', 'openai', 'winreg', 'translation_cache', 'tkinter.filedialog'],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=['pandas', 'numpy', 'scipy', 'matplotlib', 'PIL', 'IPython', 'torch', 'sympy'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
options = dict(name='WorkshopTranslator', icon=str(root / 'assets/app-icon.ico'), debug=False,
               bootloader_ignore_signals=False, strip=False, upx=False, console=True)
if os.environ.get('WORKSHOP_BUILD_MODE') == 'onefile':
    exe = EXE(pyz, analysis.scripts, analysis.binaries, analysis.datas, [], **options)
else:
    exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True, **options)
    collection = COLLECT(exe, analysis.binaries, analysis.datas, strip=False, upx=False,
                         name='WorkshopTranslator')
