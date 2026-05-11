# -*- mode: python ; coding: utf-8 -*-
# CineSort — PyInstaller spec (QA onedir + Release onefile)
# Usage: pyinstaller --clean --noconfirm CineSort.spec

import os
import re
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_submodules

# ---------------------------------------------------------------------------
# Pre-flight: verify build environment
# ---------------------------------------------------------------------------

try:
    import webview  # noqa: F401
    import cffi  # noqa: F401
    import _cffi_backend  # noqa: F401
except Exception as exc:
    raise SystemExit(
        "pywebview n'est pas installe dans l'environnement de build. "
        "Active .venv puis lance build_windows.bat."
    ) from exc

_cffi_backend_path = Path(_cffi_backend.__file__).resolve()
if not _cffi_backend_path.exists():
    raise SystemExit(
        "_cffi_backend introuvable pour le packaging. "
        "Installez/reparez cffi dans l'environnement Python de build avant le build."
    )
if getattr(cffi, "__version__", None) != getattr(_cffi_backend, "__version__", None):
    raise SystemExit(
        "Version mismatch entre cffi et _cffi_backend dans l'environnement de build. "
        "Reinstallez cffi dans le venv utilise pour le packaging."
    )

# ---------------------------------------------------------------------------
# Version info — read from VERSION file, generate version_info at build time
# ---------------------------------------------------------------------------

_version_raw = (Path("VERSION").read_text(encoding="utf-8").strip() if Path("VERSION").exists() else "0.0.0-dev")
_version_match = re.match(r"(\d+)\.(\d+)\.(\d+)", _version_raw)
_major = int(_version_match.group(1)) if _version_match else 0
_minor = int(_version_match.group(2)) if _version_match else 0
_patch = int(_version_match.group(3)) if _version_match else 0

# D2 audit : si la VERSION contient un suffixe (-dev, -beta, -rc), marquer le
# binaire comme non-release pour eviter de le confondre avec une build stable.
_is_prerelease = bool(re.search(r"-(dev|alpha|beta|rc)", _version_raw, re.IGNORECASE))
_file_description = (
    f"CineSort ({_version_raw}) — Tri & organisation de bibliothèques films"
    if _is_prerelease
    else "CineSort — Tri & organisation de bibliothèques films"
)

_vi_template = Path("version_info.txt").read_text(encoding="utf-8")
_vi_content = (
    _vi_template
    .replace("{major}", str(_major))
    .replace("{minor}", str(_minor))
    .replace("{patch}", str(_patch))
    .replace("{version_str}", _version_raw)
    .replace("{file_description}", _file_description)
)
_vi_path = Path("build/_version_info_generated.txt")
_vi_path.parent.mkdir(parents=True, exist_ok=True)
_vi_path.write_text(_vi_content, encoding="utf-8")

# ---------------------------------------------------------------------------
# Hidden imports for pywebview / pythonnet / cffi
# ---------------------------------------------------------------------------

hiddenimports = collect_submodules("webview") + [
    "_cffi_backend",
    "cffi",
    "clr_loader",
    "clr_loader.ffi",
    "pythonnet",
    "clr",
]

cffi_datas, cffi_binaries, cffi_hiddenimports = collect_all("cffi")
clr_loader_datas, clr_loader_binaries, clr_loader_hiddenimports = collect_all("clr_loader")
pythonnet_datas, pythonnet_binaries, pythonnet_hiddenimports = collect_all("pythonnet")

hiddenimports += cffi_hiddenimports + clr_loader_hiddenimports + pythonnet_hiddenimports

# Modules V3 importes en lazy (dans des fonctions) — PyInstaller peut les manquer
hiddenimports += [
    "cinesort.app.watcher",
    "cinesort.app.plugin_hooks",
    "cinesort.app.email_report",
    "cinesort.app.watchlist",
    "cinesort.app.radarr_sync",
    "cinesort.app.jellyfin_validation",
    "cinesort.app.export_support",
    "cinesort.infra.plex_client",
    "cinesort.infra.radarr_client",
    "cinesort.infra.jellyfin_client",
    "cinesort.domain.edition_helpers",
    "cinesort.domain.film_history",
    "cinesort.domain.mkv_title_check",
    "cinesort.domain.perceptual",
    "cinesort.domain.perceptual.constants",
    "cinesort.domain.perceptual.models",
    "cinesort.domain.perceptual.ffmpeg_runner",
    "cinesort.domain.perceptual.frame_extraction",
    "cinesort.domain.perceptual.video_analysis",
    "cinesort.domain.perceptual.grain_analysis",
    "cinesort.domain.perceptual.audio_perceptual",
    "cinesort.domain.perceptual.composite_score",
    "cinesort.domain.perceptual.comparison",
    "cinesort.domain.perceptual.parallelism",
    "cinesort.domain.perceptual.audio_fingerprint",
    "cinesort.domain.perceptual.scene_detection",
    "cinesort.domain.perceptual.spectral_analysis",
    "cinesort.domain.perceptual.ssim_self_ref",
    "cinesort.domain.perceptual.hdr_analysis",
    "cinesort.domain.perceptual.upscale_detection",
    "cinesort.domain.perceptual.metadata_analysis",
    "cinesort.domain.perceptual.grain_signatures",
    "cinesort.domain.perceptual.av1_grain_metadata",
    "cinesort.domain.perceptual.grain_classifier",
    "cinesort.domain.perceptual.mel_analysis",
    "cinesort.domain.perceptual.lpips_compare",
    "cinesort.domain.perceptual.composite_score_v2",
    "cinesort.infra.probe.auto_install",
    # Modules v7.3.0 (importes lazy depuis compute_quality_score,
    # plan_support, apply_support, cinesort_api). PyInstaller les detecte
    # deja (cf xref) mais on les liste explicitement pour la robustesse.
    "cinesort.domain.explain_score",        # P2.1 explain-score narrative
    "cinesort.domain.title_ambiguity",      # P2.2 titre ambigu (Dune 1984/2021)
    "cinesort.app.apply_audit",             # P2.3 journal apply JSONL
    "cinesort.domain.calibration",          # P4.1 calibration feedback
    "cinesort.domain.genre_rules",          # P4.2 scoring genre-aware
    "cinesort.domain.profile_exchange",     # P4.3 import/export profils
]

