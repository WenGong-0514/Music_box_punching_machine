@echo off
rem Pure-ASCII launcher.
rem Kept ASCII + bracket-free (goto labels only) so cmd.exe cannot mis-parse it.
chcp 65001 >nul
rem ASCII-safe code page switch so the app's UTF-8 banner (printed by Python) renders.
setlocal
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set "_PY="

set "_VENVPY=%~dp0.venv\Scripts\python.exe"
if exist "%_VENVPY%" set "_PY=%_VENVPY%"

if defined _PY goto :run
where python >nul 2>nul
if %errorlevel%==0 set "_PY=python"
if defined _PY goto :run

set "_OLD=C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe"
if exist "%_OLD%" set "_PY=%_OLD%"
if defined _PY goto :run

echo [!] No Python found. In a terminal inside this folder run:
echo        python -m venv .venv
echo        .venv\Scripts\python -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
echo        .venv\Scripts\python -m pip install third_party\basic_pitch-0.4.0-py2.py3-none-any.whl --no-deps
echo    Then run this file again (see README "Environment Matrix").
pause
exit /b 1

:run
"%_PY%" -m server.main
endlocal
pause
