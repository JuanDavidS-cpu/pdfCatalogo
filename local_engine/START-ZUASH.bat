@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo       ZUASH - PDF TEXT AI ENGINE
echo ==========================================
where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python no esta instalado o no esta en PATH.
  pause
  exit /b 1
)
if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creando entorno virtual...
  py -3.12 -m venv .venv
  if errorlevel 1 py -m venv .venv
)
echo [2/3] Instalando/verificando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (
  echo [ERROR] No se pudieron instalar las dependencias.
  pause
  exit /b 1
)
echo [3/3] Iniciando servidor...
echo.
echo IMPORTANTE: Ollama debe estar instalado y ejecutandose.
echo Modelo esperado: qwen3:8b
echo.
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
