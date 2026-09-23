@echo off
setlocal enabledelayedexpansion
REM ============================================================
REM  F.R.I.D.A.Y. one-command build + sign pipeline
REM
REM  Usage - from the project root, or just double-click:
REM    build.bat                  build app exes + installers, sign everything
REM    build.bat --no-installers  build only the two app exes, then sign
REM    build.bat --selftest       ...and smoke-test the signed portable exe
REM
REM  Steps:
REM    1. Verify the venv and PyInstaller are available
REM    2. Build dist\friday.exe + dist\friday-embedded.exe via friday.spec
REM    3. Build the two installer exes via build\build_installers.py
REM    4. Sign every dist\*.exe via build\sign_installers.ps1
REM       - self-signed cert reuse, per-user trust, DigiCert timestamp
REM    5. Optional - run the packaged self-test on the signed portable exe
REM
REM  NOTE: inside parenthesized if/for blocks, literal parentheses in
REM  echo text must be escaped with ^ or cmd misparses the block.
REM ============================================================

set "SKIP_INSTALLERS=0"
set "RUN_SELFTEST=0"
for %%a in (%*) do (
    if /i "%%a"=="--no-installers" set "SKIP_INSTALLERS=1"
    if /i "%%a"=="--selftest" set "RUN_SELFTEST=1"
)

cd /d "%~dp0"
echo ============================================================
echo  F.R.I.D.A.Y. build + sign
echo ============================================================

REM ---- 1. Environment checks -------------------------------------------
if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv\Scripts\python.exe not found.
    echo         Create the venv and install requirements.txt first.
    exit /b 1
)
set "PY=.venv\Scripts\python.exe"
"!PY!" -m PyInstaller --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] PyInstaller is not installed in the venv.
    echo         Install it with: .venv\Scripts\python.exe -m pip install pyinstaller
    exit /b 1
)
for /f "delims=" %%v in ('""!PY!" -m PyInstaller --version 2^>nul"') do echo [1/4] PyInstaller %%v found.

REM ---- 2. App executables ----------------------------------------------
echo [2/4] Building app executables - friday.spec ...
"!PY!" -m PyInstaller friday.spec --noconfirm
if errorlevel 1 (
    echo [ERROR] App build failed - see the PyInstaller output above.
    exit /b 1
)
if not exist "dist\friday.exe" (
    echo [ERROR] dist\friday.exe was not produced.
    exit /b 1
)

REM ---- 3. Installers ----------------------------------------------------
if "!SKIP_INSTALLERS!"=="1" (
    echo [3/4] Skipping installers per --no-installers.
) else (
    echo [3/4] Building installers...
    "!PY!" build\build_installers.py
    if errorlevel 1 (
        echo [ERROR] Installer build failed.
        exit /b 1
    )
)

REM ---- 4. Signing -------------------------------------------------------
echo [4/4] Signing executables...
powershell -NoProfile -ExecutionPolicy Bypass -File "build\sign_installers.ps1"
if errorlevel 1 (
    echo [ERROR] Signing failed - see the PowerShell output above.
    exit /b 1
)

REM ---- Optional self-test of the signed portable exe --------------------
if "!RUN_SELFTEST!"=="1" (
    echo.
    echo Running packaged self-test on the signed dist\friday.exe...
    powershell -NoProfile -Command "$env:FRIDAY_SELFTEST='1'; $env:FRIDAY_QUIET='1'; $p = Start-Process -FilePath 'dist\friday.exe' -Wait -PassThru -NoNewWindow -RedirectStandardOutput 'workspace\selftest-exe.log' -RedirectStandardError 'workspace\selftest-exe-err.log'; exit $p.ExitCode"
    if errorlevel 1 (
        echo [ERROR] Packaged self-test failed - see workspace\selftest-exe.log
        exit /b 1
    )
    findstr /c:"SELFTEST" workspace\selftest-exe.log
)

echo.
echo ============================================================
echo  Build + sign complete. Outputs:
for %%f in (dist\*.exe) do echo    %%f  ^[%%~zf bytes^]
echo ============================================================
endlocal
exit /b 0
