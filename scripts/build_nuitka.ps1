# scripts/build_nuitka.ps1
# -----------------------------------------------------------------------------
# V2.5 hybride PyInstaller + Nuitka -- build local Nuitka (opt-in dev).
#
# Backward compat : ce script NE remplace PAS build_windows.bat (PyInstaller
# reste le binaire officiel). Il ajoute un binaire Nuitka cote a cote dans
# dist-nuitka/CineSortNuitka.exe pour benchmarks / experimentations.
#
# Usage :
#   .\scripts\build_nuitka.ps1                  # build complet
#   .\scripts\build_nuitka.ps1 -SkipUpx         # sans plugin UPX
#   .\scripts\build_nuitka.ps1 -KeepBuildDir    # garde dist-nuitka/ intermediaire
#
# Pre-requis :
#   - Python 3.13 (meme contrainte que PyInstaller : pythonnet KO en 3.14+)
#   - venv active (.venv) avec requirements.txt installes
#   - nuitka, ordered-set, zstandard installes
#   - UPX dans le PATH (optionnel, sinon -SkipUpx)
# -----------------------------------------------------------------------------

[CmdletBinding()]
param(
    [switch]$SkipUpx,
    [switch]$KeepBuildDir,
    [string]$OutputDir = "dist-nuitka",
    [string]$OutputName = "CineSortNuitka.exe"
)

$ErrorActionPreference = "Stop"

# 1. Pre-flight Python
$pyVersion = & python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
if ($pyVersion -ne "3.13") {
    Write-Error "Nuitka build necessite Python 3.13 (detecte: $pyVersion). pythonnet est incompatible avec 3.14+."
    exit 1
}

# 2. Pre-flight Nuitka
try {
    & python -m nuitka --version | Out-Null
} catch {
    Write-Error "Nuitka introuvable. Installer : pip install nuitka ordered-set zstandard"
    exit 1
}

# 3. Pre-flight UPX (optionnel)
$upxPlugin = $true
if ($SkipUpx) {
    $upxPlugin = $false
    Write-Host "[INFO] UPX desactive (--SkipUpx)" -ForegroundColor Yellow
} else {
    $upx = Get-Command upx -ErrorAction SilentlyContinue
    if ($null -eq $upx) {
        Write-Host "[WARN] UPX introuvable dans le PATH, build sans --enable-plugin=upx" -ForegroundColor Yellow
        $upxPlugin = $false
    }
}

# 4. Nettoyage previous build (sauf si KeepBuildDir)
if (-not $KeepBuildDir -and (Test-Path $OutputDir)) {
    Write-Host "[INFO] Nettoyage $OutputDir" -ForegroundColor Cyan
    Remove-Item -Recurse -Force $OutputDir
}

# 5. Construction des arguments Nuitka
$nuitkaArgs = @(
    "--standalone",
    "--onefile",
    "--assume-yes-for-downloads",
    "--windows-console-mode=disable",
    "--windows-icon-from-ico=assets/cinesort.ico",
    "--include-data-dir=web=web",
    "--include-data-dir=locales=locales",
    "--include-data-dir=cinesort/infra/db/migrations=cinesort/infra/db/migrations",
    "--include-data-files=VERSION=VERSION",
    # Excludes alignes sur CineSort.spec :
    "--nofollow-import-to=torch",
    "--nofollow-import-to=torchvision",
    "--nofollow-import-to=torchaudio",
    "--nofollow-import-to=tensorflow",
    "--nofollow-import-to=transformers",
    "--nofollow-import-to=scipy",
    "--nofollow-import-to=matplotlib",
    "--nofollow-import-to=pandas",
    "--nofollow-import-to=tkinter",
    "--nofollow-import-to=pytest",
    "--nofollow-import-to=playwright",
    "--output-filename=$OutputName",
    "--output-dir=$OutputDir"
)

if ($upxPlugin) {
    $nuitkaArgs += "--enable-plugin=upx"
}

# 6. Assets optionnels (fpcalc, LPIPS) — ajout conditionnel
if (Test-Path "assets/tools/fpcalc.exe") {
    $nuitkaArgs += "--include-data-files=assets/tools/fpcalc.exe=assets/tools/fpcalc.exe"
}
if (Test-Path "assets/models/lpips_alexnet.onnx") {
    $nuitkaArgs += "--include-data-files=assets/models/lpips_alexnet.onnx=assets/models/lpips_alexnet.onnx"
}

# 7. Lancement
Write-Host "[BUILD] python -m nuitka $($nuitkaArgs -join ' ') app.py" -ForegroundColor Green
$start = Get-Date
& python -m nuitka @nuitkaArgs app.py
$exitCode = $LASTEXITCODE
$elapsed = (Get-Date) - $start

if ($exitCode -ne 0) {
    Write-Error "Build Nuitka a echoue (exit code $exitCode) apres $($elapsed.TotalMinutes.ToString('F1')) min"
    exit $exitCode
}

# 8. Verification de l'EXE
$exePath = Join-Path $OutputDir $OutputName
if (-not (Test-Path $exePath)) {
    Write-Error "EXE attendu introuvable : $exePath"
    exit 1
}
$sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 2)
Write-Host "" -ForegroundColor Green
Write-Host "[OK] Build Nuitka termine en $($elapsed.TotalMinutes.ToString('F1')) min" -ForegroundColor Green
Write-Host "    Binaire : $exePath ($sizeMB MB)" -ForegroundColor Green
Write-Host "    Comparer avec dist/CineSort.exe (PyInstaller, binaire officiel)" -ForegroundColor Green
