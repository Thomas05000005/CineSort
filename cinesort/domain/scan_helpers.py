from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# SCAN-1 (zone L13) : regex renforcee.
# - Avant : r"\b(sample|trailer|teaser|demo)\b" matchait trop large
#   ('demo' attrapait des films legitimes comme "Demo Day (2015)").
# - Apres : exige un separateur explicite (point/tiret/underscore/espace) au
#   debut OU en fin de stem, ce qui evite les faux positifs au milieu d'un mot.
#   'demo' retire (trop ambigu).
IGNORE_VIDEO_NAME_RE = re.compile(
    r"(?:^|[\.\-_\s])(sample|trailer|teaser)(?:[\.\-_\s]|$)",
    re.IGNORECASE,
)
GENERIC_EXTRA_VIDEO_NAMES = {
    "bonus",
    "bonus feature",
    "bonus features",
    "extra",
    "extras",
    "featurette",
    "featurettes",
    "interview",
    "interviews",
    "making of",
    "deleted scene",
    "deleted scenes",
    "behind the scenes",
}


def file_name_looks_bonus(name: str) -> bool:
    """Filtrage textuel uniquement (pas de stat) : detecte les fichiers video
    qui sont vraisemblablement des bonus/making-of/extras d'apres leur nom seul.

    SOURCE UNIQUE de cette heuristique dans le module. Deux clones existaient :
    `_looks_like_nested_extra_video` (variante `Path`, zero appelant), supprime
    par #705, et la closure `_file_looks_bonus` de `discover_candidate_folders`,
    supprimee ici au profit de cette fonction. Elles etaient a l'octet pres la
    meme regle et pouvaient deriver independamment.

    Args:
        name: Nom du fichier (avec ou sans chemin parent).

    Returns:
        True si le nom matche un pattern bonus (sample/trailer/teaser) ou un
        nom generique de bonus (bonus/extras/featurette/...).
    """
    if not name:
        return False
    if IGNORE_VIDEO_NAME_RE.search(name):
        return True
    stem = name.rsplit(".", 1)[0].lower().replace(".", " ").replace("_", " ").replace("-", " ")
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem in GENERIC_EXTRA_VIDEO_NAMES


def _bump_stats_reject(stats: Any, key: str, *, path: str | None = None) -> None:
    """Incremente stats.analyse_ignores_par_raison[key] avec defense en profondeur.

    Tolere stats=None (compat appelants existants) et un objet stats incomplet.
    """
    if stats is None:
        return
    try:
        bucket = getattr(stats, "analyse_ignores_par_raison", None)
        if bucket is None:
            return
        bucket[key] = int(bucket.get(key, 0)) + 1
    except (AttributeError, TypeError, ValueError):
        return


def iter_videos(
    cfg: Any,
    folder: Path,
    *,
    min_video_bytes: int,
    stats: Any = None,
) -> List[Path]:
    # BUG 3 : optimisation NAS. `os.scandir()` retourne les metadata
    # (is_file, stat) en une seule operation systeme au lieu de round-trips
    # separes comme avec `folder.iterdir() + p.is_file() + p.stat()`.
    # SCAN-1 (zone L38-L41) : tracabilite des rejets scandir + observabilite par
    # categorie (extension, taille, nom suspect). `stats` est optionnel pour
    # preserver la backward-compat des appelants existants.
    vids: List[Path] = []
    video_exts = cfg.video_exts or set()
    min_bytes = int(min_video_bytes)
    try:
        scandir_ctx = os.scandir(str(folder))
    except (OSError, PermissionError, FileNotFoundError) as exc:
        logger.warning("scan: scandir failed on %s: %s", folder, exc)
        _bump_stats_reject(stats, "ignore_scandir_error", path=str(folder))
        return vids
    try:
        for entry in scandir_ctx:
            name = entry.name
            # suffix via string slicing pour eviter un Path()
            dot = name.rfind(".")
            if dot < 0:
                continue
            ext = name[dot:].lower()
            if ext not in video_exts:
                _bump_stats_reject(stats, "ignore_extension", path=entry.path)
                continue
            if IGNORE_VIDEO_NAME_RE.search(name):
                _bump_stats_reject(stats, "ignore_nom_suspect", path=entry.path)
                continue
            try:
                if not entry.is_file(follow_symlinks=False):
                    continue
                # stat() sur le DirEntry utilise le cache de scandir (0 round-trip NAS)
                st = entry.stat(follow_symlinks=False)
                if st.st_size < min_bytes:
                    _bump_stats_reject(stats, "ignore_taille_min", path=entry.path)
                    continue
            except (OSError, PermissionError, FileNotFoundError, ValueError, TypeError):
                _bump_stats_reject(stats, "ignore_scandir_error", path=entry.path)
                continue
            vids.append(Path(entry.path))
    finally:
        with contextlib.suppress(OSError, AttributeError):
            scandir_ctx.close()
    return vids


