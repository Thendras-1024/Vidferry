@echo off
setlocal

set "ROOT=%~dp0"
set "CONDA_BAT=E:\miniforge3\condabin\conda.bat"

if not exist "%CONDA_BAT%" (
  echo Conda was not found: %CONDA_BAT%
  pause
  exit /b 1
)

start "Vidferry Backend" /D "%ROOT%" cmd /k ""%CONDA_BAT%" run -n vidferry python run.py"
start "Vidferry Frontend" /D "%ROOT%sau_frontend" cmd /k "npm run dev"
