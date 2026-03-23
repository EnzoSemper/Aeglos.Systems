@echo off
:: ============================================================
:: AEGLOS Analytics Pro — Windows .exe Builder
:: Produces:  dist\AEGLOS-Analytics-Pro-1.0.0-Windows-x64.exe
:: Requires:  Windows 10/11, Python 3.10+
:: Usage:     Run from the aeglos-analytics directory
:: ============================================================

setlocal enabledelayedexpansion
set ROOT=%~dp0..
set VERSION=1.0.0
set APP_NAME=AEGLOS Analytics Pro
set EXE_NAME=AEGLOS-Analytics-Pro-%VERSION%-Windows-x64

echo.
echo ========================================================
echo   AEGLOS Analytics Pro - Windows .exe Build
echo ========================================================
echo.

:: Check Python
where python >nul 2>&1
if %ERRORLEVEL% neq 0 (
    echo ERROR: Python not found. Install Python 3.10+ from python.org
    exit /b 1
)
for /f "tokens=*" %%V in ('python --version') do echo Found: %%V

:: Create build venv
if not exist "%ROOT%\venv_build" (
    echo Creating build virtual environment...
    python -m venv "%ROOT%\venv_build"
)
call "%ROOT%\venv_build\Scripts\activate.bat"
echo Virtual environment active.

:: Install dependencies
echo Installing dependencies (may take several minutes)...
pip install -q --upgrade pip
pip install -q -r "%ROOT%\requirements.txt"
pip install -q pyinstaller Pillow pywin32
echo Dependencies installed.

:: Generate icon
echo Generating app icon...
python "%ROOT%\build\make_icon.py"

:: Clean previous build
if exist "%ROOT%\dist_app" rmdir /s /q "%ROOT%\dist_app"

:: Run PyInstaller
echo Running PyInstaller (3-10 minutes)...
pyinstaller ^
    --distpath "%ROOT%\dist_app" ^
    --workpath "%ROOT%\build\pyinstaller_work" ^
    --noconfirm ^
    --log-level WARN ^
    "%ROOT%\build\aeglos.spec"

if not exist "%ROOT%\dist_app\%APP_NAME%" (
    echo ERROR: Build failed - output directory not found
    exit /b 1
)
echo PyInstaller build complete.

:: Create installer with NSIS if available, otherwise zip
where makensis >nul 2>&1
if %ERRORLEVEL% equ 0 (
    echo NSIS found - creating installer...
    python "%ROOT%\build\make_nsis.py"
    makensis "%ROOT%\build\aeglos_installer.nsi"
    echo Installer created.
) else (
    echo NSIS not found - creating portable zip...
    if not exist "%ROOT%\dist" mkdir "%ROOT%\dist"
    powershell -Command "Compress-Archive -Path '%ROOT%\dist_app\%APP_NAME%' -DestinationPath '%ROOT%\dist\%EXE_NAME%-portable.zip' -Force"
    echo Portable zip: dist\%EXE_NAME%-portable.zip

    :: Also create a simple .exe launcher using self-extracting approach
    echo Creating single-exe wrapper...
    python "%ROOT%\build\make_sfx.py" "%ROOT%\dist_app\%APP_NAME%" "%ROOT%\dist\%EXE_NAME%.exe"
)

echo.
echo ========================================================
echo   BUILD COMPLETE
echo ========================================================
echo.
echo   Output: dist\%EXE_NAME%.exe  (or -portable.zip)
echo.
echo   To install: Run the .exe as Administrator
echo   Or extract the portable zip and run:
echo     "%APP_NAME%\%APP_NAME%.exe"
echo.
