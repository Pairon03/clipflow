@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist .venv (echo Execute primeiro setup-windows.bat & pause & exit /b 1)
call .venv\Scripts\activate.bat
cd backend
rem aplica atualizacoes copiadas por cima (dependencias novas e recompila a interface se mudou)
python -m app.update_check
python -m app
pause
