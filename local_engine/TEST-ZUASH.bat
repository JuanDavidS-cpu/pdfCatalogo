@echo off
setlocal
cd /d "%~dp0"
echo === ZUASH TEXT AI TEST ===
python --version
echo.
echo Verificando Ollama...
curl -s http://127.0.0.1:11434/api/tags
echo.
echo.
echo Verificando FastAPI...
".venv\Scripts\python.exe" -c "import fitz,fastapi,ollama,requests,bs4; print('Dependencias OK')"
echo.
pause
