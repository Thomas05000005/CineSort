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

echo [4/5] Pytest suite avec coverage (exclut E2E, live/stress, et tests pollution inter-tests v1.0.0-beta)...
REM v1.0.0-beta : 9 modules a fix dans v7.9.0 (cf docs/internal/audit_v7_8_0/results/v7_8_0_inter_test_pollution.md).
REM Ces tests passent a 100%% en isolation mais echouent en suite (etat global non-reinitialise).
"%PYTHON_EXE%" -m coverage run -m pytest tests/ ^
  --ignore=tests/e2e ^
  --ignore=tests/e2e_dashboard ^
  --ignore=tests/e2e_desktop ^
  --ignore=tests/live ^
  --ignore=tests/stress ^
  --ignore=tests/test_undo_apply.py ^
  --ignore=tests/test_undo_checksum.py ^
  --ignore=tests/test_incremental_scan.py ^
  --ignore=tests/test_scan_streaming.py ^
  --ignore=tests/test_quality_score.py ^
  --ignore=tests/test_tv_detection.py ^
  --ignore=tests/test_multi_root.py ^
  --ignore=tests/test_perceptual_parallel.py ^
  --ignore=tests/test_run_report_export.py ^
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