def detect_single_with_extras(cfg: Any, videos: List[Path]) -> bool:
    if not getattr(cfg, "detect_extras_in_single_folder", False):
        return False
    if len(videos) <= 1:
        return False
    sizes = []
    for v in videos:
        try:
            sizes.append(v.stat().st_size)
        except (OSError, PermissionError, FileNotFoundError):
            sizes.append(0)
    sizes_sorted = sorted(sizes, reverse=True)
    if len(sizes_sorted) < 2:
        return False
    biggest, second = sizes_sorted[0], sizes_sorted[1]
    if second <= 0:
        return True
    return (biggest / second) >= float(getattr(cfg, "extras_size_ratio", 4.0))


def collect_non_video_extensions(cfg: Any, folder: Path) -> Dict[str, int]:
    out: Dict[str, int] = {}
    try:
        entries = list(folder.iterdir())
    except (OSError, PermissionError, FileNotFoundError):
        return out
    for p in entries:
        if not p.is_file():
            continue
        ext = p.suffix.lower()
        if ext in cfg.video_exts:
            continue
        key = ext or "<sans_ext>"
        out[key] = int(out.get(key, 0)) + 1
    return out


# BUG 5 : regex qui detecte un nom de dossier "film" via sa parenthese d'annee.
# Un dossier comme "Inception (2010)" est presque certainement un dossier de film,
# donc inutile de faire un scandir dessus pour verifier. Phase 2 (iter_videos) fera
# le tri. Sur NAS SMB, chaque scandir evite = ~14ms de round-trip economise.
_FILM_FOLDER_NAME_RE = re.compile(r"\(\s*(19|20)\d{2}\s*\)")


