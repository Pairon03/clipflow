@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   ClipFlow Studio - instalacao (Windows)
echo ============================================

where python >nul 2>nul || (echo [ERRO] Python nao encontrado. Instale o Python 3.12 ou 3.13 em https://www.python.org/downloads/ marcando "Add python.exe to PATH". & pause & exit /b 1)
where node >nul 2>nul || (echo [ERRO] Node.js nao encontrado. Instale o Node.js LTS em https://nodejs.org & pause & exit /b 1)
where ffmpeg >nul 2>nul
if errorlevel 1 (
  if not exist bin\ffmpeg.exe (
    echo [AVISO] FFmpeg nao encontrado no PATH nem em .\bin
    echo         Instale com:  winget install Gyan.FFmpeg
    echo         ou baixe a build "full" e copie ffmpeg.exe e ffprobe.exe para a pasta .\bin
  )
)

if not exist .venv (
  echo Criando ambiente virtual Python...
  python -m venv .venv || (echo [ERRO] Falha ao criar .venv & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r backend\requirements.txt || (echo [ERRO] Falha ao instalar dependencias Python & pause & exit /b 1)

echo Instalando e compilando a interface...
pushd frontend
call npm install || (popd & echo [ERRO] npm install falhou & pause & exit /b 1)
call npm run build || (popd & echo [ERRO] build da interface falhou & pause & exit /b 1)
popd

if not exist config.toml copy config.example.toml config.toml >nul
echo.
echo Instalacao concluida! Execute start-windows.bat para abrir o ClipFlow Studio.
pause
