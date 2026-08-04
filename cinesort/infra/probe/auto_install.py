"""Installation automatique des outils d'analyse video (ffprobe, MediaInfo).

Telecharge les binaires depuis les sources officielles via urllib.request,
les extrait dans tools/ a cote de l'executable (ou du projet en mode dev).

Modele de menace (CWE-494 / CWE-409)
-----------------------------------
Les fichiers ecrits par ce module sont des EXECUTABLES, lances ensuite par
subprocess avec les droits de l'utilisateur (cf. `tools_manager`). Un attaquant
en position de MITM (Wi-Fi public, DNS spoofing, CA d'entreprise compromise) ou
qui compromet un miroir peut donc servir un `ffprobe.exe` verole. HTTPS ne
suffit pas : il protege le canal, pas la source.

Deux defenses, toutes deux ACTIVES PAR DEFAUT :

1. Empreinte SHA256 epinglee, verifiee AVANT ouverture de l'archive, et
   FAIL-CLOSED : sans empreinte de reference, on REFUSE d'installer (issue #466).
2. Bornes de decompression : taille telechargee, nombre d'entrees, taille
   decompressee cumulee, et copie en streaming qui abandonne DES le
   depassement (issue #734). L'en-tete ZIP (`ZipInfo.file_size`) est controle
   par l'attaquant : il sert de rejet precoce, jamais de borne unique.
"""

from __future__ import annotations

