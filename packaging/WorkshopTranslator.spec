# Build with PyInstaller on Windows x64; include only application resources.
from pathlib import Path
root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'workshop_app.py')],
    pathex=[str(root)],
    binaries=[],
    datas=[(str(root / 'workshop_ui.html'), '.'), (str(root / 'rules.json'), '.'), (str(root / 'vendor'), 'vendor'), (str(root / 'assets'), 'assets')],
    hiddenimports=['paradox', 'request', 'openai', 'winreg', 'translation_cache', 'tkinter.filedialog'],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, analysis.binaries, analysis.datas, [],
    name='WorkshopTranslator', icon=str(root / 'assets/app-icon.ico'), debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=True,
)
