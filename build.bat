@echo off
cd /d "%~dp0"
title Build LellaVerse Smart Organizer Pro v2.0
echo =======================================================
echo   LellaVerse Smart Organizer Pro v2.0 - Build Pipeline
echo =======================================================
echo Working folder: %cd%
echo.

set PY=python
python --version >nul 2>&1
if errorlevel 1 set PY=py -3
%PY% --version >nul 2>&1
if errorlevel 1 goto nopython

if not exist lellaverse_organizer.py goto nofile
if not exist requirements.txt goto nofile

REM 1. Create clean virtual environment
if not exist .venv_build\Scripts\python.exe (
    echo [1/4] Creating isolated clean virtual environment .venv_build...
    %PY% -m venv .venv_build
    if errorlevel 1 goto fail
) else (
    echo [1/4] Using existing isolated virtual environment .venv_build...
)

set VENV_PY=.venv_build\Scripts\python.exe

echo Installing minimal dependencies into .venv_build...
%VENV_PY% -m pip install --upgrade pip
%VENV_PY% -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto fail

REM 2. Build with PyInstaller spec
echo.
echo [2/4] Building standalone executable with optimized spec...
%VENV_PY% -m PyInstaller --noconfirm --clean LellaVerseOrganizer.spec
if errorlevel 1 goto fail

REM 3. Build Inno Setup Installer
echo.
echo [3/4] Checking for Inno Setup compiler ISCC.exe...
set ISCC=
where iscc >nul 2>&1
if not errorlevel 1 set ISCC=iscc
if not defined ISCC (
    if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set ISCC="%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
)
if not defined ISCC (
    if exist "C:\Program Files\Inno Setup 6\ISCC.exe" set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
)

if defined ISCC (
    echo Compiling Windows installer with Inno Setup...
    %ISCC% LellaVerseOrganizer_Setup.iss
    if errorlevel 1 (
        echo [WARNING] Inno Setup compilation failed.
    ) else (
        echo [OK] Installer compiled successfully into Output\
    )
) else (
    echo [NOTE] Inno Setup compiler not found. Installer compilation skipped.
)

REM 4. Make zip package
echo.
echo [4/4] Creating distribution zip archive...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\LellaVerseOrganizer' -DestinationPath 'dist\LellaVerseOrganizer-v2.0.0.zip' -Force"
if errorlevel 1 goto fail

echo.
echo =======================================================
echo   BUILD COMPLETED SUCCESSFULLY!
echo =======================================================
echo App Folder   : dist\LellaVerseOrganizer
echo Executable   : dist\LellaVerseOrganizer\LellaVerseOrganizer.exe
echo Zip Archive  : dist\LellaVerseOrganizer-v2.0.0.zip
if exist Output\LellaVerseOrganizer_Setup_v2.0.0.exe (
    echo Setup Exe    : Output\LellaVerseOrganizer_Setup_v2.0.0.exe
)
echo.
exit /b 0

:nopython
echo.
echo Python was not found on this PC.
goto fail

:nofile
echo.
echo Required files missing in %cd%
goto fail

:fail
echo.
echo [ERROR] Build failed! Check the log messages above.
exit /b 1
