@echo off
setlocal

REM ===== CineSort build Windows EXE =====
cd /d "%~dp0"

set "PYTHON_EXE="
if exist ".venv313\Scripts\python.exe" set "PYTHON_EXE=.venv313\Scripts\python.exe"
if "%PYTHON_EXE%"=="" if exist ".venv\Scripts\python.exe" set "PYTHON_EXE=.venv\Scripts\python.exe"

REM v1.0.0-beta : sur CI (GitHub Actions), pas de venv local. Python est
REM installe directement par actions/setup-python. Fallback sur python global.
if "%PYTHON_EXE%"=="" (
  where python >nul 2>&1
  if errorlevel 1 (
    echo [ERREUR] Environnement Python de build introuvable.
    echo Creez de preference un venv Python 3.13 avec: py -3.13 -m venv .venv313
    exit /b 1
  )
  set "PYTHON_EXE=python"
)

echo [1/5] Verification Python venv...
"%PYTHON_EXE%" -c "import sys; print(sys.version)" >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Python .venv invalide.
  exit /b 1
)

echo [1b/5] Verification version Python compatible pythonnet...
"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info < (3, 14) else 1)" >nul 2>&1
if errorlevel 1 (
  echo [ERREUR] Le build EXE avec pywebview/pythonnet n'est pas compatible avec Python 3.14+.
  echo [ERREUR] Recréez .venv avec Python 3.13, par exemple:
  echo          py -3.13 -m venv .venv
  exit /b 1
)

echo [2/5] Verification dependances build...
"%PYTHON_EXE%" -c "import webview, requests, PyInstaller, PIL" >nul 2>&1
if errorlevel 1 (
  echo [INFO] Installation requirements-build.txt...
  "%PYTHON_EXE%" -m pip install -r requirements-build.txt
  if errorlevel 1 (
    echo [ERREUR] Echec installation requirements-build.txt
    exit /b 1
  )
)

echo [3/5] Generation icone ICO...
"%PYTHON_EXE%" scripts/generate_icon.py >nul 2>&1
if errorlevel 1 (
  echo [WARN] Generation icone impossible, build continue.
)

echo [4/5] Nettoyage build/dist...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"

echo [5/5] Build PyInstaller...
"%PYTHON_EXE%" -m PyInstaller --clean --noconfirm CineSort.spec
if errorlevel 1 (
  echo [ERREUR] Build PyInstaller echoue.
  exit /b 1
)

echo [INFO] Verification sortie...
set "QA_EXE_PATH="
set "RELEASE_EXE_PATH="
if exist "dist\CineSort_QA\CineSort.exe" set "QA_EXE_PATH=dist\CineSort_QA\CineSort.exe"
if exist "dist\CineSort.exe" set "RELEASE_EXE_PATH=dist\CineSort.exe"

if "%QA_EXE_PATH%"=="" (
  echo [ERREUR] Build termine mais binaire QA onedir introuvable.
  exit /b 1
)

if "%RELEASE_EXE_PATH%"=="" (
  echo [ERREUR] Build termine mais binaire release onefile introuvable.
  exit /b 1
)

if exist "scripts\package_zip.py" (
  echo [INFO] Packaging ZIP QA + release...
  "%PYTHON_EXE%" scripts\package_zip.py --qa --release
  if errorlevel 1 (
    echo [ERREUR] Echec du packaging ZIP QA/release.
    exit /b 1
  )
)

echo.
echo Build termine avec succes.
echo QA onedir : %QA_EXE_PATH%
echo Release onefile : %RELEASE_EXE_PATH%
endlocal & exit /b 0
