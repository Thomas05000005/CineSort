from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

APP_NAME = "CineSort"
_DEBUG_ENV_VALUES = {"1", "true", "yes", "on", "debug"}


def _debug_enabled() -> bool:
    return str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() in _DEBUG_ENV_VALUES


def _debug_log_state(state_dir: Path, message: str) -> None:
    if not _debug_enabled():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        p = state_dir / "debug_state.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except OSError:
        # Best-effort debug logging : mkdir / open / write peuvent lever OSError
        # (PermissionError, FileNotFoundError, etc., qui en derivent). Les
        # ImportError / KeyError / TypeError / ValueError historiques ici
        # n'avaient pas de cause plausible et masquaient des bugs reels.
        return


def default_state_dir() -> Path:
    """
    Local PC (evite ecritures reseau).
    """
    base = os.environ.get("LOCALAPPDATA", ".")
    return Path(base) / APP_NAME


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    plan_jsonl: Path
    ui_log_txt: Path
    summary_txt: Path
    validation_json: Path


class RunDirectoryConflictError(FileExistsError):
    """Le dossier `runs/tri_films_<run_id>` est deja pris.

    Herite de `FileExistsError` (donc d'`OSError`) pour que les boundaries
    existantes qui filtrent OSError continuent de la traiter proprement.
    """


def create_run_dir(run_dir: Path, *, exclusive: bool) -> None:
    """Cree le dossier d'un run sans jamais ecraser silencieusement l'existant.

    Deux modes :

    - `exclusive=True` : RESERVATION ATOMIQUE. Le `mkdir` est fait sans
      `exist_ok`, donc c'est le systeme de fichiers lui-meme qui arbitre la
      course (EEXIST comme signal). C'est le seul mode qui protege le DISQUE :
      le dossier de run est cree AVANT l'insertion en base, une garde purement
      cote base arriverait trop tard.
    - `exclusive=False` : compat des flux qui rouvrent un run EXISTANT (apply,
      diagnostics, historique). On tolere un dossier deja la, mais on refuse
      quand meme d'en faire un point de creation s'il est deja PEUPLE lorsque
      l'appelant a la semantique « nouveau run » (cf. `new_run`).
    """
    if exclusive:
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_dir.mkdir()
        except FileExistsError as exc:
            raise RunDirectoryConflictError(
                f"Le dossier de run {run_dir} existe deja : run_id deja utilise, "
                "creation refusee pour ne pas ecraser un plan existant."
            ) from exc
        return
    run_dir.mkdir(parents=True, exist_ok=True)


def new_run(state_dir: Path, run_id: str, *, exclusive: bool = False) -> RunPaths:
    runs = state_dir / "runs"
    run_dir = runs / f"tri_films_{run_id}"
    if exclusive:
        create_run_dir(run_dir, exclusive=True)
    else:
        # Sans reservation atomique, on refuse au moins de reutiliser un dossier
        # deja PEUPLE : c'est exactement le scenario ou le second run ecrasait
        # le plan.jsonl du premier sans rien signaler.
        if run_dir.is_dir() and any(run_dir.iterdir()):
            raise RunDirectoryConflictError(
                f"Le dossier de run {run_dir} existe deja et contient des donnees "
                "(plan, logs ou quarantaine) : refus de le reutiliser pour un nouveau run."
            )
        create_run_dir(run_dir, exclusive=False)

    return RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        return ""


