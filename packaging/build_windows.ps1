$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ($env:OS -ne 'Windows_NT') { throw 'Build this executable on Windows x64.' }
$env:PYTHONUTF8 = '1'
if (!(Test-Path '.venv-build/Scripts/python.exe')) {
    py -3.12 -m venv .venv-build
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.12 x64 is required.' }
}
$python = '.venv-build/Scripts/python.exe'
& $python -m pip install -r requirements.txt -r packaging/requirements-build.txt
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
& $python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed.' }
& $python -m PyInstaller --clean --noconfirm packaging/WorkshopTranslator.spec
if ($LASTEXITCODE -ne 0) { throw 'Executable build failed.' }
& '.\dist\WorkshopTranslator\WorkshopTranslator.exe' --self-test
if ($LASTEXITCODE -ne 0) { throw 'Packaged executable self-test failed.' }
& $python packaging/build_release.py
if ($LASTEXITCODE -ne 0) { throw 'Release packaging failed.' }
Write-Host 'Completed: dist/WorkshopTranslator-Windows.zip'
