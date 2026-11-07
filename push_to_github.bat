@echo off
setlocal
cd /d "%~dp0"
echo ========================================================
echo        Paradox AI Translator - GitHub Push Helper
echo ========================================================
echo.
echo Pushing overhaul to GitHub:
echo   1. Legacy branch: legacy-main
echo   2. Legacy tag:    v0.2.0-legacy
echo   3. Overhaul main: main
echo.
echo Note: If a browser window appears, click Authorize.
echo.
echo [1/3] Pushing legacy-main branch...
git push origin legacy-main
echo.
echo [2/3] Pushing v0.2.0-legacy tag...
git push origin v0.2.0-legacy
echo.
echo [3/3] Pushing main branch...
git push origin main
echo.
echo ========================================================
if errorlevel 1 (
    echo [Notice] Push finished with warnings or errors. Check log above.
) else (
    echo [Success] Pushed all branches and tags to GitHub!
)
echo ========================================================
echo.
pause