def discover_candidate_folders(
    cfg: Any,
    *,
    max_depth: int = 6,
    stats: Any = None,
) -> List[Path]:
    """BUG 1 + BUG 5 : decouverte rapide des dossiers candidats, optimisee NAS.

    Strategie :
    - Descente recursive via os.scandir (un scandir par dossier visite).
    - AUCUN stat() sur les fichiers, AUCUN .nfo parse, AUCUNE signature.
    - BUG 5 : si le nom du dossier contient `(YYYY)`, il est considere directement
      comme un dossier de film → candidat immediat, AUCUN scandir n'est fait dessus.
      Gain massif sur bibliotheque plate (857 films x 14ms = 12s → <1s).
      Les dossiers sans `(YYYY)` (categories, sagas, anomalies) sont explores
      normalement pour preserver la detection recursive.

    Regle de candidature (dossiers sans annee) :
    - Dossier feuille (pas de sous-dossiers) avec fichiers → candidat
    - Dossier avec sous-dossiers + des fichiers video non-bonus → candidat + descente
    - Dossier avec sous-dossiers mais uniquement des bonus/trailers → descente seule
    - Dossier vide → ignore

    SCAN-1 (L122) : max_depth eleve de 3 a 6 pour gerer les organisations
    profondes type Films/A-F/Action/2024/MovieName/Movie.mkv (5 niveaux).
    SCAN-1 (L174-L179) : le skip des dossiers prefixes '_' est limite a depth == 0
    (racine), sauf le dossier collection (CineSort interne, toujours skip).
    SCAN-1 (L157-L163) : tous les echecs scandir sont logges et comptabilises
    dans stats.analyse_ignores_par_raison['ignore_scandir_error'].

    Cible : < 2s sur NAS SMB pour ~1000 dossiers a majorite plate.
    """
    root = Path(cfg.root)
    collection_name_lower = str(getattr(cfg, "collection_root_name", "") or "").lower()
    video_exts = set(getattr(cfg, "video_exts", set()) or set())
    candidates: List[Path] = []
    # Issue #888 : identites reelles des dossiers deja visites, pour ne pas
    # explorer deux fois le meme dossier physique atteint par deux chemins.
    # Voir `_identite_reelle` et la garde en tete de `_walk`.
    vus: set[tuple[int, int]] = set()

    def _yyyy_folder_shape(path: Path) -> tuple[bool, bool]:
        """Inspecte un dossier `(YYYY)` en UN scandir.

        Retourne (a_video_directe_non_bonus, a_des_sous_dossiers). Sert au
        fast-path `(YYYY)` a decider entre candidat-direct (film pose dans le
        dossier annee) et descente (film dans un sous-dossier release imbrique).
        Tout echec scandir → (False, False) : le dossier reste candidat (le
        comportement historique d'avant ce fix), iter_videos tranchera en phase 2.
        """
        try:
            sub = os.scandir(str(path))
        except (OSError, PermissionError, FileNotFoundError) as exc:
            logger.warning("scan: scandir (YYYY)-shape failed on %s: %s", path, exc)
            _bump_stats_reject(stats, "ignore_scandir_error", path=str(path))
            return (False, False)
        has_direct_video = False
        has_subdirs = False
        try:
            for e in sub:
                try:
                    if e.is_dir(follow_symlinks=False):
                        has_subdirs = True
                        continue
                except OSError:
                    continue
                en = e.name
                d = en.rfind(".")
                if d >= 0 and en[d:].lower() in video_exts and not file_name_looks_bonus(en):
                    has_direct_video = True
        finally:
            with contextlib.suppress(OSError, AttributeError):
                sub.close()
        return (has_direct_video, has_subdirs)

    def _identite_reelle(path: Path) -> tuple[int, int] | None:
        """Identite PHYSIQUE du dossier : `(st_dev, st_ino)`, ou None si illisible.

        Deux chemins qui rendent le meme couple designent le meme dossier sur le
        disque, meme si l'un passe par une jonction NTFS. Mesure sur Windows 11
        (CPython 3.13), avec une vraie jonction `mklink /J` :

            cible : st_dev=16600885243136770875 st_ino=562949956034177
            lien  : st_dev=16600885243136770875 st_ino=562949956034177

        `os.stat` suit deliberement la jonction, ce qui est exactement ce qu'on
        veut ici : on cherche la cible, pas le lien.

        Pourquoi pas `os.path.realpath` : il donne le meme verdict mais coute
        **4,6x plus cher** (17,9 ms contre 3,9 ms pour 300 dossiers, meme
        machine). Ce module est explicitement optimise pour le NAS SMB, ou
        chaque aller-retour evite compte.

        En cas d'echec (permission, jonction cassee, volume deconnecte) on rend
        None et l'appelant DESCEND quand meme. C'est le sens permissif, choisi
        deliberement : ce chemin-ci ne detruit rien, il analyse, et le
        proprietaire a tranche que l'application ne doit jamais renoncer a
        analyser. Un dossier reellement illisible sera de toute facon arrete
        juste apres par l'echec du `scandir`.
        """
        try:
            st = os.stat(str(path))
        except (OSError, ValueError) as exc:
            logger.warning("scan: stat identite failed on %s: %s", path, exc)
            return None
        # st_ino vaut 0 sur les systemes de fichiers qui ne le renseignent pas :
        # dans ce cas le couple ne distingue plus rien et deviendrait un faux
        # "deja vu" qui masquerait des dossiers legitimes.
        if not st.st_ino:
            return None
        return (st.st_dev, st.st_ino)

    def _retenir(path: Path) -> bool:
        """Enregistre `path` comme visite. Rend False s'il l'etait deja.

        Rend True quand l'identite est illisible : on prefere analyser deux fois
        que ne pas analyser du tout (cf. `_identite_reelle`).
        """
        identite = _identite_reelle(path)
        if identite is None:
            return True
        if identite in vus:
            logger.info(
                "scan: %s designe un dossier deja visite (jonction ou lien), ignore",
                path,
            )
            _bump_stats_reject(stats, "ignore_dossier_deja_visite", path=str(path))
            return False
        vus.add(identite)
        return True

    def _walk(current: Path, depth: int, in_year_descent: bool = False) -> None:
        # Issue #888 : ne pas explorer deux fois le meme dossier physique.
        #
        # Une jonction NTFS n'est detectee par AUCUNE garde naturelle
        # (`is_symlink()` rend False depuis Python 3.8, `is_dir()` rend True),
        # donc `Bibliotheque/Raccourci -> Bibliotheque/Films` fait apparaitre
        # chaque film DEUX fois dans le plan. Mesure (vraie jonction) :
        #
        #     candidat : Films\Dune (2021)
        #     candidat : Raccourci\Dune (2021)
        #     -> 1 seul realpath unique pour 2 candidats
        #
        # Ce ne sont pas deux films qui se ressemblent : c'est le meme dossier
        # compte deux fois. L'ecran Doublons propose alors de « supprimer le
        # doublon » d'un fichier unique, et un apply qui deplace par un chemin
        # casse l'autre. Une jonction vers un ANCETRE produit le meme film
        # jusqu'a 4 fois (la descente est bornee par max_depth, il n'y a donc
        # pas de boucle infinie — verifie).
        #
        # Cette garde N'EXCLUT RIEN. Un dossier atteignable uniquement a travers
        # une jonction (cas courant : un disque mutualise monte dans la
        # bibliotheque) n'a jamais ete vu, donc il est visite normalement. Seule
        # la SECONDE visite du meme dossier physique est supprimee.
        if not _retenir(current):
            return
        if depth > max_depth:
            # SCAN-1 (L122) : tracer les dossiers abandonnes par depasement
            # de profondeur pour permettre un diagnostic UI.
            logger.warning(
                "scan: max_depth=%d depasse pour %s (abandon descente)",
                max_depth,
                current,
            )
            _bump_stats_reject(stats, "ignore_profondeur_max", path=str(current))
            return
        try:
            scandir_ctx = os.scandir(str(current))
        except (OSError, PermissionError, FileNotFoundError) as exc:
            # SCAN-1 (L160-L163) : tracer l'echec scandir pour diagnostic SMB.
            logger.warning("scan: scandir failed on %s: %s", current, exc)
            _bump_stats_reject(stats, "ignore_scandir_error", path=str(current))
            return
        subdirs: List[Path] = []
        # Sous-dossiers `(YYYY)` dont le film est imbrique (pas de video directe
        # non-bonus) et qu'il faut donc DESCENDRE au lieu de marquer candidat.
        yyyy_descend: List[Path] = []
        any_file = False
        video_files: List[str] = []
        # Issue #888 : les sous-dossiers sont collectes AVANT d'etre classes, pour
        # pouvoir traiter les dossiers reels avant les liens. `os.scandir` ne
        # garantit aucun ordre — mesure faite : il a rendu `lien` AVANT `reel`
        # sur un cas a deux entrees. Sans ce tri, c'est le chemin passant par la
        # jonction qui pourrait etre retenu, et le plan afficherait a
        # l'utilisateur un chemin qu'il ne reconnait pas, sur un ecran dont
        # l'action deplace des dossiers. Le tri est stable : a egalite de nature,
        # l'ordre du systeme de fichiers est preserve.
        entrees_dossiers: List[tuple[bool, str, Path]] = []
        try:
            for entry in scandir_ctx:
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                except OSError:
                    continue
                nm = entry.name
                if is_dir:
                    try:
                        # is_junction() existe depuis Python 3.12 (plancher du
                        # projet) et lit le cache de scandir : aucun aller-retour
                        # supplementaire. is_symlink() couvre les liens Windows,
                        # que is_junction() ignore.
                        est_lien = entry.is_junction() or entry.is_symlink()
                    except (OSError, AttributeError):
                        est_lien = False
                    entrees_dossiers.append((est_lien, nm, Path(entry.path)))
                    continue
                any_file = True
                # Extension via slicing (pas de Path)
                dot = nm.rfind(".")
                if dot >= 0 and nm[dot:].lower() in video_exts:
                    video_files.append(nm)
        finally:
            with contextlib.suppress(OSError, AttributeError):
                scandir_ctx.close()

        # Issue #888 : dossiers reels d'abord, liens ensuite (tri stable).
        entrees_dossiers.sort(key=lambda e: e[0])

        for est_lien, nm, entry_path in entrees_dossiers:
            # SCAN-1 (L174-L179) : limite le skip '_' a la racine
            # (depth == 0). En profondeur, certains utilisateurs
            # legitimes ont des sous-dossiers prefixes '_' (snapshots,
            # versionnage manuel, etc.). On garde toujours le skip du
            # dossier collection (interne CineSort).
            if depth == 0 and nm.startswith("_"):
                # `_retenir` AVANT le `continue` : sans cet enregistrement, le
                # dossier ecarte n'entre jamais dans `vus`, et une jonction
                # portant un AUTRE nom qui pointe dessus le fait rentrer par la
                # fenetre. Mesure sur `main` avant ce correctif :
                #
                #   Bibliotheque/_Collection/Deja Trie (2019)/...  (bac interne)
                #   Bibliotheque/Raccourci -> _Collection          (jonction)
                #   -> candidat : Raccourci\Deja Trie (2019)
                #
                # Un film DEJA trie et quarantine redevenait candidat au tri, et
                # l'apply pouvait le redeplacer. Le skip par NOM ne suffit pas :
                # il faut interdire le dossier PHYSIQUE, pas l'un de ses chemins.
                _retenir(entry_path)
                _bump_stats_reject(
                    stats,
                    "ignore_prefix_underscore",
                    path=str(entry_path),
                )
                continue
            if depth == 0 and nm.lower() == collection_name_lower:
                # Skip le dossier _Collection au niveau 1 du root. Meme raison
                # que ci-dessus : on enregistre son identite pour qu'aucun autre
                # chemin ne le rende visible.
                _retenir(entry_path)
                continue
            # BUG 5 : fast-path — si le nom contient `(YYYY)`, on suppose
            # un dossier de film. SCAN-FIX (Opus 2026-06-11) : un dossier
            # `Avatar (2009)/` peut contenir le film DIRECTEMENT (cas plat,
            # majoritaire) OU dans un sous-dossier release imbrique
            # (`Avatar (2009)/Avatar.2009.1080p-GRP/film.mkv`). iter_videos
            # en phase 2 est NON-recursif : marquer candidat sans descendre
            # rendait le film imbrique invisible (absent du plan).
            # Decision en 1 scandir :
            #   - video directe non-bonus presente  -> candidat seul (rapide,
            #     PAS de descente : evite de planifier featurettes/extras des
            #     sous-dossiers comme films + evite tout doublon).
            #   - pas de video directe MAIS sous-dossiers -> DESCENTE (_walk)
            #     qui appliquera sa propre logique candidat/bonus a chaque
            #     niveau (le film imbrique redevient detectable).
            #   - ni l'un ni l'autre (feuille sans video / non-video) ->
            #     candidat (comportement historique, iter_videos tranchera).
            if depth >= 0 and _FILM_FOLDER_NAME_RE.search(nm):
                has_direct_video, has_subdirs = _yyyy_folder_shape(entry_path)
                if not has_direct_video and has_subdirs:
                    # Descente : c'est `_walk` qui enregistrera l'identite.
                    yyyy_descend.append(entry_path)
                elif _retenir(entry_path):
                    # Ce raccourci retient un candidat SANS passer par `_walk` :
                    # sans cet enregistrement, un lien pointant droit sur un
                    # dossier `(YYYY)` (`Bibliotheque/Lien -> .../Dune (2021)`)
                    # produirait le meme film deux fois — la garde en tete de
                    # `_walk` ne le verrait jamais.
                    candidates.append(entry_path)
            else:
                subdirs.append(entry_path)

        if depth == 0:
            # Films poses directement a la racine : la racine devient candidat.
            # iter_videos() en phase 2 est non-recursif, donc les fichiers des
            # sous-dossiers ne seront pas double-comptes.
            non_bonus_root_videos = [v for v in video_files if not file_name_looks_bonus(v)]
            if non_bonus_root_videos:
                candidates.append(current)

        # SCAN-FIX (Opus 2026-06-11) : descendre dans les dossiers `(YYYY)` dont le
        # film est imbrique (decides ci-dessus). On le fait dans tous les cas, meme
        # quand `subdirs` est vide, sinon le film imbrique resterait invisible. On
        # propage in_year_descent=True pour que le tri bonus s'applique aux feuilles
        # de la release imbriquee (ex: un `Extras/` voisin ne doit pas devenir film).
        for yd in yyyy_descend:
            _walk(yd, depth + 1, in_year_descent=True)

        if subdirs:
            # Dossier avec sous-dossiers : candidat uniquement si au moins un fichier
            # video non-bonus est present au niveau courant.
            non_bonus_videos = [v for v in video_files if not file_name_looks_bonus(v)]
            if depth >= 1 and non_bonus_videos:
                candidates.append(current)
            for sd in subdirs:
                _walk(sd, depth + 1, in_year_descent=in_year_descent)
        else:
            # Dossier feuille (du point de vue des sous-dossiers "normaux") :
            # candidat si au moins un fichier est present. On ne filtre PAS les
            # bonus ici par defaut car certains dossiers legitimes n'ont que des
            # videos renommees bizarrement — iter_videos fera le tri en phase 2.
            # SCAN-FIX (Opus 2026-06-11) : EXCEPTION en descente `(YYYY)` — une
            # feuille dont TOUTES les videos sont des bonus (Extras/, Featurettes/,
            # bonus.mkv...) ne doit pas etre planifiee comme film. Hors descente
            # `(YYYY)`, le comportement historique est strictement preserve.
            if depth >= 1 and any_file:
                if in_year_descent and video_files and all(file_name_looks_bonus(v) for v in video_files):
                    _bump_stats_reject(stats, "ignore_bonus_only_folder", path=str(current))
                else:
                    candidates.append(current)

    _walk(root, depth=0)
    candidates.sort(key=lambda p: (str(p.parent).lower(), p.name.lower()))
    return candidates


