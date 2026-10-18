@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================
echo   ClipFlow Studio - instalacao (Windows)
echo ============================================

rem Escolhe Python 3.13 ou 3.12 (o faster-whisper ainda nao tem pacotes para 3.14+ no Windows)
set "PY="
py -3.13 -c "import sys" >nul 2>nul && set "PY=py -3.13"
if not defined PY py -3.12 -c "import sys" >nul 2>nul && set "PY=py -3.12"
if not defined PY (
  echo [ERRO] Python 3.13 ou 3.12 nao encontrado.
  echo         Baixe o Python 3.13 em https://www.python.org/downloads/windows/
  echo         Ele pode ficar instalado junto com outras versoes, como a 3.15.
  pause & exit /b 1
)
echo Usando %PY%
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
  %PY% -m venv .venv || (echo [ERRO] Falha ao criar .venv & pause & exit /b 1)
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
