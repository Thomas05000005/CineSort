@echo off
setlocal

set "PYTHON_EXE=python"
if exist ".venv313\Scripts\python.exe" (
  set "PYTHON_EXE=.venv313\Scripts\python.exe"
) else if exist ".venv\Scripts\python.exe" (
  set "PYTHON_EXE=.venv\Scripts\python.exe"
)
echo [INFO] Python utilise: %PYTHON_EXE%

"%PYTHON_EXE%" -m ruff --version >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Ruff est requis. Lance: %PYTHON_EXE% -m pip install -r requirements-dev.txt
  exit /b 1
)

"%PYTHON_EXE%" -m coverage --version >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Coverage est requis. Lance: %PYTHON_EXE% -m pip install -r requirements-dev.txt
  exit /b 1
)

"%PYTHON_EXE%" -m pytest --version >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Pytest est requis. Lance: %PYTHON_EXE% -m pip install -r requirements-dev.txt
  exit /b 1
)

echo [1/5] Python compile check...
"%PYTHON_EXE%" scripts\check_python_compile.py
if errorlevel 1 (
  echo [ERREUR] Recursive compile check failed.
  exit /b 1
)

echo [2/5] Ruff lint check (projet entier, excludes via pyproject.toml)...
"%PYTHON_EXE%" -m ruff check .
if errorlevel 1 (
  echo [ERREUR] Ruff lint check failed.
  exit /b 1
)

echo [3/5] Ruff format check (projet entier)...
"%PYTHON_EXE%" -m ruff format --check .
if errorlevel 1 (
  echo [ERREUR] Ruff format check failed.
  exit /b 1
)

echo [4/5] Pytest suite avec coverage (exclut E2E et live/stress)...
REM Pollution inter-tests (issue #4) resolue en v1.0.0-beta : subprocess
REM dans test_import_cycle_guard au lieu de manipuler sys.modules.
"%PYTHON_EXE%" -m coverage run -m pytest tests/ ^
  --ignore=tests/e2e ^
  --ignore=tests/e2e_dashboard ^
  --ignore=tests/e2e_desktop ^
  --ignore=tests/live ^
  --ignore=tests/stress ^
  -q
if errorlevel 1 (
  echo [ERREUR] Tests failed.
  exit /b 1
)

echo [5/5] Coverage report...
"%PYTHON_EXE%" -m coverage report --fail-under=80
if errorlevel 1 (
  echo [ERREUR] Coverage report failed.
  exit /b 1
)

echo.
echo All checks passed.
endlocal ^& exit /b 0
