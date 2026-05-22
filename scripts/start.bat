@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "VENV_PYTHON=%PROJECT_ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Virtual environment was not found. Run scripts\install.bat first.
    exit /b 1
)

call :is_ollama_provider
if not errorlevel 1 (
    call :ensure_ollama
    if errorlevel 1 exit /b 1
)

pushd "%PROJECT_ROOT%" >nul
"%VENV_PYTHON%" -m hotel_search_assistant %*
set "APP_EXIT_CODE=%ERRORLEVEL%"
popd >nul

endlocal & exit /b %APP_EXIT_CODE%

:is_ollama_provider
"%VENV_PYTHON%" -c "from hotel_search_assistant.config import load_config; raise SystemExit(0 if load_config().provider.lower() == 'ollama' else 1)" >nul 2>nul
exit /b %ERRORLEVEL%

:ensure_ollama
call :check_ollama
if not errorlevel 1 (
    echo Ollama is already running at http://localhost:11434
    exit /b 0
)

where ollama >nul 2>nul
if errorlevel 1 (
    echo Ollama was not found. Install it from https://ollama.com/ and try again.
    exit /b 1
)

echo Ollama is not running. Starting ollama serve...
start "Ollama Server" /min cmd /c "ollama serve"

echo Waiting for Ollama to become ready...
for /L %%I in (1,1,30) do (
    call :check_ollama
    if not errorlevel 1 (
        echo Ollama is ready.
        exit /b 0
    )
    timeout /t 1 /nobreak >nul
)

echo Ollama did not become ready within 30 seconds.
echo Try running "ollama serve" manually in another terminal.
exit /b 1

:check_ollama
powershell -NoProfile -ExecutionPolicy Bypass -Command "try { $response = Invoke-WebRequest -UseBasicParsing -Uri 'http://localhost:11434/api/tags' -TimeoutSec 2; if ($response.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>nul
exit /b %ERRORLEVEL%
