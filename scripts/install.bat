@echo off
setlocal

set "PROJECT_ROOT=%~dp0.."
set "VENV_PATH=%PROJECT_ROOT%\.venv"
set "VENV_PYTHON=%VENV_PATH%\Scripts\python.exe"
set "REQUIREMENTS_PATH=%PROJECT_ROOT%\requirements.txt"

echo Project root: %PROJECT_ROOT%

if not exist "%VENV_PYTHON%" (
    echo Creating virtual environment in %VENV_PATH%
    where py >nul 2>nul
    if %ERRORLEVEL% EQU 0 (
        py -3 -m venv "%VENV_PATH%"
    ) else (
        where python >nul 2>nul
        if %ERRORLEVEL% EQU 0 (
            python -m venv "%VENV_PATH%"
        ) else (
            echo Python 3 was not found. Install Python 3 and try again.
            exit /b 1
        )
    )

    if errorlevel 1 exit /b 1
) else (
    echo Virtual environment already exists: %VENV_PATH%
)

echo Upgrading pip
"%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b 1

if exist "%REQUIREMENTS_PATH%" (
    echo Installing dependencies from requirements.txt
    "%VENV_PYTHON%" -m pip install -r "%REQUIREMENTS_PATH%"
    if errorlevel 1 exit /b 1
) else (
    echo requirements.txt was not found, skipping dependency install
)

echo.
echo Done. Start the app with:
echo   scripts\start.bat

endlocal