# VN-F.3 (2026-06-01) : `stream_scan_targets` (legacy os.walk streaming) et
# `iter_scan_targets` (wrapper liste) supprimes — 81 LOC, 0 caller production.
# Le code prod passe via `discover_candidate_folders` depuis Phase 6+. Les 2
# tests historiques (test_scan_streaming, test_core_heuristics) ont ete migres
# vers `discover_candidate_folders` qui couvre le meme contrat de decouverte.


# =========================================================
# Detection contenu non-film (scoring par heuristiques)
# =========================================================

# Seuil : score >= 60 → flag not_a_movie
_NOT_A_MOVIE_THRESHOLD = 60

# Points par heuristique
_NAM_SUSPECT_NAME_PTS = 40
_NAM_SIZE_TINY_PTS = 30  # < 100 Mo
_NAM_SIZE_SMALL_PTS = 15  # 100-300 Mo
_NAM_NO_TMDB_PTS = 25
_NAM_SHORT_TITLE_PTS = 10  # ≤ 3 mots
_NAM_UNCOMMON_EXT_PTS = 10
_NAM_DURATION_VERY_SHORT_PTS = 35  # < 5 min
_NAM_DURATION_SHORT_PTS = 25  # < 20 min
_NAM_DURATION_VERY_SHORT_S = 300  # 5 minutes
_NAM_DURATION_SHORT_S = 1200  # 20 minutes

