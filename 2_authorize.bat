@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist main.exe (
  main.exe --authorize
  goto end
)
if not exist ".venv\Scripts\python.exe" (
  echo Run 1_setup.bat first / Сначала запустите 1_setup.bat.
  goto end
)
".venv\Scripts\python.exe" main.py --authorize
:end
pause
