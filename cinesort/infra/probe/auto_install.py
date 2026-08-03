"""Installation automatique des outils d'analyse video (ffprobe, MediaInfo).

Telecharge les binaires depuis les sources officielles via urllib.request,
les extrait dans tools/ a cote de l'executable (ou du projet en mode dev).
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import socket
import sys
import tempfile
import zipfile
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, Optional
from urllib.parse import urlparse
from urllib.request import urlretrieve

logger = logging.getLogger(__name__)

# URLs officielles des binaires Windows
FFMPEG_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
MEDIAINFO_URL = "https://mediaarea.net/download/binary/mediainfo/24.11/MediaInfo_CLI_24.11_Windows_x64.zip"

# Fix VN-A.4 (Vague N batch 1) — SHA256 fail-closed pour auto_install.
#
# Modele de menace : un attaquant en MITM (Wi-Fi public, DNS spoofing, CA
# corporate compromise) peut servir un faux ZIP avec un ffprobe.exe ou un
# MediaInfo.exe verole, qui sera execute via subprocess avec les droits de
# l'utilisateur. HTTPS aide mais ne suffit pas si la chaine de confiance est
# compromise. La defense : verifier le SHA256 de l'archive telechargee avant
# de l'ouvrir, et refuser (fail closed) en cas de mismatch.
#
# Probleme pratique : les URLs ci-dessus pointent vers des "release-essentials"
# rolling (gyan.dev) et un MediaInfo 24.11 pin. Pour les rolling, le hash
# change a chaque rebuild upstream, donc on ne peut pas l'embarquer en dur.
# La regle adoptee :
#   - Si le hash attendu est defini (constante non None ou override) : VERIFIER
#     et FAIL CLOSED si mismatch.
#   - Si le hash attendu est None : continuer mais LOGUER un warning explicite
#     ("integrity unverified") + calculer et logguer le hash reel pour audit.
# L'utilisateur ou le packager peut pinner via override (parametre kwarg) ou
# via une future config TOML (cf v8 roadmap).
#
# Hashs constants (a mettre a jour quand on pin une release stable) :
#   Source MediaInfo 24.11 Windows x64 zip : page de download mediaarea.net
#     (verifie au telechargement du 2026-06-01 ; rolling release donc peut
#     evoluer si MediaInfo republie 24.11)
#   Source FFmpeg essentials gyan.dev : rolling, hash impossible a fixer
EXPECTED_SHA256_FFMPEG: Optional[str] = None
EXPECTED_SHA256_MEDIAINFO: Optional[str] = None

# AUDIT 2026-06-10 : les constantes ci-dessus sont None (FFmpeg gyan.dev est une
# rolling release dont le hash ne peut etre fige sans casser les futurs installs).
# Pour permettre a un deploiement sensible a la securite de FORCER la
# verification fail-closed sans modifier le code, on accepte un hash epingle via
# variable d'environnement. Ordre de resolution : override kwarg > env var >
# constante module. Si tout est None, le comportement documente (warning
# "integrity UNVERIFIED") est conserve.
_ENV_SHA256_FFMPEG = "CINESORT_FFMPEG_SHA256"
_ENV_SHA256_MEDIAINFO = "CINESORT_MEDIAINFO_SHA256"


def _resolve_expected_sha256(env_var: str, override: Optional[str], constant: Optional[str]) -> Optional[str]:
    """Resout le SHA256 attendu : override kwarg > variable d'env > constante."""
    if override is not None:
        return override
    env_val = (os.environ.get(env_var) or "").strip()
    if env_val:
        return env_val
    return constant


# Timeout socket pour urlretrieve : sans cela, un serveur muet (hosts en panne,
# firewall corporate qui drop) fait hang l'install indefiniment.
# 120s couvre des downloads de ~120 MB sur une connexion lente (1 Mbps).
_DOWNLOAD_TIMEOUT_S = 120.0

# Borne anti-zip-bomb (CWE-409). Le SHA256 de l'archive est None par defaut
# (rolling release gyan.dev), donc _verify_archive est fail-open : rien ne
# controle la taille decompressee. Une entree ...ffprobe.exe de plusieurs Go
# provoquerait un OOM avant meme d'executer le binaire. ffmpeg/ffprobe.exe font
# ~100-170 Mo ; 300 Mo laisse une marge confortable pour les 3 binaires vises.
_MAX_UNCOMPRESSED_BYTES = 300 * 1024 * 1024


