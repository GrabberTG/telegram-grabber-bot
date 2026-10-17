@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
if exist main.exe goto configure
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Install Python 3.11 x64 with Python Launcher from python.org.
  echo Установите Python 3.11 x64 с Python Launcher.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" py -3.11 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
:configure
if not exist config.json copy config.example.json config.json >nul
echo Fill in your own credentials, save the file, then run 2_authorize.bat.
echo Заполните свои данные, сохраните файл и запустите 2_authorize.bat.
notepad config.json
pause
exit /b 0
:failed
echo Installation failed. Save the error from this window.
echo Установка не завершена. Сохраните текст ошибки.
pause
exit /b 1
