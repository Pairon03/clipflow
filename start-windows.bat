@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (echo Execute primeiro setup-windows.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
cd backend
python -m app
pause