_NAM_SIZE_TINY_BYTES = 100 * 1024 * 1024  # 100 Mo
_NAM_SIZE_SMALL_BYTES = 300 * 1024 * 1024  # 300 Mo

# Mots-cles suspects dans le nom de fichier/dossier
_NOT_A_MOVIE_KEYWORDS_RE = re.compile(
    r"\b(sample|trailer|making|featurette|interview|deleted|extra|behind|teaser|demo|promo|blooper|outtake|recap|gag\s?reel)\b",
    re.IGNORECASE,
)

# Extensions peu courantes (fragments DVD/BD)
_UNCOMMON_VIDEO_EXTS = frozenset({".m2ts", ".ts", ".vob"})


def not_a_movie_score(
    video_name: str,
    file_size: int,
    proposed_source: str,
    confidence: int,
    title: str,
    *,
    duration_s: float | None = None,
) -> int:
    """Calcule un score de probabilite que la video ne soit pas un film.

    Score >= _NOT_A_MOVIE_THRESHOLD (60) → flag not_a_movie.
    """
    score = 0

    # 1. Nom contient un mot-cle suspect
    name_combined = f"{video_name} {title}"
    if _NOT_A_MOVIE_KEYWORDS_RE.search(name_combined):
        score += _NAM_SUSPECT_NAME_PTS

    # 2. Taille du fichier
    sz = int(file_size or 0)
    if 0 < sz < _NAM_SIZE_TINY_BYTES:
        score += _NAM_SIZE_TINY_PTS
    elif _NAM_SIZE_TINY_BYTES <= sz < _NAM_SIZE_SMALL_BYTES:
        score += _NAM_SIZE_SMALL_PTS

    # 3. Pas de match TMDb
    src = str(proposed_source or "").strip().lower()
    if src in ("unknown", "") or int(confidence or 0) == 0:
        score += _NAM_NO_TMDB_PTS

    # 4. Nom tres court (≤ 3 mots dans le titre)
    words = [w for w in str(title or "").split() if len(w) > 1]
    if 0 < len(words) <= 3:
        score += _NAM_SHORT_TITLE_PTS

    # 5. Extension peu courante
    ext = ""
    dot_idx = str(video_name or "").rfind(".")
    if dot_idx >= 0:
        ext = str(video_name)[dot_idx:].lower()
    if ext in _UNCOMMON_VIDEO_EXTS:
        score += _NAM_UNCOMMON_EXT_PTS

    # 6. Duree courte (si disponible)
    if duration_s is not None and duration_s > 0:
        if duration_s < _NAM_DURATION_VERY_SHORT_S:
            score += _NAM_DURATION_VERY_SHORT_PTS
        elif duration_s < _NAM_DURATION_SHORT_S:
            score += _NAM_DURATION_SHORT_PTS

    if score >= _NOT_A_MOVIE_THRESHOLD:
        logger.debug("not_a_movie: %s score=%d", video_name, score)
    return score