class IntegrityError(Exception):
    """Leve quand le SHA256 d'un binaire telecharge ne matche pas la valeur attendue.

    Fail-closed : l'archive est effacee et l'install est refusee, on ne tente
    PAS d'extraire un binaire potentiellement compromis.
    """


def _sha256_file(path: str) -> str:
    """Calcule le SHA256 hex (lowercase) d'un fichier en streaming (memoire bornee)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # 1 MiB par chunk : compromis entre I/O syscalls et empreinte memoire.
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _assert_https(url: str) -> None:
    """Refuse les URLs non-HTTPS (defense en profondeur cote URL).

    Note : on autorise file:// uniquement pour tests unitaires (mocks).
    """
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("https", "file"):
        raise IntegrityError(f"URL scheme '{scheme}' refuse (HTTPS requis) : {url}")


def _verify_archive(
    zip_path: str,
    expected_sha256: Optional[str],
    *,
    label: str,
) -> None:
    """Verifie l'integrite SHA256 d'une archive telechargee. Fail closed.

    - Si `expected_sha256` est fourni : compare, leve IntegrityError sur mismatch
      et efface le fichier suspect (pour eviter qu'un caller reutilise).
    - Si `expected_sha256` est None : logue un warning + le hash reel calcule,
      n'echoue PAS (permet la flexibilite rolling-release documentee plus haut).
    """
    actual = _sha256_file(zip_path)
    if expected_sha256 is None:
        logger.warning(
            "auto_install: integrity UNVERIFIED for %s (no pinned SHA256). "
            "Actual sha256=%s. Pin EXPECTED_SHA256_* to enable fail-closed verification.",
            label,
            actual,
        )
        return
    expected_norm = expected_sha256.strip().lower()
    if actual.lower() != expected_norm:
        # Fail closed : on detruit l'archive pour empecher toute extraction
        # ulterieure par erreur, et on leve une exception explicite.
        with suppress(OSError):
            os.remove(zip_path)
        raise IntegrityError(
            f"SHA256 mismatch pour {label} : attendu={expected_norm}, reel={actual}. Install refuse (fail-closed)."
        )
    logger.info("auto_install: SHA256 verifie OK pour %s (%s)", label, actual)


@contextmanager
def _socket_timeout(seconds: float) -> Iterator[None]:
    """Force un timeout socket global pendant le download (urllib.request n'expose
    pas de parametre timeout sur urlretrieve). Restaure la valeur precedente
    en sortie, meme sur exception.
    """
    previous = socket.getdefaulttimeout()
    socket.setdefaulttimeout(seconds)
    try:
        yield
    finally:
        socket.setdefaulttimeout(previous)


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


def _extract_entry_bounded(zf: zipfile.ZipFile, entry: str, dest: Path) -> None:
    """Extrait `entry` vers `dest` en bornant la taille decompressee (anti zip-bomb).

    `_find_in_zip` matche par suffixe de nom => l'attaquant controle le nom de
    l'entree. On refuse (fail-closed) toute entree dont la taille decompressee
    annoncee depasse _MAX_UNCOMPRESSED_BYTES, puis on copie en flux chunke plutot
    que de charger l'entree entiere en memoire via zf.read().
    """
    info = zf.getinfo(entry)
    if info.file_size > _MAX_UNCOMPRESSED_BYTES:
        raise IntegrityError(
            f"entree '{entry}' trop volumineuse ({info.file_size} octets decompresses, "
            f"cap {_MAX_UNCOMPRESSED_BYTES})"
        )
    with zf.open(entry) as src, open(dest, "wb") as dst:
        shutil.copyfileobj(src, dst, length=1 << 20)


def install_ffprobe(
    progress_callback: Optional[Callable[[str], None]] = None,
    *,
    expected_sha256: Optional[str] = None,
) -> str:
    """Telecharge et extrait ffprobe.exe. Retourne le chemin ou leve une exception.

    Fix VN-A.4 : verifie le SHA256 de l'archive telechargee avant extraction
    (fail-closed). Par defaut utilise EXPECTED_SHA256_FFMPEG ; un override
    `expected_sha256=` (kwarg) permet aux callers (config user / tests) de
    pinner un hash specifique.
    """
    tools = get_tools_dir()
    ffprobe_path = tools / "ffprobe.exe"
    if ffprobe_path.exists():
        return str(ffprobe_path)

    _assert_https(FFMPEG_URL)
    logger.info("auto_install: telechargement ffprobe depuis %s", FFMPEG_URL)
    if progress_callback:
        progress_callback("Telechargement de FFprobe...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "ffmpeg.zip")
        with _socket_timeout(_DOWNLOAD_TIMEOUT_S):
            urlretrieve(FFMPEG_URL, zip_path)

        # Fix VN-A.4 : verification SHA256 AVANT toute ouverture/extraction.
        # IntegrityError remonte et abandonne l'install (fail-closed).
        _verify_archive(
            zip_path,
            _resolve_expected_sha256(_ENV_SHA256_FFMPEG, expected_sha256, EXPECTED_SHA256_FFMPEG),
            label="ffmpeg.zip",
        )

        logger.info("auto_install: extraction ffprobe.exe")
        if progress_callback:
            progress_callback("Extraction de FFprobe...")

        with zipfile.ZipFile(zip_path) as zf:
            # Extraire ffprobe.exe
            entry = _find_in_zip(zf, "ffprobe.exe")
            if not entry:
                raise FileNotFoundError("ffprobe.exe non trouve dans l'archive")
            _extract_entry_bounded(zf, entry, ffprobe_path)
            logger.info("auto_install: ffprobe installe → %s", ffprobe_path)

            # Extraire aussi ffmpeg.exe (utile pour le perceptuel)
            ffmpeg_entry = _find_in_zip(zf, "ffmpeg.exe")
            if ffmpeg_entry:
                ffmpeg_path = tools / "ffmpeg.exe"
                if not ffmpeg_path.exists():
                    _extract_entry_bounded(zf, ffmpeg_entry, ffmpeg_path)
                    logger.info("auto_install: ffmpeg installe → %s", ffmpeg_path)

    return str(ffprobe_path)


def install_mediainfo(
    progress_callback: Optional[Callable[[str], None]] = None,
    *,
    expected_sha256: Optional[str] = None,
) -> str:
    """Telecharge et extrait MediaInfo.exe. Retourne le chemin ou leve une exception.

    Fix VN-A.4 : verifie le SHA256 de l'archive telechargee avant extraction
    (fail-closed). Voir install_ffprobe pour la doc du parametre expected_sha256.
    """
    tools = get_tools_dir()
    mi_path = tools / "MediaInfo.exe"
    if mi_path.exists():
        return str(mi_path)

    _assert_https(MEDIAINFO_URL)
    logger.info("auto_install: telechargement MediaInfo depuis %s", MEDIAINFO_URL)
    if progress_callback:
        progress_callback("Telechargement de MediaInfo...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "mediainfo.zip")
        with _socket_timeout(_DOWNLOAD_TIMEOUT_S):
            urlretrieve(MEDIAINFO_URL, zip_path)

        # Fix VN-A.4 : verification SHA256 avant extraction (fail-closed).
        _verify_archive(
            zip_path,
            _resolve_expected_sha256(_ENV_SHA256_MEDIAINFO, expected_sha256, EXPECTED_SHA256_MEDIAINFO),
            label="mediainfo.zip",
        )

        if progress_callback:
            progress_callback("Extraction de MediaInfo...")

        with zipfile.ZipFile(zip_path) as zf:
            entry = _find_in_zip(zf, "mediainfo.exe")
            if not entry:
                raise FileNotFoundError("MediaInfo.exe non trouve dans l'archive")
            _extract_entry_bounded(zf, entry, mi_path)
            logger.info("auto_install: MediaInfo installe → %s", mi_path)

    return str(mi_path)


def install_all(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Installe tous les outils manquants. Retourne les chemins et erreurs."""
    results: Dict[str, str] = {}
    errors: list[str] = []

    # Fix VN-A.4 : IntegrityError (SHA256 mismatch) ajoute au tuple de captures.
    # Pas de retry ni de fallback : si l'archive est compromise, on refuse.
    try:
        results["ffprobe"] = install_ffprobe(progress_callback)
    except (OSError, FileNotFoundError, zipfile.BadZipFile, IntegrityError) as exc:
        logger.error("auto_install: echec ffprobe: %s", exc)
        errors.append(f"FFprobe: {exc}")

    try:
        results["mediainfo"] = install_mediainfo(progress_callback)
    except (OSError, FileNotFoundError, zipfile.BadZipFile, IntegrityError) as exc:
        logger.error("auto_install: echec MediaInfo: %s", exc)
        errors.append(f"MediaInfo: {exc}")

    return {"installed": results, "errors": errors}