# Dependances V4 importees en lazy
hiddenimports += [
    "segno",
    "rapidfuzz",
    "rapidfuzz.fuzz",
    "rapidfuzz.process",
    "rapidfuzz.utils",
    "rapidfuzz.distance",
    "cinesort.infra.network_utils",
    "cinesort.app._fuzzy_utils",
]

# Dependances v7.5.0 (§9 spectral, §12 mel, §7 fake 4K, §11 LPIPS, §13 SSIM, §15 grain)
hiddenimports += [
    "numpy",
    "numpy.fft",
    "onnxruntime",
]

# V1-06 (H9 polish v7.7.0) — defense en profondeur : collect TOUS les sous-modules
# perceptual via PyInstaller, pour couvrir automatiquement les futurs lazy imports
# (ex: from .audio_fingerprint import ... dans audio_perceptual.py L384,
# from .spectral_analysis import ... L405/428, from .mel_analysis import ... L427,
# from .grain_classifier import ... dans grain_analysis.py L392,
# from .grain_signatures import ... L393, et tous les from cinesort.domain.perceptual.X
# import ... a l'interieur de fonctions dans perceptual_support.py).
# Audit V1-06 confirme que tous les modules sont deja listes ci-dessus,
# mais collect_submodules garantit une couverture exhaustive sans maintenance manuelle.
hiddenimports += collect_submodules("cinesort.domain.perceptual")

# ---------------------------------------------------------------------------
# Data files: web/ (sans preview/), migrations SQL, deps dynamiques
# ---------------------------------------------------------------------------

# Collect web/ files excluding the dev-only preview/ subdirectory
web_datas = []
_web_root = Path("web")
for p in sorted(_web_root.rglob("*")):
    if not p.is_file():
        continue
    rel = p.relative_to(_web_root)
    # Skip preview/ directory (dev-only) and backup files.
    # Note: web/dashboard/ est inclus pour le dashboard distant.
    if rel.parts[0] == "preview":
        continue
    if p.suffix in (".bak", ".tmp", ".pyc"):
        continue
    web_datas.append((str(p), str(Path("web") / rel.parent)))

migration_datas = [
    (str(p), "cinesort/infra/db/migrations")
    for p in Path("cinesort/infra/db/migrations").glob("*.sql")
]

# V6-01 Polish Total v7.7.0 : fichiers de traduction i18n (locales/<lang>.json)
# servis par /locales/* via REST + lus par cinesort/domain/i18n_messages.py.
locales_datas = [
    (str(p), "locales")
    for p in Path("locales").glob("*.json")
] if Path("locales").is_dir() else []

datas = (
    web_datas
    + migration_datas
    + locales_datas
    + cffi_datas
    + clr_loader_datas
    + pythonnet_datas
)
# Inclure le fichier VERSION dans le bundle (lu a l'execution par _read_app_version)
if Path("VERSION").exists():
    datas += [("VERSION", ".")]

# §3 v7.5.0 — fpcalc.exe pour le fingerprint audio Chromaprint
if Path("assets/tools/fpcalc.exe").exists():
    datas += [("assets/tools/fpcalc.exe", "assets/tools")]

# §11 v7.5.0 — modele LPIPS AlexNet ONNX (perceptual distance apprise)
if Path("assets/models/lpips_alexnet.onnx").exists():
    datas += [("assets/models/lpips_alexnet.onnx", "assets/models")]

binaries = cffi_binaries + clr_loader_binaries + pythonnet_binaries
binaries.append((str(_cffi_backend_path), "."))

# ---------------------------------------------------------------------------
# Excludes — strip unused stdlib and dev-only modules (~15-25 MB saved)
# ---------------------------------------------------------------------------

excludes = [
    # GUI toolkit we don't use
    "tkinter", "_tkinter",
    # Testing frameworks (not needed at runtime)
    "unittest", "test", "doctest", "pydoc",
    # Protocoles reseau inutilises (NB: smtplib, email, ssl, http.client NON exclus — requis par email_report.py)
    "xmlrpc", "ftplib", "imaplib", "poplib", "telnetlib", "nntplib",
    # Dev/build tools
    "lib2to3", "ensurepip", "pip", "setuptools",
    # Pillow (build-time only, not runtime)
    "PIL", "Pillow",
    # Other unused stdlib
    "curses", "turtledemo", "turtle", "idlelib",
]

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

a = Analysis(
    ["app.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["runtime_hooks/splash_hook.py"],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# ---------------------------------------------------------------------------
# QA build (onedir) — fast iteration, debug-friendly
# ---------------------------------------------------------------------------

qa_exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CineSort",
    icon="assets/cinesort.ico",
    version=str(_vi_path),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest="CineSort.exe.manifest",
)

coll = COLLECT(
    qa_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="CineSort_QA",
)

# ---------------------------------------------------------------------------
# Release build (onefile) — single EXE for distribution
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="CineSort",
    icon="assets/cinesort.ico",
    version=str(_vi_path),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    manifest="CineSort.exe.manifest",
)
