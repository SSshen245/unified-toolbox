@echo off
rem ============================================================
rem  Unified Toolbox - one-click release
rem  Double-click this file, or run:
rem      venv\Scripts\python.exe release.py "commit message"
rem
rem  All messages are printed by release.py (this file stays
rem  ASCII-only on purpose: cmd.exe cannot reliably read
rem  non-ASCII text from a .cmd file without a BOM).
rem ============================================================
cd /d %~dp0
chcp 65001 >nul 2>&1

if not exist "venv\Scripts\python.exe" (
    echo [ERROR] venv\Scripts\python.exe not found.
    echo         Create the environment first, then install deps:
    echo             python -m venv venv
    echo             venv\Scripts\python.exe -m pip install -r requirements.txt
    pause
    exit /b 1
)

venv\Scripts\python.exe "release.py" %*
echo.
pause