import hashlib
import logging
import os
import re
import sys
import tempfile
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Any, Callable, Dict, Optional
from urllib.parse import urlparse
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Sources et empreintes epinglees (fix #466)
# ---------------------------------------------------------------------------
# Une URL "rolling" est INEPINGLABLE par construction : son contenu change a
# chaque rebuild amont, donc aucune empreinte ne peut y survivre. L'ancienne URL
# `ffmpeg-release-essentials.zip` etait de ce type — c'est la raison pour
# laquelle EXPECTED_SHA256_FFMPEG valait None, et donc la raison pour laquelle
# la verification etait inerte. On passe donc a l'URL VERSIONNEE et IMMUABLE
# (c'est exactement celle vers laquelle la rolling redirige en HTTP 303).
#
# Provenance des empreintes — chacune est confirmee par au moins deux hotes
# INDEPENDANTS. Un fichier `.sha256` servi par le meme hote que l'archive ne
# prouve rien contre le modele de menace ci-dessus (qui remplace l'archive
# remplace le sidecar) : c'est pourquoi on epingle ici, dans le depot, sous
# revue de code et historique git, plutot que de recuperer l'empreinte au
# moment de l'installation.
#
#   FFmpeg 8.1.2 essentials (zip) :
#     - digest publie par l'API GitHub pour l'asset de la release 8.1.2 du
#       miroir officiel GyanD/codexffmpeg (calcule cote GitHub) ;
#     - sidecar https://www.gyan.dev/ffmpeg/builds/packages/
#       ffmpeg-8.1.2-essentials_build.zip.sha256 (hote gyan.dev) ;
#     - recalcul local de l'archive telechargee.
#     Les trois concordent. Verifie le 2026-08-03.
#     Le telechargement passe par le miroir GitHub : c'est l'URL qu'utilise
#     aussi le manifeste winget `Gyan.FFmpeg`, les assets de release y sont
#     permanents (gyan.dev purge les anciennes versions de packages/).
#
#   MediaInfo CLI 24.11 x64 (zip) :
#     - `InstallerSha256` du manifeste microsoft/winget-pkgs
#       manifests/m/MediaArea/MediaInfo/24.11 — meme URL exactement, hote
#       independant, historique git public ;
#     - recalcul local de l'archive telechargee.
#     Les deux concordent. Verifie le 2026-08-03. mediaarea.net ne publie
#     ni sidecar `.sha256` (404 verifie) ni signature detachee.
#
# MISE A JOUR AMONT : bump la version ET l'empreinte dans le meme commit. Sans
# empreinte valide, l'installation est refusee — c'est voulu (fail-closed).
FFMPEG_VERSION = "8.1.2"
FFMPEG_URL = (
    f"https://github.com/GyanD/codexffmpeg/releases/download/{FFMPEG_VERSION}/"
    f"ffmpeg-{FFMPEG_VERSION}-essentials_build.zip"
)
EXPECTED_SHA256_FFMPEG: Optional[str] = "db580001caa24ac104c8cb856cd113a87b0a443f7bdf47d8c12b1d740584a2ec"

MEDIAINFO_VERSION = "24.11"
MEDIAINFO_URL = (
    f"https://mediaarea.net/download/binary/mediainfo/{MEDIAINFO_VERSION}/"
    f"MediaInfo_CLI_{MEDIAINFO_VERSION}_Windows_x64.zip"
)
EXPECTED_SHA256_MEDIAINFO: Optional[str] = "501fbf68ffcf646c7722fb87280ae4539545feee3989876e43986676a2d81792"

# Surcharge par variable d'environnement : permet a un packager ou a un
# deploiement de pointer un miroir interne sans modifier le code. Ordre de
# resolution : override kwarg > variable d'env > constante module. Une valeur
# mal formee est REFUSEE (et non ignoree) : une coquille ne doit pas retomber
# silencieusement sur une autre empreinte.
_ENV_SHA256_FFMPEG = "CINESORT_FFMPEG_SHA256"
_ENV_SHA256_MEDIAINFO = "CINESORT_MEDIAINFO_SHA256"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# ---------------------------------------------------------------------------
# Bornes de decompression (fix #734)
# ---------------------------------------------------------------------------
# Valeurs MESUREES le 2026-08-03 sur les deux archives reellement servies :
#   ffmpeg-8.1.2-essentials_build.zip : 104.6 Mio, 49 entrees, 303.8 Mio
#     decompresses au total, plus gros membre ffplay.exe 98.6 Mio ;
#     l'installation en extrait deux (ffprobe.exe + ffmpeg.exe) = 194.2 Mio.
#   MediaInfo_CLI_24.11_Windows_x64.zip : 3.5 Mio, 25 entrees, 8.5 Mio
#     decompresses, plus gros membre MediaInfo.exe 7.6 Mio.
# Chaque plafond garde une marge d'environ x2.6 a x10 sur le reel : assez pour
# absorber la croissance normale d'une version amont, trop peu pour un OOM.
_MAX_ARCHIVE_BYTES = 400 * 1024 * 1024
_MAX_ZIP_ENTRIES = 512
_MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_MAX_MEMBER_UNCOMPRESSED_BYTES = 256 * 1024 * 1024
# Volontairement INFERIEUR a 2 x le plafond par membre : sinon la borne cumulee
# serait inatteignable (l'installation extrait au plus deux membres) et ne
# serait qu'un decor.
_MAX_EXTRACTED_BYTES_PER_INSTALL = 384 * 1024 * 1024
# 1 Mio par chunk : borne l'empreinte memoire ET le depassement maximal avant
# detection (on ne peut pas depasser le plafond de plus d'un chunk lu, et aucun
# octet au-dela du plafond n'est ecrit sur disque).
_EXTRACT_CHUNK_BYTES = 1024 * 1024

# Timeout du telechargement : sans cela, un serveur muet (hote en panne,
# firewall corporate qui drop) fait hang l'install indefiniment.
# C'est un timeout PAR OPERATION socket, pas une duree totale de transfert : un
# telechargement de 105 Mio sur une ligne lente reste possible tant que le
# serveur ne reste pas 120 s sans envoyer un octet.
# Il est passe a `urlopen(..., timeout=)`, donc porte sur la SEULE connexion
# ouverte ici (cf. `_download_to_file` et issue #514).
_DOWNLOAD_TIMEOUT_S = 120.0

# Taille de bloc de lecture reseau. Sert aussi d'unite au `reporthook` (contrat
# `urlretrieve` : blocknum, blocksize, totalsize).
_DOWNLOAD_BLOCK_BYTES = 64 * 1024


class IntegrityError(Exception):
    """Leve quand une archive telechargee ne peut pas etre jugee sure.

    Trois causes : empreinte SHA256 absente ou differente de l'attendue, ou
    depassement d'une borne de taille/nombre d'entrees.

    Fail-closed : rien n'est extrait, rien n'est laisse sur disque, l'install
    est refusee. On n'execute jamais un binaire qu'on n'a pas pu verifier.
    """


def _degraded_mode_hint(label: str) -> str:
    """Message d'echec actionnable : ce qui est refuse, ce qui se degrade, quoi faire.

    L'application reste utilisable sans ces binaires : seule la probe technique
    (codec, HDR, pistes audio, debit) devient indisponible. `ProbeService`
    marque alors la ligne `degraded_source` et le score qualite est calcule sans
    les donnees techniques ; scan, identification, renommage des dossiers,
    doublons et apply continuent de fonctionner.
    """
    return (
        f"Installation automatique refusee pour {label} : aucune empreinte SHA256 de reference "
        "n'est disponible, et CineSort n'installe pas un executable telecharge qu'il ne peut pas "
        "verifier (fail-closed). "
        "Consequence : seule l'analyse technique des fichiers (codec, HDR, pistes audio, debit) "
        "reste indisponible ; le scan, l'identification, la detection de doublons, le renommage "
        "des dossiers et l'apply fonctionnent normalement, le score qualite est simplement calcule "
        "sans ces donnees et s'affiche 'indisponible'. "
        "Pour obtenir l'outil quand meme : l'installer via winget (bouton « Mettre a jour » de la "
        "page Parametres > Outils externes), ou le telecharger manuellement depuis le site officiel "
        "et renseigner son chemin dans Parametres > Outils externes."
    )


def _sha256_file(path: str) -> str:
    """Calcule le SHA256 hex (lowercase) d'un fichier en streaming (memoire bornee)."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        # 1 MiB par chunk : compromis entre I/O syscalls et empreinte memoire.
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_expected_sha256(value: str, *, source: str) -> str:
    """Normalise (strip + lowercase) et VALIDE une empreinte attendue.

    Une valeur mal formee leve IntegrityError plutot que d'etre ignoree : sinon
    une coquille dans la variable d'environnement retomberait silencieusement
    sur la constante module, c'est-a-dire sur une empreinte que l'operateur
    croyait avoir remplacee.
    """
    norm = str(value).strip().lower()
    if not _SHA256_RE.fullmatch(norm):
        raise IntegrityError(
            f"Empreinte SHA256 attendue invalide ({source}) : {value!r}. "
            "Une empreinte SHA256 compte exactement 64 caracteres hexadecimaux. "
            "Install refuse (fail-closed)."
        )
    return norm


def _resolve_expected_sha256(env_var: str, override: Optional[str], constant: Optional[str]) -> Optional[str]:
    """Resout le SHA256 attendu : override kwarg > variable d'env > constante.

    Retourne None uniquement si AUCUNE des trois sources n'est renseignee — cas
    dans lequel `_verify_archive` refuse l'installation (fail-closed).
    """
    if override is not None:
        return _normalize_expected_sha256(override, source="parametre expected_sha256")
    env_val = (os.environ.get(env_var) or "").strip()
    if env_val:
        return _normalize_expected_sha256(env_val, source=f"variable d'environnement {env_var}")
    if constant is None:
        return None
    return _normalize_expected_sha256(constant, source="constante EXPECTED_SHA256_* du module")


def _assert_https(url: str) -> None:
    """Refuse tout schema d'URL autre que HTTPS.

    `file://` etait tolere « pour les tests unitaires » : c'etait un
    contournement du controle de transport laisse dans le code de production.
    Les tests simulent desormais le transport (`urlopen` mocke) et n'ont plus
    besoin de cette breche.
    """
    scheme = urlparse(url).scheme.lower()
    if scheme != "https":
        raise IntegrityError(f"URL scheme '{scheme}' refuse (HTTPS requis) : {url}")


def _verify_archive(
    zip_path: str,
    expected_sha256: Optional[str],
    *,
    label: str,
) -> None:
    """Verifie l'integrite SHA256 d'une archive telechargee. Fail closed.

    - `expected_sha256` None : REFUS (issue #466). Auparavant ce cas se
      contentait d'un warning et laissait passer — la verification avait donc
      l'apparence d'exister sans rien verifier.
    - mismatch : IntegrityError et destruction de l'archive suspecte.

    Dans les deux cas de refus, le fichier est efface pour qu'aucun appelant ne
    puisse le reutiliser par erreur.
    """
    if expected_sha256 is None:
        with suppress(OSError):
            os.remove(zip_path)
        raise IntegrityError(_degraded_mode_hint(label))
    expected_norm = _normalize_expected_sha256(expected_sha256, source=f"empreinte attendue pour {label}")
    actual = _sha256_file(zip_path)
    if actual.lower() != expected_norm:
        # Fail closed : on detruit l'archive pour empecher toute extraction
        # ulterieure par erreur, et on leve une exception explicite.
        with suppress(OSError):
            os.remove(zip_path)
        raise IntegrityError(
            f"SHA256 mismatch pour {label} : attendu={expected_norm}, reel={actual}. Install refuse (fail-closed)."
        )
    logger.info("auto_install: SHA256 verifie OK pour %s (%s)", label, actual)


class _ExtractBudget:
    """Budget d'octets decompresses partage par une installation.

    Porte sur la taille decompressee CUMULEE reellement ecrite (plusieurs
    membres peuvent etre extraits d'une meme archive, cf. ffprobe.exe +
    ffmpeg.exe), et non sur les tailles declarees dans l'en-tete ZIP.
    """

    def __init__(self, limit: int) -> None:
        self.limit = int(limit)
        self.consumed = 0

    def consume(self, nbytes: int, *, label: str) -> None:
        """Decompte `nbytes` et leve DES que le budget est depasse."""
        self.consumed += int(nbytes)
        if self.consumed > self.limit:
            raise IntegrityError(
                f"Decompression abandonnee pour {label} : plus de {self.limit} octets decompresses "
                f"au total (archive piegee ou anormale). Install refuse (fail-closed)."
            )


def _bounded_reporthook(label: str) -> Callable[[int, int, int], None]:
    """Hook de progression qui interrompt un telechargement trop volumineux.

    Interrompt DURANT le transfert (le `Content-Length` annonce est refuse
    immediatement, et le volume reellement recu est recontrole a chaque bloc) :
    un controle post-download aurait deja rempli le disque.
    """

    def _hook(blocknum: int, blocksize: int, totalsize: int) -> None:
        if int(totalsize) > _MAX_ARCHIVE_BYTES:
            raise IntegrityError(
                f"Telechargement refuse pour {label} : taille annoncee {int(totalsize)} octets "
                f"> plafond {_MAX_ARCHIVE_BYTES}. Install refuse (fail-closed)."
            )
        received = int(blocknum) * int(blocksize)
        if received > _MAX_ARCHIVE_BYTES:
            raise IntegrityError(
                f"Telechargement interrompu pour {label} : plus de {_MAX_ARCHIVE_BYTES} octets recus "
                "(taille non annoncee ou mensongere). Install refuse (fail-closed)."
            )

    return _hook


def _announced_size(response: Any) -> int:
    """`Content-Length` annonce par le serveur, ou -1 s'il est absent/illisible.

    -1 est la valeur que `urlretrieve` transmet au reporthook dans ce cas
    (transfert chunked, serveur avare) : le hook sait deja la traiter, la borne
    tombe alors sur le volume reellement recu.
    """
    headers = getattr(response, "headers", None)
    raw = headers.get("Content-Length") if headers is not None else None
    try:
        return int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return -1


def _download_to_file(
    url: str,
    dest: str,
    reporthook: Callable[[int, int, int], None],
    *,
    timeout_s: float,
) -> None:
    """Telecharge `url` vers `dest` en streaming, avec un timeout PAR CONNEXION.

    Remplace `urlretrieve` (issue #514). `urlretrieve` n'expose aucun parametre
    de timeout : le seul moyen de le borner etait `socket.setdefaulttimeout()`,
    c'est-a-dire de changer le DEFAUT GLOBAL du processus. Pendant les 120 s du
    telechargement, TOUT socket cree par un autre thread — serveur REST,
    clients TMDb/OMDb/Jellyfin/Plex, watcher — heritait de ce timeout sans
    l'avoir demande, et `auto_install_probe_tools` est declenchable a distance
    via la facade REST runtime. `urlopen(..., timeout=)` ne borne que la
    connexion ouverte ici : plus aucun effet de bord cross-thread.

    Le contrat du `reporthook` est celui d'`urlretrieve`
    (`blocknum, blocksize, totalsize`), appele une premiere fois a blocknum 0
    avec la taille annoncee : le refus d'une archive hors plafond tombe donc
    AVANT la lecture du moindre octet de corps.
    """
    request = Request(url, headers={"User-Agent": "CineSort/auto-install"})
    # nosec B310 - le schema est verifie HTTPS par _assert_https en amont (aucun
    # file:// ni schema exotique n'est accepte), l'URL est une constante du
    # module et non une entree utilisateur, le volume est borne par le
    # reporthook, et l'archive obtenue n'est utilisee qu'apres verification de
    # son empreinte SHA256.
    with urlopen(request, timeout=timeout_s) as response:  # nosec B310
        totalsize = _announced_size(response)
        blocknum = 0
        reporthook(blocknum, _DOWNLOAD_BLOCK_BYTES, totalsize)
        with open(dest, "wb") as out:
            while True:
                chunk = response.read(_DOWNLOAD_BLOCK_BYTES)
                if not chunk:
                    break
                out.write(chunk)
                blocknum += 1
                reporthook(blocknum, _DOWNLOAD_BLOCK_BYTES, totalsize)


def _download_bounded(url: str, dest: str, *, label: str) -> None:
    """Telecharge `url` vers `dest` avec un plafond de taille, HTTPS impose.

    Deux gardes complementaires : le reporthook coupe pendant le transfert, et
    la taille du fichier obtenu est recontrolee ensuite — le transport ne
    garantit pas que le hook soit appele (redirection locale, mock, futur
    changement d'implementation).
    """
    _assert_https(url)
    try:
        _download_to_file(url, dest, _bounded_reporthook(label), timeout_s=_DOWNLOAD_TIMEOUT_S)
    except BaseException:
        # Transfert abandonne (plafond franchi, timeout, reseau coupe) : le
        # fragment d'archive ne doit pas survivre pour etre repris par erreur.
        with suppress(OSError):
            os.remove(dest)
        raise
    size = os.path.getsize(dest)
    if size > _MAX_ARCHIVE_BYTES:
        with suppress(OSError):
            os.remove(dest)
        raise IntegrityError(
            f"Archive trop volumineuse pour {label} : {size} octets > plafond {_MAX_ARCHIVE_BYTES}. "
            "Install refuse (fail-closed)."
        )


def _check_archive_shape(zf: zipfile.ZipFile, *, label: str) -> None:
    """Rejet precoce d'une archive anormale : trop d'entrees, ou trop volumineuse.

    Ces bornes s'appuient sur l'en-tete ZIP, donc sur des valeurs controlees par
    l'attaquant : elles ecartent les cas grossiers a cout nul, mais la borne qui
    protege reellement est le budget applique pendant la copie (`_ExtractBudget`).
    """
    infos = zf.infolist()
    if len(infos) > _MAX_ZIP_ENTRIES:
        raise IntegrityError(
            f"Archive refusee pour {label} : {len(infos)} entrees > plafond {_MAX_ZIP_ENTRIES}. "
            "Install refuse (fail-closed)."
        )
    total = 0
    for info in infos:
        total += int(info.file_size)
        # Abandon DES le depassement : on ne somme pas les 4 milliards d'entrees
        # avant de conclure.
        if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise IntegrityError(
                f"Archive refusee pour {label} : taille decompressee cumulee > plafond "
                f"{_MAX_TOTAL_UNCOMPRESSED_BYTES} octets (zip bomb ?). Install refuse (fail-closed)."
            )


def _extract_member(
    zf: zipfile.ZipFile,
    entry: str,
    dest: Path,
    *,
    budget: _ExtractBudget,
    label: str,
) -> None:
    """Extrait `entry` vers `dest` en streaming borne, sans jamais laisser de binaire tronque.

    - taille declaree > plafond par membre : refus AVANT toute lecture ;
    - la copie consomme un budget partage, chunk par chunk : elle s'arrete DES
      le depassement, et aucun octet au-dela n'est ecrit ;
    - l'ecriture passe par un fichier `.part` renomme atomiquement : un
      executable partiel n'apparait JAMAIS au chemin final, ou `tools_manager`
      le detecterait comme disponible et le LANCERAIT.

    Cas de l'en-tete mensonger : `zipfile` borne lui-meme la sortie de
    `ZipExtFile.read(n)` a la taille declaree (a un chunk pres) puis leve
    `BadZipFile` sur le CRC. Un plafond supplementaire sur les octets ecrits
    pour CE membre serait donc inatteignable — on ne l'ajoute pas ; c'est le
    budget partage, lui atteignable, qui porte la borne en streaming.

    `dest` est un chemin fixe cote CineSort (jamais le nom de l'entree, que
    l'attaquant controle) : pas de zip-slip possible ici.
    """
    declared = int(zf.getinfo(entry).file_size)
    if declared > _MAX_MEMBER_UNCOMPRESSED_BYTES:
        raise IntegrityError(
            f"Entree '{entry}' refusee pour {label} : taille declaree {declared} octets > plafond "
            f"{_MAX_MEMBER_UNCOMPRESSED_BYTES}. Install refuse (fail-closed)."
        )
    tmp_dest = dest.with_name(dest.name + ".part")
    try:
        with zf.open(entry) as src, open(tmp_dest, "wb") as out:
            while True:
                chunk = src.read(_EXTRACT_CHUNK_BYTES)
                if not chunk:
                    break
                # Borne evaluee AVANT l'ecriture du chunk.
                budget.consume(len(chunk), label=label)
                out.write(chunk)
        os.replace(tmp_dest, dest)
    finally:
        # Apres un os.replace reussi le .part n'existe plus ; sur abandon il est
        # efface ici. Dans tous les cas rien de tronque ne survit.
        with suppress(OSError):
            os.remove(tmp_dest)


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
    *,
    expected_sha256: Optional[str] = None,
) -> str:
    """Telecharge et extrait ffprobe.exe. Retourne le chemin ou leve une exception.

    Verifie l'empreinte SHA256 de l'archive avant extraction et REFUSE
    l'installation si aucune empreinte de reference n'est disponible (#466).
    L'extraction est bornee en taille (#734). Un override `expected_sha256=`
    permet a un packager de pointer un miroir interne.
    """
    tools = get_tools_dir()
    ffprobe_path = tools / "ffprobe.exe"
    if ffprobe_path.exists():
        return str(ffprobe_path)

    # Resolution de l'empreinte AVANT le telechargement : inutile de tirer
    # 100 Mo pour refuser ensuite.
    expected = _resolve_expected_sha256(_ENV_SHA256_FFMPEG, expected_sha256, EXPECTED_SHA256_FFMPEG)
    if expected is None:
        raise IntegrityError(_degraded_mode_hint("ffmpeg.zip"))

    logger.info("auto_install: telechargement ffprobe depuis %s", FFMPEG_URL)
    if progress_callback:
        progress_callback("Telechargement de FFprobe...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "ffmpeg.zip")
        _download_bounded(FFMPEG_URL, zip_path, label="ffmpeg.zip")

        # Verification SHA256 AVANT toute ouverture/extraction.
        # IntegrityError remonte et abandonne l'install (fail-closed).
        _verify_archive(zip_path, expected, label="ffmpeg.zip")

        logger.info("auto_install: extraction ffprobe.exe")
        if progress_callback:
            progress_callback("Extraction de FFprobe...")

        budget = _ExtractBudget(_MAX_EXTRACTED_BYTES_PER_INSTALL)
        with zipfile.ZipFile(zip_path) as zf:
            _check_archive_shape(zf, label="ffmpeg.zip")

            # Extraire ffprobe.exe
            entry = _find_in_zip(zf, "ffprobe.exe")
            if not entry:
                raise FileNotFoundError("ffprobe.exe non trouve dans l'archive")
            _extract_member(zf, entry, ffprobe_path, budget=budget, label="ffmpeg.zip")
            logger.info("auto_install: ffprobe installe → %s", ffprobe_path)

            # Extraire aussi ffmpeg.exe (utile pour le perceptuel)
            ffmpeg_entry = _find_in_zip(zf, "ffmpeg.exe")
            if ffmpeg_entry:
                ffmpeg_path = tools / "ffmpeg.exe"
                if not ffmpeg_path.exists():
                    _extract_member(zf, ffmpeg_entry, ffmpeg_path, budget=budget, label="ffmpeg.zip")
                    logger.info("auto_install: ffmpeg installe → %s", ffmpeg_path)

    return str(ffprobe_path)


def install_mediainfo(
    progress_callback: Optional[Callable[[str], None]] = None,
    *,
    expected_sha256: Optional[str] = None,
) -> str:
    """Telecharge et extrait MediaInfo.exe. Retourne le chemin ou leve une exception.

    Memes garanties que `install_ffprobe` : empreinte SHA256 obligatoire
    (fail-closed) et extraction bornee.
    """
    tools = get_tools_dir()
    mi_path = tools / "MediaInfo.exe"
    if mi_path.exists():
        return str(mi_path)

    expected = _resolve_expected_sha256(_ENV_SHA256_MEDIAINFO, expected_sha256, EXPECTED_SHA256_MEDIAINFO)
    if expected is None:
        raise IntegrityError(_degraded_mode_hint("mediainfo.zip"))

    logger.info("auto_install: telechargement MediaInfo depuis %s", MEDIAINFO_URL)
    if progress_callback:
        progress_callback("Telechargement de MediaInfo...")

    with tempfile.TemporaryDirectory() as tmp:
        zip_path = os.path.join(tmp, "mediainfo.zip")
        _download_bounded(MEDIAINFO_URL, zip_path, label="mediainfo.zip")

        # Verification SHA256 avant extraction (fail-closed).
        _verify_archive(zip_path, expected, label="mediainfo.zip")

        if progress_callback:
            progress_callback("Extraction de MediaInfo...")

        budget = _ExtractBudget(_MAX_EXTRACTED_BYTES_PER_INSTALL)
        with zipfile.ZipFile(zip_path) as zf:
            _check_archive_shape(zf, label="mediainfo.zip")
            entry = _find_in_zip(zf, "mediainfo.exe")
            if not entry:
                raise FileNotFoundError("MediaInfo.exe non trouve dans l'archive")
            _extract_member(zf, entry, mi_path, budget=budget, label="mediainfo.zip")
            logger.info("auto_install: MediaInfo installe → %s", mi_path)

    return str(mi_path)


def install_all(
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Installe tous les outils manquants. Retourne les chemins et erreurs."""
    results: Dict[str, str] = {}
    errors: list[str] = []

    # IntegrityError (empreinte absente/mismatch, borne depassee) fait partie du
    # tuple : pas de retry ni de fallback, si l'archive n'est pas verifiable on
    # refuse et on remonte le message a l'utilisateur.
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
