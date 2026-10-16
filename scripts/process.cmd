@echo off
setlocal
cd /d "%~dp0.."
if errorlevel 1 exit /b %errorlevel%
if not exist .runtime mkdir .runtime
if errorlevel 1 exit /b %errorlevel%
".venv\Scripts\python.exe" manage.py process_jobs --limit 10 %* >> .runtime\process.log 2>&1
exit /b %errorlevel%
