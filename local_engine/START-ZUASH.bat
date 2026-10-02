@echo off
setlocal
cd /d "%~dp0"
echo ==========================================
echo       ZUASH - PDF AI VISUAL ENGINE
echo ==========================================
where py >nul 2>&1
if errorlevel 1 (echo [ERROR] Python no esta instalado o no esta en PATH.& pause& exit /b 1)
if not exist ".venv\Scripts\python.exe" (
  echo [1/4] Creando entorno virtual...
  py -3.12 -m venv .venv
  if errorlevel 1 py -m venv .venv
)
echo [2/4] Instalando/verificando dependencias...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (echo [ERROR] No se pudieron instalar las dependencias.& pause& exit /b 1)
echo [3/4] Verificando modelos Ollama...
where ollama >nul 2>&1
if errorlevel 1 (echo [ERROR] Ollama no esta instalado. Instala Ollama y vuelve a ejecutar este archivo.& pause& exit /b 1)
ollama list | findstr /I "qwen3-vl:8b" >nul
if errorlevel 1 (
  echo No se encontro qwen3-vl:8b. Descargando modelo visual (~6.1 GB)...
  ollama pull qwen3-vl:8b
  if errorlevel 1 (echo [ERROR] No se pudo descargar qwen3-vl:8b.& pause& exit /b 1)
)
echo [4/4] Iniciando servidor...
echo.
echo Qwen3-VL analiza visualmente las paginas y Qwen3 puede servir como respaldo de texto.
echo.
start "" "http://127.0.0.1:8765"
".venv\Scripts\python.exe" -m uvicorn app:app --host 127.0.0.1 --port 8765
pause
