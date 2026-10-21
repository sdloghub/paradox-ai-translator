from pathlib import Path
import platform

root = Path(SPECPATH).parent
analysis = Analysis(
    [str(root / 'workshop_app.py')], pathex=[str(root)], binaries=[],
    datas=[(str(root / 'workshop_ui.html'), '.'), (str(root / 'rules.json'), '.'),
           (str(root / 'entry_browser_ui.js'), '.'), (str(root / 'tutorial_ui.js'), '.'),
           (str(root / 'vendor'), 'vendor'), (str(root / 'assets'), 'assets')],
    hiddenimports=['paradox', 'request', 'openai', 'translation_cache', 'aggregate_export', 'mod_export', 'tkinter.filedialog'],
    hookspath=[], hooksconfig={},
    runtime_hooks=[str(root / 'packaging/macos_logging.py')],
    excludes=['pandas', 'numpy', 'scipy', 'matplotlib', 'PIL', 'IPython', 'torch', 'sympy'],
    noarchive=False,
)
pyz = PYZ(analysis.pure)
exe = EXE(pyz, analysis.scripts, [], exclude_binaries=True,
          name='WorkshopTranslator', debug=False, strip=False, upx=False,
          console=False, target_arch=platform.machine())
collection = COLLECT(exe, analysis.binaries, analysis.datas,
                     strip=False, upx=False, name='WorkshopTranslator-macOS-runtime')
app = BUNDLE(collection, name='WorkshopTranslator.app',
             icon=str(root / 'build/macos-icon.icns'),
             bundle_identifier='com.workshoptranslator.desktop',
             info_plist={'CFBundleDisplayName': 'Workshop 翻译程序',
                         'CFBundleShortVersionString': '0.2.0',
                         'NSHighResolutionCapable': True,
                         'LSMinimumSystemVersion': '11.0'})
