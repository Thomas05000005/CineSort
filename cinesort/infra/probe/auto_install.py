"""Installation automatique des outils d'analyse video (ffprobe, MediaInfo).

Telecharge les binaires depuis les sources officielles via urllib.request,
les extrait dans tools/ a cote de l'executable (ou du projet en mode dev).
"""

from __future__ import annotations

import logging
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

# URLs officielles des binaires Windows
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
MEDIAINFO_URL = "https://mediaarea.net/download/binary/mediainfo/24.11/MediaInfo_CLI_24.11_Windows_x64.zip"


def get_tools_dir() -> Path:
    """Dossier tools/ a cote de l'executable ou dans le dossier du projet."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).resolve().parent.parent.parent.parent
    tools_dir = base / "tools"
    tools_dir.mkdir(exist_ok=True)
    return tools_dir


def _find_in_zip(zf: zipfile.ZipFile, exe_name: str) -> Optional[str]:
    """Cherche un fichier exe dans l'archive (peut etre dans un sous-dossier)."""
    lower = exe_name.lower()
    for name in zf.namelist():
        if name.lower().endswith(lower) and not name.endswith("/"):
            return name
    return None


def install_ffprobe(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Telecharge et extrait ffprobe.exe. Retourne le chemin ou leve une exception."""
    tools = get_tools_dir()
    ffprobe_path = tools / "ffprobe.exe"
    if ffprobe_path.exists():
        return str(ffprobe_path)

    logger.info("auto_install: telechargement ffprobe depuis %s", FFMPEG_URL)
    if progress_callback:
        progress_callback("Telechargement de FFprobe...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "ffmpeg.zip")
        urlretrieve(FFMPEG_URL, zip_path)

        logger.info("auto_install: extraction ffprobe.exe")
        if progress_callback:
            progress_callback("Extraction de FFprobe...")

        with zipfile.ZipFile(zip_path) as zf:
            # Extraire ffprobe.exe
            entry = _find_in_zip(zf, "ffprobe.exe")
            if not entry:
                raise FileNotFoundError("ffprobe.exe non trouve dans l'archive")
            ffprobe_path.write_bytes(zf.read(entry))
            logger.info("auto_install: ffprobe installe → %s", ffprobe_path)

            # Extraire aussi ffmpeg.exe (utile pour le perceptuel)
            ffmpeg_entry = _find_in_zip(zf, "ffmpeg.exe")
            if ffmpeg_entry:
                ffmpeg_path = tools / "ffmpeg.exe"
                if not ffmpeg_path.exists():
                    ffmpeg_path.write_bytes(zf.read(ffmpeg_entry))
                    logger.info("auto_install: ffmpeg installe → %s", ffmpeg_path)

    return str(ffprobe_path)


def install_mediainfo(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> str:
    """Telecharge et extrait MediaInfo.exe. Retourne le chemin ou leve une exception."""
    tools = get_tools_dir()
    mi_path = tools / "MediaInfo.exe"
    if mi_path.exists():
        return str(mi_path)

    logger.info("auto_install: telechargement MediaInfo depuis %s", MEDIAINFO_URL)
    if progress_callback:
        progress_callback("Telechargement de MediaInfo...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "mediainfo.zip")
        urlretrieve(MEDIAINFO_URL, zip_path)

        if progress_callback:
            progress_callback("Extraction de MediaInfo...")

        with zipfile.ZipFile(zip_path) as zf:
            entry = _find_in_zip(zf, "mediainfo.exe")
            if not entry:
                raise FileNotFoundError("MediaInfo.exe non trouve dans l'archive")
            mi_path.write_bytes(zf.read(entry))
            logger.info("auto_install: MediaInfo installe → %s", mi_path)

    return str(mi_path)


def install_all(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Installe tous les outils manquants. Retourne les chemins et erreurs."""
    results: Dict[str, str] = {}
    errors: list[str] = []

    try:
        results["ffprobe"] = install_ffprobe(progress_callback)
    except (OSError, FileNotFoundError, zipfile.BadZipFile) as exc:
        logger.error("auto_install: echec ffprobe: %s", exc)
        errors.append(f"FFprobe: {exc}")

    try:
        results["mediainfo"] = install_mediainfo(progress_callback)
    except (OSError, FileNotFoundError, zipfile.BadZipFile) as exc:
        logger.error("auto_install: echec MediaInfo: %s", exc)
        errors.append(f"MediaInfo: {exc}")

    return {"installed": results, "errors": errors}