def write_text_safe(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Ecriture atomique ET durable — helper UNIQUE du depot
# ---------------------------------------------------------------------------
# Issues #511/#820 (state), #622/#732 (tmdb), #692 (probe disk_cache), #712
# (poster_proxy), #787 (updater), #822 (export nfo).
#
# Le depot possedait les DEUX bonnes moities de l'invariant, mais jamais au
# meme endroit : `omdb_client._save_cache_atomic` faisait flush+fsync+controle
# de taille avec un nom de `.tmp` FIXE ; `state.atomic_write_json` et
# `probe/disk_cache.upsert_disk_cache` faisaient le nom de `.tmp` UNIQUE sans
# aucun fsync. Chaque nouveau site recopiait une moitie au hasard. Ce module
# porte desormais le couple canonique ; tout nouvel ecrivain doit passer par
# `atomic_write_bytes` / `atomic_write_text` / `atomic_write_json` plutot que
# de reimplementer une troisieme variante.

# Infixe commun a TOUS les fichiers temporaires d'ecriture atomique. Permet aux
# purges de cache de reconnaitre (et donc de nettoyer) un orphelin de crash :
# avec un nom unique, un `.tmp` abandonne n'est plus jamais reutilise ni ecrase,
# il faut donc pouvoir l'identifier.
ATOMIC_TMP_INFIX = ".tmp."

# Politique de retentative d'`os.replace`, MESUREE par PR#718 sur 32 threads
# concurrents (`poster_proxy` sous ThreadingHTTPServer) : 19/32 echecs sans
# retentative, 0/32 avec ce backoff, pire cas 6 tentatives. Budget total
# ~0,41 s, soit MOINS que les 0,75 s de l'ancienne politique (5 x 50 ms
# lineaire) tout en persistant deux fois plus longtemps.
_ATOMIC_REPLACE_MAX_ATTEMPTS = 12
_ATOMIC_REPLACE_BACKOFF_BASE_S = 0.002
_ATOMIC_REPLACE_BACKOFF_CAP_S = 0.05


class AtomicWriteError(OSError):
    """Echec d'une ecriture atomique. Le fichier cible est laisse INCHANGE.

    Herite d'OSError pour rester attrapable par les `except OSError` deja en
    place chez les appelants (caches best-effort).
    """


def atomic_tmp_path(target: Path) -> Path:
    """Chemin de `.tmp` UNIQUE, voisin de `target` (meme repertoire => meme
    device, condition de l'atomicite d'`os.replace`).

    Unicite par (pid, thread, nanoseconde, uuid) : deux ecrivains concurrents ne
    peuvent pas se voler leur fichier intermediaire ni promouvoir le contenu de
    l'autre (CWE-362).
    """
    stamp = f"{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{uuid.uuid4().hex[:8]}"
    return target.with_name(f"{target.name}{ATOMIC_TMP_INFIX}{stamp}")


#: Forme EXACTE d'un `.tmp` produit par `atomic_tmp_path` : l'infixe, puis
#: `pid.thread.nanosecondes.uuid8`, ancre en FIN de nom.
#:
#: Une simple recherche de sous-chaine `".tmp." in name` serait le sens
#: PERMISSIF, et `sweep_atomic_tmp_orphans` est un chemin DESTRUCTIF lance au
#: demarrage, recursivement, sur `state_dir` (app.py). Or les bacs de
#: quarantaine vivent sous `<state_dir>/runs/tri_films_*/_review/` : le
#: balayage traverse donc des repertoires contenant les VIDEOS DE
#: L'UTILISATEUR. Un fichier quarantine nomme `Movie.2020.tmp.1080p.mkv`
#: serait supprime au prochain demarrage — sans confirmation, sans undo.
#:
#: Le filtre d'age n'y change rien : il protege les ecrivains VIVANTS, mais un
#: fichier legitime a par construction plus d'une heure, donc il est toujours
#: eligible. C'est bien le predicat de nom qui doit trancher.
_ATOMIC_TMP_RE = re.compile(r"\.tmp\.\d+\.\d+\.\d+\.[0-9a-f]{8}\Z")


def is_atomic_tmp_name(name: str) -> bool:
    """True si `name` a EXACTEMENT la forme produite par `atomic_tmp_path`.

    Reconnait la forme, pas une sous-chaine : un fichier de l'utilisateur ne
    peut etre pris pour un orphelin qu'en reproduisant `pid.thread.ns.uuid8`
    en fin de nom.
    """
    return _ATOMIC_TMP_RE.search(name) is not None


# Age au-dela duquel un `.tmp` d'ecriture atomique n'est plus le fichier
# intermediaire d'un ecrivain VIVANT mais un ORPHELIN de crash.
#
# Un `.tmp` vivant n'existe qu'entre `open()` et `os.replace()`. Mesure sur le
# plus gros ecrivain du depot (cache TMDb de 19,2 Mo) : 32 ms, plus au pire le
# budget de `_replace_with_retry` (~0,41 s). Une heure laisse donc ~3 orders de
# grandeur de marge avant qu'un balayage puisse voler le `.tmp` d'un ecrivain
# en cours.
ATOMIC_TMP_ORPHAN_MAX_AGE_S = 3600.0


def sweep_atomic_tmp_orphans(
    directory: Path,
    *,
    target_name: Optional[str] = None,
    max_age_s: float = ATOMIC_TMP_ORPHAN_MAX_AGE_S,
    recursive: bool = False,
) -> int:
    """Supprime les `.tmp` d'ecriture atomique ORPHELINS. Retourne le compte.

    REGRESSION QUE CETTE FONCTION REPARE. Un `.tmp` de nom FIXE etait reecrase
    a chaque ecriture : un crash en laissait au pire UN, et le suivant le
    recyclait. Le nom UNIQUE (pid/thread/ns/uuid) qui supprime la course
    CWE-362 supprime aussi ce recyclage : chaque crash laisse un residu
    DEFINITIF. Sans balayage, on echange une borne contre une accumulation —
    `tmdb_cache.json` pese 20 a 100 Mo et est reecrit toutes les 2 s pendant un
    scan, `<state_dir>/cache/posters/` n'a aucun pruner, et l'export `.nfo`
    depose son `.tmp` DANS LE DOSSIER DU FILM, a cote du `.mkv`, ou il est
    visible par l'utilisateur et par Jellyfin/Kodi.

    Deux filtres, tous les deux necessaires :

    - `is_atomic_tmp_name` : ne jamais toucher un fichier qui n'est pas a nous ;
    - `max_age_s` : ne jamais voler le `.tmp` d'un ecrivain VIVANT. C'est le
      seul filtre possible — entre le `close()` et le `os.replace()` le
      fichier n'a plus de handle ouvert, donc rien ne le distingue d'un
      orphelin sinon sa date. Tester la vivacite du pid inscrit dans le nom
      serait pire : les pids se recyclent.

    `target_name` restreint aux temporaires d'UNE cible donnee (`plan.jsonl` ->
    `plan.jsonl.tmp.*`), pour balayer un dossier partage sans toucher aux
    voisins. Best-effort integral : ne leve jamais.
    """
    removed = 0
    cutoff = time.time() - max(0.0, float(max_age_s))
    prefix = f"{target_name}{ATOMIC_TMP_INFIX}" if target_name else None
    try:
        if not directory.is_dir():
            return 0
        entries = directory.rglob("*") if recursive else directory.iterdir()
        for entry in entries:
            name = entry.name
            if not is_atomic_tmp_name(name):
                continue
            if prefix is not None and not name.startswith(prefix):
                continue
            try:
                if not entry.is_file() or entry.stat().st_mtime >= cutoff:
                    continue
                entry.unlink()
                removed += 1
            except OSError:
                # Verrou Windows, course avec un autre balayeur : on passe.
                continue
    except OSError:
        # Repertoire disparu / illisible : le balayage est un bonus, jamais une
        # condition de succes de l'appelant.
        return removed
    return removed


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """Bascule `tmp` -> `target`, en encaissant la contention Windows.

    R8-026 (F2-d) : sur Windows, `os.replace` leve `PermissionError`
    (WinError 5/32) quand un autre acteur tient la cible ouverte — un lecteur
    (poller de l'UI, 2e onglet) ou un autre ECRIVAIN qui bascule au meme
    instant. Sans retentative, l'ecriture est PERDUE : la cible garde son
    ancienne valeur et l'appelant croit avoir ecrit.

    L'atomicite n'est jamais en cause (`os.replace` reste atomique, il n'y a
    pas de contenu melange) : c'est un probleme de DISPONIBILITE de la cible.

    La politique vient de PR#718, qui l'a MESUREE sur le site le plus
    concurrent du depot (`poster_proxy`, sous `ThreadingHTTPServer`) :
    32 threads sur la meme cible donnent **19 echecs sur 32 sans retentative**
    et **0 sur 32** avec ce backoff, pire cas observe 6 tentatives.

    Elle remplace un backoff lineaire de 5 x 50 ms, qui etait moins bon des
    deux cotes : trop lent au cas courant (50 ms d'attente pour une collision
    qui se resout en 2 ms) et trop court au cas charge (5 tentatives < les 6
    du pire cas mesure, donc des pertes d'ecriture sous charge).

    Trois proprietes comptent, et aucune n'est decorative :
    - depart a 2 ms : la quasi-totalite des collisions se resout au 1er retry ;
    - croissance exponentielle plafonnee a 50 ms : on ne bloque jamais un
      handler HTTP indefiniment (budget total ~0,41 s sur 12 tentatives,
      soit MOINS que les 0,75 s de l'ancienne politique sur 5) ;
    - jitter derive de l'identifiant de thread : sans lui, N threads reveilles
      par le meme backoff se retelescopent a chaque tour.
    """
    replace_exc: Optional[PermissionError] = None
    for attempt in range(_ATOMIC_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:
            replace_exc = exc
            if attempt == _ATOMIC_REPLACE_MAX_ATTEMPTS - 1:
                break
            delay = min(_ATOMIC_REPLACE_BACKOFF_CAP_S, _ATOMIC_REPLACE_BACKOFF_BASE_S * (2**attempt))
            time.sleep(delay + (threading.get_ident() % 8) * 0.0005)
    if replace_exc is not None:
        raise replace_exc


def atomic_write_bytes(p: Path, data: bytes, *, mkdir: bool = True) -> None:
    """Ecrit `data` dans `p` de facon atomique ET durable.

    Les DEUX invariants, ensemble :

    1. **Nom de `.tmp` unique** (pid/thread/ns/uuid) : deux ecrivains
       concurrents — threads d'un `ThreadingHTTPServer`, thread daemon de purge
       au boot, 2e instance — ne partagent plus le meme fichier intermediaire.
    2. **flush + `os.fsync` + verification de la taille ecrite** avant
       `os.replace` : un crash systeme entre l'ecriture et le rename ne peut
       plus promouvoir un fichier vide ou tronque en version officielle.

    En cas d'echec, `p` est laisse INCHANGE et une `OSError` est levee
    (`AtomicWriteError` pour une taille incoherente). Le `.tmp` est nettoye.

    PORTEE EXACTE DE LA GARANTIE — ce qui n'est PAS fait, et pourquoi.
    Le fsync ci-dessous porte sur le CONTENU du fichier, pas sur l'entree de
    REPERTOIRE creee par `os.replace`. En toute rigueur POSIX il faudrait aussi
    `fsync` le descripteur du repertoire parent, sinon un crash noyau juste
    apres le rename peut laisser le repertoire pointer sur l'ancienne entree.
    C'est deliberement omis : `os.open(dir, O_RDONLY)` leve `PermissionError`
    sur Windows, qui est la seule plateforme cible (application desktop
    Windows), et NTFS journalise ses metadonnees — le rename est donc deja
    ordonne par le journal du systeme de fichiers. La garantie reelle est donc
    « jamais de contenu tronque promu », pas « rename durable au sens POSIX ».
    Un futur ecrivain ne doit pas croire l'invariant plus fort qu'il ne l'est ;
    un portage Linux devrait ajouter le fsync du repertoire ici.
    """
    if mkdir:
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = atomic_tmp_path(p)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())  # force l'ecriture sur disque AVANT le rename
        written = tmp.stat().st_size
        # `written == 0` a ete RETIRE de cette garde : la clause etait subsumee
        # par `written != len(data)` (0 != n des que data est non vide) et son
        # seul effet propre etait de rendre l'ecriture d'un fichier VIDE
        # toujours impossible. Ce n'etait pas theorique : l'export NDJSON d'une
        # selection vide (0 film) est legitime et echouait sur un « ecriture
        # atomique incomplete : 0/0 octets ». Une taille nulle DEMANDEE est
        # valide ; une taille nulle SUBIE reste attrapee, car data ne l'est pas.
        if written != len(data):
            raise AtomicWriteError(f"ecriture atomique incomplete pour {p.name}: {written}/{len(data)} octets")
        _replace_with_retry(tmp, p)
    finally:
        # Best-effort cleanup : tmp.exists() / tmp.unlink() ne peuvent lever
        # qu'OSError (PermissionError, FileNotFoundError en derivent). Apres un
        # os.replace reussi, le tmp n'existe plus : ce bloc est un no-op.
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def atomic_write_text(p: Path, text: str, *, encoding: str = "utf-8", mkdir: bool = True) -> None:
    """Variante texte d'`atomic_write_bytes` (memes invariants)."""
    atomic_write_bytes(p, text.encode(encoding), mkdir=mkdir)


def atomic_write_json(p: Path, obj: Any, *, indent: Optional[int] = 2, mkdir: bool = True) -> None:
    """Variante JSON d'`atomic_write_bytes` (memes invariants).

    `indent=None` produit la forme compacte utilisee par les gros caches.
    """
    atomic_write_text(p, json.dumps(obj, ensure_ascii=False, indent=indent), mkdir=mkdir)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


_PRESERVED_REVIEW_DIRNAME = "_preserved_review"


def clean_old_runs(state_dir: Path, keep_last: int = 10) -> None:
    runs = state_dir / "runs"
    if not runs.exists():
        return
    # R8-002 (F1, PERTE DE DONNEES) : la retention-runs supprimait les vieux run_dirs
    # entiers (shutil.rmtree), DETRUISANT au passage <run_dir>/_review qui contient les
    # ORIGINAUX quarantines de l'apply (buckets conflict/duplicate/leftover, cf
    # apply_support: run_review_root). Ces originaux etaient perdus AVANT revue
    # utilisateur, quel que soit le TTL quarantaine configure. Garde-fou : on NE detruit
    # JAMAIS une quarantaine NON REVUE -> on PRESERVE tout <run_dir>/_review contenant
    # des fichiers, en le relocant sous runs/_preserved_review/ (exclu de la retention),
    # avant de supprimer le reste du run_dir.
    preserved_root = runs / _PRESERVED_REVIEW_DIRNAME

    # Issue #609 (PERTE DE DONNEES) : le tri se faisait sur le NOM du run_dir. Les
    # run_dirs s'appellent `tri_films_{run_id}` et run_id a DEUX formats acceptes par
    # normalize_or_generate_run_id (infra/run_id.py) : `YYYYMMDD_HHMMSS_NNN` et le
    # fallback `uuid4().hex` (atteint sur collision / retry sqlite3.IntegrityError dans
    # job_runner). Des que les deux formats coexistent, l'ordre lexicographique cesse
    # d'etre chronologique (`tri_films_f3a9...` passe devant `tri_films_20260803_...`)
    # et la retention supprime des runs RECENTS en gardant de vieux uuid. On trie donc
    # sur la date de modification reelle ; `0.0` si le dir devient inaccessible entre
    # l'iterdir() et le stat() (concurrent rmtree), ce qui le classe en fin de liste
    # donc candidat a la purge, sans faire exploser tout le nettoyage.
    def _mtime_of(d: Path) -> float:
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0

    items = sorted(
        [d for d in runs.iterdir() if d.is_dir() and d.name != _PRESERVED_REVIEW_DIRNAME],
        key=_mtime_of,
        reverse=True,
    )
    for d in items[keep_last:]:
        try:
            review = d / "_review"
            if review.is_dir() and any(p.is_file() for p in review.rglob("*")):
                preserved_root.mkdir(parents=True, exist_ok=True)
                dest = preserved_root / d.name
                if dest.exists():
                    suffix = 1
                    while (preserved_root / f"{d.name}__{suffix}").exists():
                        suffix += 1
                    dest = preserved_root / f"{d.name}__{suffix}"
                shutil.move(str(review), str(dest))
                _debug_log_state(
                    state_dir,
                    f"clean_old_runs PRESERVE quarantaine non revue: {review} -> {dest}",
                )
            shutil.rmtree(d)
        except OSError as exc:
            _debug_log_state(state_dir, f"clean_old_runs warning path={d} error={exc}")
